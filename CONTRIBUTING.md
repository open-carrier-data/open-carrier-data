# Contribute to Open Carrier Data

This guide shows the three issue forms, the pull request path for tools and docs, and the checks to run before you submit. You do not need write access to the repo for any of them.

## Keep private data out

Before you post anything, remove every private value. Never include:

- phone numbers, account numbers, or customer IDs
- personal passwords, tokens, cookies, private URLs, or vendor credentials
- full IMSI or ICCID values
- IMEI, serial numbers, Android ID, or other device identifiers
- raw modem logs, bugreports, vendor responses, or firmware dumps

Safe values are the carrier name, country, brand, MCC/MNC, and Android carrier ID. A shortened ICCID prefix is safe when it is already public. APN values from public docs or the phone's settings screen are safe. So is a feature result such as "MMS receive works". A public APN username or password is fine only when it is a shared carrier setting. When unsure, leave the value out and describe the problem without it.

## Report wrong or missing carrier data

Use this path when a carrier is missing, a setting looks wrong, or you verified a fix on a device.

1. Open the `Wrong or missing carrier data` form at `https://github.com/open-carrier-data/open-carrier-data/issues/new/choose`.
2. Give the carrier name, country, and whether it is a host network or an MVNO.
3. Name the affected feature, what happens, and what you expected.
4. Add safe match details such as MCC/MNC, SPN, a GID prefix, or an Android carrier ID.
5. If you tested a fix, state the device, the setting you changed, the result, and the date.
6. Add a public source link if you have one.

## Suggest a maintained source

Use this path when you know an upstream that automation could import.

1. Open the `Maintained source suggestion` form.
2. Name the source, its owner, and what carrier facts it holds.
3. State its license or usage terms if known. A current source can still be unfit for redistribution.

A good source is maintained by a carrier, OEM, OS project, or public data project. Automation can refresh it, and its facts can be translated without publishing private material.

## Improve tooling or docs

Open a pull request for schema, validator, generator, test, or documentation changes. Keep each change to one topic. To report a problem without a fix, use the `Documentation, schema, or tooling issue` form.

## Why carrier data changes are not accepted by hand

Stable profiles in `carriers/open/` and the files under `generated/` come from maintained sources through the private sanitizer. On 2026-09-23 there is no path for a hand-written carrier data change. A pull request that edits those files is closed with a pointer to the issue forms.

Two reasons drive that. First, every published value traces to a source snapshot in `generated/evidence-index.json`. A hand edit has no snapshot, so the evidence index would record provenance the data does not have. Second, the project cannot verify a test result from an issue. A tested fix stays a report until a maintained source confirms it or a maintainer curates it into the data with the evidence attached.

A correction reaches stable data in two ways. A maintained source publishes it and the import path picks it up. Or a maintainer curates the change. An automated path for tested community changes existed until 2026-09-23 and was removed unused.

## Run the local checks

To check profiles and the device catalog, run from the repo root:

```bash
python3 tools/validate_public_carrier_data.py carriers generated/index.json --freshness fail
python3 tools/validate_device_catalog.py generated/devices --freshness fail
```

To run the tests the public workflow runs, execute:

```bash
python3 tools/test_generated_android_outputs.py
python3 tools/test_carrier_relevance_contract.py
python3 tools/test_resolve_carrier_profiles.py
```
