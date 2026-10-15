"""AWS Lambda handler behind API Gateway (HTTP API, payload format 2.0).

Exposes:
    GET  /health
    GET  /rounds   -- round-by-round training history
    GET  /clients  -- simulated hospital metadata
    GET  /presets  -- demo patient presets
    POST /predict  -- run inference against the current global model
    POST /train    -- kick off N more rounds asynchronously (no-dropout only)

DEPLOYMENT: zip this file together with the project's fl_core/, aggregator/,
api/, clients/, local_cloud/, scripts/, config/ folders and data/processed/,
all from the project root. Upload as the Lambda's code source and set
Handler to `handler.lambda_handler`. Runtime: Python 3.12.

Set these Lambda environment variables:
    FL_BUCKET_NAME   -- e.g. fl-heart-disease-7742
    AWS_REGION       -- e.g. eu-north-1 (Lambda sets this automatically, but
                        AWSObjectStore/AWSMetadataStore read from it, so make
                        sure the Lambda's own region matches your bucket/tables)
    FL_ROUNDS_TABLE, FL_COUNTERS_TABLE -- optional, default to the standard names

Attach infra/iam_policies/lambda_api_role.json to this Lambda's execution role,
plus a self-invoke permission (lambda:InvokeFunction on this function's own
ARN) since /train works by having this Lambda call itself asynchronously to
dodge the API Gateway 30s timeout. Also set this function's own timeout high
enough (e.g. 300s) to cover several rounds of background training.

Note: /train does NOT support simulated dropout -- the deployed aggregator
requires all expected clients to upload before it aggregates a round, with
no timeout/partial-aggregation path. Only whole, all-clients-present rounds
are supported here.
"""

from __future__ import annotations

import json
import os
import time

import boto3

from api.local_server import (
    PATIENT_PRESETS,
    RequestValidationError,
    build_prediction_response,
    build_rounds_response,
    get_clients_metadata,
)
from clients.local_client import train_and_upload_for_round
from local_cloud.aws_metadata_store import AWSMetadataStore
from local_cloud.aws_object_store import AWSObjectStore
from local_cloud.config import load_local_config

REGION = os.environ.get("AWS_REGION", "eu-north-1")
BUCKET_NAME = os.environ["FL_BUCKET_NAME"]
ROUNDS_TABLE = os.environ.get("FL_ROUNDS_TABLE", "FlRoundsTable")
COUNTERS_TABLE = os.environ.get("FL_COUNTERS_TABLE", "FlUploadCountersTable")

_lambda_client = boto3.client("lambda", region_name=REGION)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _response(status: int, payload: dict) -> dict:
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(payload)}


def lambda_handler(event, context):
    if event.get("_background_train"):
        return _run_training_background(event)

    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")

    if method == "OPTIONS":
        return _response(204, {})

    store = AWSObjectStore(bucket_name=BUCKET_NAME, region=REGION)
    metadata = AWSMetadataStore(ROUNDS_TABLE, COUNTERS_TABLE, region=REGION)

    try:
        if method == "GET" and path == "/health":
            return _response(
                200, {"ok": True, "service": "Federated Disease Detection API", "mode": "AWS"}
            )

        if method == "GET" and path == "/rounds":
            return _response(200, build_rounds_response(metadata))

        if method == "GET" and path == "/presets":
            return _response(200, {"presets": PATIENT_PRESETS})

        if method == "GET" and path == "/clients":
            return _response(200, {"clients": get_clients_metadata()})

        if method == "POST" and path == "/predict":
            body = event.get("body") or "{}"
            payload = json.loads(body)
            return _response(200, build_prediction_response(payload=payload, store=store))

        if method == "POST" and path == "/train":
            body = event.get("body") or "{}"
            payload = json.loads(body)
            rounds = max(1, int(payload.get("rounds", 1)))
            async_payload = json.dumps({"_background_train": True, "rounds": rounds})
            _lambda_client.invoke(
                FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
                InvocationType="Event",
                Payload=async_payload.encode("utf-8"),
            )
            return _response(202, {"ok": True, "message": f"Training started for {rounds} round(s)."})

        return _response(404, {"error": "Not found"})

    except RequestValidationError as exc:
        return _response(400, {"error": str(exc)})
    except FileNotFoundError:
        return _response(404, {"error": "No trained global model found yet."})
    except json.JSONDecodeError:
        return _response(400, {"error": "Malformed JSON body"})
    except Exception as exc:  # noqa: BLE001 -- return a graceful error, not a raw 500 trace
        return _response(500, {"error": "Request failed", "details": str(exc)})


def _run_training_background(event):
    rounds = int(event.get("rounds", 1))
    config = load_local_config()
    store = AWSObjectStore(bucket_name=BUCKET_NAME, region=REGION)
    metadata = AWSMetadataStore(ROUNDS_TABLE, COUNTERS_TABLE, region=REGION)

    state = metadata.load_state()
    existing_rounds = [int(r) for r in state.get("rounds", {}).keys()]
    current_round = max(existing_rounds) if existing_rounds else 0

    for offset in range(1, rounds + 1):
        round_number = current_round + offset
        metadata.begin_round(
            round_number=round_number,
            expected_clients=config.client_ids,
            timeout_seconds=config.timeout_seconds,
        )
        for client_id in config.client_ids:
            train_and_upload_for_round(
                client_id=client_id,
                round_number=round_number,
                store=store,
                local_epochs=config.local_epochs,
                learning_rate=config.learning_rate,
            )
        time.sleep(2)  # brief pause so each round's S3-triggered aggregation has time to fire

    return {"statusCode": 200, "body": json.dumps({"ok": True, "rounds_run": rounds})}
