"""Run the complete local Phase 1 proof."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aggregator.fedavg import fedavg
from fl_core.dataset import load_client_rows, load_normalization, prepare_phase1_data
from fl_core.model import train_local_model


def main() -> None:
    summary = prepare_phase1_data(client_count=3, seed=42)
    print("Prepared UCI Heart Disease client splits")
    print(f"clean_rows={summary.total_clean_rows}")

    normalization = load_normalization()
    results = []
    for client_id in sorted(summary.client_counts):
        rows = load_client_rows(client_id)
        result = train_local_model(client_id, rows, normalization)
        results.append(result)
        print(
            f"{client_id}: rows={len(rows)} "
            f"train={result.train_size} test={result.test_size} "
            f"local_accuracy={result.accuracy:.3f}"
        )

    global_model = fedavg(
        [result.model for result in results],
        [result.train_size for result in results],
    )
    print("FedAvg smoke test complete")
    print(f"global_weight_count={len(global_model['weights'])}")
    print(f"global_bias={global_model['bias']:.6f}")


if __name__ == "__main__":
    main()
