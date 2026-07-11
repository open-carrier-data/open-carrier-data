# Contributing To Open Carrier Data

Open Carrier Data is meant to be useful without asking contributors to know the
whole automation system first.

This guide explains what to do when carrier data is missing, wrong, stale, or
unclear.

## First Rule: Do Not Share Private Data

Do not post:

- phone numbers;
- account numbers or customer IDs;
- personal passwords, tokens, cookies, private URLs, or private vendor
  credentials;
- full IMSI values;
- full ICCID values;
- IMEI, serial numbers, Android ID, or other device identifiers;
- raw modem logs, raw bugreports, raw vendor responses, or raw firmware dumps.

Safe examples:

- carrier name;
- country;
- public plan or brand name;
- MCC/MNC, if known;
- Android carrier ID, if known;
- partial ICCID prefix only when it is already public or safely shortened;
- tested APN values from public carrier docs or phone settings;
- public APN username/password values when they are carrier settings, not
  private account credentials;
- feature result, such as "MMS receive works" or "Wi-Fi Calling menu is hidden".

If you are unsure whether something is private, do not include it. Open an
issue and describe the problem without that value.

## Which Path Should I Use?

### 1. I found missing or wrong carrier data

Open an issue:

```text
https://github.com/open-carrier-data/open-carrier-data/issues/new/choose
```

Use this when:

- a carrier is missing;
- mobile data, MMS, VoLTE, Wi-Fi Calling, RCS, eSIM, tethering, XCAP, or
  conference calling looks wrong;
- the generated Android files do not match a known-good source;
- you are not sure how to write a JSON claim.

Include:

- carrier name and country;
- whether this is a main carrier or MVNO/sub-brand;
- affected feature;
- what currently happens;
- what you expected to happen;
- device and OS, if you tested on a device;
- test date;
- public source link, if you have one;
- safe SIM matching details, such as MCC/MNC, SPN, GID1/GID2 prefix, or Android
  carrier ID.

### 2. I know a maintained source we should import

Open a source suggestion issue.

Good source suggestions are:

- maintained by a carrier, OEM, OS project, standards project, or public data
  project;
- refreshable by automation;
- narrow enough that we can extract public carrier facts;
- legal and safe to process privately when raw source material cannot be
  published.

Also include the source's license or usage terms when known. A source can be
current and still be unsuitable for redistribution.

Examples:

- public APN database;
- public Android CarrierConfig data;
- public carrier support page with APN/MMS settings;
- OEM carrier bundle source that can be handled privately and sanitized before
  publishing.

### 3. I have tested a specific fix

If you do not have write access to this repository, you still have two normal
ways to submit the claim:

- open a guided tested-claim issue;
- or fork the repository, add the claim file, and open a pull request.

Use the issue path if you do not want to edit JSON or use Git. Use the pull
request path if you are comfortable adding the claim file yourself.

For pull requests, add the claim under:

```text
community/claims/
```

A claim is a structured report. It does not silently become default phone
behavior. It is validated, indexed, and can be used for opt-in testing.

You provide the facts and evidence. The validator calculates risk, overlap with
stable profiles, conflicts, confidence, and the recommended channel. Do not add
your own `conflicts_with_stable` value or claim a `maintainer_review` evidence
type.

Use a claim when you can say:

- which carrier or MVNO it applies to;
- exactly what should change;
- how you tested it;
- when you tested it;
- when the claim should expire.

After adding or changing a claim, run:

```bash
python3 tools/validate_community_claims.py --write-index
python3 tools/validate_public_carrier_data.py carriers generated/index.json
```

If you use the issue path, include the same information in the issue form. A
maintainer or another contributor can later turn it into a JSON claim if it is
safe and useful.

### 4. I want to change stable carrier profiles

Do not directly edit stable generated output as a shortcut.

Stable data should normally come from maintained sources through importers and
the sanitizer. If a stable profile is wrong, open an issue first or update the
source/importer path that produced it.

Direct stable-profile changes may be accepted only when they are narrow,
reviewable, reproducible, and backed by a maintained source.

### 5. I want to improve tooling or docs

Open a pull request.

Good tooling and docs changes include:

- clearer documentation;
- schema improvements;
- validator improvements;
- generator fixes;
- importer improvements;
- tests for edge cases.

Run the relevant checks before submitting:

```bash
python3 tools/validate_community_claims.py community/claims generated/community
python3 tools/test_community_claims.py
python3 tools/validate_public_carrier_data.py carriers generated/index.json
python3 tools/test_generated_android_outputs.py
```

## What Happens After I Report Something?

The normal path is:

```text
issue or claim
-> discussion and evidence check
-> importer/source/schema/tooling fix if needed
-> generated output update
-> validation
-> downstream projects can sync a new snapshot
```

Community claims may also appear in:

```text
generated/community/index.json
generated/candidate/index.json
```

That does not mean they are stable defaults. It means they are structured data
that downstream projects can inspect or test.

When a claim expires, automation removes it from both generated indexes. The
claim file may remain as history, but consumers no longer see it as current.

## Good Reports Are Specific

Good report:

```text
Carrier: Example Mobile Germany
Type: MVNO
Feature: MMS
Problem: generated APN has no MMSC, MMS receive fails
Expected: MMSC should be https://mms.example/mmsc
Evidence: public carrier help page plus one device test on 2026-07-05
Safe match details: MCC/MNC 26299, SPN "Example"
```

Weak report:

```text
My SIM does not work. Please fix it.
```

The weak report may still be real, but it does not give enough information to
find the correct carrier entry without guessing.
