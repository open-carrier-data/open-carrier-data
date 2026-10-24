# Community reports

A community report is what a phone measured, uploaded by its owner. Today there is one kind: the test report of the OCD Check app's owner build. It is an **unverified hint**:

- it never changes an OCD value, a file under `carriers/` or `generated/`, or a release;
- it never makes a phone skip its own test, and it never switches anything off;
- at most it makes a phone test the entry it points at earlier than its normal rotation. The phone then keeps the entry only if it passes there.

No gate can tell a true report from a well-made fake: anyone can open an issue, nothing checks who sent a report or whether the phone exists, and no carrier signal can prove to a third party that a setting worked. So OCD does not ask "is this report true?". A report can only point, and every phone proves for itself.

The owner's own phones are the one exception (rule round 29, which fires O1 of round 18): the settled results of the owner's reports are published as **"re-tested by OCD"** in `observed/retested.json`, with a 90-day expiry. They are still pointers with a result class, never values, and they never change OCD's configured data ([The owner's results](#the-owners-results-re-tested-by-ocd)).

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
3. The bot rebuilds `observed/` from every report issue, once per issue event and once a day, and opens or updates one pull request, `automation/observed-reports`, titled "Observed reports (unverified)". It touches `observed/` only:
   - `observed/reports/issue-N.json`: one file per valid report, as submitted, with its hash, the commit or release it points into (`release`), `"verification": "unverified"` and its status after the noise filters;
   - `observed/summary.json`: other accounts' reports per device × carrier profile × stack (ROM family, IMS stack, Android major) × entry, the statuses below;
   - `observed/retested.json`: the owner's settled results as "re-tested by OCD" records ([below](#the-owners-results-re-tested-by-ocd)).
4. A maintainer merges the pull request. Merging accepts the files; it does not verify the results. The issues close with it.
5. When `observed/retested.json` changes on `main`, and once a day, the bot opens or updates one source-review issue per carrier profile and feature with a correction or a measured failure ([Source reviews](#source-reviews)).

A maintainer withdraws a report by closing its issue as **not planned**; the next rebuild drops its file. The label `report:hold-released` lifts a hold. The workflow can also be started by hand (`workflow_dispatch`).

## Statuses in observed/summary.json

| Status | Set by |
|---|---|
| `reported`: "reported, not checked by OCD" | counted reports of people's phones: how many, by result, the first and last report date, and the issues |
| `contested` | at least one counted report measured a clean failure of the entry: it was measured and did not work, and the phone's state came back. It asks the next phone to test the entry and a maintainer to look; it switches nothing off. A test that broke (a revert not proven) contests nothing |
| `retested_by_ocd` | always null here: the owner's phones' results are in `observed/retested.json`, a separate file (rule round 29) |

Each cell also gives `held`, the valid reports a noise filter holds. `summary.json` counts the reports of every account but the owner's.

## The owner's results: re-tested by OCD

Rule round 29 (2026-10-24) puts the owner's plan of 2026-10-17 into rules: the app bundled in his ROM verifies OCD's entries on his phones, corrects wrong ones on the phone, and the results flow back into OCD as measured records. This fires O1 of round 18. The owner's account is named in `tools/observed_reports.py` by its GitHub user ID (`OWNER_ACCOUNTS`), which a renamed or reclaimed login cannot take.

- **Only settled results.** A pass at L2 or L3, SMS both ways, or a clean measured failure under rounds 26 to 28, as the report's `settled` field states it. A plain `signed_in`, an off entry, an APN row, video calling and VoNR are not settled results and are not published from the owner's reports.
- **No extra hold.** The plan judge's version applies: "after a few days" is the settlement of rounds 26 to 28 itself (L3 for a working changed value, two days for a measured failure on passive calls). The owner's reports skip the account hold, the monthly cap and the supersede filter, so every report counts. A plausibility flag still holds a report until a maintainer looks, and a maintainer withdraws one by closing it as not planned.
- **A separate measured file.** `observed/retested.json` ([`schemas/observed-retested.schema.json`](../schemas/observed-retested.schema.json)), apart from `carriers/`, `lookup.json`, `carrier-variants.json`, `apns-conf.xml` and every other file under `generated/`, and not a release asset.
- **One record** per cell (device, carrier profile, network code, ROM family and build, IMS stack, Android major), entry, bearer, result class and level. It gives the result (`works`, `calls_out`, `sms_both_ways` or `failed`), the level (`L2`, `L3`), `incoming` (`tested`, `not tested` for calls out only and for a failed outgoing call, `failed`), the method, the failure's reason code, the record in plain words, whether the entry is OCD's value at the data commit (`ocd`), whether it is a correction, `n` (the distinct days measured; a report that repeats a measurement counts once), the first and last day, `valid_until` (90 days after the last day), the data commit of `main` with its `data_digest` (round 29 S13), and the report issues. The tester is always `owner`.
- **Expiry.** A record lapses 90 days after its last measurement. The daily rebuild drops it; read `valid_until`, not the file's `as_of`, which is the day of the rebuild that last changed the file.
- **What it never does.** It never carries a value, never changes a configured value, never counts toward round 19's F1 thresholds, and is not ROM-citable without R3. On another phone it only moves that entry's test earlier: it never creates, keeps, skips, pauses, reverts or protects an entry, and every phone keeps only what it measured itself.

An example record (the S20 on LineageOS 24.0 with AOSP ImsStack and a LIDL Connect SIM):

```json
{
  "status": "re-tested by OCD",
  "tester": "owner",
  "device": {"model": "SM-G981B", "codename": "x1s"},
  "carrier_profile": "open.26202.8cebd7550c67",
  "mccmnc": "26202",
  "stack": {"rom_family": "lineageos", "rom_build": "CP2A.260605.016 1792814506", "ims_stack": "aosp_imsstack", "android_major": 16},
  "entry": "vowifi:on",
  "bearer": "iwlan",
  "result": "calls_out",
  "level": "L2",
  "incoming": "not tested",
  "method": "mailbox_call",
  "reason": null,
  "text": "calls out (L2) over Wi-Fi, incoming not tested (audio from packet counts)",
  "ocd": true,
  "correction": false,
  "n": 1,
  "first_measured": "2026-10-24",
  "last_measured": "2026-10-24",
  "valid_until": "2027-01-22",
  "data": {"commit": "5358c2598be8db1bbd81e4edbb24f8b76a7f34f1", "data_digest": "sha256:e803919120235fa378226d469a9a8d6d52c15bfcb6c2655c611cf105f1b37f73"},
  "issues": [301]
}
```

## Source reviews

A configured value changes only through a review of its source and the normal data path (rule 10). So each **correction** in `observed/retested.json` (a pass of an entry that is not OCD's value, where OCD gives the other value or none, and which the phone keeps: tested and kept, or its own value) and each **clean measured failure of OCD's own value** opens a review automatically. The `source-review` job of the same workflow runs when `observed/retested.json` changes on `main`, and daily:

- one issue per carrier profile (or network code without a profile) and feature, labelled `source-review`, titled for example "[Source review] VoLTE for open.26203.0a1b2c3d4e5f (26203)";
- its text lists every current record behind it, with the phone, software, method, n, dates, expiry and data commit, and says what to do: review the source or importer behind OCD's value, fix it there with the evidence in the pull request, or say that the cause is the phone, its IMS stack or the SIM's plan;
- the bot keeps the text current, never closes the issue and never edits an issue it did not open. After a maintainer closes it, the bot opens a new one only when the measured results change (a new result, level, cell or build), not for a renewal of the same result.

The issue itself changes nothing. A phone result never changes `carriers/`, `lookup.json`, `carrier-variants.json` or the Android files.

## Noise filters

These order what people read and keep review time down. They are not a defence, and they are not proof:

- the closed schema and the privacy scan;
- a SHA-256 hash of the report text; a second issue with the same report is a `duplicate`;
- plausibility against the release (`report:suspect`);
- one counted report per account and cell: a newer one `supersedes` the older;
- at most 10 counted reports per account and month;
- an account's reports are `held` until its first accepted report here is 14 days old. The age counts from that report, not from the account's sign-up, because old accounts are easy to buy. The account names are read from the issues on each rebuild and never written to `observed/`;
- a report `expires` 90 days after its test.

The owner's account skips the account filters (the hold, the monthly cap and the supersede); the duplicate, the plausibility flag and the expiry apply to it as well ([The owner's results](#the-owners-results-re-tested-by-ocd)).

## Why it stays apart

OCD's values say what carrier tables configure, from maintained sources. A phone result is a different kind of evidence, kept beside the data, never in it:

- no report changes a capability value, an APN row, a CarrierConfig key, a device record or a release asset;
- `observed/` is not part of a release and has no compatibility promise;
- counts are not votes: a `signed_in` from one phone says nothing about another phone, stack or plan;
- a ROM maintainer who uses a cell still makes his own test call; a phone that acts on a report still runs its own test and keeps nothing that fails.

Run the checks locally:

```bash
python3 tools/test_observed_reports.py
python3 tools/observed_reports.py validate --root .   # observed/reports/, summary.json and retested.json
git fetch --no-tags --depth=1 origin '+refs/tags/data-*:refs/tags/data-*'
python3 tools/observed_reports.py check-file report.json   # one report as the app wrote it
```
