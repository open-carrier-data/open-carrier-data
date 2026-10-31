# Compatibility

This page says which parts of Open Carrier Data's files a consumer may rely on across releases, and how a change that breaks them is announced (rule decisions of 2026-10-18, round 20). [releases.md](releases.md) describes the releases themselves.

**The policy started with the first release**, [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10), published on 2026-10-19. Changes made before it stay history: no `schema_version` is bumped for them after the fact.

## What is stable

Only the files a release carries, from the release on, and only what is listed here:

| File | What is stable |
| --- | --- |
| `generated/android/apns-conf.xml` | It is valid against LineageOS's unchanged `apns-conf.xsd` (`tools/lineageos/apns-conf.xsd`); `<apns version>` equals `target.apn_database_version` in `metadata.json`; the comment it starts with carries the licence (`SPDX-License-Identifier: CC0-1.0`), `data_digest`, `checks_through` and `stale_after` lines. |
| `generated/android/lookup.json` | The fields `schemas/android-lookup.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them in the same tag. |
| `generated/android/metadata.json` | The fields `schemas/android-metadata.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them in the same tag. |
| `generated/devices/carrier-variants.json` | The fields `schemas/carrier-variants.schema.json` defines, with the meaning [data-model.md](data-model.md) gives them in the same tag. It is information, never an export. |

Each JSON file carries `schema_version`. The `validate` check runs `tools/validate_public_carrier_data.py`, which checks `lookup.json` and `metadata.json` against their schemas with standard-library code, and `tools/validate_carrier_variants.py`, which checks the device records' fields in code.

**Profile IDs are kept** (rule round 45, item 1). A `profile_id` is `open.<mccmnc>.<12 hex>`. It is assigned once, when its match set first appears, as the first 12 hex digits of a SHA-256 over that match set (`hash_id` in `tools/profile_ids.py`), and from then on it is kept: it is not recomputed when the match set changes. It stays with the profile while the profile covers exactly the same SIMs (the match set written differently: list order, duplicates or letter case), or across a change that a continuity entry computed by `tools/profile_ids.py` and accepted by a reviewer allows; `aliases/ids.json` lists such IDs under `continued`. Any other change of a profile's SIMs, and every split or merge, gives a new ID and retires the old one. A retired ID is never given to other SIMs. It gets an entry in `aliases/ids.json` ([schema](../schemas/profile-id-aliases.schema.json)) of kind `replaced`, `split`, `merge` or `withdrawn`, naming the profile or profiles a SIM of its old rule matches in the data it was retired in; entries are only ever added. Follow an alias to update a link or a saved report, never to carry a value over: the new profile may describe other SIMs. The release notes list every kept ID whose match set changed and every new alias entry. Which profiles exist, and their values, stay data. A new match set whose hash equals a live or retired ID is hashed again with a counter, so every ID keeps the `open.<mccmnc>.<12 hex>` form.

A schema's `$id` is the raw URL of the file on `main`. It is an identifier, not a pin: the schema that describes a release's files is the one under `schemas/` in that release's tag. Validate a file against the schema of the same tag. A schema refuses fields it does not list, so a reader that validates against an older tag's schema refuses a newer file's additions; a reader that does not validate should ignore fields it does not know.

## What is not part of the contract

- **Values, rows and their order.** Which APN leads a scope, the values of a capability or a CarrierConfig key, the rows and the profiles are data. They change with every publish, and a release's notes list the changes.
- **Which profile a SIM gets.** Profiles are added, split, merged and retired with the sources. Even with kept IDs, **key what you store by the SIM's own facts** (MCC and MNC, SPN, GID1, GID2, IMSI, ICCID prefix, Android carrier ID) **and the release tag**, and resolve them again against each new release: a kept ID can cover other SIMs after an accepted continuity entry, and a retired ID's alias names where its SIMs go, not that the values went with them. Until round 45 (2026-10-31) a profile ID was the hash of its current match set and changed with it; IDs retired before then have no alias entry.
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

- **`generated/android/lookup.json`: a new resolution order (rule round 45, item 3; announced in `data-2026.11`).** The documented order changes from the number of selectors a profile uses (`specificity`, then `profile_id`) to the order OcdCarrierSettings and the OCD Check app already use: (1) Android's weight, the score Android's `CarrierResolver` gives the fields a profile pins (MCC/MNC 256, IMSI prefix 128, ICCID prefix 64, GID1 32, GID2 16, SPN 2), a carrier-ID selector adding the fields of Android's rules behind the ID on that network and ranking above a raw profile of equal weight; (2) the longer prefix or more fixed digits (IMSI, ICCID, GID1, GID2); (3) an OCD profile above a fill-only one; (4) fewer list values; (5) fewer network codes; (6) `profile_id`, which a checker keeps from deciding between profiles whose served values differ. Matching itself does not change. It merges to `main` only after `data-2026.11` is cut, with `lookup.json` `schema_version` 2 and `tools/resolve_carrier_profiles.py` defaulting to it, and the first release that carries it comes at least 28 days after `data-2026.11`. To prepare: read each profile's `weight` (in `lookup.json` since this notice) and run `tools/resolve_carrier_profiles.py --order android`, or the golden vectors in `tests/vectors/resolution-order.json`; the order is written out in [ocd-dataset.md](ocd-dataset.md#profiles).
