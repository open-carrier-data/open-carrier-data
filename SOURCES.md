# Data Sources

Open Carrier Data combines carrier facts from maintained sources. It does not
publish raw vendor packages, credentials, signed URLs, device identifiers, or
private logs.

The exact public Git revisions used for the current snapshot are recorded in:

```text
generated/evidence-index.json
```

Every public-source record contains two dates:

- `revision_date`: when the exact upstream commit was created;
- `checked_at`: when automation last fetched the source successfully.

Freshness uses `checked_at`, not `revision_date`. An unchanged old commit can
still be current when automation checked it recently. A source is quarantined
when its recorded check is more than 180 days old.

## Current Source Families

### AOSP CarrierConfig and carrier IDs

- upstream: Android Open Source Project
- data: Android CarrierConfig values and Android carrier identity rules
- terms: Apache-2.0
- update method: the current `android-latest-release` branch is fetched and
  recorded by full Git commit ID

### LineageOS APNs

- upstream: `LineageOS/android_vendor_apn`
- data: Android APN and MVNO matching rows
- terms: Apache-2.0, as declared by the upstream files
- update method: scheduled Git import recorded by full commit ID

### Mobile Broadband Provider Info

- upstream: GNOME `mobile-broadband-provider-info`
- data: public carrier and APN facts
- terms: Creative Commons Public Domain dedication (`CC-PD` in this project)
- update method: scheduled Git import recorded by full commit ID

### Apple carrier bundles

- upstream used by automation: `dwilliamsuk/ios-carrier-bundles`, generated
  from current Apple system images
- data: translated APN facts only
- upstream license: `NOASSERTION`; the mirror does not declare a license
- public policy: raw Apple bundles are not republished here; only narrow,
  sanitized factual fields are emitted
- update method: scheduled Git import recorded by full commit ID

### Samsung OMC

- upstream: Samsung firmware OMC baselines and Samsung GRAS/OMC update checks
- data: narrow translated APN, capability, carrier identity, CarrierConfig,
  and neutral add-on facts
- upstream license: no Samsung license is asserted by this project
- public policy: raw Samsung firmware, OMC files, requests, responses, signed
  URLs, and credentials remain private
- freshness: live GRAS observations need a recent check and complete model,
  CSC, sales-code, Android-version, OMC-revision, and OMC-version scope;
  firmware observations need a real release date, not merely a recent import
  date

## Merge Rules

Sources are observations, not public carrier identities.

- One broad profile owns each MCC/MNC.
- SPN, GID, ICCID-prefix, IMSI-prefix, and Android carrier-ID profiles remain
  separate when they are genuinely more specific.
- Agreement strengthens a fact.
- Conflicting CarrierConfig and add-on values are omitted from stable output
  and reported in `generated/evidence-index.json`.
- APN rows with the same applicability selector but different operational
  values are omitted instead of publishing several indistinguishable choices.
- Conflicting capabilities become `conditional`.
- Lower-confidence generic APNs require corroboration or a primary maintained
  APN source.
- Source names never become duplicate public carrier profiles.
- `fact_sources` in the evidence index shows which source family supports each
  exported fact; a profile-wide source list is not treated as proof for every
  field.

## Suggest A Source

Use the maintained-source issue form:

https://github.com/open-carrier-data/open-carrier-data/issues/new/choose

A useful source must be refreshable by automation, have a clear carrier-data
scope, and be safe to translate without publishing private material.
