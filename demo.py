"""
Command-line demo: run a sample applicant through the full pipeline offline.

    python demo.py                 # list the sample applicants
    python demo.py u21             # sanctions match with surname-first OCR
    python demo.py u29 --json      # full decision packet

No AWS account needed. Set UNDERWRITING_LLM=anthropic and ANTHROPIC_API_KEY to
have Claude write the rationale (the decision still comes from the rules).
"""

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("DEMO_MODE", "true")

from scoring.pipeline import underwrite  # noqa: E402

CASES = Path(__file__).resolve().parent / "eval" / "applicants.jsonl"


def main():
    cases = {c["id"]: c for c in map(json.loads, CASES.read_text().splitlines())}
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", nargs="?")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.case_id:
        for cid, case in cases.items():
            print(f"{cid}  {case['expected_decision']:<14} {case['description']}")
        return

    case = cases[args.case_id]
    packet = underwrite(case["id"], case["applicant"], case["liveness"], as_of="2026-10-18")
    if args.json:
        print(json.dumps(packet, indent=2, default=str))
        return
    print(f"\n{case['description']}\n")
    print(f"decision: {packet['final_decision']}   risk score: {packet['risk_score']}   "
          f"confidence: {packet['decision_confidence']}%")
    for rule in packet["rule_results"]:
        print(f"  {'PASS' if rule['passed'] else 'FAIL'}  {rule['rule_id']:<22} {rule['message']}")
    print("\nnext actions:")
    for action in packet["review_actions"]:
        print(f"  - {action}")
    print(f"\nrationale: {packet['agent_rationale']}\n")


if __name__ == "__main__":
    main()
