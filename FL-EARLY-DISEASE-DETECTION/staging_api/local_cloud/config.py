"""Configuration helpers for local FL runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fl_core.dataset import REPO_ROOT


DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "fl_config.json"
DEFAULT_CLIENT_IDS = ["hospital_1", "hospital_2", "hospital_3"]


@dataclass(frozen=True)
class LocalFLConfig:
    client_ids: list[str]
    total_rounds: int = 8
    timeout_seconds: int = 300
    local_epochs: int = 35
    learning_rate: float = 0.05


def load_local_config(path: Path = DEFAULT_CONFIG_PATH) -> LocalFLConfig:
    if not path.exists():
        return LocalFLConfig(client_ids=DEFAULT_CLIENT_IDS)

    payload = json.loads(path.read_text(encoding="utf-8"))
    return LocalFLConfig(
        client_ids=list(payload.get("client_ids", DEFAULT_CLIENT_IDS)),
        total_rounds=int(payload.get("total_rounds", 8)),
        timeout_seconds=int(payload.get("timeout_seconds", 300)),
        local_epochs=int(payload.get("local_epochs", 35)),
        learning_rate=float(payload.get("learning_rate", 0.05)),
    )
