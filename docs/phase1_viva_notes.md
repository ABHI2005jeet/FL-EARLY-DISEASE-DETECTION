# Phase 1 Viva Notes

## One-Line Summary

This phase simulates three hospitals training locally on separate patient-data partitions, then sends only model weights to a FedAvg aggregator.

## Why Federated Learning

In a normal centralized ML setup, hospitals would upload raw patient records to one server. In this prototype, each hospital keeps its local CSV split and only shares learned model parameters. That demonstrates the privacy-preserving pattern.

## Dataset Choice

We use the UCI Heart Disease processed Cleveland dataset because it is small, tabular, public, and suitable for a quick disease-presence classification demo. The original target has values `0` to `4`; Phase 1 converts it to binary:

- `0`: no disease presence
- `1`: disease presence

Rows with missing values are dropped.

## Model Choice

The model is simple logistic regression implemented with Python standard library code. That keeps the focus on the federated-learning workflow rather than model complexity.

## What FedAvg Does

Each client trains its own model and produces weights and a bias. FedAvg averages those weights into one global model. In Phase 1 this happens locally as a smoke test; in Phase 2 the same concept will happen through S3/Lambda/DynamoDB orchestration.

## How To Explain The Privacy Boundary

Raw rows live in `data/processed/hospital_*.csv`. The aggregator does not read those CSVs directly in the intended FL boundary. It only needs the model dictionaries shaped like:

```text
{"weights": [...], "bias": ...}
```

## Phase 1 Limitation

This is a local proof. It does not yet prove AWS permissions, S3 triggers, DynamoDB counters, dropout handling, or dashboard APIs. Those are the hard parts of Phase 2 and Phase 3.
