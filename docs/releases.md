# Releases

This page describes the planned releases of Open Carrier Data (rule decisions of 2026-10-18, round 20). **No release exists yet, and no file is supported today.** Until the first release, everything here is a plan; the tooling that drafts a release, the compatibility policy and the schemas come in later pull requests, and this page changes with them.

## Two channels

- **`main` is the edge channel.** Every publish lands there, several times a day. It is guarded by the `validate` check and the phone guard ([how-it-is-built.md](how-it-is-built.md)), and OCD makes no other promise about it. A maintainer may pin a `main` commit by hand, as the owner's S20 build does today.
- **Releases will be the production channel.** A release is a git tag `data-YYYY.MM`, at most one a month, with a fix release `data-YYYY.MM.N` only for a defect in the newest release that affects phones. A bad release is marked withdrawn in its title and in the next release's notes; its tag and files stay. Tooling drafts a release from a `main` commit; the owner reads the notes and publishes it. Nothing releases on a timer. A month with no candidate that passes every check has no release. The first release is planned as `data-2026.11`, with no date promised.

Daily publishing to `main`, the phone guard, the freshness alarm and the data rules do not change.

## Planned tiers

| File | Planned tier | For |
| --- | --- | --- |
| `generated/android/apns-conf.xml` | supported, once it ships in a release, the review of its emergency APN rows has ruled and its result is in that release, and the owner's S20 has built and booted that release once with its APN list loaded | ROMs, at build time |
| `generated/android/lookup.json` | supported, from the first release | apps and tools, bundled at build time |
| `generated/android/metadata.json` | supported, from the first release | apps and tools; a ROM's build log |
| `generated/devices/carrier-variants.json` | supported as information, from the first release; never an export | apps |
| `generated/android/carrier-config-list.xml` | not supported for ROM application, and not a release asset, until the per-key review of its emergency, TTY, RTT, WPS and `iwlan.*` keys has run and been implemented | reviewers; a maintainer doing their own review |
| `carriers/open/`, `generated/index.json`, `generated/evidence-index.json`, the other files under `generated/devices/` | reference: in the tagged tree, with no further promise | the resolver, `--explain`, reviewers |

## What a release will contain

- the four supported files, each byte-identical to the file in the tagged commit;
- `release.json`: the tag, the commit, the previous tag, `data_digest`, `checks_through`, `stale_after` and the days left, the APN database version, and per file its path, tier, size and SHA-256;
- `SHA256SUMS`, so `sha256sum -c SHA256SUMS` checks the files;
- release notes, generated from the previous release to this one: the freshness window and counts, the phone guard's result, IMS and emergency lead changes in full, internet, attach and MMS lead changes, CarrierConfig changes with the emergency, TTY, RTT, WPS and `iwlan.*` keys in full, and the profile IDs added and removed.

## What a release will guarantee

The guarantees cover the files and the process that made them, never that a value works.

- **Fixed and identifiable.** A tag is never moved or deleted. The files are byte copies of the tagged commit, and `SHA256SUMS` and `release.json` list them. The XML header carries `data_digest`.
- **Reproducible.** Regenerating `generated/android/` from `carriers/` at the tag gives the same bytes.
- **Valid.** Every validator passes with `--freshness fail`, `apns-conf.xml` passes LineageOS's unchanged `apns-conf.xsd`, and `<apns version>` equals `metadata.json`'s `target.apn_database_version`.
- **Fresh.** `stale_after` is at least 30 days after the release, and the notes print the days left.
- **Guarded.** The phone guard runs from the previous release to this one, and every trip is listed and was accepted on `main`.
- **Changes are visible.** The notes list the changes above in full.
- **Format changes come with notice.** A breaking change to a supported file, such as a removed or renamed file or field or a changed meaning, comes only at a release, is announced in an earlier release's notes, and bumps the file's `schema_version`. The policy starts at the first release; earlier changes stay history.

## What a release never guarantees

- That a value works on a network, a plan or a phone model, or that the operator still offers the service. Values are configured, not verified: `verified_observation_count` is 0.
- Anything about emergency calls. OCD never tests or places one.
- That a `profile_id` stays the same. It is a hash of the match set and changes when a source's selectors change; key what you store by the SIM's facts and the release.
- Anything about `main` between releases.
- A response time, or that releases continue. One maintainer and one self-hosted runner run the pipeline.

## If releases stop

Keep the last release until its `stale_after`, then switch back to your ROM's own list (on the S20 tree, `LINEAGE_APN_SOURCE=lineage`).
