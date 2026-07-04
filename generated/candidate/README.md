# Candidate Claim Index

This directory contains generated indexes for community claims that have enough
evidence for opt-in testing.

Candidate claims are not stable phone defaults. They are a review and testing
layer between broad community input and the stable maintained-source snapshot.

The stable carrier snapshot is:

```text
generated/index.json
```

To refresh this index locally, run:

```bash
python3 tools/validate_community_claims.py --write-index
```
