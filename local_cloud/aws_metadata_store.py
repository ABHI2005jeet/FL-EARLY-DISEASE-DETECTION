"""Real DynamoDB-backed metadata store, matching LocalMetadataStore's interface.

Design (deliberately simple, matches the local JSON-blob-per-round shape):

FlRoundsTable (partition key: round_number, Number)
  - Item round_number = 0  -> global training state (total_rounds,
    expected_clients, training_complete, current_model_key), stored as a
    JSON string in the "state" attribute.
  - Item round_number = N  -> that round's full state dict (status, uploads,
    local_accuracy, etc.), also stored as a JSON string in "state".
  Storing the whole dict as one JSON string sidesteps DynamoDB's float ->
  Decimal conversion requirements entirely, and mirrors the local file
  store's "rewrite the whole state" pattern.

FlUploadCountersTable (partition key: round_number, Number)
  - Item round_number = N -> "count" (Number), incremented atomically via
    an UpdateExpression ADD. This is the value a real S3-triggered Lambda
    should use to decide "have all hospitals uploaded yet?" -- it is safe
    under concurrent invocations, unlike read-modify-write on the JSON blob.

Note: record_upload/record_client_error/mark_timeout/record_aggregation use
a read-modify-write on the JSON blob for round state, which is fine for this
project's sequential local-runner script. If you later have multiple Lambda
invocations racing to update the *same* round concurrently, use the
FlUploadCountersTable count (not round_state["uploads_received"]) as your
source of truth for "all uploads are in" -- that part already is safe.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import boto3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AWSMetadataStore:
    def __init__(
        self,
        rounds_table_name: str = "FlRoundsTable",
        counters_table_name: str = "FlUploadCountersTable",
        region: str = "eu-north-1",
    ) -> None:
        resource = boto3.resource("dynamodb", region_name=region)
        self.rounds_table = resource.Table(rounds_table_name)
        self.counters_table = resource.Table(counters_table_name)

    # ---- internal helpers -------------------------------------------------

    def _get_state_item(self, round_number: int) -> dict[str, Any] | None:
        response = self.rounds_table.get_item(Key={"round_number": round_number})
        item = response.get("Item")
        if item is None:
            return None
        return json.loads(item["state"])

    def _put_state_item(self, round_number: int, state: dict[str, Any]) -> None:
        self.rounds_table.put_item(
            Item={"round_number": round_number, "state": json.dumps(state)}
        )

    # ---- public interface (mirrors LocalMetadataStore) --------------------

    def initialize_training(
        self,
        *,
        total_rounds: int,
        expected_clients: list[str],
        current_model_key: str,
    ) -> None:
        self._put_state_item(
            0,
            {
                "training_complete": False,
                "total_rounds": total_rounds,
                "expected_clients": expected_clients,
                "current_model_key": current_model_key,
            },
        )

    def load_state(self) -> dict[str, Any]:
        global_state = self._get_state_item(0) or {
            "training_complete": False,
            "total_rounds": 0,
            "expected_clients": [],
            "current_model_key": None,
        }

        rounds: dict[str, Any] = {}
        # Small table (a handful of rounds) -- a scan is fine here.
        response = self.rounds_table.scan()
        for item in response.get("Items", []):
            round_number = int(item["round_number"])
            if round_number == 0:
                continue
            rounds[str(round_number)] = json.loads(item["state"])

        return {**global_state, "rounds": rounds}

    def begin_round(
        self,
        *,
        round_number: int,
        expected_clients: list[str],
        timeout_seconds: int,
    ) -> None:
        self._put_state_item(
            round_number,
            {
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
            },
        )
        # Reset the atomic counter for this round.
        self.counters_table.put_item(Item={"round_number": round_number, "count": 0})

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
        # Atomic increment first -- this is the safe-under-concurrency value.
        counter_response = self.counters_table.update_item(
            Key={"round_number": round_number},
            UpdateExpression="ADD #c :incr",
            ExpressionAttributeNames={"#c": "count"},
            ExpressionAttributeValues={":incr": 1},
            ReturnValues="UPDATED_NEW",
        )
        uploads_received = int(counter_response["Attributes"]["count"])

        # Then update the descriptive JSON blob (read-modify-write; fine for
        # a single sequential runner -- see module docstring for caveats).
        round_state = self._get_state_item(round_number)
        if round_state is None:
            raise KeyError(f"Round {round_number} has not been started")

        round_state["uploads"][client_id] = {
            "model_key": model_key,
            "uploaded_at": utc_now(),
            "train_size": train_size,
            "test_size": test_size,
        }
        round_state["local_accuracy"][client_id] = local_accuracy
        round_state["uploads_received"] = uploads_received
        self._put_state_item(round_number, round_state)

        return uploads_received

    def record_client_error(
        self,
        *,
        round_number: int,
        client_id: str,
        error: str,
    ) -> None:
        round_state = self._get_state_item(round_number)
        if round_state is None:
            raise KeyError(f"Round {round_number} has not been started")
        round_state["client_errors"][client_id] = {
            "error": error,
            "recorded_at": utc_now(),
        }
        self._put_state_item(round_number, round_state)

    def mark_timeout(self, *, round_number: int, skipped_clients: list[str]) -> None:
        round_state = self._get_state_item(round_number)
        if round_state is None:
            raise KeyError(f"Round {round_number} has not been started")
        round_state["status"] = "timed_out"
        round_state["skipped_clients"] = skipped_clients
        self._put_state_item(round_number, round_state)

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
        round_state = self._get_state_item(round_number)
        if round_state is None:
            raise KeyError(f"Round {round_number} has not been started")
        round_state["status"] = "aggregated"
        round_state["completed_at"] = utc_now()
        round_state["global_model_key"] = global_model_key
        round_state["global_accuracy"] = global_accuracy
        round_state["participated_clients"] = participated_clients
        round_state["skipped_clients"] = skipped_clients
        round_state["aggregation_trigger"] = trigger_reason
        self._put_state_item(round_number, round_state)

        global_state = self._get_state_item(0) or {}
        global_state["current_model_key"] = current_model_key
        self._put_state_item(0, global_state)

    def mark_training_complete(self) -> None:
        global_state = self._get_state_item(0) or {}
        global_state["training_complete"] = True
        global_state["training_completed_at"] = utc_now()
        self._put_state_item(0, global_state)

    def get_round(self, round_number: int) -> dict[str, Any]:
        round_state = self._get_state_item(round_number)
        if round_state is None:
            raise KeyError(f"Round {round_number} has not been started")
        return round_state

    def round_history(self) -> list[dict[str, Any]]:
        state = self.load_state()
        rounds = state["rounds"]
        return [rounds[key] for key in sorted(rounds, key=lambda value: int(value))]
