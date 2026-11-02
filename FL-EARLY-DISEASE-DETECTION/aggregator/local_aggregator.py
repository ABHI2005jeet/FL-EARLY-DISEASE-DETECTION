"""Local aggregator that performs FedAvg over uploaded client weights."""

from __future__ import annotations

from dataclasses import dataclass

from aggregator.fedavg import fedavg
from clients.local_client import CURRENT_GLOBAL_MODEL_KEY
from fl_core.dataset import load_client_rows, load_normalization
from fl_core.model import evaluate_accuracy, train_test_split
from local_cloud.metadata_store import LocalMetadataStore
from local_cloud.object_store import LocalObjectStore


@dataclass(frozen=True)
class AggregationResult:
    round_number: int
    participated_clients: list[str]
    skipped_clients: list[str]
    global_accuracy: float
    global_model_key: str


def global_model_key(round_number: int) -> str:
    return f"global/round_{round_number:03d}/model.json"


def aggregate_round(
    *,
    round_number: int,
    store: LocalObjectStore,
    metadata: LocalMetadataStore,
    expected_clients: list[str],
    trigger_reason: str,
) -> AggregationResult:
    """Load uploaded weight objects, FedAvg them, and publish the global model."""

    round_state = metadata.get_round(round_number)
    uploads = round_state["uploads"]
    if not uploads:
        raise ValueError(f"Round {round_number} has no uploaded client weights")

    participated_clients = [
        client_id for client_id in expected_clients if client_id in uploads
    ]
    skipped_clients = [
        client_id for client_id in expected_clients if client_id not in uploads
    ]

    uploaded_payloads = [
        store.get_json(actor="aggregator", key=uploads[client_id]["model_key"])
        for client_id in participated_clients
    ]
    global_model = fedavg(
        [payload["model"] for payload in uploaded_payloads],
        [int(payload["metrics"]["train_size"]) for payload in uploaded_payloads],
    )
    global_accuracy = evaluate_global_accuracy(global_model, expected_clients)
    round_model_key = global_model_key(round_number)
    model_payload = {
        "round": round_number,
        "model": global_model,
        "metrics": {
            "global_accuracy": global_accuracy,
            "participated_clients": participated_clients,
            "skipped_clients": skipped_clients,
        },
    }

    store.put_json(
        actor="aggregator",
        key=round_model_key,
        payload=model_payload,
        metadata={"content_type": "application/json", "sse": "SSE-S3"},
    )
    store.put_json(
        actor="aggregator",
        key=CURRENT_GLOBAL_MODEL_KEY,
        payload=model_payload,
        metadata={"content_type": "application/json", "sse": "SSE-S3"},
    )
    metadata.record_aggregation(
        round_number=round_number,
        global_model_key=round_model_key,
        current_model_key=CURRENT_GLOBAL_MODEL_KEY,
        global_accuracy=global_accuracy,
        participated_clients=participated_clients,
        skipped_clients=skipped_clients,
        trigger_reason=trigger_reason,
    )

    return AggregationResult(
        round_number=round_number,
        participated_clients=participated_clients,
        skipped_clients=skipped_clients,
        global_accuracy=global_accuracy,
        global_model_key=round_model_key,
    )


def evaluate_global_accuracy(
    model: dict[str, object],
    client_ids: list[str],
    split_seed: int = 7,
) -> float:
    normalization = load_normalization()
    test_rows = []
    for client_id in client_ids:
        rows = load_client_rows(client_id)
        _, client_test_rows = train_test_split(rows, seed=split_seed)
        test_rows.extend(client_test_rows)

    return evaluate_accuracy(model, test_rows, normalization)
