"""AWS Lambda handler behind API Gateway (HTTP API, payload format 2.0).

Exposes:
    GET  /health
    GET  /rounds   -- round-by-round training history
    GET  /clients  -- simulated hospital metadata
    GET  /presets  -- demo patient presets
    GET  /audit    -- S3-backed audit trail (added to match the dashboard's
                      existing audit panel, which previously only worked
                      against api/local_server.py's local /audit route)
    POST /predict  -- run inference against the current global model

DEPLOYMENT: zip this file together with the project's fl_core/, aggregator/,
api/, clients/, local_cloud/, scripts/, config/ folders and data/processed/,
all from the project root. Upload as the Lambda's code source and set
Handler to `handler.lambda_handler`. Runtime: Python 3.12.

Set these Lambda environment variables:
    FL_BUCKET_NAME   -- e.g. fl-heart-disease-aps2
    AWS_REGION       -- e.g. ap-south-2
    FL_ROUNDS_TABLE, FL_COUNTERS_TABLE -- optional, default to the standard names

Attach infra/iam_policies/lambda_api_role.json to this Lambda's execution role.
Note: /train from the local dev server is intentionally NOT exposed here --
a full multi-round training run doesn't fit inside an API Gateway request
timeout. Training happens via hospital uploads + the aggregator Lambda.
"""

from __future__ import annotations

import json
import os

from api.local_server import (
    PATIENT_PRESETS,
    RequestValidationError,
    build_prediction_response,
    build_rounds_response,
    get_clients_metadata,
)
from local_cloud.aws_metadata_store import AWSMetadataStore
from local_cloud.aws_object_store import AWSObjectStore

REGION = os.environ.get("AWS_REGION", "eu-north-1")
BUCKET_NAME = os.environ["FL_BUCKET_NAME"]
ROUNDS_TABLE = os.environ.get("FL_ROUNDS_TABLE", "FlRoundsTable")
COUNTERS_TABLE = os.environ.get("FL_COUNTERS_TABLE", "FlUploadCountersTable")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _response(status: int, payload: dict) -> dict:
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(payload)}


def lambda_handler(event, context):
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

        if method == "GET" and path == "/audit":
            return _response(200, {"events": store.get_audit_logs()})

        if method == "POST" and path == "/predict":
            body = event.get("body") or "{}"
            payload = json.loads(body)
            return _response(200, build_prediction_response(payload=payload, store=store))

        return _response(404, {"error": "Not found"})

    except RequestValidationError as exc:
        return _response(400, {"error": str(exc)})
    except FileNotFoundError:
        return _response(404, {"error": "No trained global model found yet."})
    except json.JSONDecodeError:
        return _response(400, {"error": "Malformed JSON body"})
    except Exception as exc:  # noqa: BLE001 -- return a graceful error, not a raw 500 trace
        return _response(500, {"error": "Request failed", "details": str(exc)})