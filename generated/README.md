# Generated files

The Android files under `generated/android/` are produced from the carrier profiles in `carriers/open/`. The evidence index and the device catalog are published from the private repo. Never edit the data files here by hand; these README files are documentation.

| Path | Meaning |
| --- | --- |
| `index.json` | one entry per carrier profile in the latest publish, with `profile_id`, `display_name`, `path` |
| `evidence-index.json` | source snapshot records, per-profile fact sources, observed scope, exact source versions, conflicts, quality gates, newest entry dates |
| `android/` | APN XML, CarrierConfig XML, `lookup.json`, `metadata.json` with the freshness window |
| `devices/` | the device catalog, the two carrier artifact registries, and the device records (`carrier-variants.json`) for VoLTE, Wi-Fi calling, video calling and VoNR |

The Android files come from `python3 tools/generate_android_outputs.py carriers generated --apn-version 8`. The profiles, the evidence index, and the device catalog are published from the private repo.

`android/metadata.json` carries `checks_through` and `stale_after`. Read both before you ship. The validators warn past `stale_after` and fail only with `--freshness fail`, which the daily public job passes. That job opens an issue labeled `stale-data` when it fails.

Phones read these files after a ROM, app, or build has packaged them. Nothing here is served at runtime.

These files on `main` are the edge channel: each publish replaces them, several times a day. No release exists yet. The planned monthly releases, `data-YYYY.MM`, will be the production channel; [docs/releases.md](../docs/releases.md) describes them. No file is supported today. The planned tiers: `android/apns-conf.xml` for ROMs, from the first release that carries the review of its emergency APN rows and has passed one boot check; `android/lookup.json`, `android/metadata.json` and `devices/carrier-variants.json` for apps and tools, the device records as information only; `android/carrier-config-list.xml` not for ROM application until the per-key review of its safety keys has run; `index.json`, `evidence-index.json` and the other files under `devices/` reference files for the resolver and for reviewers.
