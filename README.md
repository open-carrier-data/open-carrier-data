# Open Carrier Data

> **Early development.** Open Carrier Data is in early development. Data, formats, tools and apps change often, and values can be wrong or missing. Don't rely on it for anything important yet. Feedback and reports are welcome.

Open Carrier Data is a public database of mobile carrier settings. It stores neutral JSON carrier profiles in `carriers/open/` and turns them into Android APN and CarrierConfig files under `generated/`. It exists for ROM builders, carrier configuration apps, eSIM tools, and build systems. They can ship APN, MMS, IMS, RCS, and eSIM data locally instead of maintaining the same fixes alone. Phones read the packaged files at runtime. Nothing in this project is a network service.

## Get the data

You can get the data in three ways. Each one takes the latest publish on `main`, the edge channel: it changes several times a day, and the validators and the phone guard are its only checks. For a fixed, checked snapshot, take a release instead. The first is [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10); [Releases and support](#releases-and-support) below says what it supports.

To take everything, including tools and schemas, clone the public repo:

```bash
git clone https://github.com/open-carrier-data/open-carrier-data.git
```

To read the latest publish on `main` (edge) without a checkout, download the raw index:

```bash
curl -sL https://raw.githubusercontent.com/open-carrier-data/open-carrier-data/main/generated/index.json | head -c 200
```

To ship the APN list in a build, copy the one file Android reads:

```bash
cp generated/android/apns-conf.xml /path/to/your/build/vendor/apn/open-carrier-data/apns-conf.xml
```

[docs/consume.md](docs/consume.md) shows the `Android.bp` switch that installs it and what `carrier-config-list.xml` overrides. Take the file from a release, or pin one commit, and record the file's SHA-256 and the `data_digest` in its header. In `data-2026.10` this file is not supported yet: it waits for the boot check on the owner's phone.

Read [docs/consume.md](docs/consume.md) before you ship the XML. The checked-in APN XML targets database version 8. `carrier-config-list.xml` is not for ROM application until the per-key review of its emergency, TTY, RTT, WPS and `iwlan.*` keys has run.

## Releases and support

`main` is the edge channel: every publish lands there, several times a day. It is guarded by the `validate` check and the phone guard, and OCD makes no other promise about it. The production channel is monthly tagged releases, `data-YYYY.MM`, drafted by tooling and published by the owner or, on his direction, by an agent after an independent read. The first, [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10), was published on 2026-10-19; the next, `data-2026.11`, is planned for about 2026-11-02. [docs/releases.md](docs/releases.md) describes the releases: the tiers, what a release guarantees and what it never does.

The tiers in `data-2026.10`, in short:

| File | Tier |
| --- | --- |
| `generated/android/apns-conf.xml` | supported for ROMs, since 2026-10-20. It carries the review of its emergency APN rows, and the boot check on the owner's phone passed with `data-2026.10`: mobile data, IMS registration, and outgoing calls over LTE and Wi-Fi on one 26202 SIM. MMS was not checked, because that network has ended it. [docs/releases.md](docs/releases.md#the-s20-boot-check-of-apns-confxml) says what the check covered |
| `generated/android/lookup.json`, `generated/android/metadata.json`, `generated/devices/carrier-variants.json` | supported for apps and tools; the device records as information, never an export |
| `generated/android/carrier-config-list.xml` | not for ROM application and not a release asset until the per-key review of its safety keys has run |
| everything else under `carriers/` and `generated/` | reference: for the resolver and for reviewers |
| `generated/ocd-dataset/`, `generated/devices/device-records.json` | the OCD dataset, which OcdCarrierSettings serves as a ROM's carrier data on every ROM whose builder chooses it, baked at a validated `main` commit or a release's commit and kept current by the ROM's own build of the OCD Check app; not a release asset (rule rounds 30 and 31, [docs/rom-builders.md](docs/rom-builders.md), [docs/ocd-dataset.md](docs/ocd-dataset.md)). The records are the owner's measured results, served only in their exact cell, with a 90-day expiry, and, until round 31's S20 build has passed, the S20's device fixes |
| `observed/` | never supported and never a release asset: unverified phone reports from the OCD Check app ([community/README.md](community/README.md)) |

## Resolve one SIM

To find every profile that applies to one SIM, run the resolver with the SIM's facts:

```bash
python3 tools/resolve_carrier_profiles.py --mccmnc 26202 --spn Vodafone.de
```

On 2026-10-03 the output starts like this:

```text
{
  "profiles": [
    {
      "android_apn_count": 15,
      "capabilities": {
        "esim": "unknown",
        "ims_conference": "unknown",
        "mms": "conditional",
```

Profiles come back in generic-to-specific order. Apply each one as an overlay on the previous one. Capabilities are not inherited; see [docs/consume.md](docs/consume.md). With `--mccmnc` alone only the broad profile returns. SPN, GID, IMSI, and ICCID profiles need their own flags.

## What is in this repository

| Path | Contents |
| --- | --- |
| `carriers/open/` | the carrier profiles, one JSON file per profile, listed in `generated/index.json` |
| `aliases/ids.json` | the retired profile IDs, each with the profile or profiles its SIMs match now: an ID is assigned once and kept, and a retired one is never reused (rule round 45, [docs/compatibility.md](docs/compatibility.md)) |
| `generated/index.json` | one entry per profile in the latest publish |
| `generated/evidence-index.json` | source revisions, check dates, fact sources, exact source versions, conflicts, newest entry dates |
| `generated/android/` | APN XML, CarrierConfig XML, `lookup.json`, `metadata.json` |
| `generated/devices/` | the device catalog, carrier artifact registries, and the device records (`carrier-variants.json`) |
| `generated/ocd-dataset/` | the OCD dataset that OcdCarrierSettings serves as a ROM's carrier data (rule rounds 30 and 31, [docs/rom-builders.md](docs/rom-builders.md)): the manifest, the profiles per network with OCD's match rules and the Google-lane fill, the Google lane's values as source family `google`, and the APN row index ([docs/ocd-dataset.md](docs/ocd-dataset.md)) |
| `devices/records/` | the sources of `generated/devices/device-records.json`: the owner's devices' configured records, the owner's measured records (written by the report bot) and the second-agent reads group A records need |
| `observed/` | test reports from the OCD Check app, one file per report issue; people's reports counted as unverified hints (`observed/summary.json`): pointers to entries with the measured result, never a value; they never change an OCD value |
| `community/` | how community reports reach `observed/` and why they stay apart from the data |
| `schemas/` | JSON schemas for the data files and for OCD Check reports |
| `tools/` | validators, the Android generator, the resolver, a diff against your own `apns-conf.xml`, tests |
| `docs/` | data model, build explanation, consumer guide, the guide for ROM builders who ship OCD's dataset, release plan |

## Status

The data republishes whenever a source changes, so this page gives no counts. These commands print the current ones, run from the repo root:

```bash
ls carriers/open | wc -l    # carrier profiles
python3 -c 'print(len({s for p in __import__("json").load(open("generated/evidence-index.json"))["profiles"] for s in p["sources"]}))'    # source names in profile evidence
python3 -c 'print(len(__import__("json").load(open("generated/evidence-index.json"))["source_snapshots"]))'    # source snapshot records
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["checks_through"])'
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["stale_after"])'
python3 -c 'print(len(__import__("json").load(open("generated/devices/android.json"))["devices"]))'    # Android devices in the device catalog
python3 -c 'print(len(__import__("json").load(open("generated/devices/apple.json"))["devices"]))'    # Apple products in the device catalog
python3 -c 'print(__import__("json").load(open("generated/devices/index.json"))["platforms"]["android"]["carrier_data_coverage_counts"]["exact_carrier_data_observed"])'    # Android identities with observed carrier data
python3 -c 'print(sum(p["verified_observation_count"] for p in __import__("json").load(open("generated/evidence-index.json"))["profiles"]))'    # observations verified on a device
```

Source names and snapshot records do not map one to one: `aosp` maps to the snapshots `aosp_carrier_config` and `aosp_carrier_ids`, `lineageos_device_overlays` maps to `lineageos_device_carrier_overlays`, and on 2026-10-18 `samsung_carrier_config` has no snapshot record of its own. The `samsung_omc` and `samsung_ims` records carry a content hash as their revision and `NOASSERTION` as their terms.

## Limits to read before you ship

Read these before you depend on the data:

- In plain words, the four capability values mean:
  - `supported`: at least one phone maker's or OS settings for this SIM turn the feature on, and no source whose off counts turns it off. For VoLTE, Wi-Fi calling and video calling, one maker's or maintainer's own files may still turn it off on some phone models: `generated/devices/carrier-variants.json` lists those models as `off` and at least one model as `on`, so if you know the phone model, read its record first. It does not tell you that the carrier still offers it, that your plan includes it, or that your phone model is allowed.
  - `conditional`: the sources disagree, often between phone models. Often one phone model's own table turns it off while others turn it on; `generated/devices/carrier-variants.json` shows which. For VoLTE, Wi-Fi calling and video calling, the device file does not settle the disagreement: an off is older than five years or not tied to one model, the off comes from the operator or two families, or no model's own file says on.
  - `unsupported`: the carrier's own settings, or two independent sources, turn it off. Since rule round 32, for MMS, `unsupported` with the source `operator_statement` means the operator states on its own pages that MMS ended, and the profile's `enabledMMS` false comes from that statement.
  - `unknown`: no reliable source. It does not mean "no".
- A carrier can still block a feature that its settings turn on. The usual gates are a list of approved phone models (common in the US, Australia and Sweden), an option you must book in your plan (LIDL Connect's Wi-Fi calling, for example), a carrier server that must approve the phone first (in the US, often with a registered emergency address for Wi-Fi calling), a service the operator has ended (MMS in Germany), roaming limits, and the Wi-Fi network you use (its DNS or firewall can keep Wi-Fi calling from reaching the carrier). None of these shows in carrier settings, so no source tells OCD about them; only a test with your SIM, plan and phone does. Some keys hint at a gate: `carrier_volte_provisioning_required_bool` and the `REG09` Wi-Fi calling error mapping.
- A switch that `carrier-config-list.xml` leaves out is not neutral: your phone keeps what its ROM already says, which for VoLTE, Wi-Fi calling and video calling is usually off, and for MMS, SMS over IMS and conference calls usually on. [docs/consume.md](docs/consume.md) lists the defaults.
- A phone that has already picked an APN keeps it after you install a newer `apns-conf.xml`. Android finds its chosen row again by its content. New rows and a new order take effect for a newly inserted SIM, or after Settings, Access Point Names, Reset to default.
- No profile has been verified on a phone. Every value comes from a maintained source, not from a test call. No value has been tested for emergency calls; [docs/consume.md](docs/consume.md#emergency-calls-are-not-tested) says which keys a ROM should keep.
- `apns-conf.xml` carries an emergency APN row (`type="emergency"`) only where it asks for exactly Android's own default emergency request (`sos`, `IPV4V6`) or where a current Pixel or Galaxy configuration or LineageOS's own list gives that row: 525 rows in 473 scopes on 2026-10-18, where LineageOS's own list has 36 (rule decisions of 2026-10-18, round 21). Elsewhere Android uses its own default emergency profile. None has been tested. `metadata.json` counts the rows left out, and [docs/consume.md](docs/consume.md#emergency-apn-rows) gives the rule and the command that counts them.
- A capability value says what carrier tables configure, not what works. It does not say the operator still offers the service: tables often keep a service for months or years after an operator ends it. `supported` means at least one phone maker's or OS carrier table turns the feature on for this SIM and no off that counts turns it off (for VoLTE, Wi-Fi calling and video calling, one maker's or maintainer's per-device offs do not count where `generated/devices/carrier-variants.json` lists every one of them and some device record there says on); it may still be off on your phone, or on phones the carrier has not approved. `unsupported` needs the operator's own configuration, or two independent source families, turning it off. One maker's off alone is published as `unknown`, and its false CarrierConfig switch is left out. For VoLTE, Wi-Fi calling and video calling, whose switch is off when it is missing, that off also does not take out a true switch another source sets: the switch is left out only for the operator's own off, an off from two families, or a true too old to publish. Where every such off is an `off` record in `generated/devices/carrier-variants.json` and that file also has an `on` record, the label of those three is `supported`, not `conditional`; the device file names the phone models whose own table says off. [docs/data-model.md](docs/data-model.md#capability-names-and-values) defines the four values, and `capability_sources` in `generated/evidence-index.json` names the families that turn each capability on and off.
- An MVNO without its own SPN, GID, or IMSI prefix in any source merges into the host network's profile. LIDL Connect runs on Vodafone Germany, and no profile names it, so its SIM resolves the `26202` profiles.
- CarrierConfig and add-on conflicts are omitted; conflicting APN rows are all published as variants. Every conflict is listed in `generated/evidence-index.json`.
- A capability whose only source family has no entry newer than five years is published as `unknown`: video calling for its age alone; VoLTE, VoWiFi, MMS and Wi-Fi calling while roaming only when that source is a frozen copy (Sony's or Fairphone's tree) or no fresh observation covers the profile's own scope. The CarrierConfig key that switches a withheld capability on is left out with it. Other APN rows and CarrierConfig values stay, however old, except APN rows LineageOS removed, which are left out unless a newer source gives them. `generated/evidence-index.json` gives the month of the newest entry behind each profile and each published capability where it is known. [docs/how-it-is-built.md](docs/how-it-is-built.md) explains entry age.
- Every snapshot carries a freshness window. `generated/android/metadata.json` publishes `checks_through`, the oldest source check behind the data, and `stale_after`, the last date the data should ship. A check date means the lane behind the data ran, not that a value is current: only Samsung's update service and Google's Pixel update check confirm vendor data as current. How old the data is shows in `newest_entry` per profile in `generated/android/lookup.json`. The commands under the status table print both. The oldest Samsung observations set `checks_through`. Samsung's lane runs daily on the owner's self-hosted runner. It re-confirms observations whose firmware build is still current and re-extracts up to 50 CSC packages per run. Observations from superseded builds keep their July 2026 dates until they are re-extracted; whatever is still from July is quarantined on the day it turns 180 days old, the first on 2027-01-10. A weekly job re-checks the other source families, on the owner's self-hosted runner since 2026-10-28, when the organisation's free hosted minutes for October were spent. Their check dates are in `generated/evidence-index.json` under `source_snapshots`. The validators compare the UTC date with `stale_after`. By default they warn and exit 0, so a clone keeps validating after the deadline. The push and pull request check runs the validators in warn mode, so a stale snapshot never blocks a fix. The daily job runs them with `--freshness fail` and opens an issue labeled `stale-data` when they fail, and also when one lane's source was not checked within its limit (10 days for the daily Samsung lanes, 21 for the weekly ones) or the last publish is more than 21 days old.
- For VoLTE, Wi-Fi calling, video calling and VoNR, a profile's value is a summary over every source and every phone model's table, made by the family rule above. It is not a vote or a count over phone models. `generated/devices/carrier-variants.json` holds the device records: what one phone model's own carrier file sets for the SIM, every device value OCD publishes, including those that agree with the profile value. A device record is configuration from one vendor or ROM file, not confirmed by a second source and not a test result. It holds for one software stack (stock firmware, a LineageOS tree, or Sony's AOSP tree), says nothing about the operator's offer or emergency calls, and is not an export: never write an `off` from it into a phone's settings. A phone model without a record for a profile and switch has no file OCD reads that sets a value there, or its value is older than five years, or its codename or model does not bind to one catalog device. It never means `off`, and it never means the device agrees with the profile value. [docs/data-model.md](docs/data-model.md#device-records) describes the file.
- A device listed in `generated/devices/` is an inventory fact. It is not a support claim. A device is covered only when carrier evidence names that exact identity. `generated/devices/README.md` defines the rule and the one command that prints the number.

## How it is built

The pipeline runs in the private repo and publishes here:

```text
source families -> candidate observations -> the sanitizer -> carrier profiles -> generated files
```

[docs/how-it-is-built.md](docs/how-it-is-built.md) explains the merge rules, why profiles are neutral, and the freshness policy.

## How to contribute

[CONTRIBUTING.md](CONTRIBUTING.md) explains the four issue forms under [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/) and the pull request path for tools and docs. A correction reaches stable data through a maintained source, or a maintainer changes an importer, mapping or source with the evidence in the pull request. A field report never changes a published value by itself. It starts a review of the source or importer behind the value, and a fix reaches the data through that source or importer. There are no per-carrier overrides. A test report from the OCD Check app goes in the `OCD Check report` form and is recorded under `observed/`, marked unverified, apart from the data ([community/README.md](community/README.md)).

## License

Software and documentation are Apache-2.0. The text is in [LICENSE](LICENSE). The published carrier values are facts the project derived and normalized. The project publishes no vendor files and waives its own rights in the data under CC0 1.0. The details are in [DATA-LICENSE.md](DATA-LICENSE.md).
