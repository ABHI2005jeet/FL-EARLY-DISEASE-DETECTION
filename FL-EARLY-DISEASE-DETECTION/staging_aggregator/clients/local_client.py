"""Local simulated hospital client behavior for multi-round FL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fl_core.dataset import load_client_rows, load_normalization
from fl_core.model import train_local_model
from local_cloud.object_store import LocalObjectStore


CURRENT_GLOBAL_MODEL_KEY = "global/current_model.json"


@dataclass(frozen=True)
class WeightUploadEvent:
    round_number: int
    client_id: str
    model_key: str
    local_accuracy: float
    train_size: int
    test_size: int


def client_weight_key(client_id: str, round_number: int) -> str:
    return f"clients/{client_id}/round_{round_number:03d}/weights.json"


def train_and_upload_for_round(
    *,
    client_id: str,
    round_number: int,
    store: LocalObjectStore,
    local_epochs: int,
    learning_rate: float,
) -> WeightUploadEvent:
    """Train one client from the current global model and upload weights only."""

    current_global = store.get_json(actor=client_id, key=CURRENT_GLOBAL_MODEL_KEY)
    initial_model = current_global["model"]
    rows = load_client_rows(client_id)
    normalization = load_normalization()
    result = train_local_model(
        client_id,
        rows,
        normalization=normalization,
        epochs=local_epochs,
        learning_rate=learning_rate,
        initial_model=initial_model,
    )

    model_key = client_weight_key(client_id, round_number)
    payload: dict[str, Any] = {
        "round": round_number,
        "client_id": client_id,
        "model": result.model,
        "metrics": {
            "local_accuracy": result.accuracy,
            "train_size": result.train_size,
            "test_size": result.test_size,
        },
        "privacy_note": "Raw patient rows stay on the simulated hospital client.",
    }
    store.put_json(
        actor=client_id,
        key=model_key,
        payload=payload,
        metadata={"content_type": "application/json", "sse": "SSE-S3"},
    )

    return WeightUploadEvent(
        round_number=round_number,
        client_id=client_id,
        model_key=model_key,
        local_accuracy=result.accuracy,
        train_size=result.train_size,
        test_size=result.test_size,
    )
