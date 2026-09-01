# API

Local Phase 3 dashboard backend. This is the local equivalent of API Gateway + Lambda.

Available routes:

- `GET /rounds`: return round history and accuracy metrics.
- `POST /predict`: load the current global model and return a disease-risk prediction.

The browser should call this API layer rather than reading S3 or DynamoDB directly.

Run locally:

```powershell
python scripts/run_api_server.py
```
