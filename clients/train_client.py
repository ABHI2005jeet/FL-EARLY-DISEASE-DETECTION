"""Train a single simulated hospital client locally for Phase 1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fl_core.dataset import load_client_rows, load_normalization
from fl_core.model import train_local_model


def run_client(client_id: str, epochs: int = 250, learning_rate: float = 0.08) -> None:
    rows = load_client_rows(client_id)
    normalization = load_normalization()
    result = train_local_model(
        client_id,
        rows,
        normalization=normalization,
        epochs=epochs,
        learning_rate=learning_rate,
    )

    print(f"client={result.client_id}")
    print(f"train_size={result.train_size}")
    print(f"test_size={result.test_size}")
    print(f"local_accuracy={result.accuracy:.3f}")
    print("model_weights=" + json.dumps(result.model))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train one local hospital client.")
    parser.add_argument(
        "--client",
        default="hospital_1",
        choices=["hospital_1", "hospital_2", "hospital_3"],
        help="Client split to train.",
    )
    parser.add_argument("--epochs", type=int, default=250)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_client(args.client, epochs=args.epochs, learning_rate=args.learning_rate)


if __name__ == "__main__":
    main()
