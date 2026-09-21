# Infrastructure

AWS deployment is intentionally not done yet. The current project completes the local application logic first, then AWS can be wired after testing.

Remaining AWS work:

- S3 model bucket with default SSE-S3 encryption.
- DynamoDB tables for round metadata, upload counters, and model versioning.
- Lambda functions for aggregation and prediction.
- API Gateway routes for dashboard access.
- IAM roles scoped per simulated hospital node.
- CloudTrail and CloudWatch logging.
- Optional SNS round-complete notifications.

See `docs/aws_remaining.md` for the full AWS checklist.
