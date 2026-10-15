# AegisFL: Federated Learning for Early Heart Disease Detection

> A privacy-preserving, cloud-native Federated Learning (FedAvg) prototype across simulated hospital nodes on AWS, keeping raw patient health records 100% decentralized.

[![Live Demo](https://img.shields.io/badge/Demo-AWS%20Amplify%20Live-00c853?style=flat-square&logo=amazon-aws)](https://main.d27bxeyf5b5sth.amplifyapp.com/)
[![API Status](https://img.shields.io/badge/API-AWS%20API%20Gateway-ff9900?style=flat-square&logo=amazon-aws)](https://kl58tsjkw6.execute-api.ap-south-2.amazonaws.com/health)
[![Architecture](https://img.shields.io/badge/Architecture-Serverless%20%2F%20S3%20%2B%20DynamoDB%20%2B%20Lambda-232f3e?style=flat-square)](https://github.com/ABHI2005jeet/FL-EARLY-DISEASE-DETECTION)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776ab?style=flat-square&logo=python)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js%2014-black?style=flat-square&logo=next.js)](https://nextjs.org/)
[![Tests](https://img.shields.io/badge/Tests-9%20Passing-brightgreen?style=flat-square)](https://github.com/ABHI2005jeet/FL-EARLY-DISEASE-DETECTION)

---

## 💡 Why We Built This (The Problem & The Market Gap)

In healthcare, machine learning models are only as good as the diversity and volume of patient data they train on. But clinical datasets are trapped inside isolated hospital silos:

1. **The Legal & Compliance Barrier**: Regulations like **HIPAA** (US), **GDPR** (EU), and the **DPDP Act / DISHA** (India) make pooling raw Electronic Health Records (EHR) into a central multi-tenant cloud data lake legally perilous and ethically questionable. A single data breach on a centralized medical database can compromise millions of patient records.
2. **The Small-Data Bottleneck**: A standalone regional hospital with 50–100 cardiac patients cannot train a statistically robust, generalizable model on its own. Small local models overfit, suffer from demographic bias, and fail when exposed to edge-case cardiac biomarkers.
3. **The Gap in Current Market Solutions**:
   - **Centralized Data Lakes**: High compliance friction, massive legal liability, and a single point of failure.
   - **Academic FL Frameworks** (PySyft, Flower, OpenFL): Excellent for research, but usually run either as in-memory simulations or require multi-node Kubernetes clusters with complex networking that are cost-prohibitive for real-world pilot deployments.
   - **Cost & Complexity Trap**: Cloud-based FL solutions often rack up unexpected bills using dedicated EC2 instances, paid AWS KMS customer-managed keys, and frequent polling cron jobs.

### Our Solution
As 3rd-year engineering students, we built **AegisFL**: a lean, serverless, and privacy-preserving Federated Learning prototype deployed on AWS. 
- **Raw patient data NEVER leaves the hospital node.**
- Only abstract mathematical weight updates (13 floats + 1 bias) are transmitted to the cloud.
- Aggregation is entirely event-driven using AWS Lambda and DynamoDB counters (zero polling loops).
- Infrastructure cost is kept near **$0** (well within the AWS Free Tier) by enforcing default SSE-S3 encryption (avoiding paid KMS) and serverless compute.

---

## 🎯 System Architecture & Design Decisions

```
+-----------------------------------------------------------------------------------+
|                           HOSPITAL LOCAL DATA BOUNDARY                            |
|                                                                                   |
|   +-----------------------+   +-----------------------+   +-------------------+   |
|   | Hospital 1 (St. Jude) |   |   Hospital 2 (Mayo)   |   | Hospital 3 (GHI)  |   |
|   | 99 Local Patients CSV |   | 99 Local Patients CSV |   | 99 Patients CSV   |   |
|   | Trains Local Weights  |   | Trains Local Weights  |   | Trains Weights    |   |
|   +-----------+-----------+   +-----------+-----------+   +---------+---------+   |
|               |                           |                         |             |
|  Only Weights |              Only Weights |            Only Weights |             |
+---------------+---------------------------+-------------------------+-------------+
                |                           |                         |
                v                           v                         v
       clients/hospital_1/         clients/hospital_2/       clients/hospital_3/
       =========================================================================
                           AWS S3 BUCKET (fl-heart-disease-aps2)
                           [Enforced Default SSE-S3 (AES-256) Encryption]
       =========================================================================
                                            |
                                            | S3 ObjectCreated Event Trigger
                                            v
                               +----------------------------+
                               | fl-aggregator (AWS Lambda) |
                               +--------------+-------------+
                                              |
                   Atomic Upload Counter      | If 3/3 Uploads Received:
                   + Update Round State       | Runs FedAvg Weighted Math
                                              v
                              +-------------------------------+
                              |   DynamoDB (FlRoundsTable)    |
                              |   S3 (global/current_model)   |
                              +---------------+---------------+
                                              ^
                                              | Reads Latest Global Weights
                               +--------------+--------------+
                               |     fl-api (AWS Lambda)     |
                               +--------------+--------------+
                                              ^
                                              | HTTPS REST API (/rounds, /predict)
                               +--------------+--------------+
                               |     Amazon API Gateway      |
                               +--------------+--------------+
                                              ^
                                              | HTTPS Calls (CORS Enabled)
                               +--------------+--------------+
                               |   Next.js 14 Web Dashboard  |
                               |  (Hosted on AWS Amplify)    |
                               +-----------------------------+
```

### 1. Zero Patient Data Egress & Privacy Boundary
We partition the **UCI Heart Disease (Cleveland)** dataset across three simulated hospital nodes:
- 🏥 **Hospital 1 (St. Jude Cardio Center)**: 99 private patient records (`hospital_1.csv`)
- 🏥 **Hospital 2 (Mayo Regional Health)**: 99 private patient records (`hospital_2.csv`)
- 🏥 **Hospital 3 (General Heart Institute)**: 99 private patient records (`hospital_3.csv`)

Each hospital trains a binary logistic regression model locally for 250 epochs. When training finishes, the node packages only `{ "weights": [...], "bias": ... }` and uploads it to its designated S3 folder:
`s3://fl-heart-disease-aps2/clients/<hospital_id>/round_N/weights.json`

### 2. Strict IAM Prefix Isolation (Verified with Negative Tests)
To simulate true institutional boundaries, each hospital client operates under a scoped IAM policy:
- Hospital 1 has write access **strictly** to `clients/hospital_1/*` and read access to `global/*`.
- Hospital 1 has **zero** permission to read or write into `clients/hospital_2/*` or `clients/hospital_3/*`.
- An automated unit test verifies that cross-tenant access attempts immediately fail with an AWS `AccessDenied` exception.

### 3. Event-Driven Aggregation (DynamoDB Atomic Counters, Not Polling)
Many distributed FL designs use wasteful polling loops (e.g. checking every 10 seconds if clients have uploaded). We replaced that with an event-driven pattern:
1. Each weight upload triggers an S3 `ObjectCreated` event.
2. The `fl-aggregator` Lambda inspects the event and atomically increments the `uploads_received` counter for that round in DynamoDB (`FlUploadCountersTable`).
3. Only when `uploads_received == expected_clients` (3/3), the Lambda triggers **Federated Averaging (FedAvg)**.
4. FedAvg computes sample-size-weighted global weights:
   $$w_{t+1}^{global} = \sum_{k=1}^K \frac{n_k}{n} w_{t+1}^k$$
5. The resulting global model is saved to S3 (`global/current_model.json`), and round performance is recorded in DynamoDB (`FlRoundsTable`).

### 4. Decoupled Inference Read-Path
Inference is completely decoupled from the training cycle:
- Clinicians interact with the Next.js dashboard to input patient clinical metrics.
- The browser calls `POST /predict` on **Amazon API Gateway**, which invokes `fl-api` Lambda.
- The Lambda reads the *current* global model weights directly from S3, applies Z-score normalization, and computes disease probability via the sigmoid function:
  $$\hat{y} = \sigma(w^T x + b) = \frac{1}{1 + e^{-(w^T x + b)}}$$
- It returns the risk percentage alongside automated biomarker risk flags (Hypertension warning $\ge 140$ mmHg, Cholesterol warning $\ge 240$ mg/dL, Exercise Angina detected, ST Depression $> 2.0$).

### 5. Asynchronous Training Orchestration (`/train`)
API Gateway HTTP APIs enforce a strict 30-second request timeout. Multi-round federated training across multiple nodes can exceed 30 seconds. To solve this without breaking the client request:
- `POST /train` validates the payload and responds immediately with `202 Accepted`.
- In the background, it triggers an asynchronous self-invocation of the Lambda (`InvocationType=Event`).
- The async worker executes the full multi-round training cycle within Lambda's 300-second execution envelope, writing progress directly to DynamoDB.

---

## 🛠️ Real Engineering Challenges & Lessons Learned

Building and deploying this to real AWS taught us lessons that no classroom slides or tutorials ever cover:

1. **The Windows Zip Backslash Trap in AWS Lambda**:
   When bundling Lambda packages from Windows, PowerShell's `Compress-Archive` (and .NET's `ZipFile`) writes directory separators as backslashes (`\`). When unpacked onto Amazon Linux inside the Lambda microVM, directories like `fl_core/model.py` appeared as flat filenames (`fl_core\model.py`). This caused cryptic `ModuleNotFoundError: No module named 'fl_core'`. We solved this by writing a Python packaging script using `zipfile` that explicitly normalizes all path separators to POSIX `/`.
2. **Cross-Region Architecture (`ap-south-2` vs `ap-south-1`)**:
   Our backend serverless stack (S3, DynamoDB, Lambda, API Gateway) was provisioned in **Hyderabad (`ap-south-2`)**. However, AWS Amplify Hosting was not available in `ap-south-2`. Rather than rebuilding the backend, we deployed the Next.js static export to Amplify in **Mumbai (`ap-south-1`)** and configured CORS on the API Gateway to allow cross-origin requests from the Amplify domain.
3. **Zero-KMS Cost Discipline**:
   AWS Key Management Service (KMS) charges $1/month per customer-managed key plus per-request fees. To keep this academic prototype 100% cost-free, we enforced default bucket-level **SSE-S3 (AES-256)** encryption. Every model artifact at rest is encrypted with zero key-management fees.
4. **Pure Python vs Framework Bloat**:
   We deliberately wrote the logistic regression and FedAvg math in standard Python without heavy dependencies like PyTorch, TensorFlow, or Scikit-learn. This kept the Lambda zip package under **15 KB** (instead of 250+ MB), completely eliminated Lambda cold start penalties (< 180ms execution), and forced us to understand the underlying mathematics from scratch.

---

## 📊 Dataset & Model Performance

- **Dataset**: UCI Heart Disease (Processed Cleveland dataset)
- **Samples**: 303 original rows $\rightarrow$ 297 clean rows (6 incomplete records removed)
- **Partitions**: 3 hospital splits (99 records each), internal 80/20 train/test split (seed=7)
- **Clinical Features (13 biomarkers)**:
  `age`, `sex`, `cp` (chest pain type), `trestbps` (resting blood pressure), `chol` (serum cholesterol), `fbs` (fasting blood sugar), `restecg` (resting ECG), `thalach` (maximum heart rate), `exang` (exercise angina), `oldpeak` (ST depression), `slope`, `ca` (major vessels), `thal` (thalassemia).
- **Target**: Binarized (0 = No Heart Disease, 1 = Presence of Heart Disease).

### Federated Learning Results
| Metric | Isolated Local Models (Mean) | AegisFL Global Model (12 Rounds) | Improvement |
|---|:---:|:---:|:---:|
| **Test Accuracy** | **77.2%** | **82.5%** | **+5.3%** |
| **Data Privacy** | ❌ High risk (if centralized) | ✅ 100% local custody | Zero raw data egress |
| **Generalization** | ⚠️ High variance across hospitals | ✅ Robust consensus model | Shared learning |

---

## 📂 Repository Structure

```text
├── aggregator/          # Core FedAvg aggregation math and S3 upload triggers
├── api/                 # REST handler logic shared by local server and AWS Lambda
├── clients/             # Local hospital simulation scripts (hospital_1, hospital_2, hospital_3)
├── config/              # Federated hyperparameters (learning rate, epochs, rounds)
├── dashboard/           # Next.js 14 cyberpunk-medical frontend (deployed on AWS Amplify)
├── data/                # Raw UCI Cleveland data and deterministic processed hospital splits
├── docs/                # Architecture guides, viva notes, and AWS deployment logs
├── fl_core/             # Pure Python logistic regression, sigmoid activation, and normalization
├── infra/               # Scoped IAM policy JSON files for hospital nodes and Lambda roles
├── lambda/              # Packaging scripts and AWS Lambda entrypoints (aggregator & api)
├── local_cloud/         # Dual-mode storage interfaces (local filesystem mocks vs live boto3 AWS)
├── scripts/             # CLI runners for data prep, local FL simulations, and API server
└── tests/               # 9 automated unit tests verifying FedAvg math, IAM, and SSE-S3 encryption
```

---

## 🌐 Deployed AWS Cloud Resources

| Resource | Identifier / Name | AWS Region | Configuration |
|---|---|---|---|
| **S3 Model Bucket** | `fl-heart-disease-aps2` | `ap-south-2` (Hyderabad) | Default SSE-S3 (`AES256`) encryption |
| **DynamoDB Tables** | `FlRoundsTable`, `FlUploadCountersTable` | `ap-south-2` (Hyderabad) | On-Demand capacity mode |
| **Aggregator Lambda** | `fl-aggregator` | `ap-south-2` (Hyderabad) | S3 ObjectCreated event trigger |
| **API Lambda** | `fl-api` | `ap-south-2` (Hyderabad) | API Gateway proxy integration |
| **API Gateway** | `fl-api-gateway` (HTTP API) | `ap-south-2` (Hyderabad) | CORS enabled for Amplify frontend |
| **Amplify Web App** | `fl-dashboard` (`d27bxeyf5b5sth`) | `ap-south-1` (Mumbai) | Static Next.js export hosting |
| **IAM Users** | `hospital_1`, `hospital_2`, `hospital_3` | Global | Scoped exclusively to `clients/{id}/*` |

---

## 🚀 Running the Project

### Option A: Run 100% Locally (Zero Cloud Setup Needed)

You can run and test the complete pipeline locally using our built-in cloud mocks:

1. **Clone & install dependencies**:
   ```powershell
   git clone https://github.com/ABHI2005jeet/FL-EARLY-DISEASE-DETECTION.git
   cd FL-EARLY-DISEASE-DETECTION
   pip install -r requirements.txt
   ```

2. **Prepare the dataset**:
   ```powershell
   python scripts/prepare_data.py
   ```

3. **Run the multi-round Federated Learning simulation**:
   ```powershell
   python scripts/run_local_fl.py
   ```
   *(Simulates 8 rounds of FedAvg across 3 hospital nodes, including simulated dropout handling).*

4. **Start the local API backend**:
   ```powershell
   python scripts/run_api_server.py
   ```
   *(Listens on `http://127.0.0.1:8000` with `/health`, `/rounds`, `/presets`, `/predict`, `/audit`).*

5. **Launch the Next.js Dashboard**:
   ```powershell
   cd dashboard
   npm install
   npm run dev
   ```
   Open **`http://localhost:3000`** in your browser.

---

### Option B: Run Against Real AWS Cloud

If testing against the deployed cloud resources in AWS:

```powershell
$env:FL_BUCKET_NAME = "fl-heart-disease-aps2"
$env:AWS_REGION = "ap-south-2"
python scripts/run_aws_fl.py --rounds 1
```

Or trigger training directly via the public API Gateway:

```powershell
Invoke-RestMethod -Method POST `
  -Uri "https://kl58tsjkw6.execute-api.ap-south-2.amazonaws.com/train" `
  -ContentType "application/json" `
  -Body '{"rounds": 1}'
```

---

## 🧪 Automated Test Suite

We maintain 9 unit tests verifying all core mathematical and cloud security guarantees:

```powershell
python -m unittest discover -s tests -v
```

**What gets tested:**
- `test_fedavg.py`: Verifies sample-weighted FedAvg math against analytical expectations.
- `test_local_cloud.py`: Validates that `hospital_1` receives an `AccessDenied` error when attempting to access `clients/hospital_2/*` (IAM prefix isolation negative test), and asserts that every uploaded object has `AES256` SSE-S3 metadata.
- `test_trigger_and_api.py`: Tests DynamoDB atomic upload counter triggers and asserts that `/predict` rejects malformed payloads with clean error responses.

---

## 👨‍💻 Academic Project Context

- **Academic Level**: 3rd Year Computer Science & Engineering (Cloud Architecture & Systems Track)
- **Primary Domain**: Privacy-Preserving Machine Learning & Serverless Cloud Computing
- **Live Deployment**: [AegisFL on AWS Amplify](https://main.d27bxeyf5b5sth.amplifyapp.com/)

---

## 📜 License
MIT License. Built for educational and research purposes.
