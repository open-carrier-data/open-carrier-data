# Use the data in a ROM, an app, or a build

This guide shows how to package the generated files, how to resolve profiles from code, how to check freshness, and how to validate a snapshot. Run every command from the repo root.

## Use the data in an Android ROM

The Android files live in `generated/android/`. Each file has one job.

| File | Put it where |
| --- | --- |
| `apns-conf.xml` | the APN database path your TelephonyProvider reads |
| `carrier-config-list.xml` | your CarrierConfig overlay input |
| `lookup.json` | a tool that resolves profiles for a SIM, see below |
| `metadata.json` | your build log, so you know which profiles the XML left out |

To copy the Android files into a build tree, run:

```bash
cp -r generated/android/ /path/to/your/build/carrier-data/
```

The checked-in `apns-conf.xml` carries `version="8"`. Android's TelephonyProvider expects the APN database version to match the build. To generate for a different version, write into a scratch directory so the checked-in files stay untouched. Pass the evidence index, because the generator orders APN rows by it:

```bash
mkdir -p /tmp/ocd-out
python3 tools/generate_android_outputs.py carriers /tmp/ocd-out --apn-version 9 --evidence-index generated/evidence-index.json
grep -m1 '<apns ' /tmp/ocd-out/android/apns-conf.xml
```

The generator prints one summary line, and the root element shows the new version. On 2026-10-04 the output is:

```text
generated Android output for 7816 profile(s): 25406 APN row(s), 6351 CarrierConfig profile(s), 5261 CarrierConfig XML block(s), 0 APN row(s) left out because LineageOS's schema rejects them
<apns version="9">
```

Read `metadata.json` before you ship. On 2026-10-03 it lists 18 profiles whose match cannot be expressed in APN XML and 1,386 profiles left out of CarrierConfig XML. `omissions.apn_rows_rejected_by_lineageos_schema` counts the APN rows left out because LineageOS's schema rejects them. Print the two profile counts with:

```bash
python3 -c 'print({k: v for k, v in __import__("json").load(open("generated/android/metadata.json"))["omissions"].items() if k.endswith("_unrepresentable_match") and not k.endswith("ids_with_unrepresentable_match")})'
```

The CarrierConfig omissions are profiles whose match uses GID or ICCID prefixes, which `config_filter_records` in `tools/generate_android_outputs.py` skips. On 2026-10-03, of the 1,386, 1,080 use GID only, 298 use ICCID only, and 8 use both. Recount them with:

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

## Check the file against LineageOS's schema

A LineageOS build checks its APN file against `apns-conf.xsd` in `vendor/apn`. The generator leaves out every row that schema rejects, and `metadata.json` counts them as `omissions.apn_rows_rejected_by_lineageos_schema`. On 2026-10-04 that is 0 rows. To check the file before you build, run:

```bash
xmllint --noout --schema /path/to/lineage/vendor/apn/apns-conf.xsd generated/android/apns-conf.xml
```

The public check runs the same command with `tools/lineageos/apns-conf.xsd`, a byte copy of `apns-conf.xsd` at LineageOS revision `6e73ba90`.

Until 2026-10-04 the repo also published the rows as one file per country under `generated/android/apns/`. Nothing used them, LineageOS's `format.py` re-sorts such files and so drops the row order of `apns-conf.xml`, and 250 rows had no country file, so they were removed. Use `apns-conf.xml`.

## Compare with the APN list you ship today

`tools/diff_apns_conf.py` takes your `apns-conf.xml`, or a directory of per-country files such as LineageOS's `vendor/apn`, and compares it with `generated/android/apns-conf.xml`. Rows match on network code, MVNO selector, APN, and type set, ignoring case and type order.

```bash
python3 tools/diff_apns_conf.py /path/to/android_vendor_apn --json diff.json
```

The summary counts rows in both, rows only in ours, and rows only in yours split by cause: same APN with other types, an APN we lack, or a network we lack. `--mccmnc 26202` limits the comparison to one network. To compare one of LineageOS's country files with ours, pass it with the networks it covers, for example `python3 tools/diff_apns_conf.py /path/to/android_vendor_apn/DE.xml --mccmnc 26201 --mccmnc 26202`. The JSON report lists every row with its label. Against the LineageOS repository at revision `6e73ba90` on 2026-10-03, 358 of its 3,967 rows have no exact match in ours. 335 of them have the same network, MVNO selector, and APN in ours with another type set, often without `mms` where no row of that APN has an MMSC. 23 have an APN we lack: 17 rows with an empty APN (15 initial-attach rows and 2 Lycamobile UK MMS rows, see [Rows with an empty APN](#rows-with-an-empty-apn)), 5 MMS rows without an MMSC, which no phone can send MMS with, and one row that carries an MVNO match value without an MVNO type. Every LineageOS network is in ours.

## Use the data in an app or tool

Read the profiles directly when you need the full shape. `generated/index.json` lists every profile with its path. `generated/android/lookup.json` adds `match`, `capabilities`, and `specificity` per profile, so most tools never open the individual files.

To resolve every profile for one SIM, run the resolver with what you know:

```bash
python3 tools/resolve_carrier_profiles.py --mccmnc 26202 --spn Vodafone.de
```

On 2026-10-03 the first lines of the output are:

```text
{
  "profiles": [
    {
      "android_apn_count": 15,
      "capabilities": {
```

The resolver accepts `--mccmnc`, `--spn`, `--gid1`, `--gid2`, `--iccid`, `--imsi`, and `--android-carrier-id`. It returns profiles in generic-to-specific order. Apply each one on top of the previous one. Overlay APN rows and CarrierConfig keys. For capabilities, report the most specific profile's value; an `unknown` there means no usable source for this brand, and the host network's value is only the host's. A value is what carrier tables configure, not a test result. `supported` means at least one phone maker's or OS carrier table turns the feature on for this SIM and none turns it off, and the feature may still be off on a given phone or on phones the carrier has not approved. `unsupported` means the operator's own configuration, or two independent source families, turn it off. One maker's off alone is `unknown`. To see which source families turn a capability on and which turn it off, read `capability_sources` in `generated/evidence-index.json`.

When sources disagree on one APN, `apns-conf.xml` carries every variant, and the variant most sources back comes first. Rows that Android treats as one APN, because they differ only in their label, their type set, or an attribute that repeats TelephonyProvider's default, are collapsed into one row with the union of their types. [how-it-is-built.md](how-it-is-built.md#how-the-android-apn-file-is-ordered) gives the ranking. To pick per type yourself, read `fact_sources` in `generated/evidence-index.json`; [data-model.md](data-model.md) gives the key of each APN fact.

Every row carries `mcc` and `mnc`. A row whose profile or source names an Android carrier id also carries `carrier_id`, the shape of AOSP's own `apns-full-conf.xml`.

Android picks a SIM's rows in its own way. In Android 16, which LineageOS 23.2 builds on, `getSubscriptionMatchingAPNListSynchronized` in TelephonyProvider does it in three steps:

1. If rows match the SIM's network code and MVNO selector, Android uses those rows and ignores the plain rows of that network.
2. Otherwise, it uses the plain rows of the SIM's network code.
3. Otherwise, it uses the rows that carry the SIM's carrier id under another network code.

Rows that carry the SIM's carrier id and no network code are added in every case. A `carrier_id` on a row that also has a network code does not restrict that row, and Android does not prefer such rows. Rows come back in file order. Without a preferred APN, the first row that can serve a request on the current radio technology is tried first. After a failure, the rows not tried yet come next, in file order. For the initial attach, Android takes the first row that serves `ia`, and the first row that serves `default` when none does. For MMS, the MMS service looks up the MMSC by the APN the MMS data connection uses, among the SIM's rows that serve `mms` and carry an MMSC. Every row in `apns-conf.xml` that serves `mms` has an MMSC, or shares its APN with one that has.

`apns-conf.xml` groups rows by network code and MVNO selector and ranks each group by the evidence behind its rows, so Android first tries the internet APN that the most independent source families give, and never a row named `default` while a row with a real APN is there. On 2026-10-03, 1,224 network and MVNO scopes of LineageOS's list at `6e73ba90` have an internet row. In 993 of them our first internet row has the same APN as LineageOS's. In 201 of the other 231, more independent source families back our first APN than LineageOS's; in 29 the families tie; in one LineageOS's first row is the placeholder `default`.

### Rows with an empty APN

An `ia` row with an empty APN tells the modem to attach without naming an APN, so the network picks the subscription's default. LineageOS's list has 15 such rows at `6e73ba90`, and two MMS rows with an empty APN and no MMSC. This project publishes neither kind. The profile schema requires an APN, and every importer drops a row whose APN is empty, because no source states why the value is empty, and an empty MMS APN cannot work. Without such a row, Android attaches with the first row of the SIM's scope that serves `ia`, or else the first that serves `default`, which names the network's own internet APN. The attach then also takes that row's protocol, which can be IPv4 only where LineageOS's empty attach row asks for `IPV4V6`.

The resolver works on profiles, not on rows. To reuse its rules in your own code, read the `specificity` function and the match loop in `tools/resolve_carrier_profiles.py`.

## Check freshness before you ship

Three facts tell you whether a snapshot is safe to ship.

To read the APN target version and the omission counts, run:

```bash
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["target"])'
```

Output on 2026-10-04:

```text
{'apn_database_version': 8, 'carrier_config_gid_matching': 'omitted', 'carrier_config_iccid_matching': 'omitted'}
```

To read the freshness window, run:

```bash
python3 -c 'print(*[__import__("json").load(open("generated/android/metadata.json"))[k] for k in ("checks_through", "stale_after")])'
```

It prints two dates, `checks_through` and then `stale_after`.

`checks_through` is the oldest source check behind the data. `stale_after` is `checks_through` plus 180 days. Do not ship a snapshot after `stale_after`. The per-profile `stale_after` in `generated/android/lookup.json` is the precise value for each profile; the file-wide one is the earliest of them. Use `checks_through`, not `revision_date`. An upstream revision can be old and still current if automation confirmed it inside the window.

The validators apply the same window. `check_freshness` in `tools/validate_public_carrier_data.py` and in `tools/validate_device_catalog.py` compares the UTC date with `stale_after`. By default both print one warning line to stderr and exit 0, so a clone keeps validating after the deadline. With `--freshness fail` they exit 1 instead. The daily public job passes that flag and opens an issue labeled `stale-data` when it fails. Pushes and pull requests run in warn mode and keep passing. `checks_through` also follows the oldest observation, a Samsung one from a superseded firmware build, so the first stale-data issue opens the day after `stale_after` unless the daily Samsung run re-extracts those observations first. A weekly GitHub-hosted job re-checks the other ten families. Samsung runs daily on the self-hosted runner.

## Validate a snapshot

Run both validators before you package anything. Both must exit 0. Pass `--freshness fail` so a snapshot past `stale_after` fails instead of warning.

```bash
python3 tools/validate_public_carrier_data.py carriers generated/index.json --freshness fail
python3 tools/validate_device_catalog.py generated/devices --freshness fail
```

Output on 2026-10-03:

```text
validated 7833 public carrier profile(s)
validated 42473 Android devices, 183 Apple products, and 4642 carrier artifacts
```

The first validator also checks every source snapshot date.
