"""Real S3-backed object store, matching LocalObjectStore's public interface.

This version also writes a lightweight audit trail to S3 itself
(audit/events.jsonl in the same bucket) on every put/get, in the same
{timestamp, actor, action, resource, status, details} shape the dashboard's
/audit panel already expects (see local_cloud/cloudtrail.py's local
equivalent, and api/local_server.py's get_audit_logs()).

Caveat, stated plainly: S3 has no atomic "append" operation, so this does a
read-modify-write on one JSON-lines object. Under genuinely concurrent
Lambda invocations (e.g. 3 hospitals uploading within milliseconds of each
other), it's possible for one audit entry to be lost if two writes race.
This does NOT affect training correctness -- FlUploadCountersTable's atomic
counter (see aws_metadata_store.py) is the real source of truth for "have
all hospitals uploaded". This audit log is a best-effort visibility feature,
not a security control, and should not be treated as a complete guarantee
the way real AWS CloudTrail data events would be.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

AUDIT_LOG_KEY = "audit/events.jsonl"
AUDIT_LOG_MAX_ENTRIES = 500  # keep the object from growing unbounded


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
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(envelope, indent=2).encode("utf-8"),
                ContentType="application/json",
                ServerSideEncryption=self.default_encryption,
            )
        except ClientError as exc:
            self._record_audit(actor=actor, action="PutObject", resource=key, status="Denied",
                                details={"error": str(exc)})
            raise
        self._record_audit(actor=actor, action="PutObject", resource=key, status="Allowed",
                            details={"encryption": self.default_encryption})

    def get_json(self, *, actor: str, key: str) -> dict[str, Any]:
        envelope = self.get_envelope(actor=actor, key=key)
        return envelope["payload"]

    def get_envelope(self, *, actor: str, key: str) -> dict[str, Any]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            status = "NotFound" if error_code in {"NoSuchKey", "404"} else "Denied"
            self._record_audit(actor=actor, action="GetObject", resource=key, status=status,
                                details={"error": str(exc)})
            if error_code in {"NoSuchKey", "404"}:
                raise FileNotFoundError(key) from exc
            raise
        self._record_audit(actor=actor, action="GetObject", resource=key, status="Allowed")
        return json.loads(response["Body"].read().decode("utf-8"))

    def list_keys(self, *, actor: str, prefix: str) -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return sorted(keys)

    def clear(self) -> None:
        raise NotImplementedError("clear() is disabled for AWSObjectStore -- see docstring")

    # ---- audit log (S3-backed, best-effort -- see module docstring) -------

    def _record_audit(
        self,
        *,
        actor: str,
        action: str,
        resource: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        # Never let audit logging break the actual operation it's observing.
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "action": action,
                "resource": resource,
                "status": status,
                "details": details or {},
            }
            try:
                response = self.client.get_object(Bucket=self.bucket, Key=AUDIT_LOG_KEY)
                existing = response["Body"].read().decode("utf-8").splitlines()
            except ClientError:
                existing = []
            existing.append(json.dumps(entry))
            existing = existing[-AUDIT_LOG_MAX_ENTRIES:]
            self.client.put_object(
                Bucket=self.bucket,
                Key=AUDIT_LOG_KEY,
                Body=("\n".join(existing) + "\n").encode("utf-8"),
                ContentType="application/x-ndjson",
                ServerSideEncryption=self.default_encryption,
            )
        except Exception:
            pass

    def get_audit_logs(self, limit: int = 40) -> list[dict[str, Any]]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=AUDIT_LOG_KEY)
        except ClientError:
            return []
        lines = response["Body"].read().decode("utf-8").splitlines()
        events = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events[-limit:][::-1]