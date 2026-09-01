"""Local S3-style object store with SSE-S3 and IAM behavior mocked."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from local_cloud.cloudtrail import LocalCloudTrail
from local_cloud.iam import AccessDenied, assert_allowed
from local_cloud.paths import AUDIT_LOG_PATH, OBJECT_STORE_DIR


class LocalObjectStore:
    """Store JSON objects under runtime/local_cloud/s3.

    Every object is wrapped with metadata that records default SSE-S3 style
    encryption. This is a local proof only; it does not encrypt bytes at rest.
    """

    def __init__(
        self,
        root: Path = OBJECT_STORE_DIR,
        audit_log_path: Path = AUDIT_LOG_PATH,
        default_encryption: str = "AES256",
    ) -> None:
        self.root = root
        self.default_encryption = default_encryption
        self.audit = LocalCloudTrail(audit_log_path)

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def put_json(
        self,
        *,
        actor: str,
        key: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            assert_allowed(actor, "PutObject", key)
            path = self._path_for_key(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            envelope = {
                "metadata": {
                    "server_side_encryption": self.default_encryption,
                    "kms_key_id": None,
                    **(metadata or {}),
                },
                "payload": payload,
            }
            path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
            self.audit.log(actor=actor, action="PutObject", resource=key, status="success")
        except AccessDenied as exc:
            self.audit.log(
                actor=actor,
                action="PutObject",
                resource=key,
                status="denied",
                details={"error": str(exc)},
            )
            raise

    def get_json(self, *, actor: str, key: str) -> dict[str, Any]:
        try:
            assert_allowed(actor, "GetObject", key)
            path = self._path_for_key(key)
            envelope = json.loads(path.read_text(encoding="utf-8"))
            self.audit.log(actor=actor, action="GetObject", resource=key, status="success")
            return envelope["payload"]
        except AccessDenied as exc:
            self.audit.log(
                actor=actor,
                action="GetObject",
                resource=key,
                status="denied",
                details={"error": str(exc)},
            )
            raise
        except FileNotFoundError:
            self.audit.log(actor=actor, action="GetObject", resource=key, status="not_found")
            raise

    def get_envelope(self, *, actor: str, key: str) -> dict[str, Any]:
        assert_allowed(actor, "GetObject", key)
        return json.loads(self._path_for_key(key).read_text(encoding="utf-8"))

    def list_keys(self, *, actor: str, prefix: str) -> list[str]:
        try:
            assert_allowed(actor, "ListObjects", prefix)
            root = self._path_for_key(prefix)
            if not root.exists():
                self.audit.log(actor=actor, action="ListObjects", resource=prefix, status="success")
                return []

            keys = [
                path.relative_to(self.root).as_posix()
                for path in root.rglob("*.json")
                if path.is_file()
            ]
            self.audit.log(actor=actor, action="ListObjects", resource=prefix, status="success")
            return sorted(keys)
        except AccessDenied as exc:
            self.audit.log(
                actor=actor,
                action="ListObjects",
                resource=prefix,
                status="denied",
                details={"error": str(exc)},
            )
            raise

    def _path_for_key(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key or ".." in Path(key).parts:
            raise ValueError(f"Invalid object key: {key}")
        return self.root / Path(*key.split("/"))
