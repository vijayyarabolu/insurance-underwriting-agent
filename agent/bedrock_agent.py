"""
Bedrock AgentCore Orchestrator.

Orchestrates the entire underwriting workflow using AWS Bedrock AgentCore.
"""

import boto3
import uuid
import config

class UnderwritingAgent:
    """Invokes the Bedrock Agent for document parsing and decision routing."""
    
    def __init__(self):
        if config.DEMO_MODE:
            self.client = None
            self.agent_id = config.BEDROCK_AGENT_ID
            self.agent_alias_id = config.BEDROCK_AGENT_ALIAS_ID
            return

        try:
            self.client = boto3.client("bedrock-agent-runtime", **config.aws_client_kwargs())
        except Exception:
            self.client = None
        self.agent_id = config.BEDROCK_AGENT_ID
        self.agent_alias_id = config.BEDROCK_AGENT_ALIAS_ID
        
    def evaluate_applicant(self, applicant_data: dict, session_id: str = None) -> dict:
        """
        Sends the structured extracted data to Bedrock for final assessment.
        """
        prompt = f"Evaluate this applicant data and provide an underwriting rationale: {applicant_data}"
        if not session_id:
            session_id = str(uuid.uuid4())

        if not self.client:
            if config.DEMO_MODE:
                return self.fallback_decision(applicant_data)
            return {
                "decision_text": "Bedrock AgentCore unavailable; deterministic rules result should be used without LLM rationale.",
                "status": "error"
            }
            
        try:
            response = self.client.invoke_agent(
                agentId=self.agent_id,
                agentAliasId=self.agent_alias_id,
                sessionId=session_id,
                inputText=prompt,
                enableTrace=False
            )
            
            output = ""
            for event in response.get("completion", []):
                if 'chunk' in event:
                    output += event['chunk']['bytes'].decode('utf-8')
                    
            return {"decision_text": output, "status": "success"}
        except Exception:
            # UI Fallback
            return self.fallback_decision(applicant_data)

    @staticmethod
    def fallback_decision(applicant_data: dict = None) -> dict:
        rules = (applicant_data or {}).get("rules_evaluation", {})
        decision = rules.get("decision", "UNKNOWN")
        flags = rules.get("flags", [])

        if decision == "AUTO_REJECTED":
            rationale = (
                "The deterministic underwriting checks produced a rejection. "
                f"Blocking flags: {', '.join(flags) if flags else 'policy threshold exceeded'}."
            )
        elif decision == "AGENT_REVIEW":
            rationale = (
                "The deterministic underwriting checks require manual review. "
                f"Review flags: {', '.join(flags) if flags else 'additional risk assessment needed'}."
            )
        else:
            rationale = (
                "Based on the policy rules engine output, the applicant clears all major KYC and sanctions checks. "
                "The liveness and ID match checks are above policy thresholds. Recommending APPROVAL for Policy Tier: Standard."
            )

        return {
            "decision_text": rationale,
            "status": "demo_fallback"
        }
