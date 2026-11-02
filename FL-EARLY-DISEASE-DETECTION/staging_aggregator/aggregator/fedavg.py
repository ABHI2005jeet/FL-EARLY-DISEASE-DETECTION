"""Federated averaging logic for model weights."""

from __future__ import annotations

from collections.abc import Sequence


def fedavg(
    weight_sets: Sequence[dict[str, object]],
    example_counts: Sequence[int] | None = None,
) -> dict[str, object]:
    """Average N model weight sets and return a new global weight set.

    Args:
        weight_sets: Sequence of models shaped like
            {"weights": [float, ...], "bias": float}.
        example_counts: Optional per-client row counts for weighted FedAvg. When
            omitted, each client contributes equally.
    """

    if not weight_sets:
        raise ValueError("fedavg requires at least one weight set")

    weight_length = len(weight_sets[0]["weights"])
    if any(len(weight_set["weights"]) != weight_length for weight_set in weight_sets):
        raise ValueError("All weight sets must have the same weight length")

    if example_counts is None:
        factors = [1.0 / len(weight_sets) for _ in weight_sets]
    else:
        if len(example_counts) != len(weight_sets):
            raise ValueError("example_counts must match the number of weight sets")
        total_examples = sum(example_counts)
        if total_examples <= 0:
            raise ValueError("example_counts must sum to a positive value")
        factors = [count / total_examples for count in example_counts]

    averaged_weights = [
        sum(float(weight_set["weights"][index]) * factor for weight_set, factor in zip(weight_sets, factors))
        for index in range(weight_length)
    ]
    averaged_bias = sum(float(weight_set["bias"]) * factor for weight_set, factor in zip(weight_sets, factors))

    return {
        "feature_columns": weight_sets[0].get("feature_columns"),
        "weights": averaged_weights,
        "bias": averaged_bias,
    }
