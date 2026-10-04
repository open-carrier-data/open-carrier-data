# Android files

These files are generated from the carrier profiles by `tools/generate_android_outputs.py`. The checked-in set targets APN database version 8.

| File | Meaning |
| --- | --- |
| `apns-conf.xml` | Android APN XML, `version="8"`, each network and MVNO selector's rows ranked by the sources behind them |
| `carrier-config-list.xml` | CarrierConfig XML in Android's `vendor.xml` format, blocks in generic-to-specific order |
| `lookup.json` | every profile with `match`, `capabilities`, `specificity`, counts, its freshness window and the month of its newest upstream entry |
| `metadata.json` | target version, output counts, the profile IDs left out of each XML, the APN rows LineageOS's schema rejects, the data digest and the freshness window |

The counts change with every publish, so this page does not repeat them. `metadata.json` carries the APN row and CarrierConfig block counts under `output`. Print them with this command:

```bash
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["output"])'
```

`metadata.json` also carries `checks_through`, the oldest source check behind the profiles, and `stale_after`, 180 days later: a lane-liveness window, not an accuracy date; `newest_entry` in `lookup.json` says how old a profile's data is. The oldest Samsung observations hold both. Print them with `python3 -c 'print(*[__import__("json").load(open("generated/android/metadata.json"))[k] for k in ("checks_through", "stale_after")])'`. Read both before you ship. The validators warn past `stale_after` and fail only with `--freshness fail`, which the daily public job passes. That job opens an issue labeled `stale-data` when it fails.

Both XML files start with a comment that names the data licence (CC0-1.0 for the project's own rights), `data_digest`, `checks_through` and `stale_after`. `data_digest` is a SHA-256 over the profile files, the evidence index and the generator's source, the same value as in `metadata.json`, so `git log -S <digest> -- generated/android/metadata.json` finds the commit that published a file you hold.

Until 2026-10-04 the directory also held `carrier-config-overrides.json`, `mccmnc-index.json` and `carrier-id-index.json`. They repeated the profiles and `lookup.json` keyed another way, and nothing but the validator read them, so they are no longer published.

Two limits apply. Profiles whose match uses GID or ICCID prefixes are left out of `carrier-config-list.xml`, because `config_filter_records` in `tools/generate_android_outputs.py` skips them; `metadata.json` says so as `carrier_config_gid_matching` and `carrier_config_iccid_matching`, both `omitted`. On 2026-10-04 that is 1,074 GID-only, 298 ICCID-only, and 8 profiles with both. APN XML cannot express every match rule, so those profiles are left out of `apns-conf.xml`. Both lists are in `metadata.json`. The full facts stay in `lookup.json`.

The public check validates `apns-conf.xml` against `tools/lineageos/apns-conf.xsd`, a copy of LineageOS's schema, and the validator refuses a row that schema rejects.

[docs/consume.md](../../docs/consume.md) shows how to package these files and how to generate for another APN version.
