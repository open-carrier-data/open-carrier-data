# Generated files

The Android files under `generated/android/` and the two claim indexes are produced from the carrier profiles in `carriers/open/` and the claims in `community/claims/`. The evidence index and the device catalog are published from the private repo. Never edit any of these files by hand.

| Path | Meaning |
| --- | --- |
| `index.json` | stable snapshot, one entry per carrier profile with `profile_id`, `display_name`, `path` |
| `evidence-index.json` | source snapshot records, per-profile fact sources, observed scope, conflicts, quality gates |
| `android/` | APN XML, CarrierConfig XML and JSON, lookup indexes, `metadata.json` |
| `devices/` | the device catalog and the two carrier artifact registries |
| `community/index.json` | valid, non-expired community claims |
| `candidate/index.json` | community claims fit for opt-in testing |

The Android files come from `python3 tools/generate_android_outputs.py carriers generated --apn-version 8`. The claim indexes come from `python3 tools/validate_community_claims.py --write-index`. The profiles, the evidence index, and the device catalog are published from the private repo.

Phones read these files after a ROM, app, or build has packaged them. Nothing here is served at runtime.
