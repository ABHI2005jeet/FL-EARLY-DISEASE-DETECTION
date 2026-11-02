"""CloudTrail-style JSONL audit logging for local runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_cloud.paths import AUDIT_LOG_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalCloudTrail:
    def __init__(self, log_path: Path = AUDIT_LOG_PATH) -> None:
        self.log_path = log_path

    def log(
        self,
        *,
        actor: str,
        action: str,
        resource: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": utc_now(),
            "actor": actor,
            "action": action,
            "resource": resource,
            "status": status,
            "details": details or {},
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
