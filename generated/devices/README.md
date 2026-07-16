# Device And Artifact Catalog

This directory answers four separate questions:

1. Which device identities are present in a current maintained inventory?
2. Which carrier artifacts are present in a current maintained vendor index?
3. Which devices match exact model scope recorded by the carrier-profile evidence?
4. Which source checks are complete, still running over time, or cannot be made?

Those questions are intentionally separate. A listed device is not automatically
tested, and a family-level carrier artifact is not proof that every carrier
feature works on every model.

Files:

- `index.json`: counts by platform and retail brand, plus source revisions;
- `android.json`: merged current and historical Android device identities plus
  per-device carrier-data coverage;
- `apple.json`: current and historical Apple product types from Apple's carrier
  index;
- `apple-carrier-artifacts.json`: current public-safe Apple artifact metadata.
- `android-carrier-artifacts.json`: current public-safe Android artifact metadata
  plus exact source-discovery and terminal scope records.

The index includes coverage-state counts per retail brand. This makes missing
OEM adapters visible without opening tens of thousands of device records.

`verification: indexed` means the artifact and its digest are present in the
current official index. `verification: verified` means automation also fetched
the package and matched that digest. Failed downloads or digest mismatches are
quarantined and are not included in the public artifact file.

For Android, `indexed` means an exact vendor query confirmed a current artifact.
`extracted` means the device-scoped carrier source was also obtained and
integrity-checked. Discovery states distinguish work in progress, a completed
check with no artifact, and identities that lack a usable vendor query key.

`carrier_data_not_applicable` is reserved for explicitly classified non-cellular
Apple product families or exact Android variants backed by an official
connectivity source. `source_transport_untrusted` records an exact Android
source whose archive or binary-package transport does not meet unattended
integrity requirements; it has no artifacts and is not a successful carrier
extraction. Unrecognized present or future identities remain `inventory_only`
until evidence classifies them.

One device can be listed by more than one maintained inventory. Such records
merge only when their canonical device ID is identical, and
`inventory_sources` keeps each source's current or historical state visible.
Android artifact and discovery records may link directly through that canonical
ID. `match_kind: exact_device_id` means the maintained source adapter supplied
that exact link; it does not rely on a similar marketing name or fuzzy alias.

Use the schemas under `schemas/` and run:

```bash
python3 tools/validate_device_catalog.py generated/devices
```
