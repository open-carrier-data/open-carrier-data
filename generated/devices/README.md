# Device catalog

The device catalog records which device identities maintained inventories list, which carrier artifacts vendor indexes hold, and which devices appear in carrier evidence. A listed device is an inventory fact. It is not a support claim.

| File | Meaning |
| --- | --- |
| `index.json` | counts per platform, coverage status, brand, and relevance, plus the 17 named sources |
| `android.json` | 42,259 Android device identities with coverage status, relevance, and inventory sources |
| `apple.json` | 180 Apple product types from Apple's carrier index |
| `android-carrier-artifacts.json` | 3,211 Android carrier source artifacts and 4,426 discovery scope records |
| `apple-carrier-artifacts.json` | 1,331 Apple carrier bundle artifacts, all digest verified |

Counts come from these commands:

```bash
python3 tools/validate_device_catalog.py generated/devices
python3 -c 'print(__import__("json").load(open("generated/devices/index.json"))["artifact_registries"])'
python3 -c 'print(len(__import__("json").load(open("generated/devices/android-carrier-artifacts.json"))["scope_coverage"]))'
python3 -c 'print(len(__import__("json").load(open("generated/devices/index.json"))["sources"]))'
```

## What covered means

One rule defines coverage. A device is covered when a maintained source produced carrier evidence for that exact device identity. On Android that is `carrier_data_coverage.status` equal to `exact_carrier_data_observed`, which means a published profile carries an observation scoped to the device. On Apple it is `exact_source_verified`, which means Apple's carrier index lists a bundle for that exact product type and the bundle matched its digest. Nothing else counts. A family match, an indexed but unobtained artifact, and an inventory listing are not partial coverage.

Print the two numbers with:

```bash
python3 -c 'import json; c=json.load(open("generated/devices/index.json"))["platforms"]; print(c["android"]["carrier_data_coverage_counts"].get("exact_carrier_data_observed", 0), "of", c["android"]["device_count"], "Android identities;", c["apple"]["carrier_data_coverage_counts"].get("exact_source_verified", 0), "of", c["apple"]["device_count"], "Apple product types")'
```

On 2026-09-24 it prints `262 of 42259 Android identities; 5 of 180 Apple product types`.

Every device carries `carrier_data_coverage.status`. The other statuses say how far a maintained source got, or why it stopped. They are steps, not fractions of coverage.

| Status | Android | Apple | Meaning |
| --- | --- | --- | --- |
| `exact_carrier_data_observed` | 262 | 0 | covered, a published observation is scoped to the device |
| `exact_source_verified` | 0 | 5 | covered, a digest-verified Apple bundle names the exact product type |
| `exact_source_extracted` | 426 | 0 | a vendor index lists an artifact for the exact device and automation obtained it, but no published observation is scoped to the device |
| `exact_source_indexed` | 1,042 | 0 | a vendor index lists an artifact for the exact device that automation has not obtained |
| `family_source_verified` | 0 | 163 | a digest-verified Apple bundle matched the product family, not the exact product type |
| `source_checked_no_artifact` | 1,254 | 0 | a maintained source was queried for the device and listed nothing |
| `source_not_queryable` | 70 | 0 | the device lacks the identifier a maintained source needs for a query |
| `inventory_only` | 39,205 | 12 | an inventory lists the device and no maintained source was queried |

The schema allows seven more statuses that no device carries on 2026-09-24. `family_source_indexed`, `source_discovery_in_progress`, `source_authentication_required`, `source_terms_restrict_extraction`, `source_transport_untrusted`, `platform_out_of_scope`, and `carrier_data_not_applicable` belonged to source lanes that were removed on 2026-09-23 or describe situations the maintained sources do not produce.

Every device also carries `carrier_relevance.status`, one of `evidence_confirmed_cellular`, `evidence_confirmed_non_cellular`, or `not_established`. A confirmed status needs evidence tied to a declared source. Names, families, and form factors are never evidence.

Artifact `verification` is `indexed` when the vendor index lists it. It is `extracted` when automation also obtained the Android source. It is `verified` when the downloaded package matched its digest. Failed and mismatched artifacts are quarantined and never published.

To validate the catalog, run `python3 tools/validate_device_catalog.py generated/devices`.
