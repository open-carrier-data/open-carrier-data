# Community reports

A community report is what a phone measured, sent by the person who holds it. There are two kinds, and they never mix:

- **The test report:** the person taps, reads it and submits it under their own GitHub login. Most of this page describes it.
- **The automatic week report:** after the person's one yes, a ROM install sends a closed weekly summary to OCD's relay. See [The automatic week report](#the-automatic-week-report). Sending is closed today.

Both are **unverified hints**:

- it never changes an OCD value, a file under `carriers/` or `generated/`, or a release;
- it never makes a phone skip its own test, and it never switches anything off;
- no result changes what another phone gets, from any account;
- at most it makes a phone test the entry it points at earlier than its normal rotation. The phone then keeps the entry only if it passes there.

No gate can tell a true report from a well-made fake: anyone can open an issue, nothing checks who sent a report or whether the phone exists, and no carrier signal can prove to a third party that a setting worked. So OCD does not ask "is this report true?". A report can only point, and every phone proves for itself.

There is no exception. Results reach OCD the same way for everyone, the project's owner included (rule rounds 47 and 48): by these two paths and no other. The app never holds a GitHub login, no key or token exists in the APK, nothing on a phone or the relay can write to GitHub, and no account or list gives a report a stronger status. Every test report reads "reported, not checked by OCD", with its date, a count of distinct accounts and whether it is contested.

## A report points, it carries no value

A report names entries of the closed list of OCD's data at one commit, each with the result the phone measured:

| Entry | Meaning |
|---|---|
| `volte:on`, `volte:off` | the VoLTE switch on or off; the same for `vowifi`, `sms_over_ims`, `video_calling` and `vonr` |
| `apn:<row key>` | one APN row of that data's `apns-conf.xml` for the SIM's network: the APN in lower case, its types in lower case and sorted, its protocol, for example `apn:web.vodafone.de\|default,supl\|IPV4V6` |

Anything else fails the schema: no APN string, no CarrierConfig key, no safety-class entry (emergency, e911, ECBM, WPS, TTY, RTT, `iwlan.*`) and no emergency APN row. Since rule round 29 (S13) the app names the commit of OCD's `main` it read its data at, the validated commit it pinned or the commit its bundled snapshot was built from, with that commit's data digest. The bot checks that the commit is in `main`'s history (GitHub also serves a fork's or an unmerged branch's commit by its SHA) and carries that data digest, that the OCD profile is in it, and that every `apn:` row key is a row it has for the SIM's network. Reports of app builds before round 29 name a data release instead: its tag and data digest, or a bundled snapshot found by its digest. They are still taken. So no report can bring a new value onto any phone.

The report follows [`schemas/ocd-check-report.schema.json`](../schemas/ocd-check-report.schema.json) (`"schema": "ocd-check-test-report"`, `"schema_version": 1`). Besides the entries it holds the app version, the test date (a date, never a time), the data commit (or release) and its data digest, the phone (model, codename `Build.DEVICE`, Android major version, ROM family, build type, IMS stack, and when known the ROM build), the SIM (network code, and when known the Android carrier ID, the SPN and the GID1 prefix of the OCD profile it matched, never the SIM's whole GID1) and the OCD profile it matched, and optionally the plan ([below](#the-plan)). The IMS stack is the IMS service the phone runs: `phh_ims` for PHH IMS, `samsung_ims` for Samsung's own, `aosp_imsstack` for Google's AOSP ImsStack (`com.android.imsstack`, which the S20 on LineageOS 24.0 runs), `other` for any other, and `not_known` when the app cannot read it. Per entry it says whether it is OCD's value for this phone and SIM (`ocd`), the phone's own value (`phone`), whether it was `observed` or `tested`, the calls measured with their call network type, and whether the app kept it.

The **result** of an entry is one of:

| Result | Meaning |
|---|---|
| `works` | `volte:on` or `vowifi:on` signed in and passed the T2 call test (an outgoing and an incoming call on its bearer, audio confirmed); an off entry of a voice feature took effect and a call went active with it; mobile data validated with an APN row |
| `signed_in` | an on entry registered IMS with the feature's service on its bearer; no call test |
| `service_off` | an off entry took effect: the service went; no call measured |
| `not_possible` | an on entry cannot be on here: the modem, the IMS stack, the network's offer |
| `failed` | the entry was measured and did not work, or the test broke something (the reason says which) |
| `not_tested` | no result, with the reason |

Since rule round 29 a result of `volte:on`, `vowifi:on` or `sms_over_ims:on` can also carry **`settled`**: the app's settled result under rounds 26 to 28, with the evidence behind it. The report then also names the data commit and the ROM build (`device.build`: `Build.ID` and the build's UTC time in seconds, for example `CP2A.260605.016 1792814506`; never the fingerprint, the incremental or the builder's user or host).

| `settled` field | Meaning |
|---|---|
| `level` | `l2` calls out: a measured outgoing call on the entry's bearer (audio from packet counts), incoming not tested; `l3` works: also an answered incoming call on the same bearer. With `result` `failed`, the rung of the clean measured failure (`l2` the outgoing call, `l3` the incoming call). SMS over IMS settles only as `l3`, SMS both ways: sent and received over IMS |
| `bearer` | `lte` for `volte:on`, `iwlan` for `vowifi:on`; for SMS over IMS the IMS bearer when known |
| `method` | `mailbox_call` (the call to the SIM's mailbox the person tapped), `real_call` (one of the person's own calls, measured passively), both legs for `l3` (`mailbox_call+real_call`, `real_call+real_call`), or `self_sms` (the data SMS to the phone's own number the person tapped) |
| `measured_on` | the UTC date the level was reached, from the phone's call ledger on the same ROM build: at most 90 days before `tested_on`, possibly after it, never in the future |

The bot checks it against rounds 26 to 28: `l3` is the result `works` with both legs (and the T2 call on the bearer), `l2` is `signed_in` with one leg, a failure is clean (measured, the phone's state came back) and names the one call that failed, SMS both ways is `works` by `self_sms`, and a settled result needs the data commit and the ROM build. A settled field changes nothing, from any account: the report stays "reported, not checked by OCD".

Only a real call or a tapped call can give `works` or a call level. No automatic call test exists, so a result from the app's background runs stops at `signed_in`, and registered IMS does not mean that calls work.

A report holds no IMSI, ICCID, IMEI, phone number, SIP or tel URI, IP address, time of day, location or free text. Every value is a fixed code or has a fixed form.

### The plan

Next to the report the app shows one picker, default `unknown`. `plan` is optional: `unknown`, or an object with `offer`, a closed offer ID from the carrier's published list, and `options`, the booked options from that list. A report without it reads as `unknown`. Until a carrier has an offer list, `unknown` is the only choice, and the bot refuses anything else. The plan comes only from the person's own choice: never free text, and never read from an account, USSD, carrier SMS or TS.43.

A plan is a label the person chose, not a fact about the tariff. It is never a matching key and feeds no carrier value or `for_you` answer. A result with a plan shows in `observed/results.json` and can only open a source review.

## Upload a report

The app does it, and only on your tap: its "Open report on GitHub" action opens the `OCD Android report` issue form with the report filled in, in your browser, and shows the report's hash. Read it and submit it yourself, under your own GitHub login, which the app never holds. Do not edit the report. Without a GitHub account you can read the report but not send it. A test report leaves the phone only when you submit it. The one other thing that can leave is the [automatic week report](#the-automatic-week-report), and only after your yes.

The issue is public under your GitHub account, so anyone can link your GitHub name to the carrier and any plan in the report. If you delete the issue, the report leaves `observed/` at the next rebuild, but older versions stay in git history, and public archives of GitHub can keep a copy.

## What happens to it

1. [`.github/workflows/ocd-check-report.yml`](../.github/workflows/ocd-check-report.yml) runs [`tools/observed_reports.py`](../tools/observed_reports.py) on the issue: the form's shape, the closed schema, a fail-closed privacy scan of every key and value and of the rest of the issue (the patterns of the app's own scan), consistency checks (for example, `works` on `volte:on` needs a passed T2 call on LTE), and the commit and release checks above.
2. The issue gets one label and one bot comment, updated on every edit, with the report's SHA-256 hash:
   - `report:valid`;
   - `report:suspect`: valid, but a plausibility check against the named data flags it (for example video calling that signed in on PHH IMS, which has no video, or an entry marked as OCD's value that the data does not give). It is held until a maintainer looks;
   - `report:invalid`: the comment lists exactly what is wrong. It names the field and the rule, never the value. Edit the issue to fix it, and the check runs again.
3. The bot rebuilds `observed/` from every report issue, once per issue event and once a day, and opens or updates one pull request, `automation/observed-reports`, titled "Observed reports (unverified)". It touches only `observed/`:
   - `observed/reports/issue-N.json`: one file per valid report, as submitted, with its hash, the commit or release it points into (`release`), `"verification": "unverified"` and its status after the noise filters;
   - `observed/summary.json`: every account's reports per device × carrier profile × stack (ROM family, IMS stack, Android major) × entry, the statuses below;
   - `observed/results.json`: the same results as device > carrier > plan, with dates and the count of accounts ([docs/data-model.md](../docs/data-model.md#results-tree)). Phones and ROM builds never read it.
4. A maintainer merges the pull request after `validate`, with the phone guard, passes. Merging accepts the files; it does not verify the results. The issues close with it.
5. When `observed/reports/` changes on `main`, and once a day, the bot opens or updates one source-review issue per carrier profile and entry for which a counted report names a failure and a passing alternative ([Source reviews](#source-reviews)).

A maintainer withdraws a report by closing its issue as **not planned**; the next rebuild drops its file, and a deleted issue drops out the same way. The label `report:hold-released` lifts a hold. The workflow can also be started by hand (`workflow_dispatch`).

## Statuses in observed/summary.json

| Status | Set by |
|---|---|
| `reported`: "reported, not checked by OCD" | counted reports of people's phones: how many, by result, the first and last report date, and the issues |
| `contested` | at least one counted report measured a clean failure of the entry: it was measured and did not work, and the phone's state came back. It asks the next phone to test the entry and a maintainer to look; it switches nothing off. A test that broke (a revert not proven) contests nothing |
| `retested_by_ocd` | always null: no account or list gives a result a stronger status (rule round 47). The field leaves the file once the app without it is on the phones |

Each cell also gives `held`, the valid reports a noise filter holds. `summary.json` counts the reports of every account alike. One report counts per account and cell, so a count is a count of distinct accounts.

## Source reviews

A configured value changes only through a review of its source and the normal data path (rule 10). So a counted report that names a **failure** of the entry OCD gives that phone and a **passing alternative** opens a review automatically: a clean measured failure (the test ran and the phone's state came back) of `volte:on` with `volte:off` passing, say, or of an APN row with another row of the same type passing. It comes through the same tap as every report. The `source-review` job of the same workflow runs when `observed/reports/` changes on `main`, and daily:

- one issue per carrier profile and entry, labelled `source-review`, titled for example "[Source review] Wi-Fi calling on for open.26202.8cebd7550c67";
- its text lists every report behind it, with the phone, software, the failure, the passing alternative, the plan, the test date, the data commit and the issue, and says what to do: review the source or importer behind OCD's value, fix it there with the evidence in the pull request, or say that the cause is the phone, its IMS stack or the SIM's plan;
- the bot keeps the text current, never closes the issue and never edits an issue it did not open. After a maintainer closes it, the bot opens a new one only when the reported findings change, not for another report of the same finding.

The issue itself changes nothing, and a plan is no part of its key.

## Noise filters

These order what people read and keep review time down. They are not a defence, and they are not proof. They apply the same to every account:

- the closed schema and the privacy scan;
- a SHA-256 hash of the report text; a second issue with the same report is a `duplicate`;
- plausibility against the release (`report:suspect`);
- one counted report per account and cell: a newer one `supersedes` the older;
- at most 10 counted reports per account and month;
- an account's reports are `held` until its first accepted report here is 14 days old. The age counts from that report, not from the account's sign-up, because old accounts are easy to buy. The accounts are read from the issues on each rebuild and never written to `observed/`, only counted;
- a report `expires` 90 days after its test.

## The automatic week report

> **Status on 2026-11-04.** Sending is closed. `relay_open` in [`relay.json`](relay.json) is false, the relay is not deployed, and the app's side is being built. `relay_open` turns true only when the question, the first-screen line and the [privacy page](../docs/privacy.md) are live in the same build. Until then a test report is the only way a result leaves a phone.

Nothing leaves a phone by itself unless the person said yes. After that one yes, and only on a ROM install, the app sends one closed week report per SIM to OCD's relay, only on an unmetered network and never while roaming. It holds no identifier, no free text, no day or time and no call details, and the person can stop it at any time. A hand install never sends by itself. Any other result leaves only when the person taps and submits it under their own GitHub login. No result, sent or tapped, ever sets a value on any phone: a carrier value changes only through a source-backed change on `main`. The app's download from GitHub carries no identifier.

**The yes.** A ROM install asks once: one notification on the first boot with a SIM, opening one screen with equal Yes and No. Dismissed or ignored means no, and it is never asked again. A person stops the send at any time in Settings > About phone > Open Carrier Data, and the phone clears what it had collected. The [privacy page](../docs/privacy.md) has the words, the exact fields, the list of what is never sent, who is responsible and how long anything is kept.

**What it says.** One flag per entry and SIM for the week, with the model, ROM family, Android version, IMS stack and carrier. Entries are the same pointers as in a test report, without any emergency row. Results are `works`, `calls_out`, `signed_in`, `service_off`, `not_possible` and `failed`, and an uncalibrated stack sends only `signed_in`, `service_off` and `not_possible`. Here `works` means calls both ways by packet counts and `calls_out` an outgoing call only. No sound was checked, and neither speaks for emergency calls. `plan` is never sent. A report cannot be found or removed afterwards, because it holds no ID.

**What happens to it.** The relay checks the closed shape and adds one to a counter. It keeps no report, address, header or log, and it holds no GitHub credential. A weekly Action in the separate [week-counts](https://github.com/open-carrier-data/week-counts) repository reads the counters and drops every value that is not on OCD's public lists. It publishes a row only with at least 3 reports in one ISO week, by month, as device > carrier > plan with plan `unknown`. Counters leave the relay after 8 weeks. A row at its cap of 500 in a week is not published that week.

**What it never does.** A week count is not a test report:

- every row reads "automatic, reported by phones, not checked by OCD, counts can be faked";
- it is never added to a count of accounts, and it never enters `observed/`, the dataset manifest or a phone: `validate` fails if it does;
- it opens no issue and no source review by itself. A person or an agent may start one after reading it;
- it needs no GitHub account, so nothing ties it to a person, and nothing proves it either.

**ROM builders** carry duties for this send: name the app in the ROM's public notes, know that shipping the question may make them share responsibility, never answer for the person, and leave the app in Settings > Apps. A builder can set the question off and can never turn the send on. [Your duties as a builder](../docs/rom-builders.md#your-duties-as-a-builder) has the details.

## Why it stays apart

OCD's values say what carrier tables configure, from maintained sources. A phone result is a different kind of evidence, kept beside the data, never in it:

- no report, tapped or automatic, changes a capability value, an APN row, a CarrierConfig key, a device record or a release asset, and `generated/devices/device-records.json` stays empty: no result of any account is served on another phone;
- `observed/` is not part of a release and has no compatibility promise;
- counts are not votes: a `signed_in` from one phone says nothing about another phone, stack or plan, and a result with a plan never says that a tariff includes a feature;
- a ROM maintainer who uses a cell still makes his own test call; a phone that acts on a report still runs its own test and keeps nothing that fails.

Run the checks locally:

```bash
python3 tools/test_observed_reports.py
python3 tools/observed_reports.py validate --root .   # observed/reports/, summary.json and results.json
git fetch --no-tags --depth=1 origin '+refs/tags/data-*:refs/tags/data-*'
python3 tools/observed_reports.py check-file report.json   # one report as the app wrote it
```
