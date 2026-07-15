# Open Carrier Data

<p align="center">
  <img src="https://open-carrier-data.github.io/assets/icon-192.png" alt="Open Carrier Data icon" width="96" height="96">
</p>

Open Carrier Data is a public database of mobile carrier settings for
open-source phone systems.

It stores carrier facts in a neutral JSON format and generates Android-ready
files from them. ROMs, carrier configuration apps, eSIM tools, and build
systems can package those files locally so phones have better APN, MMS, IMS,
RCS, eSIM, and CarrierConfig data without every project maintaining the same
fixes alone.

## Start Here

- Documentation: https://open-carrier-data.github.io/
- Report missing or wrong data: https://github.com/open-carrier-data/open-carrier-data/issues/new/choose
- Contribution guide: `CONTRIBUTING.md`
- Stable snapshot: `generated/index.json`
- Source revisions and merge evidence: `generated/evidence-index.json`
- Device and carrier-artifact coverage: `generated/devices/index.json`
- Android output: `generated/android/`
- Data schema: `schemas/carrier-profile.schema.json`
- Community claims: `community/`

If you only want to use the database, start with `generated/index.json` or
`generated/android/`.

If something is missing or wrong, open a guided issue. You do not need write
access to this repository.

## The Simple Idea

Carrier settings are small, but they matter. A wrong setting can break mobile
data, MMS, VoLTE, Wi-Fi Calling, roaming, call forwarding, or carrier
identification.

Open Carrier Data keeps those settings in one public place:

```text
maintained sources
-> neutral carrier profiles
-> generated snapshots and Android files
-> ROMs/apps/build tools package the data locally
-> phones read local data at runtime
```

This project is not a live cloud service for phones. A phone should not need to
call GitHub while loading a SIM, starting a call, sending MMS, registering IMS,
or handling emergency service.

## What Is In This Repo

```text
carriers/                 public neutral carrier profiles
community/                public community claims
generated/index.json      stable generated snapshot
generated/evidence-index.json exact source revisions and resolution evidence
generated/android/        generated Android APN, CarrierConfig, and lookup data
generated/devices/        device discovery and carrier-artifact coverage
generated/community/      generated index of valid community claims
generated/candidate/      generated index of testable community claims
schemas/                  JSON schemas
tools/                    validators, generators, and tests
```

The neutral profiles in `carriers/` are the source data. Files under
`generated/` are produced from that source data and should be regenerated when
profiles or claims change.

## Stable Data And Community Claims

The stable database is built from maintained sources. Examples are public
Android data, public APN databases, and sanitized facts imported from maintained
vendor data.

Stable data is not a dump of every file we have ever seen. Private vendor or
OEM snapshots must be refreshed and carry a recent checked date before they can
feed stable output. Private vendor/OEM checks older than about six months are
treated as stale. If a source cannot be refreshed anymore, missing data is
better than stale data that looks current.

Community input is handled separately as claims:

- a claim says what should change;
- it includes evidence and a test date;
- the validator calculates an expiry date from its risk;
- it is validated and indexed;
- it does not silently become default phone behavior.

This gives the project two useful layers:

```text
generated/index.json              stable maintained-source snapshot
generated/community/index.json    valid non-expired community claims
generated/candidate/index.json    claims that are suitable for opt-in testing
```

Stable data is conservative. Community claims are faster and useful for edge
cases, but downstream projects must choose whether to use them.

The validator, not the claim author, calculates confidence, risk, expiry,
overlap, and conflicts with stable data. A contributor cannot mark their own
claim verified. Expired claims stay out of generated indexes without blocking
the rest of the database.

## Where The Data Comes From

The current stable snapshot combines maintained AOSP, LineageOS, Mobile
Broadband Provider Info, Apple carrier-bundle, Google Pixel CarrierSettings,
Samsung OMC, and scoped Samsung IMS capability observations.
Each source is translated into the same neutral profile model.

Device discovery is tracked separately. The broad Android inventory comes from
Google's current public Google Play supported-device list. Current Pixel
CarrierSettings codenames add a second source-derived inventory and exact
extraction receipts. Samsung firmware discovery records each inventory identity
and its progress. Apple product types and carrier artifacts come directly from
Apple's official carrier index. This separate catalog makes gaps visible
without turning a device name into a carrier setting.

`generated/evidence-index.json` records:

- exact Git revisions or source-content hashes and their revision dates;
- when automation last checked each public upstream, even if its revision did
  not change;
- declared source terms;
- which source families support each exact capability, CarrierConfig key,
  add-on, and APN fact;
- Samsung model, firmware build/region, OMC, sales-code, and revision scope
  when safely publishable;
- Google Pixel device codenames, Android version, firmware build, and whether
  the observation came from a firmware baseline or a newer network delta;
- compact model-source overrides when a model was named by fewer source
  families than its merged carrier profile as a whole;
- conflicts and quality gates that caused a value to become conditional or be
  omitted.

Maintained source checks older than 180 days fail validation. Private vendor
observations also need a recent checked date. Read `SOURCES.md` for the exact
source and merge policy.

## Device Coverage Does Not Mean Device Support

`generated/devices/` keeps several claims separate:

- `present` means a maintained source currently lists the device identity;
- `historical` means the identity was listed before but is absent now;
- `carrier_observations` means current carrier evidence named a model or device
  code that a maintained artifact/discovery source uniquely binds to the stable
  `device_id`; `matched_identifiers` contains that exact ID;
- an Apple `product_family` artifact match means Apple's current index has
  carrier artifacts for that family, not that every carrier feature was tested
  on every model;
- `indexed` means an artifact and digest are in the current official index;
- `verified` also means automation downloaded the package and matched the
  indexed digest;
- Android `extracted` means automation obtained and integrity-checked the
  device-scoped carrier source;
- `source_discovery_in_progress` means scheduled vendor checks still have
  model/region work left;
- `source_not_queryable` means the maintained inventory has the identity but
  does not provide the identifier needed by that vendor update service;
- `source_checked_no_artifact` means the configured vendor scope was checked
  completely without finding a current artifact;
- `carrier_data_not_applicable` is reserved for explicitly classified
  non-cellular Apple product families or exact Android variants backed by an
  official connectivity source, and is not an extraction claim;
- `platform_out_of_scope` identifies an exact inventory record, such as a
  ChromeOS or emulator target, that is outside this Android phone/watch carrier
  extraction system; it does not claim that the hardware lacks cellular radio;
- `source_terms_restrict_extraction` means an exact official firmware source is
  known but its published terms do not permit this project to inspect it for
  carrier data. It is not a claim that the device lacks cellular support.

Failed downloads and digest mismatches are quarantined. They are counted in the
small coverage summary but are not published as usable artifacts or imported
as carrier facts.

## If A Carrier Is Missing Or Wrong

Use the path that matches what you know:

1. If you only know that something is broken, open a guided issue.
2. If you know a maintained source we should import, open a source suggestion.
3. If you tested a specific fix, open a tested-claim issue. Automation converts
   it into claim JSON, validates it, and opens a pull request.
4. If you are comfortable with Git, fork the repo, add a claim under
   `community/claims/`, and open a pull request.
5. If you want to improve schemas, validators, generated output, or docs, open
   a pull request.

Normal users do not need direct write access. Issues and fork-based pull
requests are the normal public contribution paths.

Useful reports include:

- carrier name and country;
- whether it is a main carrier, MVNO, or sub-brand;
- affected feature, such as data, MMS, VoLTE, Wi-Fi Calling, RCS, eSIM, or
  call forwarding;
- what happened;
- what you expected;
- public source links, if available;
- safe SIM matching details, such as MCC/MNC, SPN, GID1/GID2 prefix, or Android
  carrier ID;
- test date and device/OS, if you tested it yourself.

Never post phone numbers, account data, personal passwords, tokens, private
vendor credentials, full IMSI values, full ICCID values, IMEI, serial numbers,
raw logs, raw bugreports, raw firmware dumps, or private vendor responses.
Public APN usernames or passwords are allowed only when they are carrier
settings from public docs or visible phone configuration, not private account
credentials.

## Public Profile Shape

A carrier profile can contain:

- match rules, such as MCC/MNC, Android carrier ID, SPN, GID1/GID2 prefixes,
  ICCID prefixes, and safe IMSI prefix patterns;
- capabilities, such as MMS, VoLTE, Wi-Fi Calling, VoNR, RCS, eSIM, SMS over
  IMS, video calling, and conference support;
- Android APN rows for data, MMS, IMS, XCAP, emergency APN, and tethering;
- reviewed Android CarrierConfig overrides;
- optional neutral add-ons for facts that do not fit one Android key.

Profiles are carrier-centered, not source-centered. The public database should
say "this carrier has these settings", not "Samsung says this" or "Apple says
this". When several sources describe the same carrier, the public result should
be one neutral profile.

## Use The Data

Clone and validate:

```bash
git clone https://github.com/open-carrier-data/open-carrier-data.git
cd open-carrier-data
python3 tools/validate_public_carrier_data.py carriers generated/index.json
python3 tools/validate_device_catalog.py generated/devices
```

Main files for consumers:

```text
generated/index.json
generated/evidence-index.json
generated/android/apns-conf.xml
generated/android/lookup.json
generated/android/mccmnc-index.json
generated/android/carrier-id-index.json
generated/android/carrier-config-overrides.json
generated/android/carrier-config-list.xml
generated/devices/index.json
generated/devices/android.json
generated/devices/apple.json
generated/devices/android-carrier-artifacts.json
generated/devices/apple-carrier-artifacts.json
```

Within one match list, any value may match. Between different match fields,
every populated field must match. Resolve all matching profiles in
generic-to-specific order; a more specific profile is an overlay, not a reason
to ignore the generic profile. The generated indexes expose `specificity`, and
`tools/resolve_carrier_profiles.py` implements these rules.

Some match rules cannot be represented perfectly in every Android XML format.
Those details stay in JSON and lookup indexes instead of being broadened into
unsafe matches.

`generated/android/apns-conf.xml` currently targets APN database version 8.
Android requires this number to match the target build's internal APN version.
Use `--apn-version` when generating for a different target. Read
`generated/android/metadata.json` before packaging XML output; it records the
target version and every profile omitted because XML could not represent its
match safely.

## Validate Changes

For stable profile and generated-output checks:

```bash
python3 tools/validate_public_carrier_data.py carriers generated/index.json
python3 tools/test_generated_android_outputs.py
```

For community claims:

```bash
python3 tools/validate_community_claims.py community/claims generated/community
python3 tools/test_community_claims.py
python3 tools/test_issue_to_claim.py
python3 tools/test_resolve_carrier_profiles.py
```

To regenerate community indexes while working locally:

```bash
python3 tools/validate_community_claims.py --write-index
```

## What This Is Not

Open Carrier Data is not:

- a runtime phone cloud service;
- a replacement for Android telephony APIs;
- a place to publish raw vendor files or private logs;
- a manual list where any valid JSON automatically becomes stable data;
- a guarantee that every carrier feature works on every device.

It is shared source data and generated output that downstream projects can
package, test, and ship through their own normal update process.

## License And Source Terms

Project software and documentation are Apache-2.0. The project's own rights in
the neutral data compilation are waived under CC0, but upstream terms still
apply. AOSP, LineageOS, and Mobile Broadband Provider Info have clear reusable
terms. Apple declares no license, and this project does not assert a Google
CarrierSettings or Samsung license; only narrow transformed facts are published
from those sources.

Read `DATA-LICENSE.md`, `SOURCES.md`, and the source snapshots in
`generated/evidence-index.json` before redistribution.
