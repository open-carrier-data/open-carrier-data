# Contribute to Open Carrier Data

This guide shows the five ways to contribute and the checks to run before you submit. You do not need write access to the repo for any of them.

## Keep private data out

Before you post anything, remove every private value. Never include:

- phone numbers, account numbers, or customer IDs
- personal passwords, tokens, cookies, private URLs, or vendor credentials
- full IMSI or ICCID values
- IMEI, serial numbers, Android ID, or other device identifiers
- raw modem logs, bugreports, vendor responses, or firmware dumps

Safe values are the carrier name, country, brand, MCC/MNC, and Android carrier ID. A shortened ICCID prefix is safe when it is already public. APN values from public docs or the phone's settings screen are safe. So is a feature result such as "MMS receive works". A public APN username or password is fine only when it is a shared carrier setting. When unsure, leave the value out and describe the problem without it.

The claim validator blocks any digit run of 14 to 22 characters as a possible full IMSI or ICCID. The pattern is `BLOCK_PATTERNS` in `tools/validate_community_claims.py` line 43.

## Report wrong or missing carrier data

Use this path when a carrier is missing, a setting looks wrong, or you cannot write JSON.

1. Open the `Wrong or missing carrier data` form at `https://github.com/open-carrier-data/open-carrier-data/issues/new/choose`.
2. Give the carrier name, country, and whether it is a host network or an MVNO.
3. Name the affected feature, what happens, and what you expected.
4. Add safe match details such as MCC/MNC, SPN, a GID prefix, or an Android carrier ID.
5. Add the device, OS, test date, and a public source link if you have them.

## Suggest a maintained source

Use this path when you know an upstream that automation could import.

1. Open the `Maintained source suggestion` form.
2. Name the source, its owner, and what carrier facts it holds.
3. State its license or usage terms if known. A current source can still be unfit for redistribution.

A good source is maintained by a carrier, OEM, OS project, or public data project. Automation can refresh it, and its facts can be translated without publishing private material.

## Submit a tested fix as a claim

Use this path when you tested an exact setting on a real SIM. Pick the issue form or the pull request.

To submit through the issue form:

1. Open the `Tested carrier-data change` form.
2. Fill in the carrier, MCC/MNC, change type, the setting, the evidence type, the test result, and the evidence date.
3. Tick the privacy check. Automation converts the issue into a claim file, validates it, and opens a pull request on `automation/community-claim-<issue number>`.
4. If validation fails, automation comments on the issue. Edit the issue to retry.

To submit through a pull request:

1. Fork the repo and add one JSON file under `community/claims/` that follows `schemas/community-claim.schema.json`.
2. Set `schema_version`, `claim_id`, `summary`, `status`, `carrier_match`, `change_type`, `changes`, `evidence`, and `last_verified`.
3. Leave out `expires`. The validator computes it.
4. Run the local checks below and open the pull request.

Do not set your own risk or mark the claim verified. A reviewer still judges whether the evidence is credible.

## Change a stable carrier profile

Stable profiles come from maintained sources through the sanitizer. Do not edit `carriers/open/` or `generated/` by hand as a shortcut.

1. Open an issue that names the profile and the wrong value.
2. If a source is wrong, point at the source. The fix lands through the import path.
3. A direct profile change is accepted only when it is narrow, reproducible, and backed by a maintained source.

## Improve tooling or docs

Open a pull request for schema, validator, generator, test, or documentation changes. Keep each change to one topic. To report a problem without a fix, use the `Documentation, schema, or tooling issue` form.

## Run the local checks

To check profiles, the device catalog, and claims, run from the repo root:

```bash
python3 tools/validate_public_carrier_data.py carriers generated/index.json
python3 tools/validate_device_catalog.py generated/devices
python3 tools/validate_community_claims.py community/claims generated/community --stable-dir carriers --evidence-index generated/evidence-index.json
```

To refresh the claim indexes after adding or changing a claim, run:

```bash
python3 tools/validate_community_claims.py --write-index
```

To run the tests the public workflow runs, execute:

```bash
python3 tools/test_community_claims.py
python3 tools/test_issue_to_claim.py
python3 tools/test_generated_android_outputs.py
python3 tools/test_carrier_relevance_contract.py
python3 tools/test_resolve_carrier_profiles.py
```

## How a claim becomes stable

A claim never becomes a stable profile on its own. The validator computes its risk from the match breadth, the changed fields, and the change type. Risk sets the expiry. `MAX_EXPIRY_DAYS` in `tools/validate_community_claims.py` lines 31 to 35 gives 365 days for low, 180 for medium, and 90 for high. `recommended_channel` at lines 680 to 702 picks the channel. `candidate` needs a risk below high, enough confidence, a change type of `add`, `confirm`, or `correct`, and no conflict with a stable profile. Everything else stays `community`.

Valid claims appear in `generated/community/index.json`. Candidate claims also appear in `generated/candidate/index.json`. Expired claims drop out of both. A claim reaches `carriers/open/` only when a maintained source confirms it and the import path publishes it. On 2026-09-23 there are zero claims. Count them with `ls community/claims | wc -l`.
