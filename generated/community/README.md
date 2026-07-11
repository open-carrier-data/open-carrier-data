# Community Claim Index

This directory contains generated indexes for valid community claims.

`index.json` lists public, non-expired claims that pass validation. These
claims are useful for investigation and opt-in testing, but they are not stable
phone defaults.

Confidence, risk, expiry, stable overlap, and conflicts are computed by the
validator. Contributors cannot self-approve a claim. Expired claims are
automatically excluded.

The stable carrier snapshot is:

```text
generated/index.json
```

To refresh this index locally, run:

```bash
python3 tools/validate_community_claims.py --write-index
```
