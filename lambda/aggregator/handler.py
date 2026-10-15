"""AWS Lambda handler: aggregates uploaded hospital weights via FedAvg.

Triggered by an S3 ObjectCreated event on the `clients/` prefix. On each
invocation: records the upload in DynamoDB (atomic counter) and, once all
expected hospitals have uploaded for that round, runs FedAvg and publishes
the new global model back to S3.

DEPLOYMENT: zip this file together with the project's fl_core/, aggregator/,
local_cloud/, clients/, config/ folders and data/processed/ (the small
pre-generated CSV splits + normalization.json), all from the project root,
so the zip's top level looks like:
    handler.py
    fl_core/...
    aggregator/...
    local_cloud/...
    clients/...
    config/...
    data/processed/...
Upload as the Lambda's code source and set Handler to `handler.lambda_handler`.
Runtime: Python 3.12. boto3 is already included in the Lambda runtime.

Attach infra/iam_policies/lambda_aggregator_role.json to this Lambda's
execution role, and add an S3 trigger: ObjectCreated events with prefix
`clients/`.
"""

from __future__ import annotations

import json
import os
import re

from aggregator.fedavg import fedavg
from aggregator.local_aggregator import evaluate_global_accuracy, global_model_key
from clients.local_client import CURRENT_GLOBAL_MODEL_KEY
from local_cloud.aws_metadata_store import AWSMetadataStore
from local_cloud.aws_object_store import AWSObjectStore
from local_cloud.config import load_local_config

KEY_PATTERN = re.compile(
    r"^clients/(?P<client_id>[^/]+)/round_(?P<round_number>\d+)/weights\.json$"
)

REGION = os.environ.get("AWS_REGION", "eu-north-1")
ROUNDS_TABLE = os.environ.get("FL_ROUNDS_TABLE", "FlRoundsTable")
COUNTERS_TABLE = os.environ.get("FL_COUNTERS_TABLE", "FlUploadCountersTable")


def lambda_handler(event, context):
    config = load_local_config()
    metadata = AWSMetadataStore(ROUNDS_TABLE, COUNTERS_TABLE, region=REGION)

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]
        match = KEY_PATTERN.match(key)
        if not match:
            print(f"skip: key does not match expected pattern: {key}")
            continue

        client_id = match.group("client_id")
        round_number = int(match.group("round_number"))
        store = AWSObjectStore(bucket_name=bucket, region=REGION)

        payload = store.get_json(actor="aggregator", key=key)
        uploads_received = metadata.record_upload(
            round_number=round_number,
            client_id=client_id,
            model_key=key,
            local_accuracy=payload["metrics"]["local_accuracy"],
            train_size=payload["metrics"]["train_size"],
            test_size=payload["metrics"]["test_size"],
        )
        print(f"round {round_number}: {client_id} uploaded ({uploads_received}/{len(config.client_ids)})")

        if uploads_received >= len(config.client_ids):
            _aggregate(store, metadata, round_number, config.client_ids)

    return {"statusCode": 200, "body": json.dumps({"ok": True})}


def _aggregate(store, metadata, round_number, expected_clients):
    round_state = metadata.get_round(round_number)
    uploads = round_state["uploads"]
    participated = [c for c in expected_clients if c in uploads]
    skipped = [c for c in expected_clients if c not in uploads]

    payloads = [
        store.get_json(actor="aggregator", key=uploads[c]["model_key"]) for c in participated
    ]
    global_model = fedavg(
        [p["model"] for p in payloads],
        [int(p["metrics"]["train_size"]) for p in payloads],
    )
    global_accuracy = evaluate_global_accuracy(global_model, expected_clients)
    model_key = global_model_key(round_number)
    model_payload = {
        "round": round_number,
        "model": global_model,
        "metrics": {
            "global_accuracy": global_accuracy,
            "participated_clients": participated,
            "skipped_clients": skipped,
        },
    }

    store.put_json(
        actor="aggregator",
        key=model_key,
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
        global_model_key=model_key,
        current_model_key=CURRENT_GLOBAL_MODEL_KEY,
        global_accuracy=global_accuracy,
        participated_clients=participated,
        skipped_clients=skipped,
        trigger_reason="all_clients_uploaded",
    )
    print(f"round {round_number} aggregated: global_accuracy={global_accuracy:.3f}")
