"""
AWS Lambda execution handler for the Underwriting Rules Engine.

This module acts as the serverless function that executes deterministic,
hard policy rules (Age Verification, OFAC Sanctions) on extracted applicant data
before the soft constraints are evaluated by the LLM agent.

Deployed via AWS Lambda configured with strict IAM boundaries.
"""

import json
from typing import Dict, Any

from datetime import date

from scoring.policy_rules import (
    check_age_rule,
    check_document_expiration_rule,
    check_required_fields,
    screen_sanctions,
    extract_state,
    get_rules,
    parse_date,
)

def build_rule_result(rule_id: str, passed: bool, message: str, severity: str, risk_delta: int) -> Dict[str, Any]:
    return {
        "rule_id": rule_id,
        "passed": passed,
        "severity": severity,
        "risk_delta": 0 if passed else risk_delta,
        "message": message
    }

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda entry point for rules evaluation.
    
    Args:
        event: Dictionary containing the payload (requires 'applicant_data')
        context: AWS Lambda context object (ignored in local execution)
        
    Returns:
        JSON compatible dictionary with scoring results
    """
    # Extract payload. "as_of" lets tests and evals pin today's date.
    applicant_data = event.get("applicant_data", {})
    as_of = parse_date(event.get("as_of", "")) or date.today()

    rule_results = []

    # 1. Execute Deterministic Policy Rules.
    # A rule that cannot run because OCR missed its field is a review item,
    # not a rejection. Only a rule that ran and failed can hard-stop.
    dob = applicant_data.get("DOB")
    age_ok, age_msg = check_age_rule(dob, today=as_of)
    age_severity = "hard_stop" if parse_date(dob) else "review"
    rule_results.append(build_rule_result("AGE_ELIGIBILITY", age_ok, age_msg, age_severity,
                                          100 if age_severity == "hard_stop" else 35))

    first_name = applicant_data.get("FIRST_NAME", "")
    last_name = applicant_data.get("LAST_NAME", "")
    sanctions_status, sanctions_msg = screen_sanctions(first_name, last_name)
    if sanctions_status == "possible":
        rule_results.append(build_rule_result("SANCTIONS_SCREEN", False, sanctions_msg, "review", 50))
    else:
        rule_results.append(build_rule_result("SANCTIONS_SCREEN", sanctions_status == "clear",
                                              sanctions_msg, "hard_stop", 200))

    data_complete, data_msg, missing_fields = check_required_fields(applicant_data)
    rule_results.append(build_rule_result("OCR_COMPLETENESS", data_complete, data_msg, "review", 35))

    expiration = applicant_data.get("EXPIRATION_DATE")
    expiration_ok, expiration_msg = check_document_expiration_rule(expiration, today=as_of)
    expiration_severity = "hard_stop" if parse_date(expiration) else "review"
    rule_results.append(build_rule_result("DOCUMENT_EXPIRATION", expiration_ok, expiration_msg,
                                          expiration_severity, 120 if expiration_severity == "hard_stop" else 35))

    # 2. Risk Scoring Algorithm
    base_score = 0
    flags = []
    hard_stop_failed = False

    for result in rule_results:
        if result["passed"]:
            continue

        base_score += result["risk_delta"]
        flags.append(f"{result['rule_id']}: {result['message']}")
        hard_stop_failed = hard_stop_failed or result["severity"] == "hard_stop"

    # Weather-zone surcharge, based on the parsed state rather than a substring search.
    state = extract_state(applicant_data)
    if state in get_rules()["HIGH_RISK_WEATHER_STATES"]:
        base_score += 15
        flags.append(f"ZONE_RISK: {state} is a configured high-risk weather state")
        rule_results.append(build_rule_result(
            "GEOGRAPHIC_RISK", False, f"{state} is a configured high-risk weather state", "review", 15))
    else:
        rule_results.append(build_rule_result(
            "GEOGRAPHIC_RISK", True,
            f"No configured geographic risk for {state or 'unknown state'}", "review", 15))

    # 3. Decision Routing Logic
    if hard_stop_failed:
        decision = "AUTO_REJECTED"
    elif base_score == 0:
        decision = "AUTO_APPROVED"
    else:
        decision = "AGENT_REVIEW"
        
    # Return structured evaluation
    result = {
        "decision": decision,
        "risk_score": base_score,
        "flags": flags,
        "agent_required": decision == "AGENT_REVIEW",
        "missing_fields": missing_fields,
        "rule_results": rule_results,
        "explainability": {
            "decision_basis": "hard_stop" if hard_stop_failed else "risk_score",
            "straight_through_processing": decision == "AUTO_APPROVED",
            "human_review_required": decision == "AGENT_REVIEW"
        }
    }
    
    return {
        "statusCode": 200,
        "body": json.dumps(result)
    }

def invoke_rules_engine_mock(applicant_data: Dict[str, Any], as_of: str = "") -> Dict[str, Any]:
    """
    Mock invocation handler for testing the Lambda function locally
    without deploying to AWS. Used by the Streamlit application.
    """
    # Wrap data in the standard API Gateway event format
    mock_event = {"applicant_data": applicant_data, "as_of": as_of}
    
    # Execute the handler directly
    response = lambda_handler(mock_event, None)
    
    # Parse the returned serialized body just like an API client would
    return parse_lambda_response_body(response)

def parse_lambda_response_body(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize Lambda-style responses into the flat rules result expected by app.py.

    Local calls return body as a JSON string. Real boto3 Lambda invokes may expose
    the payload/body as a StreamingBody, so read and decode it before json.loads.
    """
    if "Payload" in response:
        payload = response["Payload"]
        if hasattr(payload, "read"):
            payload = payload.read()
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        response = json.loads(payload) if isinstance(payload, str) else payload

    body = response.get("body", "{}")
    if hasattr(body, "read"):
        body = body.read()
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    if isinstance(body, str):
        return json.loads(body or "{}")
    if isinstance(body, dict):
        return body

    raise TypeError(f"Unsupported Lambda response body type: {type(body).__name__}")
