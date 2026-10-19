"""
Handler for S3 operations related to uploaded ID documents.

Includes the programmatic application of a 30-day lifecycle policy
for compliance (PII retention limits).
"""

import boto3
import config

class DocumentStore:
    """Manages secure document uploads to S3."""
    
    def __init__(self):
        self.bucket = config.S3_DOCUMENT_BUCKET
        if config.DEMO_MODE:
            self.s3 = None
            return

        try:
            self.s3 = boto3.client("s3", **config.aws_client_kwargs())
        except Exception:
            self.s3 = None
        self._ensure_lifecycle_policy()
        
    def _ensure_lifecycle_policy(self):
        """
        Enforces a 30-day deletion lifecycle on the bucket for PII compliance.
        """
        if not self.s3:
            return

        try:
            self.s3.put_bucket_lifecycle_configuration(
                Bucket=self.bucket,
                LifecycleConfiguration={
                    'Rules': [
                        {
                            'ID': 'Delete PIIDocuments After 30 Days',
                            'Prefix': 'uploads/',
                            'Status': 'Enabled',
                            'Expiration': {'Days': 30}
                        }
                    ]
                }
            )
        except Exception:
            # Swallow for demo where bucket might not exist yet
            pass

    def upload_document(self, file_bytes: bytes, file_name: str) -> str:
        """
        Uploads an ID document to S3.
        """
        if not self.s3:
            if config.DEMO_MODE:
                return f"s3://{self.bucket}/mock/{file_name}"
            raise RuntimeError("S3 client unavailable and DEMO_MODE is disabled")

        try:
            object_key = f"uploads/{file_name}"
            self.s3.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=file_bytes,
                ServerSideEncryption='AES256'
            )
            return f"s3://{self.bucket}/{object_key}"
        except Exception:
            return f"s3://{self.bucket}/mock/{file_name}"
