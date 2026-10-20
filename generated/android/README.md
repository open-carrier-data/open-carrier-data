# Android files

These files are generated from the carrier profiles by `tools/generate_android_outputs.py`. The checked-in set targets APN database version 8.

| File | Meaning | Tier |
| --- | --- | --- |
| `apns-conf.xml` | Android APN XML, `version="8"`, each network and MVNO selector's rows ranked by the sources behind them, current vendors' values first, and the attach type `ia` only on rows a current vendor backs where one gives the attach APN | for ROMs: supported since the boot check on the owner's phone passed with `data-2026.10` on 2026-10-20 (`data-2026.10`'s `release.json`, published before, still says `rom, pending the S20 boot check`) |
| `carrier-config-list.xml` | CarrierConfig XML in Android's `vendor.xml` format, blocks in generic-to-specific order | not for ROM application and not a release asset until the per-key review of its emergency, TTY, RTT, WPS and `iwlan.*` keys has run |
| `lookup.json` | every profile with `match`, `capabilities`, `specificity`, counts, its freshness window and the month of its newest upstream entry | supported for apps and tools, since `data-2026.10` |
| `metadata.json` | target version, output counts, the profile IDs left out of each XML, the APN rows LineageOS's schema rejects, the rows that lost `ia`, the data digest and the freshness window | supported for apps and tools, since `data-2026.10` |

The files here are the latest publish on `main`, the edge channel, and change several times a day. The tiers above hold for the files of a release; the first is `data-2026.10`, published on 2026-10-19. [docs/releases.md](../../docs/releases.md) describes the monthly releases and their tiers.

The counts change with every publish, so this page does not repeat them. `metadata.json` carries the APN row and CarrierConfig block counts under `output`. Print them with this command:

```bash
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["output"])'
```

`metadata.json` also carries `checks_through`, the oldest source check behind the profiles, and `stale_after`, 180 days later: a lane-liveness window, not an accuracy date; `newest_entry` in `lookup.json` says how old a profile's data is. The oldest Samsung observations hold both. Print them with `python3 -c 'print(*[__import__("json").load(open("generated/android/metadata.json"))[k] for k in ("checks_through", "stale_after")])'`. Read both before you ship. The validators warn past `stale_after` and fail only with `--freshness fail`, which the daily public job passes. That job opens an issue labeled `stale-data` when it fails.

Both XML files start with a comment that names the data licence (CC0-1.0 for the project's own rights), `data_digest`, `checks_through` and `stale_after`. `data_digest` is a SHA-256 over the profile files, the evidence index and the generator's source, the same value as in `metadata.json`, so `git log -S <digest> -- generated/android/metadata.json` finds the commit that published a file you hold.

Until 2026-10-04 the directory also held `carrier-config-overrides.json`, `mccmnc-index.json` and `carrier-id-index.json`. They repeated the profiles and `lookup.json` keyed another way, and nothing but the validator read them, so they are no longer published.

Two limits apply. Profiles whose match uses GID or ICCID prefixes are left out of `carrier-config-list.xml`, because `config_filter_records` in `tools/generate_android_outputs.py` skips them; `metadata.json` says so as `carrier_config_gid_matching` and `carrier_config_iccid_matching`, both `omitted`. [docs/consume.md](../../docs/consume.md) gives the command that splits them into GID, ICCID and both. APN XML cannot express every match rule, so those profiles are left out of `apns-conf.xml`. Both lists are in `metadata.json`. The full facts stay in `lookup.json`.

The public check validates `apns-conf.xml` against `tools/lineageos/apns-conf.xsd`, a copy of LineageOS's schema, and the validator refuses a row that schema rejects.

[docs/consume.md](../../docs/consume.md) shows how to package these files and how to generate for another APN version.
