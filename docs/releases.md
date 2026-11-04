# The one channel

Open Carrier Data has one channel: `main` (rule round 46, 2026-11-04). Every publish lands there, several times a day. There are no monthly releases, no 72-hour age gate, no owner review of a draft, no `release.json` and no 28-day notice. A commit SHA is the pin: `main` blocks force pushes and deletion, also for admins, so a commit never changes or goes away.

[`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10) was the first release and is the last ([below](#data-202610-the-last-release)). [changelog.md](changelog.md) lists format and meaning changes and bad data, and [compatibility.md](compatibility.md) says what a consumer may rely on.

## main has no waiting period

A commit that passes the checks reaches consumers at once. Nothing time-based stands in for the age gate that ended, and most values get no human read. **Do not assume that `main` is settled.**

If you do not verify on a phone, as a ROM builder who bakes the data does not:

1. Pin one commit. Never read a file by the branch name.
2. Run `tools/check_phone_guard.py` and the F5 walk from your old pin to your new pin. Small changes add up across pins, and no per-publish guard sees the total.
3. Read [changelog.md](changelog.md) before you move.

```sh
git archive --prefix=old/ OLD carriers generated schemas tools | tar -x
git archive --prefix=new/ NEW carriers generated schemas tools | tar -x
python3 new/tools/check_phone_guard.py old/generated/android/apns-conf.xml new/generated/android/apns-conf.xml \
  --generator new --base-generator old
ROWS=$(python3 -c 'import sys; sys.path.insert(0, "new/tools"); import f5_read; print(f5_read.apn_rows_sha256(open("old/generated/android/apns-conf.xml", "rb").read()))')
python3 new/tools/f5_read.py chain --root new --from "$ROWS"
```

Run these in a clone of this repository, with OLD and NEW the two commit SHAs. `tools/diff_apns_conf.py` and `tools/diff_carrier_config.py` list the changes between any two files.

If a commit turns out bad, the recovery is a fix-forward commit, your previous pin (F1), the last good set (F3), the tests that a value change makes due (F4) and SM7 on phones without a tester. A ROM baked at a bad commit needs a new build, so [changelog.md](changelog.md#bad-data) names the commit range and the reason of every published commit found harmful.

## What checks a commit

Automatic checks are the only gate. They are all of these:

- **`validate`**, on every pull request, in the merge queue and on `main`: the validators, regeneration with no drift, `xmllint` against LineageOS's unchanged `apns-conf.xsd`, APN database version 8 and `data_digest` agreement.
- **The phone guard** ([how-it-is-built.md](how-it-is-built.md)). A publish that trips it waits as a draft labeled `publish-held` and does not reach `main`.
- **The F5 reads** of emergency lines (`tools/f5_read.py`, [ocd-dataset.md](ocd-dataset.md#f5-reads)). A read that holds keeps the publish a draft, and `validate` refuses a hold on `main`.
- **The group A reads** ([ocd-dataset.md](ocd-dataset.md#group-a-reads)). A group A value from any source but the Google lane is served only after an independent read has passed.
- **A consumer's own checks**: F1 to F3 below, and SM6's chain walk on pins and runtime installs ([rom-builders.md](rom-builders.md)).

A hold clears only through the existing independent agent read or a judged accept line. It never clears because the owner is away, and never by dropping the check.

Each publish's pull request lists the class (a) credential fill-ins ([consume.md](consume.md#credentials-from-old-lists)) and every selector change. Other values get no human read.

The daily freshness alarm runs `--freshness fail` and opens a `stale-data` issue. Pushes and pull requests stay in warn mode, so a passing `validate` does not say that the data is fresh. Read `stale_after` yourself ([consume.md](consume.md#check-freshness-before-you-ship)).

## F1 to F5

Five checks stand behind a pin. The owner's ROM and the ROM builds of the OCD Android app run all five.

- **F1, one commit.** Each ROM build and each app pull resolves `main` once to a commit SHA and reads every file at that SHA, never by the branch name. `data_digest` must agree across `metadata.json`, `carrier-variants.json` and the `apns-conf.xml` header. The SHA and `data_digest` are recorded with everything that is built, served, tested or reported, so a bad build can go back to the previous pin.
- **F2, `validate` passed.** Only a commit whose `validate` check run on `main` concluded `success` is taken. The check run is read from GitHub's public API, without a token.
- **F3, a known format.** A file whose `schema_version` the consumer does not know is refused, and the last good set is kept whole. A ROM build fails.
- **F4, value changes.** A new pin makes a test due only when a value of the SIM's profile, or an APN row of its scope, changed against the previous pin.
- **F5, emergency rows read before a ROM build.** The ROM build's pin step runs `tools/check_phone_guard.py --report-json` from the previous build's commit to the new one. A trip, or any emergency line (an emergency lead gained, lost, or changed to anything other than Android's default request; a network type left without an emergency profile; or an emergency profile missing under an APN set), keeps the previous commit until an agent other than the builder has read the lines. An emergency APN row is the one change no phone can test.

Since rule round 31 (2026-10-28) any ROM that serves OCD through OcdCarrierSettings, or takes only OCD's APN file, may bake a validated `main` commit under F1 to F3. It takes a change to emergency APN lines only with the independent read that OCD publishes for that commit (SM6 in [rom-builders.md](rom-builders.md)).

## Tiers

A tier says what a file is for and what OCD keeps stable for it ([compatibility.md](compatibility.md)). **`supported` is not a claim that a value works.** It holds for the file's format and for how the file is made, not for each row on `main` today.

| File | Tier | For |
| --- | --- | --- |
| `generated/android/apns-conf.xml` | supported for ROMs. Its format loads on a phone, and [the boot check](#the-s20-boot-check-of-apns-confxml) passed once, on one file, one SIM network and one phone. That pass says nothing about any later commit or any other network | ROMs, at build time |
| `generated/android/lookup.json` | supported | apps and tools, bundled at build time |
| `generated/android/metadata.json` | supported | apps and tools; a ROM's build log |
| `generated/devices/carrier-variants.json` | supported as information; never an export | apps |
| `generated/android/carrier-config-list.xml` | **not for ROM application.** Its emergency, TTY, RTT, WPS and `iwlan.*` keys are unreviewed. The file's own header says so, and it stays this way until the per-key review has run and been implemented | reviewers; a maintainer doing their own review |
| `generated/ocd-dataset/`, `generated/devices/device-records.json` | the OCD dataset, which OcdCarrierSettings serves ([ocd-dataset.md](ocd-dataset.md), [rom-builders.md](rom-builders.md)) | ROMs that ship OcdCarrierSettings, and their OCD Android build |
| `carriers/open/`, `generated/index.json`, `generated/evidence-index.json`, the other files under `generated/devices/` | reference: no further promise | the resolver, `--explain`, reviewers |

`observed/`, the OCD Android reports, is never supported and no file depends on it ([community/README.md](../community/README.md)).

## What OCD never guarantees

- That a value works on a network, a plan or a phone model, or that the operator still offers the service. Values are configured, not verified: `verified_observation_count` is 0.
- Anything about emergency calls. OCD never tests or places one.
- That a commit is free of mistakes because it passed the checks. There is no waiting period, and the checks cover the file and the phone guard's model, not each value.
- That a profile keeps its SIMs. Since rule round 45 a `profile_id` is kept once assigned and a retired one is never reused and has an alias in `aliases/ids.json`, but profiles are added, split and retired with the sources; key what you store by the SIM's facts and the commit.
- A response time, or that publishing continues. One maintainer and one self-hosted runner run the pipeline.

## data-2026.10, the last release

[`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10) was published on 2026-10-19 from `8cb64d63`. No `data-2026.11` and no other release will follow. It was not withdrawn: nothing was found wrong with it beyond its known issues.

What stays true:

- Its tag never moves or goes away. A tag ruleset on `data-*` with no bypass and immutable releases hold it.
- Its files stay byte-fixed and reproducible: regenerating `generated/android/` from `carriers/` at the tag gives the same bytes.
- `stale_after` is 2027-01-10. Do not ship it after that date.

Its known issues:

- Samsung's emergency role is not in it: 51 emergency-named rows are typed `ims`. The fix will not come as a release; it reaches `main` as the Samsung packages are re-read. At `08fa0ec5` (2026-11-02), 35 such rows were left.
- 452/02 has no emergency APN profile on IWLAN, 2G or 3G. Google's current row for it is limited to LTE and NR.

If you use it, move to a validated `main` commit or back to your ROM's own list. The F5 chain starts at its commit, so the walk from its rows to any later commit works.

Its `release.json` still names `apns-conf.xml` `rom, pending the S20 boot check`, because a published release never changes. Reports that name `data-2026.10` stay accepted.

## The S20 boot check of apns-conf.xml

The boot check was **one pass, on one file, with one SIM network, on one phone.** It ran on 2026-10-19 and 2026-10-20 with `data-2026.10`'s `apns-conf.xml` (SHA-256 `8c24a482…`, `data_digest` `sha256:36d5f7eb…`), a LIDL Connect SIM (26202) and the owner's S20 with LineageOS 23.2 and PHH IMS. It is a record of that pass, not a property of `main`. No person took part. The check never placed an emergency call and never opened the emergency dialer.

| Part | Result |
| --- | --- |
| Rows | the file was the active APN list: 22,082 stored rows, the count expected for that phone |
| Data and registration | mobile data up on `web.vodafone.de`; VoLTE and SMS over IMS registered; Wi-Fi calling registered over IWLAN, after Private DNS was set to a resolver that sends ECS, because of Vodafone Germany's DNS filter ([consume.md](consume.md#wi-fi-calling-can-fail-because-of-the-wi-fis-dns-not-the-settings)) |
| Calls out over Wi-Fi | call type 18 (IWLAN), the IMS data connection on WLAN when the call went active and at hang-up; 501 RTP packets sent and 491 received per 10 s; ended by the phone |
| Calls out over LTE, Wi-Fi off | call type 13 (LTE), the IMS data connection on WWAN and the data RAT LTE at both moments; 499 packets sent and 491 received per 10 s; ended by the phone |
| Emergency profile, read without a call | the 26202 row: APN `EMERGENCY`, IPV4V6 at home and when roaming, no restriction on network types |

The packet counts show that the media path carried RTP both ways. They do not show that a voice was heard. The check says nothing about:

- incoming calls;
- MMS on any network (Vodafone Germany ended it on 2023-01-17);
- other networks' rows;
- other phones or software stacks;
- any commit other than `8cb64d63`;
- emergency calls.

## If publishing stops

Keep your last pin until its `stale_after`, then switch back to your ROM's own list (on the S20 tree, `LINEAGE_APN_SOURCE=lineage`).
