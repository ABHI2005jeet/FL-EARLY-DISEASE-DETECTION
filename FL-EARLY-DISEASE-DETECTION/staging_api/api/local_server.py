"""Local HTTP API for dashboard reads and predictions.

This is the Phase 3 local stand-in for API Gateway + Lambda. The browser calls
this API instead of reading the local S3/DynamoDB mock files directly.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from clients.local_client import CURRENT_GLOBAL_MODEL_KEY
from fl_core.dataset import FEATURE_COLUMNS, load_client_rows, load_normalization
from fl_core.model import predict_probability
from local_cloud.config import load_local_config
from local_cloud.metadata_store import LocalMetadataStore
from local_cloud.object_store import LocalObjectStore
from local_cloud.paths import AUDIT_LOG_PATH
from scripts.run_local_fl import run_federated_pipeline


class RequestValidationError(ValueError):
    pass


PATIENT_PRESETS = [
    {
        "id": "healthy_athlete",
        "name": "Healthy Young Adult (Low Risk)",
        "description": "35yo asymptomatic runner with normal ECG, BP and low cholesterol",
        "features": {
            "age": 35, "sex": 0, "cp": 0, "trestbps": 110, "chol": 172, "fbs": 0,
            "restecg": 0, "thalach": 175, "exang": 0, "oldpeak": 0.0, "slope": 0,
            "ca": 0, "thal": 1,
        },
    },
    {
        "id": "borderline_middle_aged",
        "name": "Moderate Risk Adult (Borderline)",
        "description": "54yo with mild hypertension, moderate cholesterol, and slight ST depression",
        "features": {
            "age": 54, "sex": 1, "cp": 2, "trestbps": 135, "chol": 230, "fbs": 0,
            "restecg": 1, "thalach": 142, "exang": 0, "oldpeak": 1.2, "slope": 1,
            "ca": 1, "thal": 2,
        },
    },
    {
        "id": "high_risk_cardiac",
        "name": "Acute Cardiac Symptoms (High Risk)",
        "description": "62yo male with severe chest pain, elevated fasting sugar, fluoroscopy vessels",
        "features": {
            "age": 62, "sex": 1, "cp": 3, "trestbps": 160, "chol": 286, "fbs": 1,
            "restecg": 2, "thalach": 108, "exang": 1, "oldpeak": 2.6, "slope": 2,
            "ca": 3, "thal": 3,
        },
    },
    {
        "id": "elderly_angina",
        "name": "Elderly Angina Patient (Critical)",
        "description": "68yo with exercise-induced angina, multi-vessel defect and low max heart rate",
        "features": {
            "age": 68, "sex": 1, "cp": 3, "trestbps": 145, "chol": 260, "fbs": 0,
            "restecg": 2, "thalach": 115, "exang": 1, "oldpeak": 2.2, "slope": 1,
            "ca": 2, "thal": 3,
        },
    },
]


def build_rounds_response(metadata: LocalMetadataStore) -> dict[str, Any]:
    state = metadata.load_state()
    rounds = []
    for round_state in metadata.round_history():
        local_accuracy = round_state.get("local_accuracy", {})
        average_local_accuracy = None
        if local_accuracy:
            average_local_accuracy = sum(local_accuracy.values()) / len(local_accuracy)

        rounds.append(
            {
                "round": round_state["round"],
                "status": round_state["status"],
                "uploads_received": round_state["uploads_received"],
                "expected_uploads": len(round_state["expected_clients"]),
                "local_accuracy": local_accuracy,
                "average_local_accuracy": average_local_accuracy,
                "global_accuracy": round_state["global_accuracy"],
                "participated_clients": round_state["participated_clients"],
                "skipped_clients": round_state["skipped_clients"],
                "aggregation_trigger": round_state["aggregation_trigger"],
                "global_model_key": round_state["global_model_key"],
                "started_at": round_state["started_at"],
                "completed_at": round_state["completed_at"],
            }
        )

    return {
        "training_complete": state["training_complete"],
        "total_rounds": state["total_rounds"],
        "expected_clients": state["expected_clients"],
        "current_model_key": state["current_model_key"],
        "rounds": rounds,
    }


def validate_patient_payload(payload: dict[str, Any]) -> dict[str, float]:
    features = payload.get("features", payload)
    if not isinstance(features, dict):
        raise RequestValidationError("Request body must be an object of patient features")

    parsed: dict[str, float] = {}
    missing = [column for column in FEATURE_COLUMNS if column not in features]
    if missing:
        raise RequestValidationError("Missing required features: " + ", ".join(missing))

    for column in FEATURE_COLUMNS:
        try:
            parsed[column] = float(features[column])
        except (TypeError, ValueError) as exc:
            raise RequestValidationError(f"Feature {column} must be numeric") from exc

    return parsed


def compute_clinical_flags(features: dict[str, float]) -> list[dict[str, str]]:
    flags = []
    if features.get("trestbps", 0) >= 140:
        flags.append({"type": "warning", "label": "Hypertension (BP ≥ 140 mmHg)"})
    if features.get("chol", 0) >= 240:
        flags.append({"type": "warning", "label": "Elevated Serum Cholesterol (≥ 240 mg/dl)"})
    if features.get("fbs", 0) == 1:
        flags.append({"type": "info", "label": "Fasting Blood Sugar > 120 mg/dl"})
    if features.get("exang", 0) == 1:
        flags.append({"type": "danger", "label": "Exercise Induced Angina Present"})
    if features.get("oldpeak", 0) >= 2.0:
        flags.append({"type": "danger", "label": "Significant ST Depression (≥ 2.0)"})
    if features.get("ca", 0) >= 2:
        flags.append({"type": "danger", "label": f"{int(features['ca'])} Major Vessels Fluoroscopy Colored"})
    return flags


def build_prediction_response(
    *,
    payload: dict[str, Any],
    store: LocalObjectStore,
) -> dict[str, Any]:
    patient_features = validate_patient_payload(payload)
    current_model = store.get_json(actor="api", key=CURRENT_GLOBAL_MODEL_KEY)
    probability = predict_probability(
        current_model["model"],
        patient_features,
        load_normalization(),
    )
    prediction = "disease_presence_likely" if probability >= 0.5 else "disease_presence_unlikely"
    clinical_flags = compute_clinical_flags(patient_features)

    return {
        "prediction": prediction,
        "risk_probability": probability,
        "risk_percent": round(probability * 100, 2),
        "model_round": current_model.get("round"),
        "model_key": CURRENT_GLOBAL_MODEL_KEY,
        "clinical_flags": clinical_flags,
    }


def get_audit_logs(limit: int = 40) -> list[dict[str, Any]]:
    if not AUDIT_LOG_PATH.exists():
        return []
    logs = []
    try:
        with AUDIT_LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    logs.append(json.loads(line))
    except Exception:
        return []
    return logs[-limit:][::-1]


def get_clients_metadata() -> list[dict[str, Any]]:
    config = load_local_config()
    hospitals = []
    display_names = {
        "hospital_1": "St. Jude Cardio Center",
        "hospital_2": "Mayo Regional Health",
        "hospital_3": "General Heart Institute",
    }
    for client_id in config.client_ids:
        rows = load_client_rows(client_id)
        hospitals.append({
            "client_id": client_id,
            "display_name": display_names.get(client_id, client_id.replace("_", " ").title()),
            "sample_count": len(rows),
            "s3_prefix": f"clients/{client_id}/",
            "iam_role": f"arn:aws:iam::123456789012:role/FLClient-{client_id}",
            "encryption": "SSE-S3 (AES-256)",
            "privacy_mode": "Strict Isolation (Raw Patient Data Zero-Egress)",
        })
    return hospitals


_training_lock = threading.Lock()


def make_handler(
    *,
    store: LocalObjectStore | None = None,
    metadata: LocalMetadataStore | None = None,
) -> type[BaseHTTPRequestHandler]:
    object_store = store or LocalObjectStore()
    metadata_store = metadata or LocalMetadataStore()

    class LocalAPIHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self._send_json({}, status=HTTPStatus.NO_CONTENT)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json({"ok": True, "service": "Federated Disease Detection API", "mode": "Local Cloud Mock"})
                return

            if parsed.path == "/rounds":
                self._send_json(build_rounds_response(metadata_store))
                return

            if parsed.path == "/audit" or parsed.path == "/logs":
                self._send_json({"events": get_audit_logs()})
                return

            if parsed.path == "/presets":
                self._send_json({"presets": PATIENT_PRESETS})
                return

            if parsed.path == "/clients":
                self._send_json({"clients": get_clients_metadata()})
                return

            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/predict":
                try:
                    payload = self._read_json_body()
                    self._send_json(
                        build_prediction_response(payload=payload, store=object_store)
                    )
                except RequestValidationError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except FileNotFoundError:
                    self._send_json(
                        {"error": "No trained global model found. Run scripts/run_local_fl.py first."},
                        status=HTTPStatus.NOT_FOUND,
                    )
                except json.JSONDecodeError:
                    self._send_json({"error": "Malformed JSON body"}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:
                    self._send_json(
                        {"error": "Prediction failed gracefully", "details": str(exc)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                return

            if parsed.path == "/train":
                if _training_lock.locked():
                    self._send_json({"error": "Training simulation is already in progress"}, status=HTTPStatus.CONFLICT)
                    return

                try:
                    payload = self._read_json_body() if self.headers.get("Content-Length") else {}
                except Exception:
                    payload = {}

                rounds = payload.get("rounds", 8)
                dropout = payload.get("simulate_dropout", "hospital_3:2")

                def run_background():
                    with _training_lock:
                        try:
                            run_federated_pipeline(
                                rounds=int(rounds),
                                simulate_dropout=str(dropout),
                            )
                        except Exception as e:
                            print(f"Training background error: {e}")

                thread = threading.Thread(target=run_background, daemon=True)
                thread.start()

                self._send_json({
                    "status": "training_started",
                    "rounds": rounds,
                    "simulate_dropout": dropout,
                    "message": "Federated training pipeline triggered in background",
                })
                return

            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            if not raw_body:
                raise RequestValidationError("Request body is required")
            payload = json.loads(raw_body)
            if not isinstance(payload, dict):
                raise RequestValidationError("Request body must be a JSON object")
            return payload

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            if status == HTTPStatus.NO_CONTENT:
                self.end_headers()
                return
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return LocalAPIHandler


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), make_handler())
    print(f"Local API listening at http://{host}:{port}")
    print("Routes: GET /health, GET /rounds, GET /audit, GET /presets, GET /clients, POST /predict, POST /train")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # Ctrl+C is the normal way to stop the server — exit cleanly.
        print("\nAPI server stopped.")


