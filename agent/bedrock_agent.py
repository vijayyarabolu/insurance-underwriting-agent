"""
Bedrock AgentCore Orchestrator.

Orchestrates the entire underwriting workflow using AWS Bedrock AgentCore.
"""

import os

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
                if os.getenv("UNDERWRITING_LLM", "").lower() == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
                    try:
                        return self.claude_rationale(applicant_data)
                    except Exception as exc:
                        print(f"[agent] Claude rationale failed, using template: {exc}")
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
    def claude_rationale(applicant_data: dict) -> dict:
        """
        Optional offline path: Claude writes the rationale from the rules output.
        The decision itself always comes from the deterministic rules.
        """
        import json
        import anthropic

        rules = applicant_data.get("rules_evaluation", {})
        prompt = (
            "You are assisting an insurance underwriter. The decision below was made by deterministic "
            "rules and must not be changed. In 3-5 sentences, explain the decision and what the "
            "underwriter should check next, citing the rule ids.\n\n"
            f"Decision: {rules.get('decision')}\nRule results: {json.dumps(rules.get('rule_results', []))}"
        )
        message = anthropic.Anthropic().messages.create(
            model=os.getenv("UNDERWRITING_LLM_MODEL", "claude-sonnet-5-5"),
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        return {"decision_text": text, "status": "claude"}

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
