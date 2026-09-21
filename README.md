# Federated Learning for Early Disease Detection

Cloud-orchestrated prototype for privacy-preserving collaborative training across simulated hospital nodes.

## Current Status

Phase 1 is complete:

- Repo structure for clients, aggregator, dashboard, API, and infra.
- UCI Heart Disease Cleveland dataset loader.
- Deterministic partitioning into 3 simulated hospital client splits.
- Local training script for each client using a simple logistic regression model.
- FedAvg aggregator function signature and implementation for averaging model weights.
- Phase 1 architecture notes, viva notes, completion checklist, and sample output.

Local Phase 2/3 code is implemented:

- Multi-round FedAvg loop with configurable stopping condition.
- Local S3/DynamoDB/IAM/CloudTrail mocks for testing without AWS cost.
- Upload-triggered aggregation flow with timeout/dropout fallback.
- Round-by-round local/global accuracy and skipped-client tracking.
- Local dashboard backend with `GET /rounds` and `POST /predict`.
- Next.js dashboard for charts, predictions, and participation history.

Real AWS deployment is intentionally still pending.

## Dataset

Phase 1 uses the UCI Heart Disease dataset, specifically the processed Cleveland file. The multiclass `num` target is converted to binary:

- `0`: no heart disease presence
- `1`: heart disease presence (`num` values 1-4)

Rows with missing values are dropped during Phase 1 preparation.

## Run Phase 1 Locally

```powershell
python scripts/prepare_data.py
python clients/train_hospital_1.py
python clients/train_hospital_2.py
python clients/train_hospital_3.py
```

Or run the whole Phase 1 local proof:

```powershell
python scripts/run_phase1.py
```

Expected output includes the number of records per client, each client's local holdout accuracy, and a FedAvg smoke-test over the trained local model weights.

The reusable command-line version is also available:

```powershell
python clients/train_client.py --client hospital_1
python clients/train_client.py --client hospital_2
python clients/train_client.py --client hospital_3
```

## Run Local Phase 2/3

Run the full local federated pipeline:

```powershell
python scripts/run_local_fl.py
```

By default this runs 8 rounds and simulates `hospital_3` dropping out in round 2. To run without a dropout:

```powershell
python scripts/run_local_fl.py --simulate-dropout ""
```

Start the local dashboard API:

```powershell
python scripts/run_api_server.py
```

API Routes exposed:
- `GET /health` — Service health check
- `GET /rounds` — Full DynamoDB round metadata, convergence scores, and skipped clients
- `GET /audit` — Real-time CloudTrail security audit events stream
- `GET /presets` — Curated 1-click patient clinical archetypes
- `GET /clients` — Hospital node metadata, IAM prefix scopes, and sample counts
- `POST /predict` — High-speed clinical inference against encrypted S3 global weights with biomarker risk flags
- `POST /train` — Trigger a fresh multi-round FL simulation run directly from the browser

Quick API checks from another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/rounds
Invoke-RestMethod http://127.0.0.1:8000/audit
Invoke-RestMethod http://127.0.0.1:8000/presets
```

Test live prediction:
```powershell
$body = @{
  features = @{
    age = 54; sex = 1; cp = 3; trestbps = 130; chol = 246; fbs = 0;
    restecg = 0; thalach = 150; exang = 0; oldpeak = 1.0; slope = 1;
    ca = 0; thal = 3
  }
} | ConvertTo-Json -Depth 3
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/predict -ContentType 'application/json' -Body $body
```

Start the Next.js Cyberpunk-Medical Dashboard:

```powershell
cd dashboard
npm run dev
```

Open **`http://localhost:3000`** in your browser.

## Dashboard Highlights

- 📊 **Interactive FedAvg Convergence Chart**: Dual-curve SVG visualization showing Global Consensus vs Local Hospital accuracy, with gradient area glows and dropout event flags.
- 🩺 **Patient Risk Prediction Studio**: Real-time diagnostic inference with an animated radial risk gauge, 1-click clinical archetype presets, and biomarker threshold risk warnings.
- 🏥 **Hospital Nodes Inspector**: Visualizes simulated EC2 nodes (`hospital_1`, `hospital_2`, `hospital_3`), local patient split counts, and strict IAM prefix isolation boundaries (`s3://.../clients/hospital_X/`).
- 🛡️ **CloudTrail Security Audit Stream**: Real-time inspection of encrypted S3 `PutObject`/`GetObject` telemetry with verified `AES256` SSE-S3 headers and negative access prevention.
- 📐 **Cloud Architecture Blueprint**: Step-by-step interactive flow diagrams explaining zero-patient-data-egress, S3 DynamoDB triggers, and separate inference paths.
- ⚡ **In-Browser FL Simulation Trigger**: Run new multi-round federated training cycles with custom round counts and dropout configurations directly from the UI.

## Structure

```text
clients/      Simulated hospital training nodes (St. Jude, Mayo, General Heart).
aggregator/   FedAvg aggregation logic and DynamoDB upload trigger handlers.
api/          REST API backend exposing /health, /rounds, /audit, /presets, /clients, /predict, /train.
dashboard/    High-fidelity Next.js dashboard with dark glassmorphic medical theme.
infra/        AWS CDK / IaC scaffolding for real cloud deployment.
fl_core/      Shared dataset loaders, normalization, and logistic regression model math.
scripts/      CLI runners for Phase 1, Local FL pipeline, and API server.
tests/        Unit tests covering FedAvg, IAM prefix authorization, S3 encryption, and API validation.
docs/         Phase 1 checklist, architecture blueprints, viva notes, and sample outputs.
local_cloud/  Local mocks for S3 (SSE-S3), DynamoDB, IAM prefix guards, and CloudTrail audit logging.
config/       Federated learning hyperparameters and client node registry.
```

## Phase 1 Documentation

- `docs/phase1_architecture.md`
- `docs/phase1_completion_checklist.md`
- `docs/phase1_viva_notes.md`
- `docs/phase1_sample_output.txt`

## Local Phase 2/3 Documentation

- `docs/local_phase2_phase3.md`
- `docs/aws_remaining.md`

## Notes For Later Phases

The current local normalization statistics are created centrally during data preparation because this is a single-machine simulation. In an AWS/federated version, those statistics should be treated carefully and either computed from public constants or derived with a privacy-preserving/federated approach.

## AWS Remaining

The application is 100% functional locally with zero cloud dependencies. When ready to deploy to real AWS:

- Deploy S3 model bucket with default SSE-S3 encryption (`AES256`).
- Provision DynamoDB tables for `FlRoundsTable` and `FlUploadCountersTable`.
- Wire S3 `ObjectCreated` event notifications to the `AggregatorLambda`.
- Deploy the `ApiLambda` behind AWS API Gateway for `GET /rounds` and `POST /predict`.
- Configure per-node IAM roles scoping simulated hospital EC2 instances to strictly `clients/{hospital_id}/`.
- Deploy Next.js frontend static build to S3 + CloudFront / AWS Amplify.

-changes
