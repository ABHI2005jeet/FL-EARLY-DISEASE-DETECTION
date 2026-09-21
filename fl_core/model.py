"""Small pure-Python logistic regression used by local FL clients."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Sequence

from fl_core.dataset import FEATURE_COLUMNS, TARGET_COLUMN


@dataclass(frozen=True)
class TrainResult:
    client_id: str
    model: dict[str, object]
    train_size: int
    test_size: int
    accuracy: float


def _sigmoid(score: float) -> float:
    if score < -35:
        return 0.0
    if score > 35:
        return 1.0
    return 1.0 / (1.0 + math.exp(-score))


def _normalized_features(
    row: dict[str, float],
    normalization: dict[str, dict[str, float]],
) -> list[float]:
    means = normalization["means"]
    stds = normalization["stds"]
    return [(row[column] - means[column]) / stds[column] for column in FEATURE_COLUMNS]


def zero_model() -> dict[str, object]:
    """Return the initial global model before any client has trained."""

    return {
        "feature_columns": FEATURE_COLUMNS,
        "weights": [0.0 for _ in FEATURE_COLUMNS],
        "bias": 0.0,
    }


def validate_model_shape(model: dict[str, object]) -> None:
    weights = model.get("weights")
    if not isinstance(weights, list) or len(weights) != len(FEATURE_COLUMNS):
        raise ValueError("Model must contain one weight per feature column")
    if "bias" not in model:
        raise ValueError("Model must contain a bias value")


def train_test_split(
    rows: Sequence[dict[str, float]],
    test_fraction: float = 0.2,
    seed: int = 7,
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be between 0 and 1")
    if len(rows) < 5:
        raise ValueError("Need at least 5 rows to create a local train/test split")

    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    test_size = max(1, int(len(shuffled) * test_fraction))
    return shuffled[test_size:], shuffled[:test_size]


def fit_logistic_regression(
    rows: Sequence[dict[str, float]],
    normalization: dict[str, dict[str, float]],
    epochs: int = 250,
    learning_rate: float = 0.08,
    initial_model: dict[str, object] | None = None,
) -> dict[str, object]:
    """Train a binary logistic regression model with online gradient descent."""

    if epochs < 1:
        raise ValueError("epochs must be at least 1")
    if learning_rate <= 0:
        raise ValueError("learning_rate must be positive")

    if initial_model is None:
        weights = [0.0 for _ in FEATURE_COLUMNS]
        bias = 0.0
    else:
        validate_model_shape(initial_model)
        weights = [float(value) for value in initial_model["weights"]]
        bias = float(initial_model["bias"])

    for _ in range(epochs):
        for row in rows:
            features = _normalized_features(row, normalization)
            target = row[TARGET_COLUMN]
            prediction = _sigmoid(sum(w * x for w, x in zip(weights, features)) + bias)
            error = prediction - target

            for index, value in enumerate(features):
                weights[index] -= learning_rate * error * value
            bias -= learning_rate * error

    return {
        "feature_columns": FEATURE_COLUMNS,
        "weights": weights,
        "bias": bias,
    }


def predict_probability(
    model: dict[str, object],
    row: dict[str, float],
    normalization: dict[str, dict[str, float]],
) -> float:
    validate_model_shape(model)
    weights = [float(value) for value in model["weights"]]
    bias = float(model["bias"])
    features = _normalized_features(row, normalization)
    return _sigmoid(sum(w * x for w, x in zip(weights, features)) + bias)


def evaluate_accuracy(
    model: dict[str, object],
    rows: Sequence[dict[str, float]],
    normalization: dict[str, dict[str, float]],
) -> float:
    if not rows:
        raise ValueError("Cannot evaluate on an empty row set")

    correct = 0
    for row in rows:
        predicted = 1.0 if predict_probability(model, row, normalization) >= 0.5 else 0.0
        if predicted == row[TARGET_COLUMN]:
            correct += 1
    return correct / len(rows)


def train_local_model(
    client_id: str,
    rows: Sequence[dict[str, float]],
    normalization: dict[str, dict[str, float]],
    epochs: int = 250,
    learning_rate: float = 0.08,
    split_seed: int = 7,
    initial_model: dict[str, object] | None = None,
) -> TrainResult:
    train_rows, test_rows = train_test_split(rows, seed=split_seed)
    model = fit_logistic_regression(
        train_rows,
        normalization=normalization,
        epochs=epochs,
        learning_rate=learning_rate,
        initial_model=initial_model,
    )
    accuracy = evaluate_accuracy(model, test_rows, normalization)
    return TrainResult(
        client_id=client_id,
        model=model,
        train_size=len(train_rows),
        test_size=len(test_rows),
        accuracy=accuracy,
    )
