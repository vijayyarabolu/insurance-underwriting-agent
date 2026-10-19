"""
Decision eval for the underwriting pipeline.

Runs every applicant in eval/applicants.jsonl through rules, the identity gate
and the decision packet, with today's date pinned to AS_OF so age and expiry
cases stay stable. Reports decision accuracy, a confusion matrix, and the
count that matters most: unsafe approvals, meaning an applicant who should
have been rejected or reviewed but was approved automatically.

    python -m eval.run_eval            # report, exit 1 if a gate fails
    python -m eval.run_eval --write    # also rewrite eval/RESULTS.md
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from scoring.pipeline import underwrite

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "applicants.jsonl"
RESULTS = ROOT / "RESULTS.md"
AS_OF = "2026-10-18"
DECISIONS = ["AUTO_APPROVED", "AGENT_REVIEW", "AUTO_REJECTED"]
MIN_ACCURACY = 0.95


def run():
    rows = []
    for line in CASES.read_text().splitlines():
        case = json.loads(line)
        packet = underwrite(case["id"], case["applicant"], case["liveness"], as_of=AS_OF)
        rows.append({**case, "got": packet["final_decision"], "packet": packet})
    return rows


def render(rows):
    correct = sum(r["got"] == r["expected_decision"] for r in rows)
    unsafe = [r for r in rows if r["got"] == "AUTO_APPROVED" and r["expected_decision"] != "AUTO_APPROVED"]
    over_strict = [r for r in rows if r["got"] == "AUTO_REJECTED" and r["expected_decision"] != "AUTO_REJECTED"]
    matrix = Counter((r["expected_decision"], r["got"]) for r in rows)

    lines = ["# Eval results", "",
             f"{len(rows)} applicants from `eval/applicants.jsonl`, evaluated as of {AS_OF}.", "",
             "| Metric | Value |", "|---|---|",
             f"| Decision accuracy | {correct}/{len(rows)} ({correct / len(rows):.0%}) |",
             f"| Unsafe auto-approvals | {len(unsafe)} |",
             f"| Wrongful auto-rejections | {len(over_strict)} |", "",
             "## Confusion matrix (rows = expected, columns = got)", "",
             "| | " + " | ".join(DECISIONS) + " |", "|---|" + "---|" * len(DECISIONS)]
    for expected in DECISIONS:
        lines.append(f"| **{expected}** | " + " | ".join(str(matrix[(expected, got)]) for got in DECISIONS) + " |")

    lines += ["", "## By case type", "", "| Type | Cases | Correct |", "|---|---|---|"]
    for case_type in dict.fromkeys(r["type"] for r in rows):
        group = [r for r in rows if r["type"] == case_type]
        lines.append(f"| {case_type} | {len(group)} | {sum(r['got'] == r['expected_decision'] for r in group)} |")

    misses = [r for r in rows if r["got"] != r["expected_decision"]]
    lines += ["", "## Misses", ""]
    lines += [f"- `{r['id']}` {r['description']}: expected `{r['expected_decision']}`, got `{r['got']}`"
              for r in misses] or ["None."]
    return "\n".join(lines) + "\n", correct / len(rows), len(unsafe)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    report, accuracy, unsafe = render(run())
    print(report)
    if args.write:
        RESULTS.write_text(report)

    failures = []
    if unsafe:
        failures.append(f"{unsafe} unsafe auto-approvals")
    if accuracy < MIN_ACCURACY:
        failures.append(f"accuracy {accuracy:.2f} < {MIN_ACCURACY}")
    if failures:
        print("EVAL GATE FAILED: " + "; ".join(failures))
        return 1
    print("Eval gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
