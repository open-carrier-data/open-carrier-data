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
```

## How To Match A SIM

1. Use `mccmnc-index.json` if you only know MCC/MNC.
2. Use `carrier-id-index.json` if Android already resolved a carrier ID.
3. Load the matching profile from `lookup.json`.
4. Apply the profile's more exact rules, such as SPN, GID1/GID2, ICCID prefix,
   or IMSI prefix pattern.

Do not treat MCC/MNC alone as exact when a profile contains more specific
matching rules.

## Important Limits

The neutral JSON profiles remain the source of truth.

Some facts cannot be represented safely in Android XML alone. For example, a
match that depends on GID2 may stay in JSON lookup data because plain APN or
CarrierConfig XML could lose that condition.

Runtime phone code should read a local snapshot. It should not fetch these
files from GitHub while a SIM is loading or a call is starting.
