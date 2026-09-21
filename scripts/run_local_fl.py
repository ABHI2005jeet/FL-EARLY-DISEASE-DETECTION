"""Run Phase 2/3 federated learning locally with mock AWS services."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aggregator.local_aggregator import aggregate_round
from aggregator.trigger import handle_round_timeout, handle_weight_upload_event
from clients.local_client import CURRENT_GLOBAL_MODEL_KEY, train_and_upload_for_round
from fl_core.dataset import prepare_phase1_data
from fl_core.model import zero_model
from local_cloud.config import load_local_config
from local_cloud.metadata_store import LocalMetadataStore
from local_cloud.object_store import LocalObjectStore
from local_cloud.paths import LOCAL_RUNTIME_DIR


def parse_dropout_spec(spec: str) -> dict[int, set[str]]:
    """Parse `hospital_3:2,hospital_1:4` into round -> clients."""

    dropouts: dict[int, set[str]] = {}
    if not spec:
        return dropouts

    for item in spec.split(","):
        client_id, round_text = item.split(":", maxsplit=1)
        round_number = int(round_text)
        dropouts.setdefault(round_number, set()).add(client_id)
    return dropouts


def parse_args() -> argparse.Namespace:
    config = load_local_config()
    parser = argparse.ArgumentParser(description="Run the local multi-round FL loop.")
    parser.add_argument("--rounds", type=int, default=config.total_rounds)
    parser.add_argument("--timeout-seconds", type=int, default=config.timeout_seconds)
    parser.add_argument("--local-epochs", type=int, default=config.local_epochs)
    parser.add_argument("--learning-rate", type=float, default=config.learning_rate)
    parser.add_argument(
        "--simulate-dropout",
        default="hospital_3:2",
        help="Comma-separated client:round values. Empty string disables dropouts.",
    )
    return parser.parse_args()


def reset_runtime() -> None:
    if LOCAL_RUNTIME_DIR.exists():
        shutil.rmtree(LOCAL_RUNTIME_DIR, ignore_errors=True)


def run_federated_pipeline(
    rounds: int | None = None,
    timeout_seconds: int | None = None,
    local_epochs: int | None = None,
    learning_rate: float | None = None,
    simulate_dropout: str = "hospital_3:2",
    store: object | None = None,
    metadata: object | None = None,
) -> dict[str, object]:
    """Run the multi-round FL loop.

    By default this uses LocalObjectStore/LocalMetadataStore (local disk,
    runtime/ reset on every run). Pass `store`/`metadata` instances (e.g.
    AWSObjectStore/AWSMetadataStore) to run the exact same orchestration
    logic against real AWS instead -- see scripts/run_aws_fl.py.
    """

    config = load_local_config()
    actual_rounds = rounds if rounds is not None else config.total_rounds
    actual_timeout = timeout_seconds if timeout_seconds is not None else config.timeout_seconds
    actual_epochs = local_epochs if local_epochs is not None else config.local_epochs
    actual_lr = learning_rate if learning_rate is not None else config.learning_rate

    client_ids = config.client_ids
    dropouts = parse_dropout_spec(simulate_dropout)
    using_local_store = store is None

    prepare_phase1_data(client_count=len(client_ids), seed=42)
    if using_local_store:
        # Only wipe the local scratch directory when we're actually using it.
        # Never touch a real AWS bucket/tables here.
        reset_runtime()

    store = store if store is not None else LocalObjectStore()
    metadata = metadata if metadata is not None else LocalMetadataStore()
    metadata.initialize_training(
        total_rounds=actual_rounds,
        expected_clients=client_ids,
        current_model_key=CURRENT_GLOBAL_MODEL_KEY,
    )
    store.put_json(
        actor="system",
        key=CURRENT_GLOBAL_MODEL_KEY,
        payload={"round": 0, "model": zero_model(), "metrics": {}},
        metadata={"content_type": "application/json", "sse": "SSE-S3"},
    )

    print("Starting local federated learning run")
    print(f"rounds={actual_rounds}")
    print(f"clients={','.join(client_ids)}")
    print(f"timeout_seconds={actual_timeout}")
    if dropouts:
        printable = [
            f"{client_id}@round_{round_number}"
            for round_number, clients in sorted(dropouts.items())
            for client_id in sorted(clients)
        ]
        print("simulated_dropouts=" + ",".join(printable))
    else:
        print("simulated_dropouts=none")

    for round_number in range(1, actual_rounds + 1):
        metadata.begin_round(
            round_number=round_number,
            expected_clients=client_ids,
            timeout_seconds=actual_timeout,
        )
        print(f"\nround={round_number} status=collecting")
        aggregated = False

        for client_id in client_ids:
            if client_id in dropouts.get(round_number, set()):
                print(f"{client_id}: skipped upload (simulated dropout)")
                continue

            try:
                event = train_and_upload_for_round(
                    client_id=client_id,
                    round_number=round_number,
                    store=store,
                    local_epochs=actual_epochs,
                    learning_rate=actual_lr,
                )
                print(
                    f"{client_id}: uploaded weights "
                    f"local_accuracy={event.local_accuracy:.3f}"
                )
                should_aggregate = handle_weight_upload_event(
                    event=event,
                    metadata=metadata,
                    expected_clients=client_ids,
                )
                if should_aggregate:
                    result = aggregate_round(
                        round_number=round_number,
                        store=store,
                        metadata=metadata,
                        expected_clients=client_ids,
                        trigger_reason="all_clients_uploaded",
                    )
                    aggregated = True
                    print_round_result(result)
            except Exception as exc:
                metadata.record_client_error(
                    round_number=round_number,
                    client_id=client_id,
                    error=str(exc),
                )
                print(f"{client_id}: error={exc}")

        if not aggregated:
            can_continue = handle_round_timeout(
                round_number=round_number,
                metadata=metadata,
                expected_clients=client_ids,
            )
            if not can_continue:
                raise RuntimeError(f"Round {round_number} had no uploaded weights")

            result = aggregate_round(
                round_number=round_number,
                store=store,
                metadata=metadata,
                expected_clients=client_ids,
                trigger_reason="timeout",
            )
            print_round_result(result)

    metadata.mark_training_complete()
    print("\ntraining_complete=true")
    if using_local_store:
        print("round_history=runtime/local_cloud/dynamodb/rounds.json")
        print("model_store=runtime/local_cloud/s3")
        print("audit_log=runtime/local_cloud/cloudtrail/events.jsonl")
    else:
        print("round_history=DynamoDB (FlRoundsTable)")
        print("model_store=S3 bucket (see AWSObjectStore bucket_name)")

    return {
        "training_complete": True,
        "rounds": actual_rounds,
        "client_ids": client_ids,
    }


def main() -> None:
    args = parse_args()
    run_federated_pipeline(
        rounds=args.rounds,
        timeout_seconds=args.timeout_seconds,
        local_epochs=args.local_epochs,
        learning_rate=args.learning_rate,
        simulate_dropout=args.simulate_dropout,
    )


def print_round_result(result) -> None:
    print(
        f"aggregated=true global_accuracy={result.global_accuracy:.3f} "
        f"participated={','.join(result.participated_clients)} "
        f"skipped={','.join(result.skipped_clients) or 'none'}"
    )


if __name__ == "__main__":
    main()

