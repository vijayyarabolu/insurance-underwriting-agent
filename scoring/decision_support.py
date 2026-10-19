"""
Decision support utilities for underwriting review packets.

These helpers keep the Streamlit app focused on presentation while the
underwriting evidence, identity gates, and review actions stay testable.
"""

from datetime import UTC, datetime
from typing import Any, Dict, List

IDENTITY_THRESHOLDS = {
    "MIN_LIVENESS_CONFIDENCE": 90,
    "MIN_FACE_MATCH": 80
}

def apply_identity_gate(rules_result: Dict[str, Any], liveness_metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adds identity verification as a hard stop before final routing.
    """
    result = {
        **rules_result,
        "flags": list(rules_result.get("flags", [])),
        "rule_results": list(rules_result.get("rule_results", [])),
        "risk_score": rules_result.get("risk_score", 0)
    }

    liveness_confidence = liveness_metrics.get("liveness_confidence", 0) or 0
    face_match = liveness_metrics.get("face_match", 0) or 0
    face_match_passed = liveness_metrics.get("face_match_passed", False)

    identity_failed = (
        liveness_confidence < IDENTITY_THRESHOLDS["MIN_LIVENESS_CONFIDENCE"]
        or face_match < IDENTITY_THRESHOLDS["MIN_FACE_MATCH"]
        or not face_match_passed
    )

    if not identity_failed:
        result["rule_results"].append({
            "rule_id": "IDENTITY_VERIFICATION",
            "passed": True,
            "severity": "hard_stop",
            "risk_delta": 0,
            "message": "Face liveness and ID match are above policy thresholds"
        })
        return result

    identity_flag = "IDENTITY_VERIFICATION_FAILED: Face liveness or ID match below policy threshold"
    if identity_flag not in result["flags"]:
        result["flags"].append(identity_flag)

    result["decision"] = "AUTO_REJECTED"
    result["risk_score"] = result.get("risk_score", 0) + 100
    result["agent_required"] = False
    result["rule_results"].append({
        "rule_id": "IDENTITY_VERIFICATION",
        "passed": False,
        "severity": "hard_stop",
        "risk_delta": 100,
        "message": (
            f"Liveness={liveness_confidence}, face_match={face_match}, "
            f"match_passed={face_match_passed}"
        )
    })
    result.setdefault("explainability", {})
    result["explainability"].update({
        "decision_basis": "hard_stop",
        "straight_through_processing": False,
        "human_review_required": False
    })
    return result

def build_review_actions(rules_result: Dict[str, Any]) -> List[str]:
    """
    Converts rule outcomes into underwriter-facing next actions.
    """
    actions = []
    for rule in rules_result.get("rule_results", []):
        if rule.get("passed"):
            continue

        rule_id = rule.get("rule_id")
        if rule_id == "OCR_COMPLETENESS":
            actions.append("Request clearer ID image or manually key missing OCR fields.")
        elif rule_id == "DOCUMENT_EXPIRATION":
            actions.append("Request a non-expired government ID before issuing coverage.")
        elif rule_id == "AGE_ELIGIBILITY":
            actions.append("Verify age eligibility against carrier binding guidelines.")
        elif rule_id == "SANCTIONS_SCREEN":
            actions.append("Escalate sanctions match for compliance review.")
        elif rule_id == "IDENTITY_VERIFICATION":
            actions.append("Re-run liveness check or route to manual identity verification.")
        elif rule_id == "GEOGRAPHIC_RISK":
            actions.append("Confirm address territory and apply location-specific underwriting guidelines.")

    return actions or ["No underwriter action required for straight-through approval."]

def estimate_decision_confidence(rules_result: Dict[str, Any], liveness_metrics: Dict[str, Any]) -> int:
    """
    Produces an operational confidence score for triage, not an actuarial score.
    """
    confidence = 95
    confidence -= min(rules_result.get("risk_score", 0), 80)

    if liveness_metrics.get("liveness_confidence", 0) < IDENTITY_THRESHOLDS["MIN_LIVENESS_CONFIDENCE"]:
        confidence -= 20
    if liveness_metrics.get("face_match", 0) < IDENTITY_THRESHOLDS["MIN_FACE_MATCH"]:
        confidence -= 20
    if rules_result.get("missing_fields"):
        confidence -= 15

    return max(0, min(100, confidence))

def build_decision_packet(
    applicant_id: str,
    applicant_data: Dict[str, Any],
    rules_result: Dict[str, Any],
    liveness_metrics: Dict[str, Any],
    agent_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Builds a structured packet for audit, handoff, and human review.
    """
    decision = rules_result.get("decision", "UNKNOWN")
    review_actions = build_review_actions(rules_result)

    return {
        "applicant_id": applicant_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "final_decision": decision,
        "risk_score": rules_result.get("risk_score", 0),
        "decision_confidence": estimate_decision_confidence(rules_result, liveness_metrics),
        "straight_through_processing": decision == "AUTO_APPROVED",
        "human_review_required": decision == "AGENT_REVIEW",
        "flags": rules_result.get("flags", []),
        "missing_fields": rules_result.get("missing_fields", []),
        "rule_results": rules_result.get("rule_results", []),
        "identity_metrics": liveness_metrics,
        "applicant_snapshot": applicant_data,
        "agent_rationale": agent_result.get("decision_text", ""),
        "review_actions": review_actions,
        "audit_controls": [
            "Deterministic hard-stop rules are evaluated before agent rationale.",
            "Identity verification is treated as a hard-stop gate.",
            "Every rule emits pass/fail evidence for review and audit."
        ]
    }
