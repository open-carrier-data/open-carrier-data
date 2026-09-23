# Android files

These files are generated from the carrier profiles by `tools/generate_android_outputs.py`. The checked-in set targets APN database version 8.

| File | Meaning |
| --- | --- |
| `apns-conf.xml` | Android APN XML, 21,900 rows, `version="8"` |
| `carrier-config-list.xml` | CarrierConfig XML, 4,115 blocks in generic-to-specific order |
| `carrier-config-overrides.json` | reviewed CarrierConfig values per profile, 5,119 profiles |
| `lookup.json` | every profile with `match`, `capabilities`, `specificity`, and counts |
| `mccmnc-index.json` | profiles keyed by MCC/MNC, 2,158 keys |
| `carrier-id-index.json` | profiles keyed by Android carrier ID, 179 keys |
| `metadata.json` | target version, output counts, the profile IDs left out of each XML, and the freshness window |

Counts come from these commands:

```bash
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["output"])'
python3 -c 'print(len(__import__("json").load(open("generated/android/carrier-config-overrides.json"))["profiles"]))'
python3 -c 'print(len(__import__("json").load(open("generated/android/mccmnc-index.json"))["mccmnc"]))'
python3 -c 'print(len(__import__("json").load(open("generated/android/carrier-id-index.json"))["android_carrier_ids"]))'
```

`metadata.json` also carries `checks_through`, the oldest source check behind the profiles, and `stale_after`, 180 days later. On 2026-09-23 they are 2026-07-13 and 2027-01-09. Read both before you ship. The validators warn past `stale_after` and fail only with `--freshness fail`, which CI passes.

Two limits apply. Profiles whose match uses GID or ICCID prefixes are left out of `carrier-config-list.xml`, because `config_filter_records` in `tools/generate_android_outputs.py` lines 409 to 414 skips them. On 2026-09-23 that is 985 GID-only, 300 ICCID-only, and 9 profiles with both. APN XML cannot express every match rule, so those profiles are left out of `apns-conf.xml`. Both lists are in `metadata.json`. The full facts stay in `lookup.json`.

[docs/consume.md](../../docs/consume.md) shows how to package these files and how to generate for another APN version.
