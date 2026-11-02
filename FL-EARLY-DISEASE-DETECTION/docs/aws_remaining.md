# AWS Work Remaining

The local Phase 2/3 code is designed so the real AWS work can be done after testing.

## Phase 2 AWS Work

- Create an S3 model bucket with default SSE-S3 encryption. Do not use KMS.
- Create per-client S3 prefixes such as `clients/hospital_1/`.
- Add IAM roles/policies so each hospital can write only to its own prefix and read the global model prefix.
- Add a negative IAM test proving hospital 1 cannot access hospital 2's prefix.
- Create DynamoDB tables for upload counters, round metadata, model versioning, local accuracy, global accuracy, and skipped clients.
- Wire S3 object-created events to a Lambda trigger that increments the DynamoDB upload counter.
- Deploy the aggregator as Lambda and run FedAvg only when the counter reaches the expected client count or timeout fallback fires.
- Enable CloudWatch logs and CloudTrail access logging.

## Phase 3 AWS Work

- Deploy `GET /rounds` and `POST /predict` behind API Gateway + Lambda.
- Make `POST /predict` load the current global model from S3.
- Point the dashboard to the deployed API endpoint.
- Deploy the dashboard through S3 + CloudFront or Amplify.
- Add optional SNS notifications when a round completes.
- Document redeploy steps and cost controls.
