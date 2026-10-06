# Open Carrier Data

Open Carrier Data is a public database of mobile carrier settings. It stores neutral JSON carrier profiles in `carriers/open/` and turns them into Android APN and CarrierConfig files under `generated/`. It exists for ROM builders, carrier configuration apps, eSIM tools, and build systems. They can ship APN, MMS, IMS, RCS, and eSIM data locally instead of maintaining the same fixes alone. Phones read the packaged files at runtime. Nothing in this project is a network service.

## Get the data

You can get the data in three ways. Each one works as of 2026-10-04.

To take everything, including tools and schemas, clone the public repo:

```bash
git clone https://github.com/open-carrier-data/open-carrier-data.git
```

To read the stable snapshot without a checkout, download the raw index:

```bash
curl -sL https://raw.githubusercontent.com/open-carrier-data/open-carrier-data/main/generated/index.json | head -c 200
```

To ship the APN list in a build, copy the one file Android reads:

```bash
cp generated/android/apns-conf.xml /path/to/your/build/vendor/apn/open-carrier-data/apns-conf.xml
```

[docs/consume.md](docs/consume.md) shows the `Android.bp` switch that installs it and what `carrier-config-list.xml` overrides.

Read [docs/consume.md](docs/consume.md) before you ship the XML. The checked-in APN XML targets database version 8.

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
| `generated/index.json` | stable snapshot, one entry per profile |
| `generated/evidence-index.json` | source revisions, check dates, fact sources, exact source versions, conflicts, newest entry dates |
| `generated/android/` | APN XML, CarrierConfig XML, `lookup.json`, `metadata.json` |
| `generated/devices/` | the device catalog and carrier artifact registries |
| `schemas/` | five JSON schemas |
| `tools/` | validators, the Android generator, the resolver, a diff against your own `apns-conf.xml`, tests |
| `docs/` | data model, build explanation, consumer guide |

## Status on 2026-10-04

The data republishes whenever a source changes, so these values drift. The commands below the table print the current ones. The table leaves out the freshness window, which moves with every Samsung refresh. The commands print it.

| Measure | Value |
| --- | --- |
| Carrier profiles | 7,806 |
| Source names in profile evidence | 11 |
| Source snapshot records | 12 |
| Android devices in the device catalog | 42,473 |
| Apple products in the device catalog | 183 |
| Android identities with observed carrier data | 266 |
| Observations verified on a device | 0 |

Eleven source names appear in profiles and twelve snapshot records exist. `aosp` maps to the snapshots `aosp_carrier_config` and `aosp_carrier_ids`, and `lineageos_device_overlays` maps to `lineageos_device_carrier_overlays`. The `samsung_omc` and `samsung_ims` records carry a content hash as their revision and `NOASSERTION` as their terms.

Counts and the freshness window come from these commands, run from the repo root:

```bash
ls carriers/open | wc -l
python3 -c 'print(len({s for p in __import__("json").load(open("generated/evidence-index.json"))["profiles"] for s in p["sources"]}))'
python3 -c 'print(len(__import__("json").load(open("generated/evidence-index.json"))["source_snapshots"]))'
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["checks_through"])'
python3 -c 'print(__import__("json").load(open("generated/android/metadata.json"))["stale_after"])'
python3 -c 'print(len(__import__("json").load(open("generated/devices/android.json"))["devices"]))'
python3 -c 'print(len(__import__("json").load(open("generated/devices/apple.json"))["devices"]))'
python3 -c 'print(__import__("json").load(open("generated/devices/index.json"))["platforms"]["android"]["carrier_data_coverage_counts"]["exact_carrier_data_observed"])'
python3 -c 'print(sum(p["verified_observation_count"] for p in __import__("json").load(open("generated/evidence-index.json"))["profiles"]))'
```

## Limits to read before you ship

Read these before you depend on the data:

- No profile has been verified on a phone. Every value comes from a maintained source, not from a test call.
- A capability value says what carrier tables configure, not what works. `supported` means at least one phone maker's or OS carrier table turns the feature on for this SIM and none turns it off; it may still be off on your phone, or on phones the carrier has not approved. `unsupported` needs the operator's own configuration, or two independent source families, turning it off. One maker's off alone is published as `unknown`, and its false CarrierConfig switch is left out. [docs/data-model.md](docs/data-model.md#capability-names-and-values) defines the four values, and `capability_sources` in `generated/evidence-index.json` names the families that turn each capability on and off.
- An MVNO without its own SPN, GID, or IMSI prefix in any source merges into the host network's profile. LIDL Connect runs on Vodafone Germany, and no profile names it, so its SIM resolves the `26202` profiles.
- CarrierConfig and add-on conflicts are omitted; conflicting APN rows are all published as variants. Every conflict is listed in `generated/evidence-index.json`.
- A capability whose only source family has no entry newer than five years is published as `unknown`: video calling for its age alone; VoLTE, VoWiFi, MMS and Wi-Fi calling while roaming only when that source is a frozen copy (Sony's or Fairphone's tree) or no fresh observation covers the profile's own scope. The CarrierConfig key that switches a withheld capability on is left out with it. Other APN rows and CarrierConfig values stay, however old, except APN rows LineageOS removed, which are left out unless a newer source gives them. `generated/evidence-index.json` gives the month of the newest entry behind each profile and each published capability where it is known. [docs/how-it-is-built.md](docs/how-it-is-built.md) explains entry age.
- Every snapshot carries a freshness window. `generated/android/metadata.json` publishes `checks_through`, the oldest source check behind the data, and `stale_after`, the last date the data should ship. A check date means the lane behind the data ran, not that a value is current: only Samsung's update service and Google's Pixel update check confirm vendor data as current. How old the data is shows in `newest_entry` per profile in `generated/android/lookup.json`. The commands under the status table print both. The oldest Samsung observations set `checks_through`. Samsung's lane runs daily on the owner's self-hosted runner. It re-confirms observations whose firmware build is still current and re-extracts up to 50 CSC packages per run. Observations from superseded builds keep their July 2026 dates until they are re-extracted; whatever is still from July is quarantined on the day it turns 180 days old, the first on 2027-01-10. A weekly GitHub-hosted job re-checks the other source families. Their check dates are in `generated/evidence-index.json` under `source_snapshots`. The validators compare the UTC date with `stale_after`. By default they warn and exit 0, so a clone keeps validating after the deadline. The push and pull request check runs the validators in warn mode, so a stale snapshot never blocks a fix. The daily job runs them with `--freshness fail` and opens an issue labeled `stale-data` when they fail, and also when one lane's source was not checked within its limit (10 days for the daily Samsung lanes, 21 for the weekly ones) or the last publish is more than 21 days old.
- A device listed in `generated/devices/` is an inventory fact. It is not a support claim. A device is covered only when carrier evidence names that exact identity. `generated/devices/README.md` defines the rule and the one command that prints the number.

## How it is built

The pipeline runs in the private repo and publishes here:

```text
source families -> candidate observations -> the sanitizer -> carrier profiles -> generated files
```

[docs/how-it-is-built.md](docs/how-it-is-built.md) explains the merge rules, why profiles are neutral, and the freshness policy.

## How to contribute

[CONTRIBUTING.md](CONTRIBUTING.md) explains the three issue forms under [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/) and the pull request path for tools and docs. A correction reaches stable data through a maintained source, or a maintainer changes an importer, mapping or source with the evidence in the pull request; per-carrier overrides do not exist yet and will be built when the first verified report needs one.

## License

Software and documentation are Apache-2.0. The text is in [LICENSE](LICENSE). The published carrier values are facts the project derived and normalized. The project publishes no vendor files and waives its own rights in the data under CC0 1.0. The details are in [DATA-LICENSE.md](DATA-LICENSE.md).
