## What Changed

Describe the schema, tooling, generator, or documentation change. Carrier
data changes are not accepted by hand. Report them through the issue forms.

## Why

Explain the problem this fixes.

## Safety Check

- [ ] I removed every private value listed in
      [SECURITY.md](https://github.com/open-carrier-data/open-carrier-data/blob/main/SECURITY.md).
- [ ] If this changes carrier behavior, I included evidence or linked a
      maintained source.

## Checks

Run the checks that apply:

```bash
python3 tools/validate_public_carrier_data.py carriers generated/index.json
python3 tools/validate_device_catalog.py generated/devices
python3 tools/test_generated_android_outputs.py
python3 tools/test_carrier_relevance_contract.py
python3 tools/test_resolve_carrier_profiles.py
```
