# Generated files

The Android files under `generated/android/` are produced from the carrier profiles in `carriers/open/`. The evidence index and the device catalog are published from the private repo. Never edit any of these files by hand.

| Path | Meaning |
| --- | --- |
| `index.json` | stable snapshot, one entry per carrier profile with `profile_id`, `display_name`, `path` |
| `evidence-index.json` | source snapshot records, per-profile fact sources, observed scope, conflicts, quality gates |
| `android/` | APN XML, CarrierConfig XML and JSON, lookup indexes, `metadata.json` with the freshness window |
| `devices/` | the device catalog and the two carrier artifact registries |

The Android files come from `python3 tools/generate_android_outputs.py carriers generated --apn-version 8`. The profiles, the evidence index, and the device catalog are published from the private repo.

`android/metadata.json` carries `checks_through` and `stale_after`. Read both before you ship. The validators warn past `stale_after` and fail only with `--freshness fail`, which CI passes.

Phones read these files after a ROM, app, or build has packaged them. Nothing here is served at runtime.
