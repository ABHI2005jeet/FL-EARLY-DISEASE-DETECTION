"""Run the same federated learning pipeline as run_local_fl.py, but against
real AWS S3 + DynamoDB instead of local disk.

Required environment variables (set these before running):
    AWS_ACCESS_KEY_ID       -- from your fl-local-runner IAM user
    AWS_SECRET_ACCESS_KEY   -- from your fl-local-runner IAM user
    AWS_REGION              -- e.g. eu-north-1 (defaults to eu-north-1 if unset)
    FL_BUCKET_NAME          -- your S3 bucket, e.g. fl-heart-disease-7742

Optional:
    FL_ROUNDS_TABLE         -- defaults to FlRoundsTable
    FL_COUNTERS_TABLE       -- defaults to FlUploadCountersTable

Usage:
    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...
    export AWS_REGION=eu-north-1
    export FL_BUCKET_NAME=fl-heart-disease-7742
    python scripts/run_aws_fl.py --rounds 2
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_cloud.aws_metadata_store import AWSMetadataStore
from local_cloud.aws_object_store import AWSObjectStore
from local_cloud.config import load_local_config
from scripts.run_local_fl import run_federated_pipeline


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"Missing required environment variable: {name}\n"
            "See the module docstring in scripts/run_aws_fl.py for the full list."
        )
    return value


def parse_args() -> argparse.Namespace:
    config = load_local_config()
    parser = argparse.ArgumentParser(description="Run the FL loop against real AWS.")
    parser.add_argument("--rounds", type=int, default=config.total_rounds)
    parser.add_argument("--timeout-seconds", type=int, default=config.timeout_seconds)
    parser.add_argument("--local-epochs", type=int, default=config.local_epochs)
    parser.add_argument("--learning-rate", type=float, default=config.learning_rate)
    parser.add_argument(
        "--simulate-dropout",
        default="",
        help="Comma-separated client:round values. Empty string disables dropouts "
        "(recommended for your first real-AWS run).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    bucket_name = require_env("FL_BUCKET_NAME")
    region = os.environ.get("AWS_REGION", "eu-north-1")
    rounds_table = os.environ.get("FL_ROUNDS_TABLE", "FlRoundsTable")
    counters_table = os.environ.get("FL_COUNTERS_TABLE", "FlUploadCountersTable")

    # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are read automatically by
    # boto3 from the environment -- we just check they're present so the
    # error is clear instead of a confusing botocore NoCredentialsError.
    require_env("AWS_ACCESS_KEY_ID")
    require_env("AWS_SECRET_ACCESS_KEY")

    print(f"bucket={bucket_name} region={region}")
    print(f"rounds_table={rounds_table} counters_table={counters_table}")

    store = AWSObjectStore(bucket_name=bucket_name, region=region)
    metadata = AWSMetadataStore(
        rounds_table_name=rounds_table,
        counters_table_name=counters_table,
        region=region,
    )

    run_federated_pipeline(
        rounds=args.rounds,
        timeout_seconds=args.timeout_seconds,
        local_epochs=args.local_epochs,
        learning_rate=args.learning_rate,
        simulate_dropout=args.simulate_dropout,
        store=store,
        metadata=metadata,
    )


if __name__ == "__main__":
    main()
