import sys
import types
import unittest

sys.modules.setdefault("boto3", types.SimpleNamespace(client=lambda *args, **kwargs: None))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

from scoring.lambda_rules_engine import invoke_rules_engine_mock
from scoring.policy_rules import extract_state, normalize_name, screen_sanctions

BASE = {
    "FIRST_NAME": "Jane", "LAST_NAME": "Doe", "DOB": "1985-06-15", "ID_NUMBER": "D12345678",
    "EXPIRATION_DATE": "2030-06-15", "ADDRESS": "123 Main St, Springfield, IL 62701", "ISSUING_STATE": "IL",
}
AS_OF = "2026-10-18"


def decide(**changes):
    return invoke_rules_engine_mock({**BASE, **changes}, as_of=AS_OF)["decision"]


class MissingFieldsRouteToReview(unittest.TestCase):
    def test_missing_dob_is_review_not_reject(self):
        self.assertEqual(decide(DOB=""), "AGENT_REVIEW")

    def test_unreadable_expiration_is_review_not_reject(self):
        self.assertEqual(decide(EXPIRATION_DATE="sometime 2030"), "AGENT_REVIEW")

    def test_real_expired_date_still_rejects(self):
        self.assertEqual(decide(EXPIRATION_DATE="2026-10-17"), "AUTO_REJECTED")


class AgeBoundaries(unittest.TestCase):
    def test_turns_18_tomorrow_is_rejected(self):
        self.assertEqual(decide(DOB="2008-10-19"), "AUTO_REJECTED")

    def test_turned_18_today_is_approved(self):
        self.assertEqual(decide(DOB="2008-10-18"), "AUTO_APPROVED")


class SanctionsMatching(unittest.TestCase):
    def test_name_order_case_and_accents_do_not_matter(self):
        self.assertEqual(normalize_name("QUINTERO-BAEZ, Marisol"), normalize_name("marisol quintero baez"))
        self.assertEqual(screen_sanctions("Dariusz", "Kowalczýk")[0], "match")

    def test_close_spelling_goes_to_review(self):
        self.assertEqual(screen_sanctions("Viktor", "Orlenkov")[0], "possible")
        self.assertEqual(decide(FIRST_NAME="Viktor", LAST_NAME="Orlenkov"), "AGENT_REVIEW")

    def test_unrelated_name_is_clear(self):
        self.assertEqual(screen_sanctions("Jane", "Doe")[0], "clear")


class GeographicRisk(unittest.TestCase):
    def test_floor_abbreviation_is_not_florida(self):
        address = "200 W Adams St, 3rd FL, Chicago, IL 60606"
        self.assertEqual(extract_state({"ADDRESS": address}), "IL")
        self.assertEqual(decide(ADDRESS=address), "AUTO_APPROVED")

    def test_florida_zip_without_issuing_state(self):
        self.assertEqual(decide(ADDRESS="88 Ocean Dr, Miami, FL 33139", ISSUING_STATE=""), "AGENT_REVIEW")


class EvalGate(unittest.TestCase):
    def test_eval_has_no_unsafe_approvals(self):
        from eval import run_eval
        self.assertEqual(run_eval.main([]), 0)


if __name__ == "__main__":
    unittest.main()
