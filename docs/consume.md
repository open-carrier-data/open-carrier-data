# Use the data in a ROM, an app, or a build

This guide shows how to package the generated files, how to resolve profiles from code, how to check freshness, and how to validate a snapshot. Run every command from the repo root.

## Use the data in an Android ROM

The Android files live in `generated/android/`. Each file has one job.

| File | Put it where |
| --- | --- |
| `apns-conf.xml` | the one APN file your build installs, see below |
| `carrier-config-list.xml` | only if you want it: a `vendor.xml` for the CarrierConfig app, merged with your device's own, see below |
| `lookup.json` | a tool that resolves profiles for a SIM, see below |
| `metadata.json` | your build log, so you know which profiles the XML left out and how fresh the snapshot is |

A ROM reads one APN file, so copy that one file. For a LineageOS tree, put it in a subdirectory of `vendor/apn`, where the `*.xml` glob that assembles LineageOS's own country files does not pick it up:

```bash
mkdir -p /path/to/lineage/vendor/apn/open-carrier-data
cp generated/android/apns-conf.xml /path/to/lineage/vendor/apn/open-carrier-data/apns-conf.xml
```

Then let `vendor/apn/Android.bp` choose which list to install. The owner's S20 tree does it with a Soong config variable, so LineageOS's list stays the default. This is its module, with the schema line simplified: the file now passes LineageOS's unchanged schema, where the tree still points at a copy that relaxes `mmsc`:

```text
prebuilt_etc_xml {
    name: "apns-conf.xml",
    product_specific: true,
    src: select(soong_config_variable("lineage_apn", "source"), {
        "open_carrier_data": "open-carrier-data/apns-conf.xml",
        default: ":apns-conf",
    }),
    schema: "apns-conf.xsd",
}
```

A device turns it on with `$(call soong_config_set,lineage_apn,source,open_carrier_data)` in its makefile. The module keeps its name and its install path, `/product/etc/apns-conf.xml`. A phone that already has the list in its database loads the new one only when the file's checksum changes and TelephonyProvider reloads, for example after `content delete --uri content://telephony/carriers/update_db` as root; a new build with the same build ID does not reload it by itself.

The first lines of `apns-conf.xml` say which snapshot it is: the licence, `data_digest`, `checks_through` and `stale_after`. `git log -S <data_digest> -- generated/android/metadata.json` in a clone finds the commit that published it.

### carrier-config-list.xml is a vendor.xml

`carrier-config-list.xml` has the format of the CarrierConfig app's `res/xml/vendor.xml`. That file is not one carrier's config: `DefaultCarrierConfigService` first reads the per-carrier asset AOSP ships for the SIM, then applies every matching block of `vendor.xml` on top with `putAll`, so each key here overrides AOSP's own value for that carrier on every device that installs it. A build has one `vendor.xml`, and devices often ship their own (the S20 tree's overlay has one), so merge the blocks into it instead of replacing it, and keep only keys you have reason to apply. Profiles whose match needs a GID or ICCID prefix are left out, because `vendor.xml` matches GID1 only exactly; `metadata.json` says so (`carrier_config_gid_matching` and `carrier_config_iccid_matching` are `omitted`) and lists them. No value in this file has been tested on a phone.

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

Read `metadata.json` before you ship. On 2026-10-04 it lists 18 profiles whose match cannot be expressed in APN XML and 1,380 profiles left out of CarrierConfig XML. `omissions.apn_rows_rejected_by_lineageos_schema` counts the APN rows left out because LineageOS's schema rejects them. Print the two profile counts with:

```bash
python3 -c 'print({k: v for k, v in __import__("json").load(open("generated/android/metadata.json"))["omissions"].items() if k.endswith("_unrepresentable_match") and not k.endswith("ids_with_unrepresentable_match")})'
```

The CarrierConfig omissions are profiles whose match uses GID or ICCID prefixes, which `config_filter_records` in `tools/generate_android_outputs.py` skips. On 2026-10-04, of the 1,380, 1,074 use GID only, 298 use ICCID only, and 8 use both. Recount them with:

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

The resolver accepts `--mccmnc`, `--spn`, `--gid1`, `--gid2`, `--iccid`, `--imsi`, and `--android-carrier-id`. It returns profiles in generic-to-specific order. Apply each one on top of the previous one. Overlay APN rows and CarrierConfig keys. For capabilities, report the most specific profile's value; an `unknown` there means no usable source for this brand, and the host network's value is only the host's. A value is what carrier tables configure, not a test result. `supported` means at least one phone maker's or OS carrier table turns the feature on for this SIM, or for Samsung VoNR offers the user its switch (`capability_basis` names that weaker basis), and no source whose off counts turns it off. Samsung's and Apple's offs never count, including a Samsung carrier pack that switches a feature off on some phone models. It is a configuration, not a test result: the feature may still be off on a given phone, or on phones the carrier has not approved. `unsupported` means the operator's own configuration, or two independent source families, turn it off. One maker's off alone is `unknown`. To see which source families turn a capability on and which turn it off, read `capability_sources` in `generated/evidence-index.json`.

### Ask why with --explain

`--explain` answers why a SIM gets what it gets. It prints, as JSON:

- `profiles`: the profile stack, generic to specific, with each profile's sources, `newest_entry` and freshness window.
- `capabilities`: per capability, the value each profile gives, the sources that turn it on or off (`capability_sources`), any gate that withheld it, and `answer`, the most specific profile's value, with `answer_from`.
- `android_carrier_config` and `addons`: per key, the value each profile gives with the sources behind it (`fact_sources`, or all the profile's sources when it lists none), and `applied`, the value left after overlaying generic to specific.
- `apns`: the rows Android 16 gives this SIM, in `apns-conf.xml` order: the rows of its MVNO selector when any match (`scope: mvno`), otherwise the plain rows of its network (`scope: network`). Each row has its `position`, its attributes, its `lead_type` and the ranking `reasons`: whether the APN is a real name, whether a current vendor gives its value (`value_from_current_vendor`) or backs the row (`row_from_current_vendor`), whether Google gives the value only from its shared file that no maintained per-carrier source confirms (`shared_file_unconfirmed`), whether it is an internet row without an HTTP proxy, which comes before the proxied internet rows (`proxy_free_first`), whether the file took `ia` off it (`ia_left_out`), the source families and primary sources behind its APN value and behind the row itself, and the row's sources. [how-it-is-built.md](how-it-is-built.md#how-the-android-apn-file-is-ordered) explains the order.

It reads `generated/android/lookup.json`, the profile files, and `generated/evidence-index.json` (`--evidence-index` names another one). Rows that carry a carrier id and no network code are not listed; no profile produces them on 2026-10-04.

```bash
python3 tools/resolve_carrier_profiles.py --mccmnc 26201 --spn Telekom.de --android-carrier-id 3 --explain
```

On 2026-10-04 a Telekom SIM with SPN `Telekom.de` and carrier id 3 resolves three profiles. The plain 26201 profile says VoLTE `supported`, from seven sources; the SPN profile says `supported` from Samsung OMC; the most specific profile, SPN plus carrier id, rests on AOSP alone and gives no VoLTE value, so `answer` is `unknown`:

```text
"volte": {
  "answer": "unknown",
  "answer_from": "open.26201.420d035152c1",
  "by_profile": [
    {"profile_id": "open.26201.13528695fee7", "value": "supported", "on": ["apple_carrier_bundles", "google_carriersettings", "google_pixel_vendor_carriersettings", "lineageos_device_overlays", "samsung_ims", "samsung_omc", "sony_open_devices_aosp"]},
    {"profile_id": "open.26201.1f7e1db680d5", "value": "supported", "on": ["samsung_omc"]},
    {"profile_id": "open.26201.420d035152c1", "value": "unknown"}
  ]
}
```

The same command without `--spn` and `--android-carrier-id` shows the plain 26201 rows: first `internet.telekom` (IPV4V6), whose APN value four source families give for `default` (the AOSP-derived lists, Apple, Google and GNOME), then `internet.v6.telekom`.

When sources disagree on one APN, `apns-conf.xml` carries every variant, and the variant most sources back comes first. Rows that Android treats as one APN, because they differ only in their label, their type set, or an attribute that repeats TelephonyProvider's default, are collapsed into one row with the union of their types. [how-it-is-built.md](how-it-is-built.md#how-the-android-apn-file-is-ordered) gives the ranking. To pick per type yourself, read `fact_sources` in `generated/evidence-index.json`; [data-model.md](data-model.md) gives the key of each APN fact.

TelephonyProvider stores rows that are equal on its unique fields (network code, APN, proxy, port, MMS proxy, MMS port, MMSC, protocols, MVNO selector, carrier id and a few flags; `CARRIERS_UNIQUE_FIELDS`) as one row, whatever their username, password, auth type, MTU, server, label or bitmasks. The stored row keeps the place of the first of them, unites their types, merges their bearer and network type bitmasks, and takes every attribute a later row writes; an attribute a later row leaves out keeps the earlier value. So `apns-conf.xml` writes such rows next to each other at the best-ranked row's place, with the best-ranked row last: a phone stores that row's values, and from the others only what it leaves unset. If you read the file without TelephonyProvider, take the last row of such a group, not the first; `--explain` marks the rows written before their group's best row as `stored_with_best_row`.

Every row carries `mcc` and `mnc`. A row whose profile or source names an Android carrier id also carries `carrier_id`, the shape of AOSP's own `apns-full-conf.xml`.

Android picks a SIM's rows in its own way. In Android 16, which LineageOS 23.2 builds on, `getSubscriptionMatchingAPNListSynchronized` in TelephonyProvider does it in three steps:

1. If rows match the SIM's network code and MVNO selector, Android uses those rows and ignores the plain rows of that network.
2. Otherwise, it uses the plain rows of the SIM's network code.
3. Otherwise, it uses the rows that carry the SIM's carrier id under another network code.

Rows that carry the SIM's carrier id and no network code are added in every case. A `carrier_id` on a row that also has a network code does not restrict that row, and Android does not prefer such rows. Rows come back in file order. Without a preferred APN, the first row that can serve a request on the current radio technology is tried first. After a failure, the rows not tried yet come next, in file order. For the initial attach, Android takes the first row that serves `ia`, and the first row that serves `default` when none does, whatever order the internet rows have. So `apns-conf.xml` takes `ia` off a row whose APN no current vendor (Google CarrierSettings, Samsung from a build at most three years old) gives in its scope, when one gives the network's internet or attach APN, and keeps it on a row whose only type is `ia`. The profile JSON keeps the sources' type sets; `metadata.json` counts the changed rows as `omissions.ia_types_left_out_not_vendor_current`. For MMS, Android uses the internet connection when the internet APN serves `mms`, and otherwise the first row that serves `mms` on the current network type; the MMS service then looks up the MMSC, MMS proxy and MMS port by the APN that connection uses, among the SIM's rows that serve `mms` and carry an MMSC. Every row in `apns-conf.xml` that serves `mms` has an MMSC, or shares its APN with one that has. So `apns-conf.xml` sends MMS to a current vendor's MMS row: when a current vendor backs an MMS row with a real APN and an MMSC that serves a mobile (3GPP) network type, the first internet row loses `mms` if no current vendor backs it for MMS and the vendor MMS rows together serve every mobile network type it serves, and the best such vendor row moves ahead of the first row that still serves `mms`. A vendor MMS row counts only for the network types it serves, so a Wi-Fi-only row (`bearer_bitmask` 18) or a CDMA-only row never takes MMS away from the internet row. The profile JSON keeps the sources' types; `metadata.json` counts the retyped rows as `omissions.mms_types_left_out_not_vendor_backed`.

`apns-conf.xml` groups rows by network code and MVNO selector and ranks each group by the evidence behind its rows, so Android first tries an internet APN a current vendor ships, then the one the most independent source families give, and never a row named `default` while a row with a real APN is there. Among the internet rows a row without an HTTP proxy comes before a WAP row with one, unless only the proxied value is a current vendor's, because Android makes an APN's proxy the data connection's HTTP proxy and keeps the first internet APN that connects; the proxied row stays as a fallback. On 2026-10-03, 1,224 network and MVNO scopes of LineageOS's list at `6e73ba90` have an internet row. In 993 of them our first internet row has the same APN as LineageOS's. In 201 of the other 231, more independent source families back our first APN than LineageOS's; in 29 the families tie; in one LineageOS's first row is the placeholder `default`.

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

`checks_through` is the oldest source check behind the data: the last day a lane fetched its source with success, or confirmed an observation. `stale_after` is `checks_through` plus 180 days. It is a lane-liveness deadline: after it, at least one lane behind the data has not run for six months. Do not ship a snapshot after `stale_after`. The per-profile `stale_after` in `generated/android/lookup.json` is the precise value for each profile; the file-wide one is the earliest of them.

A check date does not say a value is current. Only two lanes ask the vendor: Samsung's update service confirms that the firmware build an observation came from is current, and the GrapheneOS Pixel lane checks every Pixel against Google's update service. For every other lane a check means the lane ran. How old the data is shows in `newest_entry`, the month of the newest upstream entry behind a profile, in `generated/android/lookup.json` and `generated/evidence-index.json`. On 2026-10-04, 1,009 profiles rest only on entries from before October 2021, and 711 of them put 1,056 APN rows into `apns-conf.xml`. APN rows LineageOS removed are left out unless a newer source gives them, and a capability with only old evidence from one family is `unknown`; [how-it-is-built.md](how-it-is-built.md) has both rules.

The validators apply the same window. `check_freshness` in `tools/validate_public_carrier_data.py` and in `tools/validate_device_catalog.py` compares the UTC date with `stale_after`. By default both print one warning line to stderr and exit 0, so a clone keeps validating after the deadline. With `--freshness fail` they exit 1 instead. The daily public job passes that flag, and `--liveness fail`, which fails when one lane's source was not checked within its limit (10 days for the daily Samsung lanes, 21 for the weekly ones) or the last publish is more than 21 days old, and opens an issue labeled `stale-data` when either fails. Pushes and pull requests run in warn mode and keep passing. `checks_through` follows the oldest observation, a Samsung one from a superseded firmware build; an observation is quarantined on the day it is 180 days old, so observations still from 2026-07-14 are quarantined on 2027-01-10 and the window then moves on. A weekly GitHub-hosted job re-checks the other ten families. Samsung runs daily on the self-hosted runner.

## Validate a snapshot

Run both validators before you package anything. Both must exit 0. Pass `--freshness fail` so a snapshot past `stale_after` fails instead of warning.

```bash
python3 tools/validate_public_carrier_data.py carriers generated/index.json --freshness fail
python3 tools/validate_device_catalog.py generated/devices --freshness fail
```

Output on 2026-10-04:

```text
validated 7806 public carrier profile(s)
validated 42473 Android devices, 183 Apple products, and 4642 carrier artifacts
```

The first validator also checks every source snapshot date.
