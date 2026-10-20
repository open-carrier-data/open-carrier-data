# Releases

This page describes the releases of Open Carrier Data (rule decisions of 2026-10-18, rounds 20 and 21, and of 2026-10-19, round 24) and how one is made. **The first release is [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10), published on 2026-10-19.** In it `lookup.json` and `metadata.json` are supported for apps and tools, and `carrier-variants.json` as information. `apns-conf.xml` is in it but not supported yet: it waits for the S20 boot check ([below](#the-s20-boot-check-of-apns-confxml)). The tooling that drafts a release is `tools/build_release.py`, `tools/release_notes.py` and `.github/workflows/release.yml`; [compatibility.md](compatibility.md) has the compatibility policy.

## Releases so far

| Release | Published | Candidate | Notes |
| --- | --- | --- | --- |
| [`data-2026.10`](https://github.com/open-carrier-data/open-carrier-data/releases/tag/data-2026.10) | 2026-10-19 | `8cb64d63` (#280), compared with base `98fbd8b2` (#253) | The first release. Its candidate was not yet 72 hours old: the age gate was waived once, through a public pull request (#283), on the owner's direction (round 24). `release.json` records `age_gate: waived, round 24`; every other gate passed. Known issues, as its notes list them: Samsung's emergency role is not included yet (51 emergency-named rows are still typed `ims`; they come with `data-2026.11`), and 452/02 has no emergency APN profile on IWLAN. |
| `data-2026.11` | planned for about 2026-11-02 | | The normal path: a candidate at least 72 hours old, with no waiver. The waiver can never fire again, because it needs `first_base`, which the workflow refuses once a `data-*` release exists. |

## Two channels

- **`main` is the edge channel.** Every publish lands there, several times a day. It is guarded by the `validate` check and the phone guard ([how-it-is-built.md](how-it-is-built.md)), and OCD makes no other promise about it. A maintainer may still pin a `main` commit by hand. The owner's S20 did so until 2026-10-19; it now takes `apns-conf.xml` from `data-2026.10`.
- **Releases are the production channel.** A release is a git tag `data-YYYY.MM`, at most one a month, with a fix release `data-YYYY.MM.N` only for a defect in the newest release that affects phones. A bad release is marked withdrawn in its title and in the next release's notes; its tag and files stay. Tooling drafts a release from a `main` commit. The owner publishes it, or, on his direction, an agent with his token after an independent agent has read the draft (round 24). Nothing releases on a timer. A month with no candidate that passes every check has no release, and no date is promised.

Daily publishing to `main`, the phone guard, the freshness alarm and the data rules do not change.

## Tiers

| File | Tier | For |
| --- | --- | --- |
| `generated/android/apns-conf.xml` | `rom, pending the S20 boot check` in `data-2026.10`. It becomes supported once it ships in a release, the review of its emergency APN rows has ruled and its result is in that release (true of `data-2026.10`), and the S20 boot check has passed ([below](#the-s20-boot-check-of-apns-confxml)) | ROMs, at build time |
| `generated/android/lookup.json` | supported, since `data-2026.10` | apps and tools, bundled at build time |
| `generated/android/metadata.json` | supported, since `data-2026.10` | apps and tools; a ROM's build log |
| `generated/devices/carrier-variants.json` | supported as information, since `data-2026.10`; never an export | apps |
| `generated/android/carrier-config-list.xml` | not supported for ROM application, and not a release asset, until the per-key review of its emergency, TTY, RTT, WPS and `iwlan.*` keys has run and been implemented | reviewers; a maintainer doing their own review |
| `carriers/open/`, `generated/index.json`, `generated/evidence-index.json`, the other files under `generated/devices/` | reference: in the tagged tree, with no further promise | the resolver, `--explain`, reviewers |

## What a release contains

Each file below is an asset of the GitHub release:

- the four files of the table above, each byte-identical to the file in the tagged commit. `carrier-config-list.xml` is not one of them; `release.json` lists its path and SHA-256 as a reference file;
- `release.json`: the tag, the commit and its date, the previous release and its commit, the cut time, the age gate's result (`passed`, or `waived, round 24` for the first release), `data_digest`, `checks_through`, `stale_after` and the days left, the APN database version; per file its path, tier, size, SHA-256, `schema_version` and the SHA-256 of its schema in the tag; the counts (profiles, APN rows, rows typed `emergency`, the emergency types left out by reason, CarrierConfig blocks, key lines and safety-class lines); the phone guard's verdict, trips and report counts; the "needs review" reasons; the "Reset to default" scopes and every internet, attach and MMS lead change; every profile ID added and removed; the announced changes;
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

5. **Read the draft.** It is a draft release with the seven assets and no tag yet. Read "Needs review" first, then the phone guard, the IMS and emergency sections and the CarrierConfig safety lines. When an agent will publish it (step 6), a second, independent agent does this read first and also checks the SHA-256 of the four data files against the rehearsal (step 2); any mismatch stops the release. An optional line may record an owner check on the S20 (attach, data, MMS, IMS registration, the APN list after "Reset to default"; never an emergency call).
6. **Publish it**: the owner, or under round 24 an agent with the owner's token on his direction, after the independent read of step 5. The `release` environment's admin bypass is never used. GitHub creates the tag `data-YYYY.MM` at the candidate then. A draft not published within 14 days is deleted, and the month starts again.
7. **Check it** like a consumer:

   ```sh
   gh release download data-YYYY.MM -R open-carrier-data/open-carrier-data -D data-YYYY.MM
   cd data-YYYY.MM && sha256sum -c SHA256SUMS
   ```

**Withdrawing a release.** The owner puts "Withdrawn:" in its title and the reason in its notes, and the next release repeats it. The tag and the assets stay.

## The S20 boot check of apns-conf.xml

`apns-conf.xml` becomes supported for ROMs only after the owner's S20 has run a release with its APN list loaded and passed the boot check with a SIM: the right file and row count, mobile data, MMS, IMS registration, and calls. Until then `release.json` gives its tier as `rom, pending the S20 boot check`. Once the check passes, a docs pull request changes the tier in `tools/build_release.py` and on this page. The check never places an emergency call and never opens the emergency dialer.

Where the check of `data-2026.10` stands on 2026-10-20:

- **Loaded, 2026-10-19.** The release's `apns-conf.xml` (SHA-256 `8c24a482…`, `data_digest` `sha256:36d5f7eb…`) is the S20's active APN list: 22,082 stored rows, the count expected for that phone. On the owner's direction it was loaded without a new ROM build. The release file replaced the earlier copy in `/data/misc/apns/`, which the phone reads before its build's own file, and TelephonyProvider reloaded the table (`update_db`).
- **Passed, 2026-10-19, with a LIDL Connect SIM (26202):** mobile data is up on `web.vodafone.de`; VoLTE and SMS over IMS are registered; Wi-Fi calling is registered over IWLAN. Wi-Fi calling registered only after the phone's Private DNS was set to a resolver that sends ECS, because of Vodafone Germany's DNS filter ([consume.md](consume.md#wi-fi-calling-can-fail-because-of-the-wi-fis-dns-not-the-settings)). Registration alone does not show that calls work.
- **Still open:** one outgoing and one incoming call, and one MMS sent and one received.

## If releases stop

Keep the last release until its `stale_after`, then switch back to your ROM's own list (on the S20 tree, `LINEAGE_APN_SOURCE=lineage`).
