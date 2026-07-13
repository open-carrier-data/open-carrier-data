# Device And Artifact Catalog

This directory answers three separate questions:

1. Which device identities are present in a current maintained inventory?
2. Which carrier artifacts are present in a current maintained vendor index?
3. Which devices match exact model scope recorded by the carrier-profile evidence?

Those questions are intentionally separate. A listed device is not automatically
tested, and a family-level carrier artifact is not proof that every carrier
feature works on every model.

Files:

- `index.json`: counts by platform and retail brand, plus source revisions;
- `android.json`: current and historical Google Play device identities;
- `apple.json`: current and historical Apple product types from Apple's carrier
  index;
- `apple-carrier-artifacts.json`: current public-safe Apple artifact metadata.

`verification: indexed` means the artifact and its digest are present in the
current official index. `verification: verified` means automation also fetched
the package and matched that digest. Failed downloads or digest mismatches are
quarantined and are not included in the public artifact file.

One device can be listed by more than one maintained inventory. Such records
merge only when their canonical device ID is identical, and
`inventory_sources` keeps each source's current or historical state visible.

Use the schemas under `schemas/` and run:

```bash
python3 tools/validate_device_catalog.py generated/devices
```
