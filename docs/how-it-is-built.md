# How the data is built

This page explains where a carrier profile comes from and why it looks the way it does. It is not a command reference. For commands, read [consume.md](consume.md).

## The pipeline in one picture

Every value in `carriers/open/` passes through the same five stages:

```text
source families          upstream repos, vendor indexes, firmware baselines
      |
candidate observations   private normalized records, one per source and carrier match
      |
the sanitizer            merges, quarantines, and strips private material
      |
carrier profiles         neutral JSON in carriers/open/, one file per match set
      |
generated files          generated/index.json, evidence-index.json, android/, devices/
```

The first three stages live in the private repo. The runner named `bela-open-carrier-data-network` ran them. As of 2026-09-23 that runner is offline and the 13 scheduled private workflows are disabled, so no stage runs by itself. The public repo receives carrier profiles and generated files, then its own workflow validates them. The public tools can regenerate `generated/android/` from the profiles, but they cannot rebuild profiles from sources.

## Sources become candidate observations

A source family is one upstream. Examples are the LineageOS APN repo, Apple's carrier bundle index, or a Samsung firmware baseline. An importer reads the upstream and writes candidate observations. Each observation records one carrier match set, the facts seen, the source family, the upstream revision, and the date automation checked it. Raw source material stays in the private repo.

[SOURCES.md](../SOURCES.md) lists every source family and its terms.

## The sanitizer merges observations into profiles

The sanitizer groups observations and applies fixed rules. The rules are:

- Grouping by exact match set. Observations with the same `mccmnc`, `spn`, `gid1_prefixes`, `gid2_prefixes`, `iccid_prefixes`, `imsi_prefix_patterns`, and `android_carrier_ids` form one profile. A different match set forms a different profile.
- Agreement. When every source that names a fact gives the same value, the value is published.
- Conflict omission. When sources give different values for one CarrierConfig key, one add-on key, or one APN selector, the value is left out. The evidence index records the conflict with `resolution: omitted_from_stable`.
- Conditional capabilities. Capabilities are the one exception. A disagreement becomes `conditional` instead of an omission.
- Corroboration for generic APNs. A low-confidence generic APN row needs a second source or a primary maintained APN source. Otherwise the `uncorroborated_generic_apn` gate drops it.
- No source-branded duplicates. A source name never becomes its own profile. Samsung and Apple observations for the same match set land in the same neutral profile.
- Certification test profiles are quarantined. A name starting with GCF, PTCRB, or Testbed, or a Samsung `network_type_capability` starting with `GCF-`, gets the reason `certification_test_profile`. The rule sits in the private sanitizer at `tools/sanitize_profiles.py` lines 1103 to 1105.

The evidence index keeps `fact_sources` per exported fact. A profile-wide source list is not proof for every field. Check the fact, not the profile.

## Why profiles are neutral

A profile says "this carrier has these settings". It does not say "Samsung says this" or "Apple says this". Two reasons drive that choice.

First, a consumer needs one answer per SIM. A ROM cannot ask the user which vendor to believe.

Second, source-branded profiles would leak vendor structure into public data. Neutral profiles let the project publish transformed facts from sources whose raw files it may not redistribute.

The cost is real. When sources disagree, the consumer gets nothing for that key. The evidence index shows why, so a maintainer can go back to the sources.

## Why an MVNO can land in its host's profile

Grouping by exact match set has one visible consequence. An MVNO that no source distinguishes from its host network merges into the host's profile.

LIDL Connect runs on the Vodafone Germany network, `26202`. No source names it with an SPN, GID, or IMSI prefix. So no profile names it. A LIDL Connect SIM resolves the plain `26202` profile plus whichever `26202` SPN profile matches the SPN on the SIM. The result is Vodafone's data, which may or may not be right for that MVNO.

The limit exists because the sanitizer only publishes what a source observed. It does not invent a selector. A community claim with a tested SPN or GID prefix is the way to add one.

## Why stale data is dropped after 180 days

Every source snapshot carries two dates. `revision_date` says when the upstream revision was published. `checked_at` says when automation last confirmed that revision. Freshness uses `checked_at`. Unchanged upstream content stays fresh as long as automation keeps checking it.

The sanitizer quarantines any observation whose `checked_at` is older than 180 days. `tools/validate_public_carrier_data.py` lines 754 to 757 fail the whole run when any snapshot record is older than 180 days. `tools/validate_device_catalog.py` line 195 does the same for the catalog.

Stale is worse than missing. A missing APN row makes a phone fall back to its own defaults or ask the user. A stale row looks authoritative and sends the phone to a dead MMSC. Nobody notices until messages fail. So the project drops old data instead of keeping it.

On 2026-09-23 the oldest check in the public evidence index and in the private manifests is 2026-07-13. From 2027-01-10 the validators fail and the daily public CI turns red until sources are re-checked. No new checks arrive by themselves, because the runner is offline and the schedules are disabled. The data does not change by itself. It stops validating. Run this command to see the dates:

```bash
python3 -c 'print(sorted(s["checked_at"] for s in __import__("json").load(open("generated/evidence-index.json"))["source_snapshots"]))'
```

## What the public repo checks

The workflow `Validate carrier data` in `.github/workflows/validate.yml` runs on push to `main`, on pull requests, daily at 04:17 UTC by cron, and on manual dispatch. It validates the profiles against the stable index, the device catalog, and the community claims. It runs the five test scripts. It regenerates `generated/android/` to confirm nothing drifted. The required check on `main` is `validate`.
