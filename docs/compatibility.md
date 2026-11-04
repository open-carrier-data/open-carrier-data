# Compatibility

This page says which parts of Open Carrier Data's files a consumer may rely on across commits of `main`, and how a change that breaks them is marked (rule decisions of 2026-10-18, round 20, and 2026-11-04, round 46). [releases.md](releases.md) describes the one channel.

**The policy started with [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10)**, published on 2026-10-19. Changes made before it stay history: no `schema_version` is bumped for them after the fact.

## What is stable

Only the files listed here, and only what is listed for them:

| File | What is stable |
| --- | --- |
| `generated/android/apns-conf.xml` | It is valid against LineageOS's unchanged `apns-conf.xsd` (`tools/lineageos/apns-conf.xsd`); `<apns version>` equals `target.apn_database_version` in `metadata.json`; the comment it starts with carries the licence (`SPDX-License-Identifier: CC0-1.0`), `data_digest`, `checks_through` and `stale_after` lines. |
| `generated/android/lookup.json` | The fields `schemas/android-lookup.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them at the same commit. |
| `generated/android/metadata.json` | The fields `schemas/android-metadata.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them at the same commit. |
| `generated/devices/carrier-variants.json` | The fields `schemas/carrier-variants.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them at the same commit. It is information, never an export. |

Each JSON file carries `schema_version`. The `validate` check runs `tools/validate_public_carrier_data.py`, which checks `lookup.json` and `metadata.json` against their schemas with standard-library code, and `tools/validate_carrier_variants.py`, which checks the device records' fields in code.

**Profile IDs are kept** (rule round 45, item 1). A `profile_id` is `open.<mccmnc>.<12 hex>`. It is assigned once, when its match set first appears, as the first 12 hex digits of a SHA-256 over that match set (`hash_id` in `tools/profile_ids.py`), and from then on it is kept: it is not recomputed when the match set changes. It stays with the profile while the profile covers exactly the same SIMs (the match set written differently: list order, duplicates or letter case), or across a change that a continuity entry computed by `tools/profile_ids.py` and accepted by a reviewer allows; `aliases/ids.json` lists such IDs under `continued`. Any other change of a profile's SIMs, and every split or merge, gives a new ID and retires the old one. A retired ID is never given to other SIMs. It gets an entry in `aliases/ids.json` ([schema](../schemas/profile-id-aliases.schema.json)) of kind `replaced`, `split`, `merge` or `withdrawn`, naming the profile or profiles a SIM of its old rule matches in the data it was retired in; entries are only ever added. Follow an alias to update a link or a saved report, never to carry a value over: the new profile may describe other SIMs. Each publish's pull request lists every kept ID whose match set changed and every new alias entry. Which profiles exist, and their values, stay data. A new match set whose hash equals a live or retired ID is hashed again with a counter, so every ID keeps the `open.<mccmnc>.<12 hex>` form.

A schema's `$id` is the raw URL of the file on `main`. It is an identifier, not a pin: the schema that describes a file is the one under `schemas/` at the file's commit. Validate a file against the schema of the same commit. A schema refuses fields it does not list, so a reader that validates against an older commit's schema refuses a newer file's additions; a reader that does not validate should ignore fields it does not know.

## What is not part of the contract

- **Values, rows and their order.** Which APN leads a scope, the values of a capability or a CarrierConfig key, the rows and the profiles are data. They change with every publish, with no notice. `tools/check_phone_guard.py`, `tools/diff_apns_conf.py` and `tools/diff_carrier_config.py` show the changes between any two commits.
- **Which profile a SIM gets.** Profiles are added, split, merged and retired with the sources. Even with kept IDs, **key what you store by the SIM's own facts** (MCC and MNC, SPN, GID1, GID2, IMSI, ICCID prefix, Android carrier ID) **and the commit**, and resolve them again against each new pin: a kept ID can cover other SIMs after an accepted continuity entry, and a retired ID's alias names where its SIMs go, not that the values went with them. Until round 45 (2026-10-31) a profile ID was the hash of its current match set and changed with it; IDs retired before then have no alias entry.
- **Counts**, such as the number of profiles, rows or blocks.
- **Reference files**: `carriers/open/`, `generated/index.json`, `generated/evidence-index.json`, `generated/android/carrier-config-list.xml` and the files under `generated/devices/` other than `carrier-variants.json`. Their `schema_version` is still bumped when they break.
- **When a change comes.** `main` has no waiting period and no notice period ([releases.md](releases.md#main-has-no-waiting-period)). Pin a commit, and read [changelog.md](changelog.md) before you move.

## Additive changes

These may come with any commit, and get no changelog entry:

- a new optional field;
- a new file;
- new rows, profiles, keys or values within a field's existing domain.

## Breaking changes

A change is breaking when it does any of these to a file listed above:

- removes or renames the file, or one of its fields;
- changes a field's type, meaning or value domain, a new enum value included;
- changes match semantics or resolution order;
- changes the APN database version of `apns-conf.xml`, or removes one of its header lines;
- moves the file to a lower tier.

A breaking change merges to `main` only like this:

1. **Every OCD reader in use accepts it first.** For a new `schema_version` major those are the app's two `KNOWN_SCHEMAS` maps, OcdCarrierSettings and the S20's `ocd-pin-main.py`. F3 refuses a whole pull on an unknown major, so a phone would silently stay on old data while `main` moves on.
2. **A `schema_version` bump.** A JSON file bumps its `schema_version`, and its schema changes in the same pull request.
3. **A changelog entry.** [changelog.md](changelog.md) gets one entry for each `schema_version` bump or meaning change. A change of the APN database version or a removed header line of `apns-conf.xml` has no `schema_version`, so its entry is what marks it.

There is no notice period. Your reader refuses a major it does not know, and that is the signal to read the changelog.
