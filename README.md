# Automated Insurance Underwriting Agent

An end-to-end underwriting decision-support cockpit built on AWS.
It ingests government IDs, verifies face liveness, checks deterministic policy rules using an AWS Lambda engine, routes complex cases to AWS Bedrock AgentCore for rationale, and logs the decision packet to DynamoDB for compliance.

The product posture is intentionally **decision support**, not opaque fully autonomous underwriting. Hard-stop rules run before the LLM, identity verification is a blocking gate, and every outcome includes rule-level evidence plus underwriter review actions.

## Product Capabilities

* Structured ID extraction with Textract Queries for name, DOB, address, ID number, expiration date, issue date, and issuing state.
* Deterministic hard-stop rules for age eligibility, sanctions, document expiration, and identity verification.
* Review routing for incomplete OCR and configured risk signals instead of silently rejecting borderline submissions.
* Underwriting decision packet with risk score, confidence, missing fields, rule evidence, identity metrics, review actions, and audit controls.
* Demo-safe local mode using `DEMO_MODE=true`; production-style fail-closed behavior with `DEMO_MODE=false`.

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│               Underwriting UI (Streamlit)               │
│                                                         │
│ [ Step 1: ID Upload ]           [ Step 2: Liveness ]    │
└─────────┬──────────────────────────────────┬────────────┘
          │                                  │
          ▼                                  ▼
┌──────────────────┐               ┌──────────────────┐
│  AWS Textract    │               │ AWS Rekognition  │
│  (analyze_       │               │ (FaceLiveness /  │
│   document)      │               │  FaceCompare)    │
└─────────┬────────┘               └─────────┬────────┘
          │                                  │
          ▼                                  ▼
┌────────────────────────────────────────────────────────┐
│               Step 3: Underwriting Engine              │
│                                                        │
│  ┌────────────────┐               ┌─────────────────┐  │
│  │   AWS Lambda   │──(Flags)─────►│   AWS Bedrock   │  │
│  │ (Rules Engine) │               │   AgentCore     │  │
│  │  - Age Check   │               │  (LLM decision  │  │
│  │  - Sanctions   │               │   rationale)    │  │
│  └────────────────┘               └─────────────────┘  │
└────────────────┬───────────────────────────┬───────────┘
                 │                           │
                 ▼                           ▼
       ┌──────────────────┐        ┌──────────────────┐
       │     AWS S3       │        │   AWS DynamoDB   │
       │ (Document Bucket)│        │  (Audit Trail)   │
       │                  │        │                  │
       │ - 30-day deletion│        │ - Immutable log  │
       │   lifecycle rule │        │ - Compliance reqs│
       └──────────────────┘        └──────────────────┘
```

## Setup & Running Locally

1. Create a virtual environment: `python -m venv venv && source venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Configure `.env` from `.env.example`. Keep `DEMO_MODE=true` for local demos, or set `DEMO_MODE=false` to use real AWS clients and fail closed when AWS services are unavailable.
4. Start the UI: `streamlit run app.py`

## Benchmarks & Engineering Tradeoffs

### 1. AgentCore vs Custom LangChain Orchestration
During the build timeline, we initially considered writing the orchestration logic entirely in LangChain. 

**The Challenge:** Underwriting has strict compliance requirements. We needed native trace persistence and deep IAM integration to ensure the LLM's access to external systems was strictly bound. Writing custom LangChain guardrails mapping to IAM boundaries was high overhead.

**The Solution:** We migrated to **AWS Bedrock AgentCore**. It natively injects Guardrails, logs traces automatically to CloudWatch, and maps tools to AWS IAM roles. This reduced custom orchestration code by ~60% while increasing regulatory compliance.

### 2. Edge Case Validations & Bug Fixing (Age Rule)
Our initial deterministic Lambda rules engine (`scoring/policy_rules.py`) contained a bug related to Age Verification.

The V1 implementation simply subtracted the applicant's birth year from the current year. This failed on our edge case test profiles where applicants had late-year birthdays, incorrectly approving 17-year-olds who were turning 18 later in the current year. 

We refactored the logic to use strict tuple datetime comparisons (`age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))`) and successfully re-validated against our 20-profile testing suite to ensure 100% accuracy before routing to the LLM.

## AWS Services Used

*   **AWS Bedrock AgentCore**: Final orchestration and decision reasoning layer.
*   **AWS Textract**: Used `analyze_document` with `FeatureTypes=["QUERIES"]` for structured field parsing from Driver's Licenses.
*   **AWS Rekognition**: Liveness verification to prevent visual spoofing, plus FaceCompare to match live face to ID photo.
*   **AWS Lambda**: Serverless Python execution containing deterministic underwriting logic (Age boundaries, Sanctions lists).
*   **AWS S3**: Temporarily holds PII applicant documents, fully secured by an automated `put_bucket_lifecycle_configuration` ensuring 30-day automated deletion.
*   **AWS DynamoDB**: Retains an immutable audit log of every underwriting decision, storing risk scores, triggered rule flags, and AgentCore rationale.

## Architecture Note

This project was built and tested using AWS free tier credits ($100). The services are no longer active as credits were exhausted, but the implementation reflects the full production architecture and utilizes all real `boto3` capabilities.

## License

MIT
