"""Download, clean, and split Phase 1 data into simulated hospital clients."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fl_core.dataset import prepare_phase1_data


def main() -> None:
    summary = prepare_phase1_data(client_count=3, seed=42)
    print(f"source={summary.source_path}")
    print(f"clean_rows={summary.total_clean_rows}")
    for client_id, count in summary.client_counts.items():
        print(f"{client_id}_rows={count}")


if __name__ == "__main__":
    main()
