# Community reports

A community report is what a phone measured, uploaded by its owner. Today there is one kind: the test report of the OCD Check app's owner build. It is an **unverified hint**:

- it never changes an OCD value, a file under `carriers/` or `generated/`, or a release;
- it never makes a phone skip its own test, and it never switches anything off;
- at most it makes a phone test the entry it points at earlier than its normal rotation. The phone then keeps the entry only if it passes there.

No gate can tell a true report from a well-made fake: anyone can open an issue, nothing checks who sent a report or whether the phone exists, and no carrier signal can prove to a third party that a setting worked. So OCD does not ask "is this report true?". A report can only point, and every phone proves for itself.

The owner's own phones are the one exception (rule round 30, item 4; round 29 fired O1 of round 18): the OCD Check owner build submits its settled results as **measured records**, which enter `devices/records/measured.json` and from there `generated/devices/device-records.json`, with a 90-day expiry. They are served only on the owner's phones of the same device, ROM line and IMS stack, and they never change OCD's configured carrier values ([The owner's measured records](#the-owners-measured-records)). Round 29's `observed/retested.json` is folded into them.

## A report points, it carries no value

A report names entries of the closed list of OCD's data at one commit, each with the result the phone measured:

| Entry | Meaning |
|---|---|
| `volte:on`, `volte:off` | the VoLTE switch on or off; the same for `vowifi`, `sms_over_ims`, `video_calling` and `vonr` |
| `apn:<row key>` | one APN row of that data's `apns-conf.xml` for the SIM's network: the APN in lower case, its types in lower case and sorted, its protocol, for example `apn:web.vodafone.de\|default,supl\|IPV4V6` |

Anything else fails the schema: no APN string, no CarrierConfig key, no safety-class entry (emergency, e911, ECBM, WPS, TTY, RTT, `iwlan.*`) and no emergency APN row. Since rule round 29 (S13) the app names the commit of OCD's `main` it read its data at, the validated commit it pinned or the commit its bundled snapshot was built from, with that commit's data digest. The bot checks that the commit is in `main`'s history (GitHub also serves a fork's or an unmerged branch's commit by its SHA) and carries that data digest, that the OCD profile is in it, and that every `apn:` row key is a row it has for the SIM's network. Reports of app builds before round 29 name a data release instead: its tag and data digest, or a bundled snapshot found by its digest. They are still taken. So no report can bring a new value onto any phone.

The report follows [`schemas/ocd-check-report.schema.json`](../schemas/ocd-check-report.schema.json) (`"schema": "ocd-check-test-report"`, `"schema_version": 1`). Besides the entries it holds the app version, the test date (a date, never a time), the data commit (or release) and its data digest, the phone (model, codename `Build.DEVICE`, Android major version, ROM family, build type, IMS stack), the SIM (network code, and when known the Android carrier ID, the SPN and the GID1 prefix of the OCD profile it matched, never the SIM's whole GID1) and the OCD profile it matched. The IMS stack is the IMS service the phone runs: `phh_ims` for PHH IMS, `samsung_ims` for Samsung's own, `aosp_imsstack` for Google's AOSP ImsStack (`com.android.imsstack`, which the S20 on LineageOS 24.0 runs), `other` for any other, and `not_known` when the app cannot read it. Per entry it says whether it is OCD's value for this phone and SIM (`ocd`), the phone's own value (`phone`), whether it was `observed` or `tested`, the calls measured with their call network type, and whether the app kept it.

The **result** of an entry is one of:

| Result | Meaning |
|---|---|
| `works` | `volte:on` or `vowifi:on` signed in and passed the T2 call test (an outgoing and an incoming call on its bearer, audio confirmed); an off entry of a voice feature took effect and a call went active with it; mobile data validated with an APN row |
| `signed_in` | an on entry registered IMS with the feature's service on its bearer; no call test |
| `service_off` | an off entry took effect: the service went; no call measured |
| `not_possible` | an on entry cannot be on here: the modem, the IMS stack, the network's offer |
| `failed` | the entry was measured and did not work, or the test broke something (the reason says which) |
| `not_tested` | no result, with the reason |

Since rule round 29 a result of `volte:on`, `vowifi:on` or `sms_over_ims:on` can also carry **`settled`**: the owner build's settled result under rounds 26 to 28, with the evidence behind it. The report then also names the data commit and the ROM build (`device.build`: `Build.ID` and the build's UTC time in seconds, for example `CP2A.260605.016 1792814506`; never the fingerprint, the incremental or the builder's user or host).

| `settled` field | Meaning |
|---|---|
| `level` | `l2` calls out: a measured outgoing call on the entry's bearer (audio from packet counts), incoming not tested; `l3` works: also an answered incoming call on the same bearer. With `result` `failed`, the rung of the clean measured failure (`l2` the outgoing call, `l3` the incoming call). SMS over IMS settles only as `l3`, SMS both ways: sent and received over IMS |
| `bearer` | `lte` for `volte:on`, `iwlan` for `vowifi:on`; for SMS over IMS the IMS bearer when known |
| `method` | `mailbox_call` (the app's own muted call to the SIM's mailbox), `real_call` (one of the owner's own calls, measured passively), both legs for `l3` (`mailbox_call+real_call`, `real_call+real_call`), or `self_sms` (the data SMS to the phone's own number) |
| `measured_on` | the UTC date the level was reached, from the phone's call ledger on the same ROM build: at most 90 days before `tested_on`, possibly after it, never in the future |

The bot checks it against rounds 26 to 28: `l3` is the result `works` with both legs (and the T2 call on the bearer), `l2` is `signed_in` with one leg, a failure is clean (measured, the phone's state came back) and names the one call that failed, SMS both ways is `works` by `self_sms`, and a settled result needs the data commit and the ROM build. A settled field from any account but the owner's changes nothing: the report stays "reported, not checked by OCD".

A report holds no IMSI, ICCID, IMEI, phone number, SIP or tel URI, IP address, time of day, location or free text. Every value is a fixed code or has a fixed form.

## Upload a report

The app does it: its "Open report on GitHub" action opens the `OCD Check report` issue form with the report filled in, in the browser, and shows the report's hash. Read it and submit it yourself. Do not edit the report.

The owner build can also submit its settled reports itself (rule round 29). That needs a fine-grained GitHub token that the owner creates and enters on his phone: Issues read and write on this one repository and nothing else. The token is held only on the owner's phones, in credential-encrypted storage, and can be removed in the app or revoked on GitHub at any time. The app sends the same report, privacy-scanned, as an issue on the same form through GitHub's REST API, so the bot checks it the same way. Without a token the app only opens the prefilled form. The read-only builds never send anything. The OCD Check README describes the token.

The issue is public under your GitHub account, and public archives of GitHub can keep a copy after the issue is deleted.

## What happens to it

1. [`.github/workflows/ocd-check-report.yml`](../.github/workflows/ocd-check-report.yml) runs [`tools/observed_reports.py`](../tools/observed_reports.py) on the issue: the form's shape, the closed schema, a fail-closed privacy scan of every key and value and of the rest of the issue (the patterns of the app's own scan), consistency checks (for example, `works` on `volte:on` needs a passed T2 call on LTE), and the commit and release checks above.
2. The issue gets one label and one bot comment, updated on every edit, with the report's SHA-256 hash:
   - `report:valid`;
   - `report:suspect`: valid, but a plausibility check against the named data flags it (for example video calling that signed in on PHH IMS, which has no video, or an entry marked as OCD's value that the data does not give). It is held until a maintainer looks;
   - `report:invalid`: the comment lists exactly what is wrong. It names the field and the rule, never the value. Edit the issue to fix it, and the check runs again.
3. The bot rebuilds `observed/` from every report issue, once per issue event and once a day, and opens or updates one pull request, `automation/observed-reports`, titled "Observed reports (unverified)". It touches only these files:
   - `observed/reports/issue-N.json`: one file per valid report, as submitted, with its hash, the commit or release it points into (`release`), `"verification": "unverified"` and its status after the noise filters;
   - `observed/summary.json`: other accounts' reports per device × carrier profile × stack (ROM family, IMS stack, Android major) × entry, the statuses below;
   - `devices/records/measured.json`: the owner's measured records ([below](#the-owners-measured-records)), and from it `generated/devices/device-records.json` and the dataset manifest `generated/ocd-dataset/manifest.json` (`tools/ocd_dataset.py generate`).
4. A maintainer merges the pull request after `validate`, with the phone guard, passes. Merging accepts the files; it does not verify the results. The issues close with it.
5. When `devices/records/measured.json` changes on `main`, and once a day, the bot opens or updates one source-review issue per carrier profile and target whose measured record corrects OCD's value ([Source reviews](#source-reviews)).

A maintainer withdraws a report by closing its issue as **not planned**; the next rebuild drops its file. The label `report:hold-released` lifts a hold. The workflow can also be started by hand (`workflow_dispatch`).

## Statuses in observed/summary.json

| Status | Set by |
|---|---|
| `reported`: "reported, not checked by OCD" | counted reports of people's phones: how many, by result, the first and last report date, and the issues |
| `contested` | at least one counted report measured a clean failure of the entry: it was measured and did not work, and the phone's state came back. It asks the next phone to test the entry and a maintainer to look; it switches nothing off. A test that broke (a revert not proven) contests nothing |
| `retested_by_ocd` | always null here: the owner's phones' results are measured records in `generated/devices/device-records.json` (rule round 30) |

Each cell also gives `held`, the valid reports a noise filter holds. `summary.json` counts the reports of every account but the owner's.

## The owner's measured records

Rule round 30 (2026-10-25, item 4): corrections measured on the owner's phones become measured records in OCD's per-device records, `generated/devices/device-records.json`, which every validated `main` commit and the owner app's dataset carry ([docs/ocd-dataset.md](../docs/ocd-dataset.md)). The owner's account is named in `tools/observed_reports.py` by its GitHub user ID (`OWNER_ACCOUNTS`, 122638570), which a renamed or reclaimed login cannot take.

The owner build submits them in the same form, with a JSON document of its own:

```json
{"schema": "ocd-measured-records", "schema_version": 1,
 "app": {"name": "OCD Check", "build": "owner", "version": "0.4.0-owner"},
 "records": [{"record_key": "r:…", "kind": "measured", "…": "one record of schemas/device-records.schema.json ($defs.record)"}]}
```

The bot takes the records into `devices/records/measured.json` only when all of these hold:

- the issue's author is the owner's account; any other account's document is refused, and other reports stay pointers in `observed/`;
- every record passes the closed schema (`kind` `measured`, `tester` `owner`, the device, ROM line, IMS stack with its fork, the carrier profile or, for a SIM without one, MCC-MNC with GID1 or SPN), and its `record_key` recomputes;
- its value is a candidate at its data commit: OCD's resolved value or an alternative of the profile's stack, the Google lane's value of the profile's fill or of `default`, the other value of a switch, or Android's default (`value_kind` `android_default`); an APN record names a row of the profile; an emergency data record says only accepted, refused or Android's default won;
- its key is not group A (those enter only with a recorded second-agent read, through a reviewed pull request) and not group B (the metered lists, which records cannot change);
- the privacy scan passes: no phone number, IMSI, ICCID, IMEI, SIP URI or IP address;
- its data commit is on `main`, carries its data digest and holds the OCD dataset;
- `validate` and the phone guard pass on the bot's pull request.

One record per `record_key` is kept, the newest by its last measurement. A record lapses at `valid_until`, 90 days after its last measurement, and the daily rebuild drops it. Round 19's holds, account gates, time spread and thresholds apply only to outside reports. A measured record is served only on the owner's phones of its device, ROM line and IMS stack; other ROMs and apps may use it only under R3. It never changes a configured carrier value in `carriers/`: a correction opens a source review.

The owner's pointer reports (`ocd-check-test-report`, round 29) are still taken and kept in `observed/reports/` as pointers. They change nothing; round 29's `observed/retested.json` is gone.

## Source reviews

A configured value changes only through a review of its source and the normal data path (rule 10). So each measured record that **corrects** OCD's published value for its profile, names a **winner after a failure**, falls back to **Android's default**, or found **no value that passed** opens a review automatically. The `source-review` job of the same workflow runs when `devices/records/measured.json` changes on `main`, and daily:

- one issue per carrier profile (or SIM key) and target, labelled `source-review`, titled for example "[Source review] config:carrier_wfc_ims_available_bool for profile:open.26202.8cebd7550c67";
- its text lists every current record behind it, with the phone, software, the measured and the published value, method, n, dates, expiry and data commit, and says what to do: review the source or importer behind OCD's value, fix it there with the evidence in the pull request, or say that the cause is the phone, its IMS stack or the SIM's plan;
- the bot keeps the text current, never closes the issue and never edits an issue it did not open. After a maintainer closes it, the bot opens a new one only when the measured results change, not for a renewal of the same result.

The issue itself changes nothing.

## Noise filters

These order what people read and keep review time down. They are not a defence, and they are not proof:

- the closed schema and the privacy scan;
- a SHA-256 hash of the report text; a second issue with the same report is a `duplicate`;
- plausibility against the release (`report:suspect`);
- one counted report per account and cell: a newer one `supersedes` the older;
- at most 10 counted reports per account and month;
- an account's reports are `held` until its first accepted report here is 14 days old. The age counts from that report, not from the account's sign-up, because old accounts are easy to buy. The account names are read from the issues on each rebuild and never written to `observed/`;
- a report `expires` 90 days after its test.

The owner's account skips the account filters (the hold, the monthly cap and the supersede); the duplicate, the plausibility flag and the expiry apply to it as well ([The owner's measured records](#the-owners-measured-records)).

## Why it stays apart

OCD's values say what carrier tables configure, from maintained sources. A phone result is a different kind of evidence, kept beside the data, never in it:

- no pointer report changes a capability value, an APN row, a CarrierConfig key, a device record or a release asset; only the owner's measured records enter `generated/devices/device-records.json`, for the owner's phones;
- `observed/` is not part of a release and has no compatibility promise;
- counts are not votes: a `signed_in` from one phone says nothing about another phone, stack or plan;
- a ROM maintainer who uses a cell still makes his own test call; a phone that acts on a report still runs its own test and keeps nothing that fails.

Run the checks locally:

```bash
python3 tools/test_observed_reports.py
python3 tools/observed_reports.py validate --root .   # observed/reports/, summary.json and devices/records/measured.json
git fetch --no-tags --depth=1 origin '+refs/tags/data-*:refs/tags/data-*'
python3 tools/observed_reports.py check-file report.json   # one report as the app wrote it
```
