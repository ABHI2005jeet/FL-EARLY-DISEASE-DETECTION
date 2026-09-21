# Federated Learning for Early Disease Detection

Cloud-orchestrated, privacy-preserving federated learning across three simulated
hospital nodes, predicting heart disease risk from the UCI Heart Disease
(Cleveland) dataset — without any hospital's raw patient data ever leaving its
own storage.

## Current Status

Phases 0 through 5 are complete and verified against real AWS infrastructure
(not a local mock). Phase 6 (CloudTrail/CloudWatch/SNS monitoring) is not yet
built.

| Phase | What it covers | Status |
|---|---|---|
| 0-1 | Local FL logic (no AWS) — dataset prep, per-client training, FedAvg | Done |
| 2 | Manual script wired to real S3 + DynamoDB | Done |
| 3 | Automated aggregation — S3 upload triggers `fl-aggregator` Lambda | Done |
| 4 | Public HTTPS API — API Gateway + `fl-api` Lambda | Done |
| 5 | Dashboard (Next.js) deployed as a static site on Amplify Hosting | Done |
| 6 | CloudTrail / CloudWatch / SNS audit + alerting | Not started |

## Architecture

Three simulated hospitals each train a small logistic-regression-style model
on their own local slice of the dataset, then upload only the trained
**weights** — never raw patient rows — to their own private folder in S3
(`clients/<hospital_id>/round_N/weights.json`). Each hospital has its own
narrowly-scoped IAM identity that can only write to its own folder and only
read the shared global model; it cannot see another hospital's uploads.

That S3 upload automatically triggers the **aggregator Lambda**
(`fl-aggregator`) via an S3 `ObjectCreated` event. Once all three hospitals
have uploaded for a round, it runs FedAvg to combine their weights, evaluates
accuracy against a held-out test split, and writes the result to:
- S3 — `global/current_model.json` (latest) and `global/round_N/model.json` (archived)
- DynamoDB — `FlRoundsTable` (round history) and `FlUploadCountersTable` (per-round upload counts)

A separate **API Lambda** (`fl-api`), sitting behind API Gateway, exposes this
to the outside world over plain HTTPS:

| Route | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness check |
| `/rounds` | GET | Round-by-round history from DynamoDB |
| `/clients` | GET | Simulated hospital metadata |
| `/presets` | GET | Demo patient profiles for the dashboard's quick-test UI |
| `/predict` | POST | Run inference against the current global model |
| `/train` | POST | Kick off N more training rounds asynchronously (see limitation below) |

The **dashboard** (`dashboard/`, Next.js, deployed as a static export on AWS
Amplify Hosting) calls this API directly from the browser — it lives in a
different AWS region (`ap-south-1`, since Amplify Hosting isn't available in
`ap-south-2`) but that's irrelevant to how it works: it's just an ordinary
cross-region HTTPS call, no special config needed.

## `/train` and the async pattern

API Gateway HTTP APIs cap out at a 30-second request timeout, but running
several rounds of training can take longer than that. So `/train` returns
immediately (`202 Accepted`) and does the real work in a second, separate
**asynchronous self-invocation** of the same Lambda (`InvocationType=Event`),
which is bound only by the Lambda's own configured timeout (set to 300s), not
API Gateway's.

**Known limitation:** the "Simulate Node Dropout" option in the dashboard's
training dialog is not currently functional. The deployed aggregator requires
*all three* hospitals to upload before it will aggregate a round — there is no
timeout/partial-aggregation path deployed. Adding that would mean porting the
timeout-and-continue logic that already exists for the local-simulation
version (`aggregator/trigger.py`) over to the real AWS Lambda, plus a
mechanism to check back on a stalled round after a delay (Lambda has no
built-in "wait and see" primitive — this would need EventBridge or a similar
scheduled trigger). Left `/train` rounds always run with full participation.

## Repo layout

```
fl_core/       Model definition + dataset loading/normalization (pure Python, no numpy)
clients/       Simulates a hospital: trains locally, packages weights for upload
aggregator/    FedAvg logic + accuracy evaluation against a held-out split
api/           Shared request-handling logic used by both the local dev server and the Lambda
local_cloud/   Object store + metadata store, each with a local-file backend AND a real-AWS
               (S3/DynamoDB) backend behind the same interface -- same app code, either backend
lambda/        Deployment packages for the two Lambdas (aggregator, api) -- entry points + zips
config/        fl_config.json -- hospital IDs, round count, local epochs, learning rate
infra/         IAM policy JSON files actually attached to each identity in AWS
scripts/       Local/manual entry points (data prep, local FL run, AWS-wired FL run)
dashboard/     Next.js dashboard, deployed as a static export to Amplify Hosting
docs/          Phase-by-phase planning and architecture notes
tests/         Unit tests
```

## Deployed AWS resources

- **S3 bucket**: `fl-heart-disease-aps2` (region `ap-south-2`), SSE-S3 (AES-256) default encryption
- **DynamoDB tables**: `FlRoundsTable`, `FlUploadCountersTable` (region `ap-south-2`)
- **Lambdas**: `fl-aggregator` (S3-triggered), `fl-api` (API Gateway-triggered) — both region `ap-south-2`
- **API Gateway**: HTTP API, `fl-api-gateway`, region `ap-south-2`
- **IAM users**: `hospital_1`, `hospital_2`, `hospital_3` — each scoped to their own S3 prefix only
- **IAM roles**: `fl-aggregator-role`, `fl-api-role` — see `infra/iam_policies/` for the intended
  least-privilege policies. In practice, `AmazonS3FullAccess` and `AmazonDynamoDBFullAccess`
  (AWS-managed policies) are also attached to both roles, added incrementally while debugging
  permission gaps during development. The inline policies in this repo describe the intended
  minimum scope; the managed policies currently attached are broader than that in the live
  account.
- **Amplify app**: `fl-dashboard`, region `ap-south-1` (Amplify Hosting is not available in
  `ap-south-2`)

## Running it yourself

### Local, no AWS

```powershell
python scripts/prepare_data.py
python scripts/run_local_fl.py
python scripts/run_api_server.py   # local dev server exposing the same routes as the Lambda
```

### Against real AWS

Requires the S3 bucket, DynamoDB tables, and IAM users/roles above to already exist.

```powershell
$env:FL_BUCKET_NAME = "fl-heart-disease-aps2"
$env:AWS_REGION = "ap-south-2"
python scripts/run_aws_fl.py --rounds 1
```

Or trigger a round without touching your local machine, via the deployed API:

```powershell
Invoke-WebRequest -Uri "https://kl58tsjkw6.execute-api.ap-south-2.amazonaws.com/train" `
  -Method POST -ContentType "application/json" -Body '{"rounds": 1}' -UseBasicParsing
```

### Deploying Lambda code changes

Both Lambdas are deployed as plain zip uploads (no layers, no external pip
dependencies beyond `boto3`, which ships with the Lambda runtime). **Build the
zip with Python's `zipfile` module, not PowerShell's `Compress-Archive`** --
`Compress-Archive` (and even .NET's `ZipFile.CreateFromDirectory`) has been
observed to write backslash path separators into the archive on Windows,
which silently breaks nested folders once deployed (see `docs/` for the full
debugging writeup). A working build looks like:

```powershell
python -c "
import zipfile, os
with zipfile.ZipFile('lambda/api/api_deploy.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('deploy_stage'):
        for f in files:
            full = os.path.join(root, f)
            zf.write(full, os.path.relpath(full, 'deploy_stage').replace(os.sep, '/'))
"
aws lambda update-function-code --function-name fl-api --zip-file fileb://lambda/api/api_deploy.zip --region ap-south-2
```

See each Lambda's own docstring (`lambda/aggregator/handler.py`,
`lambda/api/handler.py`) for the exact folder set each zip needs to contain.

### Deploying the dashboard

The dashboard builds as a static export (`output: "export"` in
`next.config.js`) and deploys to Amplify Hosting via manual zip upload — same
backslash-path caveat as above applies, so build the zip with Python's
`zipfile`, not `Compress-Archive`.

```powershell
cd dashboard
npm install
npm run build
python ../build_zip.py   # or equivalent -- see deployment notes above
aws amplify create-deployment --app-id d27bxeyf5b5sth --branch-name main --region ap-south-1
# upload the zip to the returned zipUploadUrl, then:
aws amplify start-deployment --app-id d27bxeyf5b5sth --branch-name main --job-id <jobId> --region ap-south-1
```

## Dataset

UCI Heart Disease dataset, Cleveland subset. The multiclass `num` target is
converted to binary:
- `0`: no heart disease presence
- `1`: heart disease presence (`num` values 1-4)

Rows with missing values are dropped during data preparation. The 13 clinical
features used are: `age`, `sex`, `cp`, `trestbps`, `chol`, `fbs`, `restecg`,
`thalach`, `exang`, `oldpeak`, `slope`, `ca`, `thal`.
