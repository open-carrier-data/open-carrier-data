# Android Generated Output

This directory contains Android-facing files generated from the neutral carrier
profiles.

Use these files when a ROM, carrier configuration app, test suite, or build
pipeline needs Android-style carrier data.

## Files

```text
apns-conf.xml                     Android APN XML
lookup.json                       full profile lookup data
mccmnc-index.json                 compact index by MCC/MNC
carrier-id-index.json             compact index by Android carrier ID
carrier-config-overrides.json     reviewed CarrierConfig overrides
carrier-config-list.xml           Android-style CarrierConfig XML
metadata.json                     target version, output counts, and omissions
```

## How To Match A SIM

1. Use `mccmnc-index.json` if you only know MCC/MNC.
2. Use `carrier-id-index.json` if Android already resolved a carrier ID.
3. Test every populated match field. Values inside one list are alternatives;
   different fields are cumulative requirements.
4. Keep every matching profile and apply it in generic-to-specific order.
   Generated records expose a `specificity` number for this purpose.

The included resolver implements those rules:

```bash
python3 tools/resolve_carrier_profiles.py --mccmnc 26202 --spn Example
```

Do not treat MCC/MNC alone as exact when a profile contains more specific
matching rules.

## Important Limits

The neutral JSON profiles remain the source of truth.

Some facts cannot be represented safely in Android XML alone. For example, a
match that depends on GID2 may stay in JSON lookup data because plain APN or
CarrierConfig XML could lose that condition.

CarrierConfig XML compares GID values exactly, while the neutral schema stores
GID prefixes. Profiles that would be broadened are therefore omitted from
`carrier-config-list.xml`. `metadata.json` lists each omitted profile ID, not
only a count.

Carrier-ID-only APN rows are emitted with `carrier_id` and without a generic
MCC/MNC selector. A carrier-ID rule combined with an incompatible MVNO match is
kept in JSON and omitted from APN XML.

The checked-in APN XML targets database version 8. Android's TelephonyProvider
requires this to match the target build. Generate another target explicitly:

```bash
python3 tools/generate_android_outputs.py carriers generated --apn-version 9
```

Always inspect `metadata.json` before packaging generated XML.

CarrierConfig fragments follow AOSP's overlay order: generic matching
fragments come first and more specific matching fragments come later, so a
specific value can override a generic value.

Runtime phone code should read a local snapshot. It should not fetch these
files from GitHub while a SIM is loading or a call is starting.
