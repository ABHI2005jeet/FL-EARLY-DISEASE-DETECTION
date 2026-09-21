# Local Phase 2/3 Implementation

This stage finishes the Phase 2 and Phase 3 application logic locally before any AWS deployment.

## Local AWS Mocks

| AWS concept | Local implementation |
| --- | --- |
| S3 model bucket | `runtime/local_cloud/s3` through `local_cloud/object_store.py` |
| SSE-S3 encryption | Object metadata records `server_side_encryption=AES256` and no KMS key |
| DynamoDB round metadata | `runtime/local_cloud/dynamodb/rounds.json` through `local_cloud/metadata_store.py` |
| S3 event trigger | `aggregator/trigger.py` handles weight-upload events |
| IAM prefix scoping | `local_cloud/iam.py` blocks cross-client prefix access |
| CloudTrail | `runtime/local_cloud/cloudtrail/events.jsonl` |
| API Gateway + Lambda | `api/local_server.py` exposes local HTTP routes |

## Training Path

```text
client reads global/current_model.json
client trains on its own hospital CSV
client writes clients/<client_id>/round_XXX/weights.json
upload event increments the round counter
aggregator runs FedAvg when all uploads arrive
or aggregator runs after timeout with uploaded subset
aggregator writes global/round_XXX/model.json
aggregator updates global/current_model.json
```

The training loop stops after the configured number of rounds, default `8`, and writes `training_complete=true` to the metadata file.

## Prediction Path

```text
dashboard form
      |
      v
POST /predict on local API
      |
      v
API loads global/current_model.json
      |
      v
API returns prediction and risk percentage
```

This is intentionally separate from the training path.

## Run Locally

```powershell
python scripts/run_local_fl.py
python scripts/run_api_server.py
```

In another terminal:

```powershell
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3000`.

## Dropout Demo

The default local run simulates `hospital_3` dropping out of round 2:

```powershell
python scripts/run_local_fl.py
```

Disable simulated dropout:

```powershell
python scripts/run_local_fl.py --simulate-dropout ""
```

Add your own:

```powershell
python scripts/run_local_fl.py --simulate-dropout hospital_2:3,hospital_3:5
```
