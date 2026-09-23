# Device catalog

The device catalog records which device identities maintained inventories list, which carrier artifacts vendor indexes hold, and which devices appear in carrier evidence. A listed device is an inventory fact. It is not a support claim.

| File | Meaning |
| --- | --- |
| `index.json` | counts per platform, coverage status, brand, and relevance, plus the 45 named sources |
| `android.json` | 42,259 Android device identities with coverage status, relevance, and inventory sources |
| `apple.json` | 180 Apple product types from Apple's carrier index |
| `android-carrier-artifacts.json` | 8,599 Android carrier source artifacts and 14,171 discovery scope records |
| `apple-carrier-artifacts.json` | 1,331 Apple carrier bundle artifacts, all digest verified |

Counts come from these commands:

```bash
python3 tools/validate_device_catalog.py generated/devices
python3 -c 'print(__import__("json").load(open("generated/devices/index.json"))["artifact_registries"])'
python3 -c 'print(len(__import__("json").load(open("generated/devices/android-carrier-artifacts.json"))["scope_coverage"]))'
python3 -c 'print(len(__import__("json").load(open("generated/devices/index.json"))["sources"]))'
```

Every device carries `carrier_data_coverage.status`. The schema allows `inventory_only`, `exact_carrier_data_observed`, `exact_source_extracted`, `exact_source_verified`, `exact_source_indexed`, `family_source_verified`, `family_source_indexed`, `source_discovery_in_progress`, `source_checked_no_artifact`, `source_not_queryable`, `source_authentication_required`, `source_terms_restrict_extraction`, `source_transport_untrusted`, `platform_out_of_scope`, and `carrier_data_not_applicable`. Only `exact_carrier_data_observed` means carrier evidence named that device.

Every device also carries `carrier_relevance.status`, one of `evidence_confirmed_cellular`, `evidence_confirmed_non_cellular`, or `not_established`. A confirmed status needs evidence tied to a declared source. Names, families, and form factors are never evidence.

Artifact `verification` is `indexed` when the vendor index lists it. It is `extracted` when automation also obtained the Android source. It is `verified` when the downloaded package matched its digest. Failed and mismatched artifacts are quarantined and never published.

To validate the catalog, run `python3 tools/validate_device_catalog.py generated/devices`.
