# Android files

These files are generated from the carrier profiles by `tools/generate_android_outputs.py`. The checked-in set targets APN database version 8.

| File | Meaning |
| --- | --- |
| `apns-conf.xml` | Android APN XML, `version="8"`, each network and MVNO selector's rows ranked by the sources behind them |
| `apns/<country>.xml` | the rows of `apns-conf.xml` again, one file per country in the layout of LineageOS's `vendor/apn` |
| `carrier-config-list.xml` | CarrierConfig XML, blocks in generic-to-specific order |
| `carrier-config-overrides.json` | reviewed CarrierConfig values per profile |
| `lookup.json` | every profile with `match`, `capabilities`, `specificity`, and counts |
| `mccmnc-index.json` | profiles keyed by MCC/MNC |
| `carrier-id-index.json` | profiles keyed by Android carrier ID |
| `metadata.json` | target version, output counts, the profile IDs left out of each XML, the APN rows LineageOS's schema rejects, and the freshness window |

The counts change with every publish, so this page does not repeat them. `metadata.json` carries the APN row and CarrierConfig block counts under `output`. Print those and the other counts with these commands:

```bash
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["output"])'
python3 -c 'print(len(__import__("json").load(open("generated/android/carrier-config-overrides.json"))["profiles"]))'
python3 -c 'print(len(__import__("json").load(open("generated/android/mccmnc-index.json"))["mccmnc"]))'
python3 -c 'print(len(__import__("json").load(open("generated/android/carrier-id-index.json"))["android_carrier_ids"]))'
```

`metadata.json` also carries `checks_through`, the oldest source check behind the profiles, and `stale_after`, 180 days later. The oldest Samsung observations hold both. Print them with `python3 -c 'print(*[__import__("json").load(open("generated/android/metadata.json"))[k] for k in ("checks_through", "stale_after")])'`. Read both before you ship. The validators warn past `stale_after` and fail only with `--freshness fail`, which the daily public job passes. That job opens an issue labeled `stale-data` when it fails.

Two limits apply. Profiles whose match uses GID or ICCID prefixes are left out of `carrier-config-list.xml`, because `config_filter_records` in `tools/generate_android_outputs.py` skips them. On 2026-10-03 that is 1,080 GID-only, 298 ICCID-only, and 8 profiles with both. APN XML cannot express every match rule, so those profiles are left out of `apns-conf.xml`. Both lists are in `metadata.json`. The full facts stay in `lookup.json`.

The files in `apns/` are named by country code as in LineageOS, for example `DE.xml`. Each starts with an SPDX comment and repeats its country's lines of `apns-conf.xml` unchanged and in the same order. Rows go to files by MCC the way LineageOS split its list: MCC 425 rows appear in both `IL.xml` and `PS.xml`, MCC 647 rows in both `RE.xml` and `YT.xml`, and MCC 901 rows in `INTL.xml`. A row whose MCC has no country, such as 001 for test networks, stays only in `apns-conf.xml`. A row LineageOS's `apns-conf.xsd` rejects is in neither file. The public check validates `apns-conf.xml` and every country file against `tools/lineageos/apns-conf.xsd`. The validator checks that the files match `apns-conf.xml`. To count the files, run `ls generated/android/apns | wc -l`.

[docs/consume.md](../../docs/consume.md) shows how to package these files, how to use the per-country files in a LineageOS tree, and how to generate for another APN version.
