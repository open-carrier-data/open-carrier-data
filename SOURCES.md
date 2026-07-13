# Data Sources

Open Carrier Data combines carrier facts from maintained sources. It does not
publish raw vendor packages, credentials, signed URLs, device identifiers, or
private logs.

The exact public Git revisions or downloaded-content hashes used for the
current snapshot are recorded in:

```text
generated/evidence-index.json
```

Every public-source record contains two dates:

- `revision_date`: when the exact upstream commit or source revision was
  published;
- `checked_at`: when automation last fetched the source successfully.

Freshness uses `checked_at`, not `revision_date`. Unchanged source content can
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

- upstream used by automation: Apple's official carrier index at
  `itunes.apple.com/WebObjects/MZStore.woa/wa/com.apple.jingle.appserver.client.MZITunesClientCheck/version`
- data: current Apple product types, current carrier-bundle selections, and
  translated APN/MMS facts from verified IPCC packages
- upstream license: `NOASSERTION`; this project makes no license claim for
  Apple's bundle data
- verification: the index is fetched over HTTPS; every selected IPCC must
  match the SHA-1 or SHA-384 digest carried by that index before its facts are
  imported
- legacy transport: a current HTTPS index can still point to an old HTTP Apple
  CDN URL; that package is accepted only when its full digest matches
- public policy: raw Apple indexes, package URLs, package paths, selectors, and
  IPCC files are not republished; only sanitized facts and small safe artifact
  summaries are emitted
- failure policy: unavailable packages and digest mismatches are quarantined,
  excluded from carrier import, and retried by later scheduled runs
- update method: scheduled direct check recorded by full index SHA-256 and last
  successful check date; no third-party mirror is used

### Google Pixel CarrierSettings

- maintained snapshot source: the newest numeric Android branch in
  `GrapheneOS/adevtool`, which contains decoded CarrierSettings snapshots for
  current supported Pixel devices
- live update source: Google's per-device CarrierSettings update endpoint
- data: safe carrier match rules, APNs, reviewed CarrierConfig values, and
  feature observations
- upstream terms: the GrapheneOS tooling is MIT; this project makes no license
  claim for Google's CarrierSettings data
- public policy: raw textproto/protobuf files, endpoint responses, download
  URLs, and firmware material stay private; only narrow normalized facts and
  safe scope summaries are published
- update method: automation records the exact GrapheneOS revision, checks every
  Pixel device against Google's live endpoint, and applies a delta only when
  its internal version is newer than the firmware baseline
- device differences: conflicting Pixel variants remain separate source
  observations and become conditional or omitted during the neutral public
  merge; identical variants are grouped with their observed device codenames

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

### Samsung IMS capability evidence

- upstream: Samsung IMS carrier maps, service switches, and usable service
  profiles from versioned Samsung firmware
- data: positive, device-scoped VoLTE, Wi-Fi Calling, VoNR, video calling,
  SMS-over-IMS, and RCS capability observations
- public policy: raw Samsung IMS files and profile parameters remain private;
  public evidence includes only neutral carrier matches, capabilities, and a
  safe model/region/build scope summary
- freshness: automation checks Samsung's current firmware metadata for the
  exact model and region; a build mismatch triggers a narrowly scoped firmware
  download and minimal index rebuild, while a failed rebuild cannot relabel old
  observations as current
- negative rule: a false or absent Samsung switch is not published as proof
  that the carrier universally lacks a feature

## Device Inventories And Artifact Coverage

Device discovery is separate from carrier-profile resolution. An inventory
entry answers "which identity did this maintained source list?" It does not
answer "does VoLTE work on this device?"

### Android device inventory

- upstream: Google's public Google Play supported-device CSV at
  `storage.googleapis.com/play_public/supported_devices.csv`
- identity rule: Google defines a device model by retail brand plus device;
  model and marketing-name values are retained as aliases and variants
- scope: Google Play supported devices, not a claim that every row has cellular
  hardware and not a complete list of non-Google-Play Android devices
- history: identities removed from a later source revision remain available as
  `historical`; current aliases come only from the current revision
- update method: scheduled direct check recorded by full CSV SHA-256
- terms: `NOASSERTION`; only normalized factual identity fields are published

### Apple product and artifact inventory

- upstream: the same official Apple carrier index used for carrier-bundle
  import
- product identity: Apple's exact product-type strings
- artifact scope: exact product types where Apple publishes an override,
  otherwise product-family scope such as iPhone, iPad, or Watch
- verification states: `indexed` means the current official index lists the
  artifact and digest; `verified` additionally means the downloaded package
  matched that digest

### Exact carrier evidence

`generated/evidence-index.json` can contain an `observed_scope.models` list for
Samsung and Google CarrierSettings observations. The device catalog matches
those exact values against Android device codes and model aliases. It does not
guess from marketing names.

The coverage files live under `generated/devices/`. Failed artifact checks are
not included in the public artifact list.

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
