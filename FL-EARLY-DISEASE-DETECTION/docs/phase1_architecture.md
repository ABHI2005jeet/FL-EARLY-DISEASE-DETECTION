# Phase 1 Architecture

Phase 1 is a local-only proof of the federated learning flow. It proves that each simulated hospital can train on its own data split and that the cloud-side aggregator can average model weights without reading hospital records.

```text
UCI Heart Disease processed Cleveland data
        |
        v
scripts/prepare_data.py
        |
        +--> data/processed/hospital_1.csv --> clients/train_hospital_1.py
        +--> data/processed/hospital_2.csv --> clients/train_hospital_2.py
        +--> data/processed/hospital_3.csv --> clients/train_hospital_3.py
                                                |
                                                v
                                      local model weights only
                                                |
                                                v
                                      aggregator/fedavg.py
                                                |
                                                v
                                      averaged global weights
```

## What Is Proven

- The dataset can be loaded, cleaned, and split into 3 deterministic hospital partitions.
- Each hospital trains a basic logistic regression model locally.
- Each hospital prints a local holdout accuracy.
- The aggregator receives model weights, not raw patient rows.
- FedAvg can produce a single averaged global model weight set.

## What Is Intentionally Not In Phase 1

- No AWS deployment.
- No S3 model uploads.
- No DynamoDB round counters.
- No Lambda trigger logic.
- No API Gateway or live dashboard data.

Those belong to Phase 2 and Phase 3.
