# Community Claims

Community claims are structured reports about carrier settings.

Use them when someone has evidence for a specific carrier-data change, but the
change is not ready to become stable default data yet.

## What A Claim Is

A claim says:

- which carrier or MVNO it applies to;
- what setting should be added, changed, or removed;
- how the result was tested or sourced;
- when it was last verified;
- when it expires.

A claim can help with edge cases faster than waiting for every maintained
source to update. It still stays separate from the stable database until it is
reviewed and handled through the normal source/import path.

## How To Submit One

You do not need write access to the main repo.

Use one of these paths:

- open a guided tested-claim issue:
  https://github.com/open-carrier-data/open-carrier-data/issues/new/choose
- or fork the repo, add a JSON claim under `community/claims/`, and open a pull
  request.

Use the issue path if you do not want to write JSON or use Git. Use the pull
request path if you already know the exact structured change.

## Why Claims Are Separate

Carrier data changes real phone behavior. A bad entry can break data, MMS,
VoLTE, Wi-Fi Calling, roaming, call forwarding, or emergency-related behavior.

That is why community claims are validated and indexed, but do not silently
overwrite stable profiles.

The generated claim indexes are:

```text
generated/community/index.json    valid non-expired claims
generated/candidate/index.json    claims suitable for opt-in testing
```

The stable database remains:

```text
generated/index.json
```

## Claim Rules

- Use public, non-personal facts.
- Include evidence and a test date.
- Keep the SIM match as specific as possible.
- Add an expiry date so old reports do not stay trusted forever.
- Do not include phone numbers, account data, personal passwords, tokens,
  private vendor credentials, full IMSI values, full ICCID values, IMEI, raw
  logs, raw bugreports, raw firmware dumps, or private vendor responses.
- Public APN usernames or passwords are acceptable only when they are carrier
  settings from public docs or visible phone configuration, not private account
  credentials.

The validator computes risk from the change type, match breadth, evidence,
freshness, and conflicts with stable data. A claim may include a risk value,
but CI rejects it if that value is lower than the computed risk.

## Local Checks

After adding or changing a claim, run:

```bash
python3 tools/validate_community_claims.py --write-index
python3 tools/validate_public_carrier_data.py carriers generated/index.json
```

For the full contribution guide, read `../CONTRIBUTING.md`.
