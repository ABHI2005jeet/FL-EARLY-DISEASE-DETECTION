"""Real S3-backed object store, matching LocalObjectStore's public interface.

IAM enforces access control on the real bucket (see infra/iam_policies/), so
unlike LocalObjectStore this class does not re-implement assert_allowed/audit
logging locally -- CloudTrail on the bucket is the real audit log.
"""

from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError


class AWSObjectStore:
    """Drop-in replacement for LocalObjectStore backed by a real S3 bucket."""

    def __init__(
        self,
        bucket_name: str,
        region: str = "eu-north-1",
        default_encryption: str = "AES256",
    ) -> None:
        self.bucket = bucket_name
        self.default_encryption = default_encryption
        self.client = boto3.client("s3", region_name=region)

    def put_json(
        self,
        *,
        actor: str,
        key: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        envelope = {
            "metadata": {
                "server_side_encryption": self.default_encryption,
                "kms_key_id": None,
                **(metadata or {}),
            },
            "payload": payload,
        }
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(envelope, indent=2).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption=self.default_encryption,
        )

    def get_json(self, *, actor: str, key: str) -> dict[str, Any]:
        envelope = self.get_envelope(actor=actor, key=key)
        return envelope["payload"]

    def get_envelope(self, *, actor: str, key: str) -> dict[str, Any]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(key) from exc
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def list_keys(self, *, actor: str, prefix: str) -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return sorted(keys)

    def clear(self) -> None:
        # Deliberately disabled: this points at a real bucket, not a scratch
        # local directory. Delete objects manually via the console/CLI if you
        # really need to reset the real bucket between test runs.
        raise NotImplementedError("clear() is disabled for AWSObjectStore -- see docstring")
