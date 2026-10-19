# Eval results

38 applicants from `eval/applicants.jsonl`, evaluated as of 2026-10-18.

| Metric | Value |
|---|---|
| Decision accuracy | 38/38 (100%) |
| Unsafe auto-approvals | 0 |
| Wrongful auto-rejections | 0 |

## Confusion matrix (rows = expected, columns = got)

| | AUTO_APPROVED | AGENT_REVIEW | AUTO_REJECTED |
|---|---|---|---|
| **AUTO_APPROVED** | 13 | 0 | 0 |
| **AGENT_REVIEW** | 0 | 9 | 0 |
| **AUTO_REJECTED** | 0 | 0 | 16 |

## By case type

| Type | Cases | Correct |
|---|---|---|
| clean | 4 | 4 |
| age | 7 | 7 |
| expiry | 3 | 3 |
| missing | 5 | 5 |
| sanctions | 7 | 7 |
| geo | 4 | 4 |
| identity | 4 | 4 |
| combined | 4 | 4 |

## Misses

None.
