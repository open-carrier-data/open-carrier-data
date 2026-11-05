# Changelog

This page is written by hand. It has one entry per `schema_version` bump or meaning change, and one bad-data entry whenever a published commit is found harmful (rule round 46). A meaning change includes a change of the APN database version and a removed header line in a generated file. Read it before you move a pin ([releases.md](releases.md)).

For what changed in the data itself, read the publish pull requests, `tools/check_phone_guard.py`, `tools/diff_apns_conf.py` and `tools/diff_carrier_config.py` between any two commits.

## Format and meaning changes

### 2026-11-05: `metadata.json` has `relay_open`, and `data_digest` covers the flag

`generated/android/metadata.json` has a new field, `relay_open`, a JSON boolean copied from `community/relay.json`. OCD Android reads the flag there, and until now no tool wrote it. `data_digest` also covers `community/relay.json` now, so a flip reaches phones like any new data. The flag stays false. `schema_version` stays 1, and no value, row or match changes. See [data model](data-model.md).

### 2026-11-05: a report may name a plan, and a doubtful plan reads `unknown`

The plan picker opens for tapped reports (rule round 51, item 4). OCD Android now reads `generated/operators/offers.json` and `generated/operators/sim-groups.json` for the picker only, and no carrier settings component reads them. The report bot no longer refuses a well-formed plan: one that is not on the list, was not live on the test date or whose brand is not on the profile reads `unknown`, and the report is kept. No automatic report names a plan. See [community/README.md](../community/README.md#the-plan).

### 2026-11-05: new file `generated/operators/offers.json`

Dated offers with feature states (migration step 8, rule round 47, item 4). A new file for people: no existing file, value or match changes. The report bot's refusal of a named plan now gives round 48's reason. See [data model](data-model.md#offers).

### 2026-11-05: new file `generated/operators/plan-families.json`

Plan families the SIM shows, as labels over existing profiles (migration step 7, rule round 47, item 4). A new file for people: no existing file, value or match changes. See [data model](data-model.md#plan-families).

### 2026-11-05: new file `generated/operators/sim-groups.json`

Brands per SIM group and whether a phone can tell them apart (migration step 6, rule round 47, item 4). A new file for people: no existing file, value or match changes. See [data model](data-model.md#brands-per-sim-group).

### 2026-11-05: new file `generated/operators/entities.json`

Networks, operators and brands (migration step 5, rule round 47, item 4). A new file for people: no existing file, value or match changes. See [data model](data-model.md#networks-operators-and-brands).

### 2026-11-04: `lookup.json` `schema_version` 2 (`fdf77267`, #369)

The documented resolution order changes from the number of selectors a profile uses (`specificity`, then `profile_id`) to the order OcdCarrierSettings and the OCD Android app already use (rule round 45, item 3):

1. Android's weight, the score Android's `CarrierResolver` gives the fields a profile pins (MCC/MNC 256, IMSI prefix 128, ICCID prefix 64, GID1 32, GID2 16, SPN 2), a carrier-ID selector adding the fields of Android's rules behind the ID on that network and ranking above a raw profile of equal weight;
2. the longer prefix or more fixed digits (IMSI, ICCID, GID1, GID2);
3. an OCD profile above a fill-only one;
4. fewer list values;
5. fewer network codes;
6. `profile_id`, which a checker keeps from deciding between profiles whose served values differ.

Matching itself does not change, and nothing else in the file changes. `tools/resolve_carrier_profiles.py` defaults to this order, and `--order count` keeps the old one. The order is written out in [ocd-dataset.md](ocd-dataset.md#profiles), and `tests/vectors/resolution-order.json` has golden vectors.

Every OCD reader in use accepted 2 before this merged: the app's two `KNOWN_SCHEMAS` maps and the S20's pin step. The ROM does not read `lookup.json`, and OcdCarrierSettings sorts in this order itself since `carriersettings/v1.1.0`. This file's earlier announcement promised a wait for `data-2026.11` and a release 28 days later; round 46 withdrew both.

### 2026-11-04: `carrier-config-list.xml` says in its header that it is not for ROM application (rule round 46)

A line is added to the file's header comment. The file's tier does not change, and it was never for ROM application.

## Bad data

An entry here names the commit range and the reason. If you baked a commit in a range listed here, build again from a later one. Nothing is listed so far.

## Promises withdrawn on 2026-11-04 (rule round 46)

`main` became the one channel. These promises no longer hold:

- at most one release a month, and releases as the production channel;
- `data-2026.11` and everything planned for it: tier `supported` in `release.json`, Samsung's emergency role coming with it, the notice of the new resolution order, "must merge only after `data-2026.11`", and "first release at least 28 days after `data-2026.11`";
- the 72-hour age of a candidate;
- fix releases, `data-YYYY.MM.N`;
- a breaking change only at a release, with 28 days' notice;
- `stale_after` at least 30 days away at a cut;
- the guarantees "Guarded" and "Changes are visible" as promises of a release;
- "Releases keep their draft read" in SM6.

These stay:

- A tag never moves or goes away.
- `data-2026.10`'s files stay byte-fixed and reproducible.
- Do not ship after `stale_after`.

What each gate of a release became:

| Gate of a release | Now |
| --- | --- |
| The 72-hour age gate | **Nothing.** Recovery is a fix-forward commit, the previous pin (F1), the last good set (F3), the tests a change makes due (F4) and SM7 |
| The owner's read of the draft | the F5 chain, the group A reads, the phone guard and `publish-held`. The class (a) list and the selector-change list stay in every publish body. Other values get no human read |
| The phone guard from the previous release | the consumer runs `tools/check_phone_guard.py` and the F5 walk from its old pin to its new one. The second judgment of an accepted trip ended, with no replacement |
| Freshness at a cut | the daily strict alarm, the `stale-data` issue, and the date check of a pin step |
| Regeneration, `xmllint`, APN database version 8, digest agreement | already in `validate` |
| `SHA256SUMS` and byte copies | F1, the git blob SHAs in `pin.json`, `data_digest` and `manifest.json` |
| The fixed tag | the commit SHA, under `main`'s protection |
| Release notes | publish bodies, this page, and `tools/check_phone_guard.py`, `tools/diff_apns_conf.py` and `tools/diff_carrier_config.py` between any two commits |
| The 28-day notice | `schema_version`, F3, this page, and the rule that readers accept a new major first ([compatibility.md](compatibility.md#breaking-changes)) |
| The "Withdrawn:" mark | a bad-data entry on this page |

[releases.md](releases.md#main-has-no-waiting-period) says what a consumer does before moving a pin.
