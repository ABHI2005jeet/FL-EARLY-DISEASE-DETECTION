"""Local DynamoDB-style metadata store for training rounds."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from local_cloud.cloudtrail import utc_now
from local_cloud.paths import METADATA_PATH


class LocalMetadataStore:
    def __init__(self, path: Path = METADATA_PATH) -> None:
        self.path = path

    def clear(self) -> None:
        if self.path.parent.exists():
            shutil.rmtree(self.path.parent)

    def initialize_training(
        self,
        *,
        total_rounds: int,
        expected_clients: list[str],
        current_model_key: str,
    ) -> None:
        self._write_state(
            {
                "training_complete": False,
                "total_rounds": total_rounds,
                "expected_clients": expected_clients,
                "current_model_key": current_model_key,
                "rounds": {},
            }
        )

    def load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "training_complete": False,
                "total_rounds": 0,
                "expected_clients": [],
                "current_model_key": None,
                "rounds": {},
            }
        return json.loads(self.path.read_text(encoding="utf-8"))

    def begin_round(
        self,
        *,
        round_number: int,
        expected_clients: list[str],
        timeout_seconds: int,
    ) -> None:
        state = self.load_state()
        state["rounds"][str(round_number)] = {
            "round": round_number,
            "status": "collecting",
            "started_at": utc_now(),
            "completed_at": None,
            "timeout_seconds": timeout_seconds,
            "expected_clients": expected_clients,
            "uploads_received": 0,
            "uploads": {},
            "client_errors": {},
            "participated_clients": [],
            "skipped_clients": [],
            "local_accuracy": {},
            "global_accuracy": None,
            "global_model_key": None,
            "aggregation_trigger": None,
        }
        self._write_state(state)

    def record_upload(
        self,
        *,
        round_number: int,
        client_id: str,
        model_key: str,
        local_accuracy: float,
        train_size: int,
        test_size: int,
    ) -> int:
        state = self.load_state()
        round_state = self._round_state(state, round_number)
        if client_id not in round_state["uploads"]:
            round_state["uploads_received"] += 1

        round_state["uploads"][client_id] = {
            "model_key": model_key,
            "uploaded_at": utc_now(),
            "train_size": train_size,
            "test_size": test_size,
        }
        round_state["local_accuracy"][client_id] = local_accuracy
        self._write_state(state)
        return int(round_state["uploads_received"])

    def record_client_error(
        self,
        *,
        round_number: int,
        client_id: str,
        error: str,
    ) -> None:
        state = self.load_state()
        round_state = self._round_state(state, round_number)
        round_state["client_errors"][client_id] = {
            "error": error,
            "recorded_at": utc_now(),
        }
        self._write_state(state)

    def mark_timeout(self, *, round_number: int, skipped_clients: list[str]) -> None:
        state = self.load_state()
        round_state = self._round_state(state, round_number)
        round_state["status"] = "timed_out"
        round_state["skipped_clients"] = skipped_clients
        self._write_state(state)

    def record_aggregation(
        self,
        *,
        round_number: int,
        global_model_key: str,
        current_model_key: str,
        global_accuracy: float,
        participated_clients: list[str],
        skipped_clients: list[str],
        trigger_reason: str,
    ) -> None:
        state = self.load_state()
        round_state = self._round_state(state, round_number)
        round_state["status"] = "aggregated"
        round_state["completed_at"] = utc_now()
        round_state["global_model_key"] = global_model_key
        round_state["global_accuracy"] = global_accuracy
        round_state["participated_clients"] = participated_clients
        round_state["skipped_clients"] = skipped_clients
        round_state["aggregation_trigger"] = trigger_reason
        state["current_model_key"] = current_model_key
        self._write_state(state)

    def mark_training_complete(self) -> None:
        state = self.load_state()
        state["training_complete"] = True
        state["training_completed_at"] = utc_now()
        self._write_state(state)

    def get_round(self, round_number: int) -> dict[str, Any]:
        state = self.load_state()
        return self._round_state(state, round_number)

    def round_history(self) -> list[dict[str, Any]]:
        rounds = self.load_state()["rounds"]
        return [rounds[key] for key in sorted(rounds, key=lambda value: int(value))]

    def _round_state(self, state: dict[str, Any], round_number: int) -> dict[str, Any]:
        key = str(round_number)
        if key not in state["rounds"]:
            raise KeyError(f"Round {round_number} has not been started")
        return state["rounds"][key]

    def _write_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")
