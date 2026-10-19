"""
One call that runs an application through every underwriting step.

    rules engine -> identity gate -> rationale -> decision packet

The Streamlit app walks through these steps one screen at a time. This module
runs them in one go, which is what demo.py and the eval harness use.
"""

from typing import Any, Dict, Optional

from agent.bedrock_agent import UnderwritingAgent
from scoring.decision_support import apply_identity_gate, build_decision_packet
from scoring.lambda_rules_engine import invoke_rules_engine_mock


def underwrite(applicant_id: str, applicant_data: Dict[str, Any], liveness: Dict[str, Any],
               as_of: str = "", agent: Optional[UnderwritingAgent] = None) -> Dict[str, Any]:
    rules = invoke_rules_engine_mock(applicant_data, as_of=as_of)
    gated = apply_identity_gate(rules, liveness)

    # The model is only asked for a rationale. It never changes the decision.
    agent = agent or UnderwritingAgent()
    rationale = agent.evaluate_applicant({**applicant_data, "rules_evaluation": gated})

    return build_decision_packet(applicant_id, applicant_data, gated, liveness, rationale)
