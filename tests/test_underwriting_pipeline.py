import json
import sys
import types
import unittest
from datetime import date

sys.modules.setdefault("boto3", types.SimpleNamespace(client=lambda *args, **kwargs: None))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

from extraction.textract_handler import TextractIDHandler
from agent.bedrock_agent import UnderwritingAgent
import config
from scoring.decision_support import apply_identity_gate, build_decision_packet
from scoring.lambda_rules_engine import invoke_rules_engine_mock, parse_lambda_response_body
from scoring.policy_rules import check_age_rule, check_document_expiration_rule
from verification.rekognition_handler import RekognitionHandler


class FakeStreamingBody:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


class FailingTextractClient:
    def analyze_document(self, **kwargs):
        raise RuntimeError("textract unavailable")


class FailingRekognitionClient:
    def get_face_liveness_session_results(self, **kwargs):
        raise RuntimeError("rekognition unavailable")

    def compare_faces(self, **kwargs):
        raise RuntimeError("rekognition unavailable")


class TextractQueryParsingTest(unittest.TestCase):
    def setUp(self):
        self.original_demo_mode = config.DEMO_MODE

    def tearDown(self):
        config.DEMO_MODE = self.original_demo_mode

    def test_maps_query_result_text_to_parent_query_alias(self):
        response = {
            "Blocks": [
                {
                    "BlockType": "QUERY",
                    "Id": "query-first-name",
                    "Query": {
                        "Text": "What is the first name?",
                        "Alias": "FIRST_NAME"
                    },
                    "Relationships": [
                        {
                            "Type": "ANSWER",
                            "Ids": ["answer-first-name"]
                        }
                    ]
                },
                {
                    "BlockType": "QUERY",
                    "Id": "query-dob",
                    "Query": {
                        "Text": "What is the date of birth?",
                        "Alias": "DOB"
                    },
                    "Relationships": [
                        {
                            "Type": "ANSWER",
                            "Ids": ["answer-dob"]
                        }
                    ]
                },
                {
                    "BlockType": "QUERY_RESULT",
                    "Id": "answer-first-name",
                    "Text": "Jane"
                },
                {
                    "BlockType": "QUERY_RESULT",
                    "Id": "answer-dob",
                    "Text": "1985-06-15"
                }
            ]
        }

        parsed = TextractIDHandler.parse_query_results(response)

        self.assertEqual(
            parsed,
            {
                "FIRST_NAME": "Jane",
                "DOB": "1985-06-15"
            }
        )

    def test_live_textract_errors_do_not_return_demo_identity(self):
        config.DEMO_MODE = False
        handler = TextractIDHandler.__new__(TextractIDHandler)
        handler.client = FailingTextractClient()

        self.assertEqual(handler.extract_id_data(b"document"), {})

    def test_demo_mode_returns_demo_identity_without_client(self):
        config.DEMO_MODE = True
        handler = TextractIDHandler.__new__(TextractIDHandler)
        handler.client = None

        self.assertEqual(handler.extract_id_data(b"document"), TextractIDHandler.fallback_data())


class LambdaResponseParsingTest(unittest.TestCase):
    def test_decodes_boto3_streaming_payload_response(self):
        rules_result = {
            "decision": "AUTO_APPROVED",
            "risk_score": 0,
            "flags": [],
            "agent_required": False
        }
        response = {
            "Payload": FakeStreamingBody(
                json.dumps({
                    "statusCode": 200,
                    "body": json.dumps(rules_result)
                }).encode("utf-8")
            )
        }

        self.assertEqual(parse_lambda_response_body(response), rules_result)

    def test_incomplete_ocr_routes_to_review_instead_of_auto_reject(self):
        result = invoke_rules_engine_mock({
            "FIRST_NAME": "Jane",
            "LAST_NAME": "Doe",
            "DOB": "1985-06-15",
            "ID_NUMBER": "",
            "EXPIRATION_DATE": "2030-06-15"
        })

        self.assertEqual(result["decision"], "AGENT_REVIEW")
        self.assertIn("ID_NUMBER", result["missing_fields"])

    def test_expired_document_is_hard_rejected(self):
        result = invoke_rules_engine_mock({
            "FIRST_NAME": "Jane",
            "LAST_NAME": "Doe",
            "DOB": "1985-06-15",
            "ID_NUMBER": "D12345678",
            "EXPIRATION_DATE": "2020-06-15"
        })

        self.assertEqual(result["decision"], "AUTO_REJECTED")
        self.assertTrue(any(rule["rule_id"] == "DOCUMENT_EXPIRATION" for rule in result["rule_results"]))


class PolicyRuleTest(unittest.TestCase):
    def test_age_rule_accepts_common_ocr_date_format(self):
        self.assertEqual(
            check_age_rule("06/15/1985", today=date(2026, 5, 6)),
            (True, "Age verified (40)")
        )

    def test_document_expiration_rule_uses_exact_date(self):
        self.assertEqual(
            check_document_expiration_rule("05/05/2026", today=date(2026, 5, 6)),
            (False, "ID document expired on 2026-05-05")
        )


class RekognitionFallbackTest(unittest.TestCase):
    def setUp(self):
        self.original_demo_mode = config.DEMO_MODE

    def tearDown(self):
        config.DEMO_MODE = self.original_demo_mode

    def test_face_compare_fails_when_id_document_bytes_are_missing(self):
        handler = RekognitionHandler()

        self.assertEqual(
            handler.compare_faces(b"selfie-bytes", b""),
            {"match": False, "similarity": 0}
        )

    def test_live_rekognition_errors_fail_closed(self):
        config.DEMO_MODE = False
        handler = RekognitionHandler.__new__(RekognitionHandler)
        handler.client = FailingRekognitionClient()

        self.assertEqual(
            handler.verify_liveness("session-id"),
            {"status": "FAILED", "confidence": 0}
        )
        self.assertEqual(
            handler.compare_faces(b"selfie-bytes", b"id-bytes"),
            {"match": False, "similarity": 0}
        )

    def test_demo_mode_returns_mock_rekognition_when_client_is_absent(self):
        config.DEMO_MODE = True
        handler = RekognitionHandler.__new__(RekognitionHandler)
        handler.client = None

        self.assertEqual(
            handler.verify_liveness("session-id"),
            {"status": "SUCCEEDED", "confidence": 99.2}
        )
        self.assertEqual(
            handler.compare_faces(b"selfie-bytes", b"id-bytes"),
            {"match": True, "similarity": 98.5}
        )


class BedrockFallbackTest(unittest.TestCase):
    def test_fallback_rationale_respects_rejected_rules_decision(self):
        result = UnderwritingAgent.fallback_decision({
            "rules_evaluation": {
                "decision": "AUTO_REJECTED",
                "flags": ["IDENTITY_VERIFICATION_FAILED"]
            }
        })

        self.assertIn("rejection", result["decision_text"].lower())
        self.assertNotIn("Recommending APPROVAL", result["decision_text"])


class DecisionSupportTest(unittest.TestCase):
    def test_identity_gate_adds_hard_stop_failure(self):
        result = apply_identity_gate(
            {
                "decision": "AUTO_APPROVED",
                "risk_score": 0,
                "flags": [],
                "rule_results": []
            },
            {
                "liveness_confidence": 99.2,
                "face_match": 40,
                "face_match_passed": False
            }
        )

        self.assertEqual(result["decision"], "AUTO_REJECTED")
        self.assertIn("IDENTITY_VERIFICATION_FAILED: Face liveness or ID match below policy threshold", result["flags"])

    def test_decision_packet_contains_review_actions_and_audit_controls(self):
        packet = build_decision_packet(
            applicant_id="APP-123",
            applicant_data={"FIRST_NAME": "Jane"},
            rules_result={
                "decision": "AGENT_REVIEW",
                "risk_score": 35,
                "flags": ["OCR_COMPLETENESS: Missing required OCR fields: ID_NUMBER"],
                "missing_fields": ["ID_NUMBER"],
                "rule_results": [
                    {
                        "rule_id": "OCR_COMPLETENESS",
                        "passed": False,
                        "severity": "review",
                        "risk_delta": 35,
                        "message": "Missing required OCR fields: ID_NUMBER"
                    }
                ]
            },
            liveness_metrics={"liveness_confidence": 99.2, "face_match": 98.5},
            agent_result={"decision_text": "Manual review required."}
        )

        self.assertTrue(packet["human_review_required"])
        self.assertTrue(packet["audit_controls"])
        self.assertIn("Request clearer ID image", packet["review_actions"][0])


if __name__ == "__main__":
    unittest.main()
