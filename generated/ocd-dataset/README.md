# generated/ocd-dataset/

The OCD dataset for the owner's ROM (rule round 30). With `../android/apns-conf.xml` and `../devices/device-records.json` it is one set per commit of `main`. OcdCarrierSettings reads it, the OCD Check owner app pulls it pinned per commit, and the ROM pin step bakes it into the build.

| File | Contents |
| --- | --- |
| `manifest.json` | OCD's data digest, `generated_at`, every file of the set with its size and SHA-256, the dataset digest and the counts |
| `profiles.json` | the closed key registry, groups A, B and X6, and every network's OCD and fill-only profiles with their match rules, specificity, values, sources and ordered Google-lane fill list |
| `google-lane.json` | the Google lane's values as OCD source family `google`: Google's carrier list rules in file order and every entry's CarrierConfig values, without values the privacy guard trips |
| `apn-index.json` | each row of `apns-conf.xml` in file order with its line, row key and profiles |

Beside the set, in the same commit, are four companion files (rule round 31). They are not manifest roles, so every reader on a phone today parses the set unchanged:

| File | Contents | Written by |
| --- | --- | --- |
| `f5-reads.json` | the chain of F5 reads: one per change of the APN rows on `main`, each with its emergency lines, the rule that decided each line and the verdict (SM6) | `tools/f5_read.py publish`, in the private publish run |
| `group-a-reads.json` | the group A reads of `devices/records/reads/group-a/` as CarrierSettings serves them (one item per read, profile and source family) and the display-only key findings; an optional dataset role, listed from implementation order step 8 | `tools/ocd_dataset.py generate` |
| `group-a-pending.json` | every group A value that still waits for a read, the values whose basis is not recorded, every key read, and the keys that left group A | `tools/ocd_dataset.py generate` |
| `privacy-withheld.json` | which Google-lane values the privacy guard leaves out, by entry and key, without the value (SM4) | the private publisher |

`tools/ocd_dataset.py generate` writes these files and `tools/ocd_dataset.py validate` checks them; `tools/f5_read.py check` checks the F5 chain. Do not edit them by hand. [docs/ocd-dataset.md](../../docs/ocd-dataset.md) explains the formats.
