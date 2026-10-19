"""
AWS DynamoDB Data Persistence for Insurance Underwriting.

Handles the storage of raw extracted applicant data and maintains
an immutable audit trail of underwriting decisions for compliance.
"""

from datetime import datetime
from typing import Dict, Any, List

import boto3

import config


class DynamoAuditStore:
    """
    Manages interactions with DynamoDB tables for applicant tracking and auditing.
    
    Tables:
    - Applicant Table: Transient state and raw extracted OCR data.
    - Audit Table: Immutable log of all automated decisions for compliance reporting.
    """

    def __init__(self):
        """
        Initialize the DynamoDB resource and table references.
        """
        if config.DEMO_MODE:
            self.dynamodb = None
            self.applicant_table = None
            self.audit_table = None
            return

        try:
            self.dynamodb = boto3.resource("dynamodb", **config.aws_client_kwargs())
            self.applicant_table = self.dynamodb.Table(config.DYNAMO_APPLICANT_TABLE)
            self.audit_table = self.dynamodb.Table(config.DYNAMO_AUDIT_TABLE)
        except Exception:
            self.dynamodb = None
            self.applicant_table = None
            self.audit_table = None
        
    def _convert_floats_to_decimal(self, obj: Any) -> Any:
        """
        Recursively converts float values to Decimal for DynamoDB serialization.
        DynamoDB's boto3 client does not accept native Python floats.
        """
        from decimal import Decimal
        if isinstance(obj, float):
            return Decimal(str(round(obj, 4)))
        elif isinstance(obj, dict):
            return {k: self._convert_floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimal(i) for i in obj]
        return obj

    def store_applicant(self, applicant_data: Dict[str, Any], applicant_id: str) -> bool:
        """
        Stores parsed applicant OCR data in the transient tracking table.
        
        Args:
            applicant_data: Extracted KV pairs from Textract
            applicant_id: Unique identifier for the application session
            
        Returns:
            True if stored successfully, False otherwise
        """
        if not self.applicant_table:
            return False

        try:
            # Prepare data for DynamoDB (handle float issues natively)
            safe_data = self._convert_floats_to_decimal(applicant_data)
            
            self.applicant_table.put_item(Item={
                "applicant_id": applicant_id,
                "status": "PROCESSING",
                "timestamp": datetime.utcnow().isoformat(),
                "extracted_data": safe_data
            })
            return True
            
        except Exception as e:
            print(f"[DynamoDB Error] Failed to store applicant {applicant_id}: {e}")
            return False
            
    def record_decision(
        self, 
        applicant_id: str, 
        decision: str, 
        rules_triggered: List[str],
        agent_rationale: str,
        risk_score: int
    ) -> bool:
        """
        Records the final underwriting decision into the immutable audit trail.
        
        This record serves as the official compliance log for automated decisions,
        capturing both the deterministic rules engine output and the AgentCore rationale.
        
        Args:
            applicant_id: Application session identifier
            decision: Final outcome ('APPROVED', 'REJECTED', 'MANUAL_REVIEW')
            rules_triggered: List of any hard rule violations
            agent_rationale: Text explanation from the LLM orchestrator
            risk_score: Computed integer risk score
            
        Returns:
            True if stored successfully, False otherwise
        """
        if not self.audit_table or not self.applicant_table:
            return False

        try:
            self.audit_table.put_item(Item={
                "applicant_id": applicant_id,
                "timestamp": datetime.utcnow().isoformat(),
                "decision": decision,
                "rules_triggered": rules_triggered,
                "agent_rationale": agent_rationale,
                "risk_score": risk_score,
                "audit_version": "1.0"
            })
            
            # Update the transient tracking table status as well
            self.applicant_table.update_item(
                Key={"applicant_id": applicant_id},
                UpdateExpression="SET #status = :s",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":s": decision}
            )
            return True
            
        except Exception as e:
            print(f"[DynamoDB Error] Failed to record decision for {applicant_id}: {e}")
            return False
            
    def get_applicant_history(self, applicant_id: str) -> Dict[str, Any]:
        """
        Retrieves the complete audit history for a specific application.
        """
        if not self.audit_table:
            return {}

        try:
            response = self.audit_table.get_item(Key={"applicant_id": applicant_id})
            return response.get("Item", {})
        except Exception:
            return {}
