# Community claims

A community claim is a structured report that one carrier setting should be added, confirmed, corrected, removed, or overridden. It carries the carrier match, the change, the evidence, and the date it was last verified. It lives as one JSON file under `community/claims/` and follows `schemas/community-claim.schema.json`.

## Why claims stay apart from stable data

Carrier data changes phone behaviour. A wrong row can break data, MMS, VoLTE, Wi-Fi calling, or emergency routing. So a claim never overwrites a carrier profile. The validator checks it, computes its risk and expiry, and indexes it. Downstream projects then decide whether to test it.

Two generated indexes expose claims:

| Index | Contents |
| --- | --- |
| `generated/community/index.json` | every valid claim that has not expired |
| `generated/candidate/index.json` | the subset with risk below high, enough confidence, change type `add`, `confirm`, or `correct`, and no stable conflict |

The stable snapshot stays `generated/index.json`. On 2026-09-23 there are zero claims. Count them with `ls community/claims | wc -l`.

## How the validator judges a claim

You supply the facts and the evidence. The validator computes everything else:

- risk from the match breadth, the changed fields, and the change type
- expiry from risk, at 365, 180, or 90 days
- overlap and conflicts with stable profiles
- the channel, `community` or `candidate`

You cannot set your own risk or mark a claim verified.

## Submit a claim

Use the `Tested carrier-data change` issue form if you do not want to write JSON. Fork the repo and add a file under `community/claims/` if you do. [CONTRIBUTING.md](../CONTRIBUTING.md) has the steps for both paths, the private-data rule, and the local checks.
