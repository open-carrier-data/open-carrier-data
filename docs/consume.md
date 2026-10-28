# Use the data in a ROM, an app, or a build

This guide shows how to package the generated files, how to resolve profiles from code, how to check freshness, and how to validate a snapshot. Run every command from the repo root.

## Read this first

The files on `main` are the edge channel: each publish replaces them, several times a day. The production channel is the monthly release, `data-YYYY.MM`. The first, [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10), was published on 2026-10-19 from `main` commit `8cb64d63`. [releases.md](releases.md) describes the releases and their tiers:

| File | Tier in `data-2026.10` |
| --- | --- |
| `generated/android/apns-conf.xml` | supported for ROMs, since 2026-10-20. It carries the review of its emergency APN rows, and the boot check on the owner's phone passed with `data-2026.10`: mobile data, IMS registration, and outgoing calls over LTE and Wi-Fi on one 26202 SIM. MMS was not checked, because that network has ended it ([releases.md](releases.md#the-s20-boot-check-of-apns-confxml) says what the check covered) |
| `generated/android/lookup.json`, `generated/android/metadata.json` | supported, for apps and tools |
| `generated/devices/carrier-variants.json` | supported as information, for apps and tools; never an export |
| `generated/android/carrier-config-list.xml` | not for ROM application and not a release asset until the per-key review of its safety keys has run |
| the other files under `carriers/` and `generated/` | reference: for the resolver and for reviewers |
| `observed/` | never supported and never a release asset: unverified OCD Check reports and the owner's "re-tested by OCD" records, apart from the data |

To replace a ROM's whole carrier data with OCD's dataset, through OcdCarrierSettings, read [rom-builders.md](rom-builders.md): it lists the ship minimum SM1 to SM12 that the build must meet (rule round 31).

Take a release and check its files:

```sh
gh release download data-2026.10 -R open-carrier-data/open-carrier-data -D data-2026.10
cd data-2026.10 && sha256sum -c SHA256SUMS
```

`release.json` names the commit, the `data_digest`, the window and each file's tier. Record the tag and the `data_digest` with your build. If you take files from `main` instead, pin one commit by hand and record the SHA-256 of each file you take and its `data_digest`.

What every ROM maintainer must know:

1. **Configured, not verified.** Every value comes from a vendor or ROM carrier table. No profile has been verified on a phone: `verified_observation_count` is 0 everywhere. The phone reports under `observed/` do not change that: they are unverified, anyone can send one, and they never change a value. The owner's settled results on his own phones are measured records in `generated/devices/device-records.json` (rule round 30, item 4): each names the device, the ROM line and IMS stack, the carrier profile, the level (L2 calls out, incoming not tested; L3 calls both ways), the method, the data commit and the days measured, and lapses 90 days after the last one. They change no configured carrier value and are not a support claim for any other phone, stack or plan. A ROM that ships OcdCarrierSettings serves them only in their exact cell: the device, the carrier profile, the ROM family and build line, and the IMS stack (rule round 31, SM12 in [rom-builders.md](rom-builders.md)). A ROM builder still makes his own test call on each device before a build ships (SM3) ([community/README.md](../community/README.md), [docs/ocd-dataset.md](ocd-dataset.md)). `supported` means a table turns the feature on, not that the operator offers it, that the plan includes it or that the phone model is approved.
2. **Emergency calls are not tested, and OCD never places one.** `apns-conf.xml` carries an emergency APN row only where it asks for Android's own default request or where a current Pixel or Galaxy configuration or LineageOS's own list gives that row; elsewhere Android's own default applies ([Emergency APN rows](#emergency-apn-rows)). `carrier-config-list.xml` carries emergency, TTY, RTT, WPS and `iwlan.*` keys and is not for ROM application until the per-key review of those keys has run. Switching VoLTE or Wi-Fi calling on changes how the phone places emergency calls: where there is no 2G or 3G voice, or a regulator requires emergency calls over IMS (Sweden's PTS, Australia's ACMA), confirm that your IMS stack places them before you ship.
3. **The phone must load the file.** Keep `<apns version>` equal to your framework's `frameworks/base/core/res/res/xml/apns.xml`. On a mismatch TelephonyProvider loads no APN at all.
4. **The preferred APN survives an update.** New rows and a new order apply to a newly inserted SIM or after Reset to default.
5. **Pin one snapshot and check its window.** Do not ship after `stale_after`.
6. **`profile_id` is a hash of the match set** and changes when a source's selectors change. Key your own records by the SIM's facts (MCC and MNC, SPN, GID1, IMSI, carrier id) and the snapshot, and resolve them again against each new one.
7. **Most values rest on one source family.** `generated/evidence-index.json` names it.
8. **Data rights.** OCD waives its own rights in the data (CC0). Several sources state no terms, and whether Samsung's and Apple's terms allow extracting facts is open. This is not legal advice; [DATA-LICENSE.md](../DATA-LICENSE.md) has the details.

## Use the data in an Android ROM

This section covers taking OCD's files alone. To serve OCD's whole dataset as the ROM's carrier data, ship OcdCarrierSettings instead ([rom-builders.md](rom-builders.md)).

The Android files live in `generated/android/`. Each file has one job.

| File | Put it where |
| --- | --- |
| `apns-conf.xml` | the one APN file your build installs, see below |
| `carrier-config-list.xml` | not for ROM application until the per-key review of its safety keys has run; see below |
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

The first lines of `apns-conf.xml` say which snapshot it is: the licence, `data_digest`, `checks_through` and `stale_after`. A file from a release carries the same `data_digest` as that release's `release.json`. `git log -S <data_digest> -- generated/android/metadata.json` in a clone finds the commit that published it.

### carrier-config-list.xml is a vendor.xml

Not supported for ROM application until the per-key review of its emergency, TTY, RTT, WPS and `iwlan.*` keys has run (rule decisions of 2026-10-18, round 20), and no release will carry it before then. A maintainer who applies it anyway does so on their own review. This section says what such a merge involves.

`carrier-config-list.xml` has the format of the CarrierConfig app's `res/xml/vendor.xml`. That file is not one carrier's config: `DefaultCarrierConfigService` first reads the per-carrier asset AOSP ships for the SIM, then applies every matching block of `vendor.xml` on top with `putAll`, so each key here overrides AOSP's own value for that carrier on every device that installs it. A build has one `vendor.xml`, and devices often ship their own (the S20 tree's overlay has one), so merge the blocks into it instead of replacing it, and keep only keys you have reason to apply. Profiles whose match needs a GID or ICCID prefix are left out, because `vendor.xml` matches GID1 only exactly; `metadata.json` says so (`carrier_config_gid_matching` and `carrier_config_iccid_matching` are `omitted`) and lists them. No value in this file has been tested on a phone.

A key this file leaves out is not neutral. The phone keeps the value its own layers give: AOSP's per-carrier asset, the device's `vendor.xml`, a carrier app, or Android's default. OCD leaves a capability switch out when it withholds a single family's off, when sources conflict, or when no source gives it. Android's defaults for the switches that turn a feature on or off (`CarrierConfigManager`, Android 16):

| Key | Default | Without a value from anywhere, the phone |
|---|---|---|
| `carrier_volte_available_bool` | false | hides the VoLTE switch; calls use 2G/3G |
| `carrier_wfc_ims_available_bool` | false | hides Wi-Fi calling |
| `carrier_vt_available_bool` | false | offers no video calling |
| `vonr_enabled_bool` | false | uses no VoNR (OCD publishes no VoNR key) |
| `enabledMMS` | true | sends and receives MMS |
| `imssms.sms_over_ims_supported_bool` | true | sends SMS over IMS when registered |
| `support_ims_conference_call_bool` | true | offers "Merge" on IMS calls |

So for VoLTE, Wi-Fi calling and video calling, a key OCD leaves out usually means off on a phone whose own layers do not set it. For example, LIDL Connect resolves to carrier ID 2397, which has no AOSP asset. A false OCD publishes for `enabledMMS` makes Android refuse every MMS send and download at once.

For these three switches a single family's off therefore does not take out a true that another source sets: since 2026-10-10 OCD publishes the true, and the capability stays `conditional`, or, where every such off is an `off` record in `generated/devices/carrier-variants.json` and that file has an `on` record too, `supported` (round 17, step 2); `carrier-config-list.xml` is the same either way. The label is not a switch and not a device value: step 2 changed no byte of `carrier-config-list.xml` or `apns-conf.xml`, and a `supported` never overrides an `off` record for the reader's model. An app that compares the phone's live switch with OCD shows the model's record first and, for a `supported` value with `off` records, says that some models' own files turn it off. Never write a false from the device file. Such a switch is still left out only when the operator's own configuration or two independent families turn the feature off, or when the true rests on old single-source evidence that OCD withholds (see [how-it-is-built.md](how-it-is-built.md)). A device whose own tree turns one of them off has a reason OCD does not see, so put the device's own `vendor.xml` blocks after OCD's: the last matching block wins.

### Emergency calls are not tested

No value in this project has been tested for emergency calls, and the project never places one. `carrier-config-list.xml` carries emergency-related keys as carrier tables give them, among them `carrier_use_ims_first_for_emergency_bool`, `auto_retry_failed_wifi_emergency_call`, `allow_emergency_video_calls_bool`, `support_wps_over_ims_bool` and `iwlan.epdg_static_address_string`. Unless you have tested them on your device, keep your device's own values for every key whose name contains `emergency`, `e911` or `ecbm`, for `support_wps_over_ims_bool`, the TTY and RTT keys, and the `iwlan.*` keys. Switching VoLTE or Wi-Fi calling on also changes how the phone places emergency calls. Where a network has no 2G or 3G voice, or a regulator requires emergency calls over VoLTE (Sweden's PTS, from 2026-02-02), make sure your IMS stack places emergency calls over IMS before you ship such a switch.

#### Emergency APN rows

`apns-conf.xml` carries an emergency APN row, typed `emergency`, only where it asks for exactly Android's own emergency request (APN `sos`, `IPV4V6` at home and when roaming, nothing else that reaches the request), or where a current vendor (Google's per-carrier file, a current Samsung phone build) or LineageOS's own APN list gives that exact row, with its protocols, network types and APN name, such as Verizon's `VZWEMERGENCY` (rule decisions of 2026-10-18, round 21). So for every SIM the emergency APN Android uses with this file is Android's own default, the row LineageOS's own list has, or a row a current Pixel or Galaxy configuration gives for that SIM. The generator leaves out the `emergency` type of a row whose source leaves a protocol unset (TelephonyProvider would store it as `IP`, IPv4 only, which no source stated), of a row that serves another type too, of a row that asks for something else (a narrower protocol, a carrier's own APN name, network types, an auth type, an MTU or another request attribute) when no such source gives it, and of every row of a scope where an APN set Android may prefer would leave no emergency row usable. When a scope has no emergency row, Android's `DataProfileManager` adds its own default emergency profile, APN `sos` with protocol `IPV4V6` at home and when roaming and an APN set that matches every set; a row in the file takes that default's place for its scope. The profile JSON keeps every row; `metadata.json` counts what `apns-conf.xml` leaves out under `omissions.emergency_types_left_out_unset_protocol`, `_combined`, `_not_vendor_stated` and `_apn_set`. On 2026-10-18 that leaves 525 emergency rows in 473 scopes (869 before the rule; LineageOS's own list has 36), and leaves out 344: 103 for an unset protocol, 240 that no current vendor or LineageOS gives, and 1 for an APN set (KDDI 440/51). No LineageOS scope's emergency row changes. Two scopes still ask for IPv4 only, both as a current Samsung build gives them: MTN 655/10 (`IP` at home and when roaming) and Personal 744/05 (`IP` when roaming). One known gap: Google's current row for 452/02 serves LTE and NR only, so that scope has no emergency profile on Wi-Fi (IWLAN) or 2G and 3G, as on a Pixel; Android adds its default only when no network type has one. An APN named like an emergency APN (`sos`, a name containing `emergency`, or one starting with `e911`) that a source types otherwise ranks after the other real APNs of its type, so VOO's `SOS`, which Samsung types `default`, no longer leads 206/08's internet, and CNT's emergency APN, typed `ims`, no longer leads IMS on 302/37 and 740/02. None of these rows has been tested, and OCD never places an emergency call. Whether a phone uses them depends on its IMS stack: a stack that places every emergency call over 2G or 3G never opens the emergency connection. Count them with:

```bash
python3 <<'PY'
import xml.etree.ElementTree as ET
rows = [a for a in ET.parse("generated/android/apns-conf.xml").getroot() if a.tag == "apn" and "emergency" in (a.get("type") or "").split(",")]
scopes = {(a.get("mcc"), a.get("mnc"), a.get("mvno_type"), (a.get("mvno_match_data") or "").lower()) for a in rows}
ipv4_home = sum(1 for a in rows if a.get("protocol") in (None, "IP"))
ipv4_roaming = sum(1 for a in rows if a.get("roaming_protocol") in (None, "IP"))
print(len(rows), "rows in", len(scopes), "scopes;", ipv4_home, "IPv4 only at home,", ipv4_roaming, "when roaming")
PY
```

### Installing a newer apns-conf.xml does not change an APN a phone already uses

Android remembers the APN the SIM connected with (the preferred APN) by its content, and finds that row again after a newer `apns-conf.xml` replaces the database. New rows and a new order therefore take effect for a newly inserted SIM, or after Settings, Access Point Names, Reset to default. A user who added or edited an APN keeps it until that reset. If the preferred row stops working, Android retries it instead of moving to the next row, and the status bar shows signal bars without a "4G" label. Picking another row in the APN list, or Reset to default, recovers.

The checked-in `apns-conf.xml` carries `version="8"`. Android's TelephonyProvider expects the APN database version to match the build. To generate for a different version, write into a scratch directory so the checked-in files stay untouched. Pass the evidence index, because the generator orders APN rows by it:

```bash
mkdir -p /tmp/ocd-out
python3 tools/generate_android_outputs.py carriers /tmp/ocd-out --apn-version 9 --evidence-index generated/evidence-index.json
grep -m1 '<apns ' /tmp/ocd-out/android/apns-conf.xml
```

The generator prints one summary line with the profile, APN row and CarrierConfig block counts, and the root element shows the new version, `<apns version="9">`.

Read `metadata.json` before you ship. It lists the profiles whose match cannot be expressed in APN XML and the profiles left out of CarrierConfig XML. `omissions.apn_rows_rejected_by_lineageos_schema` counts the APN rows left out because LineageOS's schema rejects them, and `omissions.emergency_types_left_out_*` the emergency types left out ([Emergency APN rows](#emergency-apn-rows)). Print the two profile counts with:

```bash
python3 -c 'print({k: v for k, v in __import__("json").load(open("generated/android/metadata.json"))["omissions"].items() if k.endswith("_unrepresentable_match") and not k.endswith("ids_with_unrepresentable_match")})'
```

The CarrierConfig omissions are profiles whose match uses GID or ICCID prefixes, which `config_filter_records` in `tools/generate_android_outputs.py` skips. Split them into GID only, ICCID only and both with:

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

### Credentials from old lists

TelephonyProvider stores rows of one APN that differ only in username, password, auth type or MTU as one row, and `apns-conf.xml` writes the best-ranked row last so its values win ([how-it-is-built.md](how-it-is-built.md#how-the-android-apn-file-is-ordered), step 8). Where the best row, from a current vendor, sets no credentials and a lower row does, the phone sends the lower row's values. When those come only from a non-current source (frozen Pixel copies, LineageOS, MBPI, Sony, Fairphone or Apple), that is class (a). On public `a2f96412` it was 37 LTE lead roles in 20 scopes, 22 of them sent. OCD keeps these values, because removing a credential can cut mobile data on a network that checks it.

Built (rule round 32, D8):

- `tools/credential_fill_ins.py CHECKOUT` prints the class (a) list per scope and role: the APN, the filled-in fields, the sources of the filling rows, whether the lead sends them or only stores them, and the network types. The release notes carry it under "Credentials from old lists". On public `a8fd1898` it has 48 LTE lead roles in 25 scopes, 25 of them sent, in 17 scopes.
- `tools/resolve_carrier_profiles.py --explain` names, under `apns.credential_sources`, the row and the sources of every username, password, auth type and MTU a SIM's internet, attach and MMS lead carries, and whether a lower-ranked row filled it in.
- The phone guard reports "credentials filled in from a non-current source on the {role} lead", with the sources, wherever a change creates or changes such a fill-in. Report only.

Being built (rule round 32, D8):

- Where every source of the values is Google's frozen Pixel copies, Google's current file gives the same APN bare, and the operator's own page names no credentials, the filling row leaves `apns-conf.xml`. The phone then sends what a current Pixel sends.
- Each publish pull request lists class (a) as well, and the rows that left the file.

On a phone without OCD's tester nothing checks these credentials, so cover those SIMs in your own device check (SM3 in [rom-builders.md](rom-builders.md)).

### MMS where the operator ended it

Being built (rule round 32). Where the operator states on its own page or PDF that MMS ended network-wide, and a second reader has checked that statement, the profile's `mms` reads `unsupported`, `capability_sources` names `operator_statement` as the off, and the profile publishes `enabledMMS` false. On such a network a long or group text that the phone turns into an MMS is lost without notice, and an MMS send waits 30 minutes before it fails. With `enabledMMS` false the phone keeps such texts as SMS and fails an MMS at once. Profiles whose MMS rows use their own MMSC, such as Fastweb on 22801 and Join on 27001, are spared, and no APN row changes. A statement that is not confirmed for 180 days lapses, and the value goes back to what the tables give. `carrier-config-list.xml` stays reference-only, so a ROM gets this value through OcdCarrierSettings ([rom-builders.md](rom-builders.md)). No statement changes VoLTE, Wi-Fi calling or any other service.

### Old Samsung MVNO scopes leave the file

Being built (rule round 32, D7). A Samsung MVNO scope that only Samsung builds older than three years state leaves `apns-conf.xml` and `lookup.json` when Samsung's current packs for the same sales code state the plain rule instead, the plain scope has a current vendor's internet row, and the brand belongs to the plain scope's operator. Its profile JSON stays, flagged `old_selector_superseded`, and SIMs that matched it get the plain scope's current rows. Round 14 found one such scope, 530/99 SPN Spark NZ, whose rows already equal the plain scope's. Other operators' old scopes, such as Join's on 270/01, stay as profiles, because an MVNO may still need its own APN.

### Wi-Fi calling can fail because of the Wi-Fi's DNS, not the settings

Before Wi-Fi calling starts, the phone looks up the carrier's ePDG, the server its Wi-Fi calling tunnel connects to. The name has the form `epdg.epc.mncXXX.mccYYY.pub.3gppnetwork.org`, and the lookup goes through the DNS server of the Wi-Fi the phone is on. Some carriers answer that lookup only for clients they place in their own country. They judge this by the EDNS Client Subnet (ECS) in the query, or, when there is none, by the address of the DNS server that asks. A DNS server that sends no ECS gets an empty answer. The phone then finds no ePDG and gives up, and the carrier never refuses anything.

Measured on 2026-10-19 for Vodafone Germany (26202, which includes its MVNOs such as LIDL Connect):

| DNS server | Answer for `epdg.epc.mnc002.mcc262.pub.3gppnetwork.org` |
|---|---|
| Quad9 9.9.9.9, Cloudflare 1.1.1.1 | empty |
| Google 8.8.8.8 with ECS switched off | empty |
| Google 8.8.8.8, Quad9 with ECS (9.9.9.11) | an address |
| Vodafone's own name servers, asked from a German home line | an address |

The paper by Gegenhuber et al., [*Why E.T. Can't Phone Home* (MobiSys 2024)](https://arxiv.org/abs/2403.11759), describes the same DNS-based blocking for Vodafone Germany. It also reports that the ePDG itself accepts connections from abroad. On the same day, the name for 1&1 (26223) resolved through every DNS server tried.

What fixes it:

- **On the router:** use the internet provider's DNS servers. AVM's own Wi-Fi calling article recommends this for Vodafone.
- **On that one phone:** set Private DNS to `dns11.quad9.net` (Quad9 with ECS) or `dns.google`. A Private DNS host that sends no ECS does not help.
- **For only these names:** a DNS forwarder on the local network, such as dnsmasq, Pi-hole, AdGuard Home or Unbound, can send `pub.3gppnetwork.org` and `vodafone-ip.de` to such a server and everything else to the usual one. A FRITZ!Box cannot forward one domain to a different server by itself.

A public DNS server that sends ECS passes the first three parts of the client's IPv4 address to the carrier's name servers. Pinning today's ePDG addresses is fragile: Vodafone's were 139.7.117.161 and .162 until 2019, and are .168 to .170 in 2026.

## Check the file against LineageOS's schema

A LineageOS build checks its APN file against `apns-conf.xsd` in `vendor/apn`. The generator leaves out every row that schema rejects, and `metadata.json` counts them as `omissions.apn_rows_rejected_by_lineageos_schema`. To check the file before you build, run:

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

The resolver accepts `--mccmnc`, `--spn`, `--gid1`, `--gid2`, `--iccid`, `--imsi`, and `--android-carrier-id`. It returns profiles in generic-to-specific order. Apply each one on top of the previous one. Overlay APN rows and CarrierConfig keys. For capabilities, report the most specific profile's value; an `unknown` there means no usable source for this brand, and the host network's value is only the host's. A value is what carrier tables configure, not a test result. It is not a statement that the operator still offers the service. `supported` means at least one phone maker's or OS carrier table turns the feature on for this SIM, or for Samsung VoNR offers the user its switch (`capability_basis` names that weaker basis), and no source whose off counts turns it off. The switch counts only where the pack serves the carrier: on a KT phone only for KT's networks, and never from Samsung's open-market US pack (XAA). Samsung's and Apple's offs never count, including a Samsung carrier pack that switches a feature off on some phone models. It is a configuration, not a test result: the feature may still be off on a given phone, or on phones the carrier has not approved. `unsupported` means the operator's own configuration, or two independent source families, turn it off. One maker's off alone is `unknown`. To see which source families turn a capability on and which turn it off, read `capability_sources` in `generated/evidence-index.json`.

### What operators say, and which brands run where

Being built (rule round 32). `generated/operators/statements.json` records what operators themselves say they offer: MMS, VoLTE, Wi-Fi calling at home and abroad, VoLTE roaming, eSIM, and 5G SA with VoNR. It starts with Telekom, Vodafone, Telefónica and 1&1 in Germany, the brands congstar and fraenk, and LIDL Connect and Aldi Talk. Each entry names the operator's own page, the day it was read and a paraphrase, never quoted text. A statement says what the operator sells, not what a tariff includes or a phone supports. Show it as "the operator states it offers X (read on <date>); whether your tariff includes it is not checked", never as "works". Apart from the MMS case above, statements change no value. An entry that is not confirmed for 180 days, or not swept for 365, lapses to `unknown`.

The same folder carries the carrier-identity table: which operators, brands and MVNOs run on which network codes, with the SIM selectors a source states and `host_only` where none does. A host-only brand, such as LIDL Connect on 26202, cannot be told apart from its host's SIMs, so show it as a brand on that network, never as a statement about the SIM. Every selector in it passes the same prefix limits as every other published file.

### Device records for the four IMS switches

APN rows and MMS settings are per carrier. VoLTE, Wi-Fi calling, video calling and VoNR also have device records in `generated/devices/carrier-variants.json`: what one device's own carrier file sets for the SIM ([data-model.md](data-model.md#device-records)). A tool that knows the phone resolves a value in three steps:

1. SIM to profile, as above, through `lookup.json`.
2. Phone to device: on a Samsung phone `samsung:` and `Build.MODEL`; otherwise the `generated/devices/android.json` device whose `device_names` list `Build.DEVICE`, compared case-folded, which gives `android:<device_id>`. Pick the records whose `stack` matches the phone's software: `stock` on stock firmware, `lineageos` on a LineageOS build.
3. The device record if there is one, shown with its source, stack and month next to the profile value, labelled as this device's own file. Otherwise the profile value, labelled as the carrier's. A missing device is never `off`.

A record from another stack can still be shown, with its stack named: a stock record on a LineageOS build of the same model is "this model's stock firmware", not "this phone". Device records are information, not an export: never write a false VoLTE, Wi-Fi calling or video calling switch from them into a phone. Each record rests on one source, is configuration and not a test, and says nothing about emergency calls.

Do not write a true from a record of another software stack either. A `stock` record says what the vendor's own IMS stack is set to, not what a LineageOS build's IMS stack can do, emergency calls included. There is no export with `device=` blocks, and since rule round 31 none is built: a device's own fixes belong in the ROM's device tree ([rom-builders.md](rom-builders.md#device-quirks-stay-in-your-device-tree)). For every profile `carrier-config-list.xml` can express, it already sets the VoLTE, Wi-Fi calling and video calling switches true wherever a device's own file turns them on, unless a gate withholds the value. On 2026-10-18 that held for all but 2 of 169,717 such device values. A `vendor.xml` block can filter by `Build.DEVICE`, board and SKU, but not by model or sales code, so Samsung's records cannot be written as device blocks. An `off` is never exported.

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

TelephonyProvider stores rows that are equal on its unique fields (network code, APN, proxy, port, MMS proxy, MMS port, MMSC, protocols, MVNO selector, carrier id and a few flags; `CARRIERS_UNIQUE_FIELDS`) as one row, whatever their username, password, auth type, MTU, server, label or bitmasks. The stored row keeps the place of the first of them, unites their types, merges their bearer and network type bitmasks, and takes every attribute a later row writes; an attribute a later row leaves out keeps the earlier value. So `apns-conf.xml` writes such rows next to each other at the best-ranked row's place, with the best-ranked row last: a phone stores that row's values, and from the others only what it leaves unset. If you read the file without TelephonyProvider, overlay a group's rows in file order (each row's written attributes replace earlier ones, types unite, bitmasks merge) to get what a phone stores; the last row alone is the best-ranked row's own values, without the credentials or MTU a phone keeps from the others; `--explain` marks the rows written before their group's best row as `stored_with_best_row`.

Two exceptions to that merge, and one merge after it. On the networks of `persist_apns_for_plmn` (20404, 310004, 310120, 311480 in AOSP's TelephonyProvider), two such rows whose types differ only by `dun` are not merged (`separateRowsNeeded`): when the later row adds `dun`, it is stored as its own row with `profile_id` 1, and when the earlier row has `dun`, the earlier row loses `dun` and the later row is not stored. Either way the later row's values do not overwrite the earlier row's. On 204/04 IMSI `204047960` a phone therefore leads with the frozen `internet.mvno.mobi` row (`mvno`/`mvno`, PAP), and Google's row is stored apart; Samsung's current builds ship the same credentials there. Then DataProfileManager merges stored rows into data profiles when `ApnSetting.similar` holds (same APN, no shared type, no `dun`, proxy, MMSC, MMS proxy and credentials unset on one side or equal, the auth type and the other settings equal; an unset auth type counts as 0 without a username and 3 with one). The merged profile sits at the earlier row's place and holds both rows' values, and MMS uses the merged profile's MMSC. The loop compares every later row with the earlier row as it was read, so when several rows are similar to one row, the last one wins and the merges before it vanish. `apns-conf.xml` leaves out a stale MMS-only row that would merge this way when its MMS setting is no current vendor's and the vendors' MMS rows serve every mobile network type it serves (`omissions.mms_rows_left_out_absorbed_by_android`); `--explain` lists such rows under `left_out`. Other rows can still merge on a phone; read the file through TelephonyProvider and DataProfileManager, or with a model of them, to know what a phone uses.

Every row carries `mcc` and `mnc`. A row whose profile or source names an Android carrier id also carries `carrier_id`, the shape of AOSP's own `apns-full-conf.xml`.

Android picks a SIM's rows in its own way. In Android 16, which LineageOS 23.2 builds on, `getSubscriptionMatchingAPNListSynchronized` in TelephonyProvider does it in three steps:

1. If rows match the SIM's network code and MVNO selector, Android uses those rows and ignores the plain rows of that network.
2. Otherwise, it uses the plain rows of the SIM's network code.
3. Otherwise, it uses the rows that carry the SIM's carrier id under another network code.

Rows that carry the SIM's carrier id and no network code are added in every case. A `carrier_id` on a row that also has a network code does not restrict that row, and Android does not prefer such rows. Rows come back in file order. Without a preferred APN, the first row that can serve a request on the current radio technology is tried first. After a failure, the rows not tried yet come next, in file order. For the initial attach, Android takes the first row that serves `ia`, and the first row that serves `default` when none does, whatever order the internet rows have. So `apns-conf.xml` takes `ia` off a row whose APN no current vendor (Google CarrierSettings, Samsung from a phone's build at most three years old, for an APN type its sales code's newest pack does not give only under another network name) gives in its scope, when one gives the network's internet or attach APN, and keeps it on a row whose only type is `ia`. The profile JSON keeps the sources' type sets; `metadata.json` counts the changed rows as `omissions.ia_types_left_out_not_vendor_current`. For MMS, Android uses the internet connection when the internet APN serves `mms`, and otherwise the first row that serves `mms` on the current network type; the MMS service then looks up the MMSC, MMS proxy and MMS port by the APN that connection uses, among the SIM's rows that serve `mms` and carry an MMSC. Every row in `apns-conf.xml` that serves `mms` has an MMSC, or shares its APN with one that has. So `apns-conf.xml` sends MMS to a current vendor's MMS row: when a current vendor backs an MMS row with a real APN and an MMSC that serves a mobile (3GPP) network type, the first internet row loses `mms` if no current vendor backs it for MMS and the vendor MMS rows together serve every mobile network type it serves, and the best such vendor row moves ahead of the first row Android stores that still serves `mms`: a row serves `mms` on the phone when any row Android stores together with it (rows equal on TelephonyProvider's unique fields) does. A vendor MMS row counts only for the network types it serves, so a Wi-Fi-only row (`bearer_bitmask` 18) or a CDMA-only row never takes MMS away from the internet row. The profile JSON keeps the sources' types; `metadata.json` counts the retyped rows as `omissions.mms_types_left_out_not_vendor_backed`.

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

Run the three validators before you package anything. All three must exit 0. Pass `--freshness fail` so a snapshot past `stale_after` fails instead of warning.

```bash
python3 tools/validate_public_carrier_data.py carriers generated/index.json --freshness fail
python3 tools/validate_device_catalog.py generated/devices --freshness fail
python3 tools/validate_carrier_variants.py . --freshness fail
```

Each prints one `validated` line with its counts.

The first validator also checks every source snapshot date.
