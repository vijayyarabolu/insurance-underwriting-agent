"""
Centralized configuration for Insurance Underwriting Agent.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# AWS Global
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() in {"1", "true", "yes", "on"}

# Bedrock AgentCore
BEDROCK_AGENT_ID = os.getenv("BEDROCK_AGENT_ID", "UNDERWRITER_001")
BEDROCK_AGENT_ALIAS_ID = os.getenv("BEDROCK_AGENT_ALIAS_ID", "PROD")

# S3 Storage
S3_DOCUMENT_BUCKET = os.getenv("S3_DOCUMENT_BUCKET", "insurance-applicant-docs")

# DynamoDB
DYNAMO_APPLICANT_TABLE = os.getenv("DYNAMO_APPLICANT_TABLE", "insurance-applicants")
DYNAMO_AUDIT_TABLE = os.getenv("DYNAMO_AUDIT_TABLE", "insurance-decisions-audit")

# Lambda
RULES_ENGINE_LAMBDA_ARN = os.getenv("RULES_ENGINE_LAMBDA_ARN", "arn:aws:lambda:us-east-1:123:function:underwriting-rules")

# App 
APP_TITLE = "Insurance Underwriting Assistant"

def aws_client_kwargs() -> dict:
    """
    Shared boto3 client/resource arguments.

    When explicit access keys are absent, boto3 can still use its normal
    credential chain, including profiles, IAM roles, SSO, or environment config.
    """
    kwargs = {"region_name": AWS_REGION}
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        kwargs.update({
            "aws_access_key_id": AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": AWS_SECRET_ACCESS_KEY
        })
    return kwargs
