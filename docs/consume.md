# Use the data in a ROM, an app, or a build

This guide shows how to package the generated files, how to resolve profiles from code, how to check freshness, and how to validate a snapshot. Run every command from the repo root.

## Use the data in an Android ROM

The Android files live in `generated/android/`. Each file has one job.

| File | Put it where |
| --- | --- |
| `apns-conf.xml` | the APN database path your TelephonyProvider reads |
| `carrier-config-list.xml` | your CarrierConfig overlay input |
| `carrier-config-overrides.json` | a build-time source for CarrierConfig if you do not consume XML |
| `lookup.json`, `mccmnc-index.json`, `carrier-id-index.json` | any local lookup your ROM does at SIM load |
| `metadata.json` | your build log, so you know which profiles the XML left out |

To copy the Android files into a build tree, run:

```bash
cp -r generated/android/ /path/to/your/build/carrier-data/
```

The checked-in `apns-conf.xml` carries `version="8"`. Android's TelephonyProvider expects the APN database version to match the build. To generate for a different version, write into a scratch directory so the checked-in files stay untouched:

```bash
mkdir -p /tmp/ocd-out
python3 tools/generate_android_outputs.py carriers /tmp/ocd-out --apn-version 9
head -2 /tmp/ocd-out/android/apns-conf.xml
```

The generator prints one summary line and the XML header shows the new version:

```text
generated Android output for 6748 profile(s): 21900 APN row(s), 5119 CarrierConfig profile(s), 2158 MCC/MNC key(s), 179 Android carrier ID key(s), 4115 CarrierConfig XML block(s)
<?xml version="1.0" encoding="utf-8"?>
<apns version="9">
```

Read `metadata.json` before you ship. On 2026-09-23 it lists 33 profiles whose match cannot be expressed in APN XML and 1,294 profiles left out of CarrierConfig XML. Print both counts with:

```bash
python3 -c 'print({k: v for k, v in __import__("json").load(open("generated/android/metadata.json"))["omissions"].items() if k.endswith("_unrepresentable_match") and not k.endswith("ids_with_unrepresentable_match")})'
```

The CarrierConfig omissions are profiles whose match uses GID or ICCID prefixes, which `config_filter_records` in `tools/generate_android_outputs.py` lines 409 to 414 skips. Of the 1,294, 985 use GID only, 300 use ICCID only, and 9 use both. Recount them with:

```bash
python3 <<'PY'
import json
lookup = json.load(open("generated/android/lookup.json"))
omitted = set(json.load(open("generated/android/metadata.json"))["omissions"]["carrier_config_profile_ids_with_unrepresentable_match"])
kinds = {"gid": 0, "iccid": 0, "both": 0}
for profile in lookup["profiles"]:
    if profile["profile_id"] not in omitted:
        continue
    match = profile["match"]
    gid = bool(match.get("gid1_prefixes") or match.get("gid2_prefixes"))
    iccid = bool(match.get("iccid_prefixes"))
    kinds["both" if gid and iccid else "gid" if gid else "iccid"] += 1
print(kinds)
PY
```

Those profiles stay available in `lookup.json`.

## Use the data in an app or tool

Read the profiles directly when you need the full shape. `generated/index.json` lists every profile with its path. `generated/android/lookup.json` adds `match`, `capabilities`, and `specificity` per profile, so most tools never open the individual files.

To resolve every profile for one SIM, run the resolver with what you know:

```bash
python3 tools/resolve_carrier_profiles.py --mccmnc 26202 --spn Vodafone.de
```

The first lines of the output are:

```text
{
  "profiles": [
    {
      "android_apn_count": 10,
      "capabilities": {
```

The resolver accepts `--mccmnc`, `--spn`, `--gid1`, `--gid2`, `--iccid`, `--imsi`, and `--android-carrier-id`. It returns profiles in generic-to-specific order. Apply each one on top of the previous one. To reuse the rules in your own code, read `specificity` at line 81 and the match loop in `tools/resolve_carrier_profiles.py`.

## Check freshness before you ship

Three facts tell you whether a snapshot is safe to ship.

To read the APN target version and the omission counts, run:

```bash
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["target"])'
```

Output on 2026-09-23:

```text
{'apn_database_version': 8, 'carrier_config_gid_matching': 'exact_only'}
```

To read the oldest source check date, run:

```bash
python3 -c 'print(min(s["checked_at"] for s in __import__("json").load(open("generated/evidence-index.json"))["source_snapshots"]))'
```

Output on 2026-09-23:

```text
2026-07-13
```

The 180-day rule applies to that date. `tools/validate_public_carrier_data.py` lines 754 to 757 fail the whole run when any snapshot is older than 180 days by `checked_at`. `tools/validate_device_catalog.py` line 195 does the same for the catalog. With the oldest check at 2026-07-13, both validators fail from 2027-01-10 and the daily public CI turns red until sources are re-checked. No new checks arrive by themselves. The private runner is offline and its 13 scheduled workflows were disabled on 2026-09-23. Use `checked_at`, not `revision_date`. An upstream revision can be old and still current if automation confirmed it within the last 180 days.

## Validate a snapshot

Run the three validators before you package anything. All three must exit 0.

```bash
python3 tools/validate_public_carrier_data.py carriers generated/index.json
python3 tools/validate_device_catalog.py generated/devices
python3 tools/validate_community_claims.py community/claims generated/community --stable-dir carriers --evidence-index generated/evidence-index.json
```

Output on 2026-09-23:

```text
validated 6748 public carrier profile(s)
validated 42259 Android devices, 180 Apple products, and 9930 carrier artifacts
validated 0 community claim(s), 0 candidate, 0 expired and excluded
```

The first validator also checks every source snapshot date. The third one confirms that no community claim conflicts with a stable profile without saying so.
