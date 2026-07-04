# Generated Output

This directory contains files generated from the public carrier profiles and
community claims.

Generated files are useful for consumers, but they are not a second source of
truth. Change the source profiles or claims first, then regenerate output.

## Files

```text
index.json              stable maintained-source snapshot
android/                Android APN, CarrierConfig, and lookup output
community/index.json    valid non-expired community claims
candidate/index.json    community claims suitable for opt-in testing
```

## Stable vs Community

`index.json` is the default stable snapshot. It is built from maintained
sources and sanitized public profiles. Private vendor/OEM source snapshots must
be refreshed and carry a recent checked date before they can affect this stable
snapshot.

Community and candidate indexes are separate. They let downstream projects
inspect or test user-reported edge cases without silently changing stable phone
behavior.

## Runtime Rule

Phones should use these files locally after a ROM, app, or build system has
packaged or synced them.

Do not make SIM loading, calls, emergency service, messaging, or IMS
registration depend on a live request to GitHub.

## Regeneration

When carrier profiles change, regenerate Android output and validate the stable
snapshot.

When community claims change, refresh the claim indexes:

```bash
python3 tools/validate_community_claims.py --write-index
```
