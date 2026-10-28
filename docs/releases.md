# Releases

This page describes the releases of Open Carrier Data (rule decisions of 2026-10-18, rounds 20 and 21, of 2026-10-19, round 24, of 2026-10-20, round 26, and of 2026-10-24, round 29) and how one is made. **The first release is [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10), published on 2026-10-19.** In it `lookup.json` and `metadata.json` are supported for apps and tools, and `carrier-variants.json` as information. Its `apns-conf.xml` is supported for ROMs since 2026-10-20, when the S20 boot check of that release passed ([below](#the-s20-boot-check-of-apns-confxml)). The release's own `release.json`, published the day before, still names it `rom, pending the S20 boot check`, because a published release never changes. The tooling that drafts a release is `tools/build_release.py`, `tools/release_notes.py` and `.github/workflows/release.yml`; [compatibility.md](compatibility.md) has the compatibility policy.

## Releases so far

| Release | Published | Candidate | Notes |
| --- | --- | --- | --- |
| [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10) | 2026-10-19 | `8cb64d63` (#280), compared with base `98fbd8b2` (#253) | The first release. Its candidate was not yet 72 hours old: the age gate was waived once, through a public pull request (#283), on the owner's direction (round 24). `release.json` records `age_gate: waived, round 24`; every other gate passed. Known issues, as its notes list them: Samsung's emergency role is not included yet (51 emergency-named rows are still typed `ims`; they come with `data-2026.11`), and 452/02 has no emergency APN profile on IWLAN. Its `apns-conf.xml` became supported for ROMs on 2026-10-20, after publication, when the S20 boot check passed. |
| `data-2026.11` | planned for about 2026-11-02 | | The normal path: a candidate at least 72 hours old, with no waiver. The waiver can never fire again, because it needs `first_base`, which the workflow refuses once a `data-*` release exists. The first release whose `release.json` gives `apns-conf.xml` the tier `supported`, with the boot check's `tier_note`. |

## Two channels

- **`main` is the edge channel, and the channel of the consumers that verify on a phone.** Every publish lands there, several times a day. It is guarded by the `validate` check and the phone guard ([how-it-is-built.md](how-it-is-built.md)): a publish that trips the guard waits as a draft labeled `publish-held` and does not reach `main`. Since round 29 (2026-10-24) the owner's ROM and the owner's builds of the OCD Check app consume validated `main`, pinned per commit, instead of releases. The app verifies OCD's values on the phone and corrects them, and the ROM build keeps the previous build for a same-day rollback, so the age gate and the monthly wait add nothing for them. Five checks replace a release's guarantees for these two consumers:
  - **F1, one commit.** Each ROM build and each app pull resolves `main` once to a commit SHA and reads every file at that SHA, never by the branch name. `data_digest` must agree across `metadata.json`, `carrier-variants.json` and the `apns-conf.xml` header. The SHA and `data_digest` are recorded with everything that is built, served, tested or reported, so a bad build can go back to the previous pin.
  - **F2, `validate` passed.** Only a commit whose `validate` check run on `main` concluded `success` is taken. The check run is read from GitHub's public API, without a token.
  - **F3, a known format.** A file whose `schema_version` the consumer does not know is refused, and the last good set is kept whole. A ROM build fails.
  - **F4, value changes.** A new pin makes a test due only when a value of the SIM's profile, or an APN row of its scope, changed against the previous pin.
  - **F5, emergency rows read before a ROM build.** The ROM build's pin step runs `tools/check_phone_guard.py --report-json` from the previous build's commit to the new one. A trip, or any emergency line (an emergency lead gained, lost, or changed to anything other than Android's default request; a network type left without an emergency profile; or an emergency profile missing under an APN set), keeps the previous commit until an agent other than the builder has read the lines. An emergency APN row is the one change no phone can test.

  Since rule round 31 (2026-10-28) any ROM that serves OCD through OcdCarrierSettings, or takes only OCD's APN file, may bake a validated `main` commit under F1 to F3 or a release. It takes a change to emergency APN lines only with the independent read that OCD publishes for that commit (SM6 in [rom-builders.md](rom-builders.md)). Any other maintainer may still pin a `main` commit by hand. Beyond the `validate` check and the phone guard, OCD promises nothing about `main` to a consumer that does not verify on a phone. The owner's S20 pinned a `main` commit until 2026-10-19 and has taken `data-2026.10` since; from its next build it takes validated `main` under F1 to F5.
- **Releases are the production channel for consumers that do not verify on a phone**: other ROM maintainers and apps that build without the OCD Check app, the website, the paper and any upstream. A release is a git tag `data-YYYY.MM`, at most one a month, with a fix release `data-YYYY.MM.N` only for a defect in the newest release that affects phones. A bad release is marked withdrawn in its title and in the next release's notes; its tag and files stay. Tooling drafts a release from a `main` commit. The owner publishes it, or, on his direction, an agent with his token after an independent agent has read the draft (round 24). Nothing releases on a timer. A month with no candidate that passes every check has no release, and no date is promised. No tag is made for each publish to `main`: a commit SHA already identifies the data.

Daily publishing to `main`, the phone guard, the freshness alarm and the data rules do not change. Neither do the release process, the 72-hour age gate and the guarantees below: round 29 changes what the owner's ROM and app consume, not what a release is.

## Tiers

| File | Tier | For |
| --- | --- | --- |
| `generated/android/apns-conf.xml` | supported, since 2026-10-20. The S20 boot check of `data-2026.10` passed with one LIDL Connect SIM (26202) and covered mobile data, IMS registration, and outgoing calls over LTE and Wi-Fi ([below](#the-s20-boot-check-of-apns-confxml)). MMS was not checked anywhere: that network no longer offers MMS (Vodafone Germany ended it on 2023-01-17). `release.json` says `supported`, with this as its `tier_note`, from `data-2026.11` on; `data-2026.10`'s still says `rom, pending the S20 boot check` | ROMs, at build time |
| `generated/android/lookup.json` | supported, since `data-2026.10` | apps and tools, bundled at build time |
| `generated/android/metadata.json` | supported, since `data-2026.10` | apps and tools; a ROM's build log |
| `generated/devices/carrier-variants.json` | supported as information, since `data-2026.10`; never an export | apps |
| `generated/android/carrier-config-list.xml` | not supported for ROM application, and not a release asset, until the per-key review of its emergency, TTY, RTT, WPS and `iwlan.*` keys has run and been implemented | reviewers; a maintainer doing their own review |
| `carriers/open/`, `generated/index.json`, `generated/evidence-index.json`, the other files under `generated/devices/` | reference: in the tagged tree, with no further promise | the resolver, `--explain`, reviewers |

## What a release contains

Each file below is an asset of the GitHub release:

- the four files of the table above, each byte-identical to the file in the tagged commit. `carrier-config-list.xml` is not one of them; `release.json` lists its path and SHA-256 as a reference file;
- `release.json`: the tag, the commit and its date, the previous release and its commit, the cut time, the age gate's result (`passed`, or `waived, round 24` for the first release), `data_digest`, `checks_through`, `stale_after` and the days left, the APN database version; per file its path, tier (with a `tier_note` that says what a check covered, where one did), size, SHA-256, `schema_version` and the SHA-256 of its schema in the tag; the counts (profiles, APN rows, rows typed `emergency`, the emergency types left out by reason, CarrierConfig blocks, key lines and safety-class lines); the phone guard's verdict, trips and report counts; the "needs review" reasons; the "Reset to default" scopes and every internet, attach and MMS lead change; every profile ID added and removed; the announced changes;
- `release-notes.md`, generated by `tools/release_notes.py` from the previous release to this one. The release text is the same notes, cut only if they exceed what a GitHub release body takes. Its sections:
  - **Needs review**, first, only when an emergency lead is lost to Android's default, an emergency lead is gained or changed to anything other than Android's default request, a network type is left with no emergency profile, or an APN set leaves a scope with none (round 21; the stricter correctness form);
  - the window and the counts;
  - the phone guard: verdict, trips, digest and report lines;
  - IMS leads and emergency-named leads, every line;
  - emergency APN rows: rows typed `emergency`, the types left out by reason, and every emergency lead gained, lost or changed with its label against Android's default, never cut;
  - internet, attach and MMS lead changes (counts, then up to 50 per role) and the scopes whose lead "Reset to default" changes;
  - capability value changes, as counts;
  - CarrierConfig: the emergency, TTY, RTT, WPS and `iwlan.*` keys in full, every other key as counts;
  - profile IDs added and removed per MCC/MNC;
  - the pull requests in between, the announced changes and the standing notice;
- `SHA256SUMS` over the other assets, so `sha256sum -c SHA256SUMS` checks them.

`observed/`, the OCD Check reports, is never a release asset and no release file depends on it ([community/README.md](../community/README.md)). Neither are the OCD dataset (`generated/ocd-dataset/`) and the records (`generated/devices/device-records.json`, `devices/records/`): a ROM that ships OcdCarrierSettings bakes them at a validated `main` commit or a release's commit, and its build of the app pulls validated `main`, pinned per commit (rule rounds 30 and 31, [docs/ocd-dataset.md](ocd-dataset.md), [docs/rom-builders.md](rom-builders.md)).

## What a release guarantees

The guarantees cover the files and the process that made them, never that a value works.

- **Fixed and identifiable.** A tag is never moved or deleted. The files are byte copies of the tagged commit, and `SHA256SUMS` and `release.json` list them. The XML header carries `data_digest`.
- **Reproducible.** Regenerating `generated/android/` from `carriers/` at the tag gives the same bytes.
- **Valid.** Every validator passes with `--freshness fail`, `apns-conf.xml` passes LineageOS's unchanged `apns-conf.xsd`, and `<apns version>` equals `metadata.json`'s `target.apn_database_version`.
- **Fresh.** `stale_after` is at least 30 days after the release, and the notes print the days left.
- **Guarded.** The phone guard runs from the previous release to this one, and every trip is listed and was accepted on `main`.
- **Changes are visible.** The notes list the changes above in full.
- **Format changes come with notice.** A breaking change to a supported file, such as a removed or renamed file or field or a changed meaning, comes only at a release, is announced in an earlier release's notes, and bumps the file's `schema_version` ([compatibility.md](compatibility.md)). The policy started with the first release, `data-2026.10`; earlier changes stay history.

## What a release never guarantees

- That a value works on a network, a plan or a phone model, or that the operator still offers the service. Values are configured, not verified: `verified_observation_count` is 0.
- Anything about emergency calls. OCD never tests or places one.
- That a `profile_id` stays the same. It is a hash of the match set and changes when a source's selectors change; key what you store by the SIM's facts and the release.
- Anything about `main` between releases.
- A response time, or that releases continue. One maintainer and one self-hosted runner run the pipeline.

## How a release is made

### Once, before the first release (owner settings)

All three were set on 2026-10-19, before `data-2026.10`: the tag ruleset "data releases" on `data-*` with no bypass, the `release` environment with the owner as its reviewer on `main` only, and immutable releases.

1. A tag ruleset on `data-*` that blocks updates and deletions, so a published tag never moves. Give it no bypass: a bypass actor could also move or delete the tag. Publishing a draft creates its tag, which this ruleset allows. Turn on immutable releases too if the repository offers them.
2. An environment named `release` with the owner as its required reviewer. `release.yml` runs in it, so every run waits for the owner's approval. Create it before the first dispatch: a run that names an environment that does not exist creates it without any reviewer. Leave "Prevent self-review" off, because the owner both dispatches and approves the run.

### Each month

1. **Pick the candidate**: the newest `main` commit that is at least 72 hours old, whose `validate` check is green. For example:

   ```sh
   gh api "repos/open-carrier-data/open-carrier-data/commits?sha=main&per_page=1&until=$(date -u -d '72 hours ago' +%Y-%m-%dT%H:%M:%SZ)" --jq '.[0].sha'
   ```

   Check that no generator or importer fix merged after it names a defect it carries.
2. **Rehearse it locally** (optional; no release is created). In a clone, with `xmllint` installed:

   ```sh
   echo '{"candidate_on_main": true, "validate": "success", "publish_held": [], "stale_data": [], "release_exists": false}' > /tmp/state.json
   python3 tools/build_release.py --repo . --candidate SHA --base PREVIOUS --tag data-YYYY.MM \
     --state /tmp/state.json --out /tmp/release --rehearsal
   ```

   `PREVIOUS` is the newest release's tag, `data-2026.10` today. (The first release was compared with `98fbd8b2b3d6a6bbc29b3d573263a8671b7661dd`, #253, the S20's earlier pin.) It writes the assets even when a gate fails, with `"rehearsal": true` and the failed gates in `release.json`. `python3 tools/release_notes.py --repo . PREVIOUS SHA` prints the notes alone.
3. **Dispatch the workflow**:

   ```sh
   gh workflow run release.yml -R open-carrier-data/open-carrier-data -f tag=data-YYYY.MM -f candidate=SHA
   ```

   Leave `first_base` empty: the newest published `data-*` release is the base. Only the first release, `data-2026.10`, was dispatched with `-f first_base=98fbd8b2b3d6a6bbc29b3d573263a8671b7661dd`, and the workflow now refuses it. Approve the run in the `release` environment.
4. **The gates.** `tools/build_release.py` refuses the candidate, and no draft is made, when any of these fails:
   - the candidate is on `main`, its `validate` check is green and it is at least 72 hours old. The daily schedule leaves a skipped `validate` run on the commit that was `main`'s head; it does not count. The age gate did not apply to the first release (round 24): only when the run has `first_base`, which the workflow refuses once any `data-*` release exists, and no `data-*` tag exists. `release.json` and the notes then record `age_gate: waived, round 24`. This happened once, for `data-2026.10`. Every later release passes the age gate;
   - no `publish-held` pull request and no `stale-data` issue is open, and no release or tag of that name exists;
   - the candidate's three validators pass with `--freshness fail`;
   - regenerating `generated/` from `carriers/` changes no byte;
   - `<apns version>` and `metadata.json` name APN database version 8, and `xmllint` accepts `apns-conf.xml` against LineageOS's unchanged `apns-conf.xsd`;
   - `stale_after` is at least 30 days after the cut;
   - `carrier-variants.json` was built on the candidate's `data_digest`;
   - the phone guard from the previous release to the candidate passes with no trip. A trip accepted on `main` does not carry over: a trip here needs a judged ruling, and no input skips it;
   - the notes have every required section.

   The run's summary names each failed gate. A month with no candidate that passes has no release, and the next release's notes say why.
If the draft step reports that the workflow token could not create the draft, every gate still passed. GitHub refuses the workflow's own token when the candidate's files under `.github/workflows/` differ from `main`. The run then keeps the seven assets as the artifact `data-YYYY.MM-assets`. Download it, run `sha256sum -c SHA256SUMS`, and create the draft with a token that holds the workflow scope: `gh release create data-YYYY.MM --draft --target <candidate> --title data-YYYY.MM --notes-file release-body.md` with the seven assets. Under round 24 an agent may do this with the owner's token on the owner's direction.

5. **Read the draft.** It is a draft release with the seven assets and no tag yet. Read "Needs review" first, then the phone guard, the IMS and emergency sections and the CarrierConfig safety lines. When an agent will publish it (step 6), a second, independent agent does this read first and also checks the SHA-256 of the four data files against the rehearsal (step 2); any mismatch stops the release. An optional line may record a check on the S20 (attach, data, IMS registration, the APN list after "Reset to default", the harness's muted mailbox calls; never an emergency call, and no MMS on a network that has ended it).
6. **Publish it**: the owner, or under round 24 an agent with the owner's token on his direction, after the independent read of step 5. The `release` environment's admin bypass is never used. GitHub creates the tag `data-YYYY.MM` at the candidate then. A draft not published within 14 days is deleted, and the month starts again.
7. **Check it** like a consumer:

   ```sh
   gh release download data-YYYY.MM -R open-carrier-data/open-carrier-data -D data-YYYY.MM
   cd data-YYYY.MM && sha256sum -c SHA256SUMS
   ```

**Withdrawing a release.** The owner puts "Withdrawn:" in its title and the reason in its notes, and the next release repeats it. The tag and the assets stay.

## The S20 boot check of apns-conf.xml

`apns-conf.xml` becomes supported for ROMs only after the owner's S20 has run a release with its APN list loaded and passed the boot check with a SIM (rounds 20, 24 and 26). The check is:

- the review of the emergency APN rows (S1-A), with its result in the release;
- the right file and row count, and mobile data on the default row;
- IMS registered over LTE and over Wi-Fi (IWLAN);
- one automatic "calls out" call per bearer, over Wi-Fi and over LTE, with the release loaded. A harness places each call over adb to the SIM's own mailbox, with the call volume muted, and ends it. A call counts when all of these hold:
  - it went active;
  - its bearer proof passed: the call type, the IMS data connection and, for LTE, the data RAT agree when the call goes active and when it is hung up;
  - RTP flowed both ways, at least 300 packets each way in 10 s, with no inactivity;
  - there was no SIP failure cause;
  - the phone hung up itself;
- the emergency data profile, read without a call.

No person takes part. An incoming call and MMS are not part of the check (round 26). MMS is never checked on a network that has ended it. The check never places an emergency call and never opens the emergency dialer. Once it passes, a docs pull request changes the tier in `tools/build_release.py` and on this page.

**`data-2026.10` passed on 2026-10-20, with a LIDL Connect SIM (26202):**

- **Loaded, 2026-10-19.** The release's `apns-conf.xml` (SHA-256 `8c24a482…`, `data_digest` `sha256:36d5f7eb…`) is the S20's active APN list: 22,082 stored rows, the count expected for that phone. On the owner's direction it was loaded without a new ROM build. The release file replaced the earlier copy in `/data/misc/apns/`, which the phone reads before its build's own file, and TelephonyProvider reloaded the table (`update_db`). On 2026-10-20 the phone's file still had that SHA-256 and the table still had 22,082 rows.
- **Data and registration, 2026-10-19.** Mobile data is up on `web.vodafone.de`. VoLTE and SMS over IMS are registered, and Wi-Fi calling is registered over IWLAN. Wi-Fi calling registered only after the phone's Private DNS was set to a resolver that sends ECS, because of Vodafone Germany's DNS filter ([consume.md](consume.md#wi-fi-calling-can-fail-because-of-the-wi-fis-dns-not-the-settings)).
- **Calls out over Wi-Fi, 2026-10-20.** Call type 18 (IWLAN), with the IMS data connection on WLAN, both when the call went active and at hang-up. 501 RTP packets sent and 491 received per 10 s, no inactivity, ended by the phone. Passed.
- **Calls out over LTE, Wi-Fi off, 2026-10-20.** Call type 13 (LTE), with the IMS data connection on WWAN and the data RAT LTE, both when the call went active and at hang-up. 499 packets sent and 491 received per 10 s, no inactivity, ended by the phone. Passed.
- **Emergency profile, read without a call.** The release's 26202 row: APN `EMERGENCY`, IPV4V6 at home and when roaming, no restriction on network types.
- **MMS: not checked.** The network no longer offers MMS: Vodafone Germany ended it on 2023-01-17.

The calls of 2026-10-18 and 2026-10-19 do not count: they ran before `data-2026.10` was loaded.

**What the check covers.** One SIM of one network (26202) on one phone and software stack: the S20 with LineageOS 23.2 and PHH IMS. On that SIM it covers mobile data, IMS registration, and outgoing calls over LTE and Wi-Fi. The packet counts show that the media path carried RTP both ways. They do not show that a voice was heard. The check says nothing about:

- incoming calls;
- MMS on any network;
- other networks' rows;
- emergency calls.

## If releases stop

Keep the last release until its `stale_after`, then switch back to your ROM's own list (on the S20 tree, `LINEAGE_APN_SOURCE=lineage`).
