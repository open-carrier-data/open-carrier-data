# Compatibility

This page says which parts of Open Carrier Data's files a consumer may rely on across releases, and how a change that breaks them is announced (rule decisions of 2026-10-18, round 20). [releases.md](releases.md) describes the releases themselves.

**The policy starts with the first release.** No release exists yet, and no file is supported today. Changes made before the first release stay history: no `schema_version` is bumped for them after the fact.

## What is stable

Only the files a release carries, from the release on, and only what is listed here:

| File | What is stable |
| --- | --- |
| `generated/android/apns-conf.xml` | It is valid against LineageOS's unchanged `apns-conf.xsd` (`tools/lineageos/apns-conf.xsd`); `<apns version>` equals `target.apn_database_version` in `metadata.json`; the comment it starts with carries the licence (`SPDX-License-Identifier: CC0-1.0`), `data_digest`, `checks_through` and `stale_after` lines. |
| `generated/android/lookup.json` | The fields `schemas/android-lookup.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them in the same tag. |
| `generated/android/metadata.json` | The fields `schemas/android-metadata.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them in the same tag. |
| `generated/devices/carrier-variants.json` | The fields `schemas/carrier-variants.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them in the same tag. It is information, never an export. |

Each JSON file carries `schema_version`. The `validate` check runs `tools/validate_public_carrier_data.py`, which checks `lookup.json` and `metadata.json` against their schemas with standard-library code, and `tools/validate_carrier_variants.py`, which checks the device records' fields in code.

A schema's `$id` is the raw URL of the file on `main`. It is an identifier, not a pin: the schema that describes a release's files is the one under `schemas/` in that release's tag. Validate a file against the schema of the same tag. A schema refuses fields it does not list, so a reader that validates against an older tag's schema refuses a newer file's additions; a reader that does not validate should ignore fields it does not know.

## What is not part of the contract

- **Values, rows and their order.** Which APN leads a scope, the values of a capability or a CarrierConfig key, the rows and the profiles are data. They change with every publish, and a release's notes list the changes.
- **`profile_id`.** It is `open.<mccmnc>.` and the first 12 hex digits of a SHA-256 over the profile's match set (`canonical_profile_id` in `tools/validate_public_carrier_data.py`). It changes whenever the match set changes, for example when a source splits a network by GID1 or drops an SPN selector, and that is not a breaking change. Keying stored results by `match` instead adds nothing, because the ID is a hash of it. **Key what you store by the SIM's own facts** (MCC and MNC, SPN, GID1, GID2, IMSI, ICCID prefix, Android carrier ID) **and the release tag**, and resolve them again against each new release. The release notes list the profile IDs added and removed; there is no old-to-new map.
- **Counts**, such as the number of profiles, rows or blocks.
- **Reference files**: `carriers/open/`, `generated/index.json`, `generated/evidence-index.json`, `generated/android/carrier-config-list.xml` and the files under `generated/devices/` other than `carrier-variants.json`. They are in every tagged tree, and their `schema_version` is still bumped when they break, but with no notice period.
- **`main` between releases.** It is the edge channel and carries no contract.

## Additive changes

These may come at any release and are listed in its notes:

- a new optional field;
- a new file;
- new rows, profiles, keys or values within a field's existing domain.

## Breaking changes

A change is breaking when it does any of these to a file a release carries:

- removes or renames the file, or one of its fields;
- changes a field's type, meaning or value domain, a new enum value included;
- changes match semantics or resolution order;
- changes the APN database version of `apns-conf.xml`, or removes one of its header lines;
- moves the file to a lower tier.

A breaking change ships only like this:

1. **One release's notice.** It is announced in the notes of an earlier release, at least 28 days before the release that carries it, and listed below under "Announced changes" by the pull request that announces it.
2. It merges to `main` only after that earlier release was cut.
3. **A `schema_version` bump.** A JSON file bumps its `schema_version`, and its schema changes in the same pull request. For `apns-conf.xml`, `release.json` names the APN database version, and the notes name the change.

The only exceptions are a privacy fix (rule 3) and a fix for a regression that breaks phones, which ship in a fix release `data-YYYY.MM.N` whose notes give the reason.

## Announced changes

None.
