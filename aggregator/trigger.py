"""Local stand-in for S3 event -> DynamoDB upload-counter trigger logic."""

from __future__ import annotations

from clients.local_client import WeightUploadEvent
from local_cloud.metadata_store import LocalMetadataStore


def handle_weight_upload_event(
    *,
    event: WeightUploadEvent,
    metadata: LocalMetadataStore,
    expected_clients: list[str],
) -> bool:
    """Record an upload event and tell the caller whether aggregation should run.

    This mirrors the intended AWS behavior:
    S3 object-created event -> DynamoDB counter update -> aggregate at expected count.
    """

    uploads_received = metadata.record_upload(
        round_number=event.round_number,
        client_id=event.client_id,
        model_key=event.model_key,
        local_accuracy=event.local_accuracy,
        train_size=event.train_size,
        test_size=event.test_size,
    )
    return uploads_received >= len(expected_clients)


def handle_round_timeout(
    *,
    round_number: int,
    metadata: LocalMetadataStore,
    expected_clients: list[str],
) -> bool:
    """Mark missing clients as skipped after a timeout and continue if possible."""

    round_state = metadata.get_round(round_number)
    uploaded_clients = set(round_state["uploads"])
    skipped_clients = [
        client_id for client_id in expected_clients if client_id not in uploaded_clients
    ]
    metadata.mark_timeout(round_number=round_number, skipped_clients=skipped_clients)
    return bool(uploaded_clients)
