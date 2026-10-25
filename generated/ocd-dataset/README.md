# generated/ocd-dataset/

The OCD dataset for the owner's ROM (rule round 30). With `../android/apns-conf.xml` and `../devices/device-records.json` it is one set per commit of `main`. OcdCarrierSettings reads it, the OCD Check owner app pulls it pinned per commit, and the ROM pin step bakes it into the build.

| File | Contents |
| --- | --- |
| `manifest.json` | OCD's data digest, `generated_at`, every file of the set with its size and SHA-256, the dataset digest and the counts |
| `profiles.json` | the closed key registry, groups A, B and X6, and every network's OCD and fill-only profiles with their match rules, specificity, values, sources and ordered Google-lane fill list |
| `google-lane.json` | the Google lane's values as OCD source family `google`: Google's carrier list rules in file order and every entry's CarrierConfig values, without values the privacy guard trips |
| `apn-index.json` | each row of `apns-conf.xml` in file order with its line, row key and profiles |

`tools/ocd_dataset.py generate` writes these files and `tools/ocd_dataset.py validate` checks them. Do not edit them by hand. [docs/ocd-dataset.md](../../docs/ocd-dataset.md) explains the formats.
