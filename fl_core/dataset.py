"""Dataset loading and client partitioning for Phase 1.

The Phase 1 prototype uses the UCI Heart Disease processed Cleveland dataset.
Only local CSV files are written; later phases can replace this with S3-backed
client prefixes without changing the client training interface.
"""

from __future__ import annotations

import csv
import json
import random
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = REPO_ROOT / "data" / "processed"
RAW_HEART_PATH = RAW_DATA_DIR / "processed.cleveland.data"
NORMALIZATION_PATH = PROCESSED_DATA_DIR / "normalization.json"
UCI_HEART_URL = (
    "https://archive.ics.uci.edu/ml/machine-learning-databases/"
    "heart-disease/processed.cleveland.data"
)

FEATURE_COLUMNS = [
    "age",
    "sex",
    "cp",
    "trestbps",
    "chol",
    "fbs",
    "restecg",
    "thalach",
    "exang",
    "oldpeak",
    "slope",
    "ca",
    "thal",
]
TARGET_COLUMN = "target"
CSV_COLUMNS = [*FEATURE_COLUMNS, TARGET_COLUMN]


@dataclass(frozen=True)
class DatasetSummary:
    source_path: Path
    total_clean_rows: int
    client_counts: dict[str, int]


def client_split_path(client_id: str) -> Path:
    return PROCESSED_DATA_DIR / f"{client_id}.csv"


def download_uci_heart_dataset(destination: Path = RAW_HEART_PATH) -> Path:
    """Download the processed Cleveland data file when it is not present."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    with urllib.request.urlopen(UCI_HEART_URL, timeout=30) as response:
        payload = response.read()

    destination.write_bytes(payload)
    return destination


def parse_uci_heart_rows(raw_path: Path = RAW_HEART_PATH) -> list[dict[str, float]]:
    """Load UCI rows and convert the target to a binary disease-present label."""

    rows: list[dict[str, float]] = []
    with raw_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for raw_row in reader:
            if not raw_row:
                continue
            if len(raw_row) != len(FEATURE_COLUMNS) + 1:
                raise ValueError(f"Unexpected UCI row width: {len(raw_row)}")
            if "?" in raw_row:
                continue

            features = [float(value) for value in raw_row[:-1]]
            target = 1.0 if int(float(raw_row[-1])) > 0 else 0.0
            rows.append(dict(zip(CSV_COLUMNS, [*features, target], strict=True)))

    if not rows:
        raise ValueError(f"No clean rows loaded from {raw_path}")

    return rows


def write_client_splits(
    rows: list[dict[str, float]],
    client_count: int = 3,
    seed: int = 42,
    output_dir: Path = PROCESSED_DATA_DIR,
) -> dict[str, int]:
    """Shuffle and partition rows into deterministic simulated hospital splits."""

    if client_count < 1:
        raise ValueError("client_count must be at least 1")

    output_dir.mkdir(parents=True, exist_ok=True)
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)

    counts: dict[str, int] = {}
    split_rows: dict[str, list[dict[str, float]]] = {
        f"hospital_{index + 1}": [] for index in range(client_count)
    }
    client_ids = list(split_rows.keys())

    for index, row in enumerate(shuffled):
        split_rows[client_ids[index % client_count]].append(row)

    for client_id, client_rows in split_rows.items():
        path = output_dir / f"{client_id}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(client_rows)
        counts[client_id] = len(client_rows)

    return counts


def compute_normalization(rows: Iterable[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Compute feature means and standard deviations used by local clients."""

    materialized = list(rows)
    if not materialized:
        raise ValueError("Cannot compute normalization for an empty dataset")

    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for column in FEATURE_COLUMNS:
        values = [row[column] for row in materialized]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        std = variance**0.5
        means[column] = mean
        stds[column] = std if std > 0 else 1.0

    return {"means": means, "stds": stds}


def write_normalization(
    rows: list[dict[str, float]],
    output_path: Path = NORMALIZATION_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalization = compute_normalization(rows)
    output_path.write_text(json.dumps(normalization, indent=2), encoding="utf-8")
    return output_path


def load_client_rows(client_id: str, processed_dir: Path = PROCESSED_DATA_DIR) -> list[dict[str, float]]:
    path = processed_dir / f"{client_id}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing client split {path}. Run `python scripts/prepare_data.py` first."
        )

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {column: float(value) for column, value in row.items()}
            for row in reader
        ]


def load_normalization(path: Path = NORMALIZATION_PATH) -> dict[str, dict[str, float]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing normalization file {path}. Run `python scripts/prepare_data.py` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_phase1_data(client_count: int = 3, seed: int = 42) -> DatasetSummary:
    raw_path = download_uci_heart_dataset()
    rows = parse_uci_heart_rows(raw_path)
    counts = write_client_splits(rows, client_count=client_count, seed=seed)
    write_normalization(rows)
    return DatasetSummary(
        source_path=raw_path,
        total_clean_rows=len(rows),
        client_counts=counts,
    )
