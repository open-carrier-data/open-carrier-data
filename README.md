# Open Carrier Data

Open Carrier Data is a public database of mobile carrier settings. It stores neutral JSON carrier profiles in `carriers/open/` and turns them into Android APN and CarrierConfig files under `generated/`. It exists for ROM builders, carrier configuration apps, eSIM tools, and build systems. They can ship APN, MMS, IMS, RCS, and eSIM data locally instead of maintaining the same fixes alone. Phones read the packaged files at runtime. Nothing in this project is a network service.

## Get the data

You can get the data in three ways. Each one works as of 2026-09-23.

To take everything, including tools and schemas, clone the public repo:

```bash
git clone https://github.com/open-carrier-data/open-carrier-data.git
```

To read the stable snapshot without a checkout, download the raw index:

```bash
curl -sL https://raw.githubusercontent.com/open-carrier-data/open-carrier-data/main/generated/index.json | head -c 200
```

To package the Android files into a build, copy the whole directory:

```bash
cp -r generated/android/ /path/to/your/build/carrier-data/
```

Read [docs/consume.md](docs/consume.md) before you ship the XML. The checked-in APN XML targets database version 8.

## Resolve one SIM

To find every profile that applies to one SIM, run the resolver with the SIM's facts:

```bash
python3 tools/resolve_carrier_profiles.py --mccmnc 26202 --spn Vodafone.de
```

The output starts like this:

```text
{
  "profiles": [
    {
      "android_apn_count": 10,
      "capabilities": {
        "esim": "unknown",
        "ims_conference": "unknown",
        "mms": "conditional",
```

Profiles come back in generic-to-specific order. Apply each one as an overlay on the previous one. With `--mccmnc` alone only the broad profile returns. SPN, GID, IMSI, and ICCID profiles need their own flags.

## What is in this repository

| Path | Contents |
| --- | --- |
| `carriers/open/` | 7,911 carrier profiles, one JSON file per profile |
| `generated/index.json` | stable snapshot, one entry per profile |
| `generated/evidence-index.json` | source revisions, check dates, fact sources, conflicts |
| `generated/android/` | APN XML, CarrierConfig XML and JSON, lookup indexes, `metadata.json` |
| `generated/devices/` | the device catalog and carrier artifact registries |
| `schemas/` | five JSON schemas |
| `tools/` | validators, the Android generator, the resolver, tests |
| `docs/` | data model, build explanation, consumer guide |

## Status on 2026-09-24

| Measure | Value |
| --- | --- |
| Carrier profiles | 7,911 |
| Source names in profile evidence | 11 |
| Source snapshot records | 10 |
| Checks through | 2026-07-13 |
| Stale after | 2027-01-09 |
| Android devices in the device catalog | 43,007 |
| Apple products in the device catalog | 183 |
| Android identities with observed carrier data | 266 |
| Observations verified on a device | 0 |

Eleven source names appear in profiles but only ten snapshot records exist. `aosp` maps to the snapshots `aosp_carrier_config` and `aosp_carrier_ids`, `lineageos_device_overlays` maps to `lineageos_device_carrier_overlays`, and `samsung_omc` and `samsung_ims` have no snapshot record. Their check dates are in `generated/devices/index.json`.

Counts come from these commands, run from the repo root:

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
- An MVNO without its own SPN, GID, or IMSI prefix in any source merges into the host network's profile. LIDL Connect runs on Vodafone Germany, and no profile names it, so its SIM resolves the `26202` profiles.
- When sources disagree on a CarrierConfig key, add-on, or APN row, the value is omitted. The conflict is listed in `generated/evidence-index.json`.
- Every snapshot carries a freshness window. `generated/android/metadata.json` publishes `checks_through`, the oldest source check behind the data, and `stale_after`, the last date the data should ship. On 2026-09-24 they are 2026-07-13 and 2027-01-09. Ten of the eleven source families were re-checked on 2026-09-24 from the machine that hosted the runner. Samsung was not, because its lane needs the runner's secrets, and `checks_through` follows the oldest observation, a Samsung one from 2026-07-13, so the window did not move. The validators compare the UTC date with `stale_after`. By default they warn and exit 0, so a clone keeps validating after the deadline. The push and pull request check runs the validators in warn mode, so a stale snapshot never blocks a fix. The daily job runs them with `--freshness fail` and opens an issue labeled `stale-data` when they fail, so the first alarm opens on 2027-01-10 unless Samsung is refreshed before then. No new checks arrive by themselves. The private runner is offline and its scheduled workflows are disabled. The data does not change by itself. It stops passing the strict check.
- A device listed in `generated/devices/` is an inventory fact. It is not a support claim. A device is covered only when carrier evidence names that exact identity. `generated/devices/README.md` defines the rule and the one command that prints the number.

## How it is built

The pipeline runs in the private repo and publishes here:

```text
source families -> candidate observations -> the sanitizer -> carrier profiles -> generated files
```

[docs/how-it-is-built.md](docs/how-it-is-built.md) explains the merge rules, why profiles are neutral, and the freshness policy.

## How to contribute

[CONTRIBUTING.md](CONTRIBUTING.md) explains the three issue forms under [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/) and the pull request path for tools and docs. There is no automated path for community carrier data yet. A correction reaches stable data only through a maintained source or a maintainer-curated change.

## License

Software and documentation are Apache-2.0. The text is in [LICENSE](LICENSE). The project's own rights in the data are waived under CC0 1.0, subject to upstream terms. The details are in [DATA-LICENSE.md](DATA-LICENSE.md).
