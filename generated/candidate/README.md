# Candidate claim index

This directory holds the generated index of community claims that have enough evidence for opt-in testing. Candidate claims are not stable defaults. The stable snapshot is `generated/index.json`.

| File | Meaning |
| --- | --- |
| `index.json` | `schema_version`, `description`, and a `claims` array of candidate claims |

A claim lands here when the validator computes medium or low risk and enough confidence. The change type must be `add`, `confirm`, or `correct`, with no conflict against a stable profile. On 2026-09-23 the array is empty.

To refresh the index, run `python3 tools/validate_community_claims.py --write-index`.
