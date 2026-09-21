# AWS Implementation Guide — Federated Heart Disease Detection

This is the full, phase-by-phase path from the local simulation to a real,
AWS-deployed system. Code referenced below is already included in this zip.

Your known values so far (fill in / confirm before starting):

| Setting            | Value                          |
|--------------------|---------------------------------|
| AWS region         | `eu-north-1`                    |
| S3 bucket          | `fl-heart-disease-7742`         |
| DynamoDB tables    | `FlRoundsTable`, `FlUploadCountersTable` |
| Hospital IAM users | `hospital_1`, `hospital_2`, `hospital_3` |
| Test-runner user   | `fl-local-runner`                |

---

## Phase 0 — Already done

- [x] S3 bucket created, SSE-S3 encryption, public access blocked.
- [x] 3 hospital IAM users created, each with console access + access keys.
- [x] Scoped inline policy attached to each hospital user (see
      `infra/iam_policies/hospital_1.json`, `hospital_2.json`, `hospital_3.json`
      — already filled in with your bucket name).
- [x] `FlRoundsTable` and `FlUploadCountersTable` DynamoDB tables created
      (on-demand billing, partition key `round_number`, type Number).
- [x] `fl-local-runner` IAM user created with `AmazonS3FullAccess`, for
      running the orchestrator script from your own laptop.

If any of these aren't done yet, go back and finish them before continuing —
everything below depends on them existing.

---

## Phase 1 — Local baseline (already working)

Nothing to do here except confirm it still works before layering AWS on top:

```
python scripts/run_local_fl.py --rounds 2
```

You should see rounds complete with `aggregated=true` and accuracy numbers.
This uses `LocalObjectStore`/`LocalMetadataStore` (local disk only) — no AWS
involved. This is your fallback for demoing the FL logic itself if AWS is
ever unavailable.

---

## Phase 2 — Run the real pipeline against AWS (S3 + DynamoDB)

**What changed in the code:** `local_cloud/aws_object_store.py` and
`local_cloud/aws_metadata_store.py` are new — they implement the exact same
methods as the local versions (`put_json`/`get_json`, `begin_round`/
`record_upload`/etc.) but call real S3 and DynamoDB via `boto3`.
`scripts/run_local_fl.py`'s `run_federated_pipeline()` was refactored to
accept optional `store=`/`metadata=` arguments — when omitted it behaves
exactly as before (local disk); when provided, it runs the identical
orchestration logic against whatever you pass in. `scripts/run_aws_fl.py` is
a new entry point that wires in the AWS-backed versions.

### Steps

1. On your laptop, make sure Python is installed:
   ```
   python3 --version
   ```
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   (This now includes `boto3`.)
3. Set your `fl-local-runner` credentials as environment variables:
   ```
   export AWS_ACCESS_KEY_ID=<fl-local-runner access key>
   export AWS_SECRET_ACCESS_KEY=<fl-local-runner secret key>
   export AWS_REGION=eu-north-1
   export FL_BUCKET_NAME=fl-heart-disease-7742
   ```
   (Windows PowerShell: `$env:AWS_ACCESS_KEY_ID="..."`, etc.)
4. Run:
   ```
   python scripts/run_aws_fl.py --rounds 2
   ```
5. **Verify in the console:**
   - S3 → your bucket → you should see `clients/hospital_1/round_001/weights.json`
     (and hospital_2, hospital_3) plus `global/round_001/model.json` and
     `global/current_model.json`.
   - DynamoDB → `FlRoundsTable` → "Explore table items" → you should see
     items with `round_number` 0, 1, 2, each holding a `state` JSON blob.
   - DynamoDB → `FlUploadCountersTable` → items with `round_number` 1, 2 and
     a `count` of 3 (or fewer, if you passed `--simulate-dropout`).

If this works, your code is genuinely talking to AWS end-to-end — the
hardest correctness risk in the whole project is now retired.

---

## Phase 3 — Aggregator Lambda + S3 event trigger

**What's new:** `lambda/aggregator/handler.py` — a real Lambda handler that
does what Phase 2's orchestrator script did, but triggered automatically by
an S3 upload event instead of a Python loop. A ready-to-upload zip is
already built at `lambda/aggregator/aggregator_deploy.zip` (contains the
handler plus `fl_core/`, `aggregator/`, `local_cloud/`, `clients/`,
`config/`, and `data/processed/`).

### Steps

1. **Create the Lambda's execution role first:**
   - IAM console → Roles → Create role.
   - Trusted entity type: **AWS service** → Use case: **Lambda**.
   - Click Next, skip attaching a managed policy for now, name it
     `fl-aggregator-role`, create it.
   - Open the new role → Add permissions → Create inline policy → JSON tab →
     paste the contents of `infra/iam_policies/lambda_aggregator_role.json`.
   - Name it `fl-aggregator-inline` → Create policy.
   - Also attach the AWS-managed policy `AWSLambdaBasicExecutionRole` (search
     for it under "Add permissions → Attach policies") so it can write to
     CloudWatch Logs.

2. **Create the Lambda function:**
   - Lambda console → Create function → Author from scratch.
   - Name: `fl-aggregator`.
   - Runtime: **Python 3.12**.
   - Under "Change default execution role", choose **Use an existing role**
     → select `fl-aggregator-role`.
   - Create function.

3. **Upload the code:**
   - On the function page, "Code source" panel → Upload from → .zip file →
     select `lambda/aggregator/aggregator_deploy.zip` from this project.
   - Save.
   - Configuration tab → General configuration → Edit → set **Timeout** to
     30 seconds (default 3s is too short) → Save.
   - Configuration tab → Runtime settings → Edit → Handler:
     `handler.lambda_handler` → Save.
   - Configuration tab → Environment variables → Edit → Add:
     `FL_ROUNDS_TABLE = FlRoundsTable`, `FL_COUNTERS_TABLE = FlUploadCountersTable`.

4. **Add the S3 trigger:**
   - Function page → Add trigger → Source: **S3**.
   - Bucket: `fl-heart-disease-7742`.
   - Event type: **PUT** (All object create events also works).
   - Prefix: `clients/`.
   - Acknowledge the recursive-invocation checkbox → Add.

5. **Reset the bucket for a clean test** (optional but recommended): delete
   everything under `clients/` and `global/` in the bucket, and delete all
   items in both DynamoDB tables, so this test starts from zero.

6. **Trigger it for real:** run a *client-only* upload — the easiest way is
   to temporarily point only the upload half of `run_aws_fl.py` at AWS. If
   you'd rather not modify anything, the simplest full test is: run
   `python scripts/run_aws_fl.py --rounds 1` as in Phase 2 — since the
   Lambda's trigger fires independently in the background as each hospital's
   `weights.json` lands in S3, both your local script's own aggregation
   *and* the Lambda's aggregation will attempt to run for round 1. That's
   fine for testing (the second write just overwrites `global/round_001/model.json`
   with an equivalent result) — but for a clean production-style test,
   comment out the aggregation call in `run_aws_fl.py`'s path (or just watch
   CloudWatch Logs to confirm the Lambda fired, which is the actual thing
   you're testing here).
7. **Check it worked:** Lambda console → `fl-aggregator` → Monitor tab →
   View CloudWatch logs → open the latest log stream → you should see your
   `print()` output (`round N: hospital_X uploaded (.../3)`, then
   `round N aggregated: global_accuracy=...`).

---

## Phase 4 — API Gateway + prediction Lambda

**What's new:** `lambda/api/handler.py` — adapts the existing
`api/local_server.py` route logic (already parameterized to take `store`/
`metadata`, so nothing there needed to change) into a single Lambda proxy
handler for API Gateway's HTTP API. Zip already built at
`lambda/api/api_deploy.zip`.

### Steps

1. **Execution role:** same pattern as Phase 3 — create role `fl-api-role`,
   trusted entity Lambda, attach `AWSLambdaBasicExecutionRole` plus an
   inline policy from `infra/iam_policies/lambda_api_role.json`.
2. **Create the Lambda:**
   - Name: `fl-api`, Runtime Python 3.12, execution role `fl-api-role`.
   - Upload `lambda/api/api_deploy.zip`.
   - Handler: `handler.lambda_handler`.
   - Timeout: 15 seconds.
   - Environment variables: `FL_BUCKET_NAME = fl-heart-disease-7742`,
     `FL_ROUNDS_TABLE = FlRoundsTable`, `FL_COUNTERS_TABLE = FlUploadCountersTable`.
3. **Create the API:**
   - API Gateway console → Create API → HTTP API → Build.
   - Add integration → Lambda → select `fl-api`.
   - API name: `fl-api-gateway` → Next.
   - Routes: the wizard will offer `ANY /{proxy+}` by default — that's fine
     and simplest (it forwards every path/method to the one Lambda, which
     already does its own routing internally based on `rawPath`/method).
   - Click through the default stage (`$default`, auto-deploy) → Create.
4. **Copy the Invoke URL** shown on the API's Overview page (looks like
   `https://abc123.execute-api.eu-north-1.amazonaws.com`).
5. **Test it directly** (no dashboard needed yet) — open in a browser:
   `https://<invoke-url>/health` → should return
   `{"ok": true, "service": "Federated Disease Detection API", "mode": "AWS"}`.
   Then try `/rounds` and `/presets` the same way.

---

## Phase 5 — Dashboard deployment

1. In `dashboard/`, set the API base URL as an environment variable (check
   `dashboard/app` for where the local server URL — likely
   `http://127.0.0.1:8000` — is currently referenced, and replace it with
   `process.env.NEXT_PUBLIC_API_URL` if it isn't already). Add a
   `.env.production` file:
   ```
   NEXT_PUBLIC_API_URL=https://<your-invoke-url>
   ```
2. Push `dashboard/` (or the whole repo) to GitHub if you haven't already.
3. Amplify console → New app → Host web app → connect your GitHub repo →
   select the branch.
4. Amplify auto-detects Next.js; confirm the build settings (root directory
   should point at `dashboard/` if it's a subfolder of the repo) → Save and
   deploy.
5. Once deployed, open the Amplify-provided URL and confirm the dashboard
   loads round history and predictions from the real API.

---

## Phase 6 — Monitoring & alerts

1. **CloudWatch logs** — already automatic for both Lambdas (Phase 3/4
   already used them to verify). Nothing extra to set up.
2. **CloudTrail:**
   - CloudTrail console → Create trail → name it `fl-audit-trail` → leave
     defaults (it creates its own S3 bucket for logs) → Create.
3. **SNS round-complete notification (optional):**
   - SNS console → Create topic → Standard → name `fl-round-complete` →
     Create.
   - Create subscription → Protocol: Email → enter your address → confirm
     via the email AWS sends you.
   - Add `sns:Publish` on this topic's ARN to `fl-aggregator-role`'s inline
     policy.
   - In `lambda/aggregator/handler.py`, after the `print(f"round {round_number}
     aggregated...")` line in `_aggregate()`, add:
     ```python
     import boto3
     sns = boto3.client("sns", region_name=REGION)
     sns.publish(
         TopicArn="<your topic ARN>",
         Subject=f"FL round {round_number} complete",
         Message=f"Global accuracy: {global_accuracy:.3f}",
     )
     ```
   - Re-zip and re-upload the aggregator Lambda after this change.

---

## Quick troubleshooting reference

| Symptom | Likely cause |
|---|---|
| `NoCredentialsError` running `run_aws_fl.py` | Environment variables not set / wrong shell session |
| `AccessDenied` on S3 in Lambda logs | Execution role's inline policy not attached, or bucket name typo in env var |
| Lambda times out | Default 3s timeout too short — raise it (Phase 3/4 steps 3) |
| `/predict` returns 404 "No trained global model found" | No round has completed aggregation yet — run Phase 2 or 3 first |
| Dashboard shows no data | `NEXT_PUBLIC_API_URL` not set at build time, or CORS — check the Lambda's CORS headers match your Amplify domain |
