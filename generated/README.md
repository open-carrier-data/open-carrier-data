# Generated files

The Android files under `generated/android/` are produced from the carrier profiles in `carriers/open/`. The evidence index and the device catalog are published from the private repo. Never edit the data files here by hand; these README files are documentation.

| Path | Meaning |
| --- | --- |
| `index.json` | one entry per carrier profile in the latest publish, with `profile_id`, `display_name`, `path` |
| `evidence-index.json` | source snapshot records, per-profile fact sources, observed scope, exact source versions, conflicts, quality gates, newest entry dates |
| `android/` | APN XML, CarrierConfig XML, `lookup.json`, `metadata.json` with the freshness window |
| `devices/` | the device catalog, the two carrier artifact registries, the device records (`carrier-variants.json`) for VoLTE, Wi-Fi calling, video calling and VoNR, and the per-device records of the owner's devices (`device-records.json`, rule round 30) |
| `ocd-dataset/` | the OCD dataset that OcdCarrierSettings serves as a ROM's carrier data (rule rounds 30 and 31, [docs/rom-builders.md](../docs/rom-builders.md)): `manifest.json`, `profiles.json` (OCD's match rules, values and the Google-lane fill per network), `google-lane.json` (the Google lane's values, family `google`) and `apn-index.json`; with `android/apns-conf.xml` and `devices/device-records.json` one set per commit. [docs/ocd-dataset.md](../docs/ocd-dataset.md) |

The Android files come from `python3 tools/generate_android_outputs.py carriers generated --apn-version 8`, the OCD dataset and the per-device records from `python3 tools/ocd_dataset.py generate` (the private publisher writes the Google lane first). The profiles, the evidence index, and the device catalog are published from the private repo.

`android/metadata.json` carries `checks_through` and `stale_after`. Read both before you ship. The validators warn past `stale_after` and fail only with `--freshness fail`, which the daily public job passes. That job opens an issue labeled `stale-data` when it fails.

Phones read these files after a ROM, app, or build has packaged them. Nothing here is served at runtime.

These files on `main` are the edge channel: each publish replaces them, several times a day. The monthly releases, `data-YYYY.MM`, are the production channel; the first is `data-2026.10`, published on 2026-10-19, and [docs/releases.md](../docs/releases.md) describes them. The tiers in `data-2026.10`: `android/apns-conf.xml` for ROMs once the boot check on the owner's phone has passed, not supported until then; `android/lookup.json`, `android/metadata.json` and `devices/carrier-variants.json` supported for apps and tools, the device records as information only; `android/carrier-config-list.xml` not for ROM application until the per-key review of its safety keys has run; `index.json`, `evidence-index.json` and the other files under `devices/` reference files for the resolver and for reviewers.
