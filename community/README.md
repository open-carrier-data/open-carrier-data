# Community reports

A community report is what a phone measured, uploaded by its owner. Today there is one kind: the test report of the OCD Check app's owner build. It is an **unverified hint**:

- it never changes an OCD value, a file under `carriers/` or `generated/`, or a release;
- it never makes a phone skip its own test, and it never switches anything off;
- at most it makes a phone test the entry it points at earlier than its normal rotation. The phone then keeps the entry only if it passes there.

No gate can tell a true report from a well-made fake: anyone can open an issue, nothing checks who sent a report or whether the phone exists, and no carrier signal can prove to a third party that a setting worked. So OCD does not ask "is this report true?". A report can only point, and every phone proves for itself.

## A report points, it carries no value

A report names entries of one OCD data release's closed list, each with the result the phone measured:

| Entry | Meaning |
|---|---|
| `volte:on`, `volte:off` | the VoLTE switch on or off; the same for `vowifi`, `sms_over_ims`, `video_calling` and `vonr` |
| `apn:<row key>` | one APN row of that release's `apns-conf.xml` for the SIM's network: the APN in lower case, its types in lower case and sorted, its protocol, for example `apn:web.vodafone.de\|default,supl\|IPV4V6` |

Anything else fails the schema: no APN string, no CarrierConfig key, no safety-class entry (emergency, e911, ECBM, WPS, TTY, RTT, `iwlan.*`) and no emergency APN row. The bot checks that the release exists (its tag and data digest; a bundled snapshot is found by its digest), that the OCD profile is in it, and that every `apn:` row key is a row it has for the SIM's network. So no report can bring a new value onto any phone.

The report follows [`schemas/ocd-check-report.schema.json`](../schemas/ocd-check-report.schema.json) (`"schema": "ocd-check-test-report"`, `"schema_version": 1`). Besides the entries it holds the app version, the test date (a date, never a time), the release, the phone (model, codename `Build.DEVICE`, Android major version, ROM family, build type, IMS stack), the SIM (network code, and when known the Android carrier ID, the SPN and the GID1 prefix of the OCD profile it matched, never the SIM's whole GID1) and the OCD profile it matched. Per entry it says whether it is OCD's value for this phone and SIM (`ocd`), the phone's own value (`phone`), whether it was `observed` or `tested`, the calls measured with their call network type, and whether the app kept it.

The **result** of an entry is one of:

| Result | Meaning |
|---|---|
| `works` | `volte:on` or `vowifi:on` signed in and passed the T2 call test (an outgoing and an incoming call on its bearer, audio confirmed); an off entry of a voice feature took effect and a call went active with it; mobile data validated with an APN row |
| `signed_in` | an on entry registered IMS with the feature's service on its bearer; no call test |
| `service_off` | an off entry took effect: the service went; no call measured |
| `not_possible` | an on entry cannot be on here: the modem, the IMS stack, the network's offer |
| `failed` | the entry was measured and did not work, or the test broke something (the reason says which) |
| `not_tested` | no result, with the reason |

A report holds no IMSI, ICCID, IMEI, phone number, SIP or tel URI, IP address, time of day, location or free text. Every value is a fixed code or has a fixed form.

## Upload a report

The app does it: its "Open report on GitHub" action opens the `OCD Check report` issue form with the report filled in, in the browser, and shows the report's hash. Read it and submit it yourself; the app sends nothing and holds no token. Do not edit the report.

The issue is public under your GitHub account, and public archives of GitHub can keep a copy after the issue is deleted.

## What happens to it

1. [`.github/workflows/ocd-check-report.yml`](../.github/workflows/ocd-check-report.yml) runs [`tools/observed_reports.py`](../tools/observed_reports.py) on the issue: the form's shape, the closed schema, a fail-closed privacy scan of every key and value and of the rest of the issue (the patterns of the app's own scan), consistency checks (for example, `works` on `volte:on` needs a passed T2 call on LTE), and the release checks above.
2. The issue gets one label and one bot comment, updated on every edit, with the report's SHA-256 hash:
   - `report:valid`;
   - `report:suspect`: valid, but a plausibility check against the release flags it (for example video calling that signed in on PHH IMS, which has no video, or an entry marked as OCD's value that the release does not give). It is held until a maintainer looks;
   - `report:invalid`: the comment lists exactly what is wrong. It names the field and the rule, never the value. Edit the issue to fix it, and the check runs again.
3. The bot rebuilds `observed/` from every report issue, once per issue event and once a day, and opens or updates one pull request, `automation/observed-reports`, titled "Observed reports (unverified)". It touches `observed/` only:
   - `observed/reports/issue-N.json`: one file per valid report, as submitted, with its hash, its release, `"verification": "unverified"` and its status after the noise filters;
   - `observed/summary.json`: per device × carrier profile × stack (ROM family, IMS stack, Android major) × entry, the statuses below.
4. A maintainer merges the pull request. Merging accepts the files; it does not verify the results. The issues close with it.

A maintainer withdraws a report by closing its issue as **not planned**; the next rebuild drops its file. The label `report:hold-released` lifts a hold. The workflow can also be started by hand (`workflow_dispatch`).

## Statuses in observed/summary.json

| Status | Set by |
|---|---|
| `reported`: "reported, not checked by OCD" | counted reports of people's phones: how many, by result, the first and last report date, and the issues |
| `contested` | at least one counted report measured a clean failure of the entry: it was measured and did not work, and the phone's state came back. It asks the next phone to test the entry and a maintainer to look; it switches nothing off. A test that broke (a revert not proven) contests nothing |
| `retested_by_ocd` | only OCD's own phones, after a passed T2 call test, from the owner's private ledger. It is always empty here until that status is published |

Each cell also gives `held`, the valid reports a noise filter holds.

## Noise filters

These order what people read and keep review time down. They are not a defence, and they are not proof:

- the closed schema and the privacy scan;
- a SHA-256 hash of the report text; a second issue with the same report is a `duplicate`;
- plausibility against the release (`report:suspect`);
- one counted report per account and cell: a newer one `supersedes` the older;
- at most 10 counted reports per account and month;
- an account's reports are `held` until its first accepted report here is 14 days old. The age counts from that report, not from the account's sign-up, because old accounts are easy to buy. The account names are read from the issues on each rebuild and never written to `observed/`;
- a report `expires` 90 days after its test.

## Why it stays apart

OCD's values say what carrier tables configure, from maintained sources. A phone result is a different kind of evidence, kept beside the data, never in it:

- no report changes a capability value, an APN row, a CarrierConfig key, a device record or a release asset;
- `observed/` is not part of a release and has no compatibility promise;
- counts are not votes: a `signed_in` from one phone says nothing about another phone, stack or plan;
- a ROM maintainer who uses a cell still makes his own test call; a phone that acts on a report still runs its own test and keeps nothing that fails.

Run the checks locally:

```bash
python3 tools/test_observed_reports.py
python3 tools/observed_reports.py validate --root .
git fetch --no-tags --depth=1 origin '+refs/tags/data-*:refs/tags/data-*'
python3 tools/observed_reports.py check-file report.json   # one report as the app wrote it
```
