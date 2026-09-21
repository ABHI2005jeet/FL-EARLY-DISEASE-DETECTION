"""Shared local runtime paths."""

from __future__ import annotations

from fl_core.dataset import REPO_ROOT


LOCAL_RUNTIME_DIR = REPO_ROOT / "runtime" / "local_cloud"
OBJECT_STORE_DIR = LOCAL_RUNTIME_DIR / "s3"
METADATA_PATH = LOCAL_RUNTIME_DIR / "dynamodb" / "rounds.json"
AUDIT_LOG_PATH = LOCAL_RUNTIME_DIR / "cloudtrail" / "events.jsonl"
