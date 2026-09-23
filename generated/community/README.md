# Community claim index

This directory holds the generated index of every valid community claim that has not expired. These claims are input for investigation and opt-in testing. They are not stable defaults. The stable snapshot is `generated/index.json`.

| File | Meaning |
| --- | --- |
| `index.json` | `schema_version`, `description`, and a `claims` array of valid claims |

The validator computes each claim's risk, expiry, confidence, stable overlap, and conflicts. Expired claims drop out on the next run. On 2026-09-23 the array is empty.

To refresh the index, run `python3 tools/validate_community_claims.py --write-index`.
