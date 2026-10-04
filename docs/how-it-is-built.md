# How the data is built

This page explains where a carrier profile comes from and why it looks the way it does. It is not a command reference. For commands, read [consume.md](consume.md).

## The pipeline in one picture

Every value in `carriers/open/` passes through the same five stages:

```text
source families          upstream repos, vendor indexes, firmware baselines
      |
candidate observations   private normalized records, one per source and carrier match
      |
the sanitizer            merges, quarantines, and strips private material
      |
carrier profiles         neutral JSON in carriers/open/, one file per match set
      |
generated files          generated/index.json, evidence-index.json, android/, devices/
```

The first three stages live in the private repo. Since 2026-09-24 a weekly GitHub-hosted job runs them for every source family except Samsung, whose lane needs firmware downloads and pinned image tools that only a self-hosted runner has. Since the same day that runner is back on the owner's machine as a user service, and the Samsung lane runs daily at 02:00 UTC in one bounded unit: up to 2,048 firmware update server probes and 50 selective CSC extractions, then a date refresh of every observation whose firmware build was confirmed current. The public repo receives carrier profiles and generated files, then its own workflow validates them. The public tools can regenerate `generated/android/` from the profiles, but they cannot rebuild profiles from sources.

## Sources become candidate observations

A source family is one upstream. Examples are the LineageOS APN repo, Apple's carrier bundle index, or a Samsung firmware baseline. An importer reads the upstream and writes candidate observations. Each observation records one carrier match set, the facts seen, the source family, the upstream revision, the date automation checked it, and, where it can be found, the date of the newest upstream entry behind it. Raw source material stays in the private repo.

[SOURCES.md](../SOURCES.md) lists every source family and its terms.

## The sanitizer merges observations into profiles

The sanitizer groups observations and applies fixed rules. The rules are:

- Grouping by exact match set. Observations with the same `mccmnc`, `spn`, `gid1_prefixes`, `gid2_prefixes`, `iccid_prefixes`, `imsi_prefix_patterns`, and `android_carrier_ids` form one profile. A different match set forms a different profile. The `spn` comparison ignores letter case, so `TELEKOM` and `Telekom` land in one profile, and the profile keeps the spelling most observations use.
- Naming. A profile takes the operator name that the most independent naming sources agree on once words like `internet` or `mms` are stripped; the number of observations breaks ties. The two Google lanes count as one naming source, and so do the LineageOS, Sony and Fairphone APN lists, which copy AOSP's list. A placeholder an importer emits when its source has no operator name, such as `LineageOS 26202` or a bare `26202`, never wins. A profile with no operator name gets the placeholder `Carrier <mccmnc>`.
- Agreement. When every source that names a fact gives the same value, the value is published. An off for a capability, or a false capability switch in CarrierConfig, also needs the evidence described below.
- Conflict omission. When sources give different values for one CarrierConfig key or one add-on key, the value is left out. The evidence index records the conflict with `resolution: omitted_from_stable`.
- APN variants. When sources disagree on one APN selector, every variant is published, because an APN list holds several rows per type by design. The evidence index records the conflict with `resolution: published_variants`. A profile lists its rows by APN. The Android files order them by the evidence behind each row, see [How the Android APN file is ordered](#how-the-android-apn-file-is-ordered).
- Usable APN values. The sanitizer removes control characters and surrounding whitespace from every APN string, SPN and display name, so Google's SPN `C Spire\r` is the same profile as `C Spire`. An MMSC without a scheme gets `http://`, because Android's MMS service opens it as a URL, and `http:/host`, `http//host` or a space after the scheme are repaired. `null`, `none` and a bare `http://` mean no MMSC. A `*` type means what Android reads from it, `ApnSetting.TYPE_ALL`: `default`, `hipri`, `mms`, `supl`, `dun`, `fota`, `ims` and `cbs`. The validator refuses a profile that breaks any of these rules.
- MMS rows need an MMSC. Android's MMS service looks the MMSC up among the SIM's `mms` rows with the APN its MMS connection uses. So a row typed `mms` without an MMSC keeps the type only when another `mms` row of the same APN and MVNO selector carries one. Otherwise it loses `mms`, and a row that served only MMS is dropped. The evidence index records the `mms_without_mmsc` gate. The validator refuses an `mms` row whose APN has no MMSC in its profile.
- Empty APNs are not published. An `ia` row with an empty APN asks the network to pick the APN, and no source says why its rows are empty; an empty APN on any other row cannot work. Every importer drops such a row. [consume.md](consume.md#rows-with-an-empty-apn) says what Android does instead.
- Empty profiles are dropped. A profile left with no APN, no CarrierConfig, no add-on, and no known capability is not written. The sanitization report counts these as `empty_profile_count`.
- Conditional capabilities. Capabilities are the one exception. A disagreement becomes `conditional` instead of an omission.
- One maker's off is not proof. A maker's or maintainer's carrier table that turns a feature off says how their phones are set up, not that the carrier lacks the feature. So a capability is `unsupported` only when the operator's own configuration turns it off, or at least two independent source families turn it off and none turns it on. An off from one family alone is published as `unknown`, and the evidence index records the gate `single_family_off:<capability>`. The LineageOS, Sony and Fairphone APN lists count as one family, as do the two Google lanes and Samsung's two lanes, the same grouping the APN ordering uses. Apple and Samsung publish only what they turn on, so their offs never count.
- The operator's own configuration. Two kinds of source count on their own, and only where it was checked: Google's CarrierSettings for its own Google Fi service (Google's carrier names `fi_us`, `fi_tmo_us`, `fi_extended_us`, `fi_at` and `fi_es`), and an AOSP CarrierConfig file whose git history shows the carrier wrote it. On 2026-10-04 that is one file, SETAR's (carrier ID 493, Aruba): both commits that wrote it are by SETAR staff. The other AOSP offs were written by Google staff and count like any other source.
- Capability switches in CarrierConfig. A false value of a key that switches a capability off on the phone is left out when one non-operator family alone sets it, so a ROM that applies the profile does not switch the feature off on that family's word. The evidence index records the gate `single_family_off:<key>`. The keys are `carrier_volte_available_bool`, `carrier_wfc_ims_available_bool`, `carrier_vt_available_bool`, `enabledMMS`, `imssms.sms_over_ims_supported_bool`, `support_ims_conference_call_bool` and `support_conference_call_bool`. No other key is affected, and true values stay. `vonr_enabled_bool` is never published.
- Corroboration for generic APNs. A low-confidence generic APN row needs a second source or a primary maintained APN source. Otherwise the `uncorroborated_generic_apn` gate drops it.
- Old single-source capabilities. A capability that rests on one source family is published as `unknown` when the newest upstream entry behind it is older than five years. The evidence index records the gate as `stale_single_source_entry:<capability>`. An entry whose date is unknown never counts as old. APN rows and CarrierConfig values are not withheld for age.
- No source-branded duplicates. A source name never becomes its own profile. Samsung and Apple observations for the same match set land in the same neutral profile.
- Certification test profiles are quarantined. A name starting with GCF, PTCRB, or Testbed, or a Samsung `network_type_capability` starting with `GCF-`, gets the reason `certification_test_profile`. The rule is `is_certification_test_profile` in the private sanitizer, `tools/sanitize_profiles.py`.

The evidence index lists `fact_sources` for every exported CarrierConfig value, APN fact and add-on whose sources are narrower than the profile's `sources`; a fact without an entry rests on all of them. A profile-wide source list is not proof for every field. Check the fact, not the profile. Capabilities have their own list, `capability_sources`: for every capability a source gives a value, the sources that turn it on and those that turn it off, whatever the profile publishes. So an `unknown` that one maker's off produced shows that maker, and a ROM can read which makers enable a feature.

`source_versions` names the exact origin behind each source family of a profile: a Pixel build ID, a Samsung firmware build, a Git commit, an Apple bundle and iOS version. To cite a fact, take the families `fact_sources` or `capability_sources` names for it, or all of `sources`, and read their versions. Where a family read several versions, the list holds all of them for the profile, not per fact.

## How the Android APN file is ordered

`generated/android/apns-conf.xml` is the file a phone loads, so its order is a decision, not a sort. Android 16 gives a SIM the rows of its scope, which is its network code and, when rows for its MVNO selector exist, that selector. It returns them in file order, and without a preferred APN it tries the first row that can serve a request first. [consume.md](consume.md) has the details. `tools/generate_android_outputs.py` therefore builds the file in four steps.

1. It leaves out every row LineageOS's `apns-conf.xsd` rejects, such as an MMSC that is an address and port without a scheme, so the file passes the schema LineageOS builds with. `metadata.json` counts these rows as `omissions.apn_rows_rejected_by_lineageos_schema`. Two values the schema rejects only because they are written out, `authtype="-1"` and `skip_464xlat="-1"`, are TelephonyProvider's defaults, so the row leaves the attribute out and stays.
2. It collapses rows that Android treats as one APN. Two rows are one APN when they differ only in their label, in their type set, or in an attribute that repeats TelephonyProvider's default, such as `carrier_enabled="true"` or `protocol="IP"`. They become one row with the union of their types, which is what TelephonyProvider makes of them when it loads the file. Rows with another APN value, protocol, credential, MTU, bitmask, MMS setting, MVNO selector or carrier id stay separate.
3. It groups the rows by scope: network code, then MVNO selector, ignoring letter case as Android does for SPN and GID.
4. It ranks each scope. A row's lead type is the first of `default`, `ia`, `mms`, `ims`, `supl`, `dun`, `xcap`, `emergency` and the remaining types that it serves, so every row that serves the internet leads with `default`. Rows come in that order of lead type. Within one lead type, these questions decide, in this order:
   1. Is the APN a real name? An APN literally named `default` comes after real names. Several lists write it where they know no APN for the network.
   2. How many independent source families give this APN value for this type in this scope? The LineageOS, Sony and Fairphone lists descend from AOSP's list and count as one family, as do the two Google lanes and Samsung's two firmware lanes.
   3. Does a primary APN source give this APN value? Primary sources ship a phone's whole APN list: LineageOS, Fairphone, Sony, Samsung OMC, Apple and the two Google lanes. GNOME's mobile-broadband-provider-info, a menu users pick from, and the AOSP, LineageOS device overlay and Samsung IMS lanes are not primary.
   4. How many families back this exact row?
   5. Does a primary source back this exact row?
   6. How many sources back this exact row?

   Rows still tied keep APN, type and label order.

A row is backed for a type by the sources whose observations support that fact: the `fact_sources` entry the evidence index lists for it, or every source of the profile when it lists none. [data-model.md](data-model.md) gives the key. The ranking reads nothing else, so anyone with the public files can reproduce it.

The rule changes the order, not the content. Every distinct APN value a source gives stays in the file, and so does every variant that differs in more than a label or a covered type set. That keeps the APN variants rule above: sources that disagree still get every variant published and recorded as `published_variants`. Before this rule the variants were ordered by APN name, so the variant that sorted first was tried first, and on many networks that was a row named `default`. Now the variant most sources back is tried first, and a primary source's row comes before a row only a menu source gives when the families tie. Collapsing only removes rows Android would have merged on load anyway.

The generator reads `generated/evidence-index.json` next to its output, or the file `--evidence-index` names. Without it every row ties, so rows fall back to APN order, with placeholders last.

## Why profiles are neutral

A profile says "the carrier tables behind this SIM configure these settings". It is a configuration, not a test result. It does not say "Samsung says this" or "Apple says this". One reason drives that choice.

A consumer needs one answer per SIM. A ROM cannot ask the user which vendor to believe.

The cost is real. When sources disagree, the consumer gets nothing for that key. The evidence index shows why, so a maintainer can go back to the sources.

## Why an MVNO can land in its host's profile

Grouping by exact match set has one visible consequence. An MVNO that no source distinguishes from its host network merges into the host's profile.

LIDL Connect runs on the Vodafone Germany network, `26202`. No source names it with an SPN, GID, or IMSI prefix. So no profile names it. A LIDL Connect SIM resolves the plain `26202` profile plus whichever `26202` SPN profile matches the SPN on the SIM. The result is Vodafone's data, which may or may not be right for that MVNO.

The limit exists because the sanitizer only publishes what a source observed. It does not invent a selector. A maintained source that publishes a tested SPN or GID prefix, or an importer/mapping change, is the way to add one.

## Why stale data is dropped after 180 days

Every source snapshot carries two dates. `revision_date` says when the upstream revision was published. `checked_at` says when automation last confirmed that revision. Freshness uses `checked_at`. Unchanged upstream content stays fresh as long as automation keeps checking it.

The sanitizer quarantines any observation whose `checked_at` is older than 180 days. The public side publishes the result as a window. `checks_through` is the oldest `checked_at` or `reviewed_range.oldest` behind the data. `stale_after` is `checks_through` plus 180 days. Both sit in `generated/android/metadata.json`. `tools/generate_android_outputs.py` copies them from `generated/evidence-index.json` when the sanitizer publishes them there and computes them otherwise. `tools/validate_public_carrier_data.py` checks that the pair agrees with every snapshot date, then compares the UTC date with `stale_after`. `tools/validate_device_catalog.py` does the same with `generated_from_checks_through` plus 180 days.

Stale is worse than missing. A missing APN row makes a phone fall back to its own defaults or ask the user. A stale row looks authoritative and sends the phone to a dead MMSC. Nobody notices until messages fail. So the project drops old data instead of keeping it.

`checks_through` is the oldest of the snapshot checks and the observation review dates. The snapshot records are re-checked weekly, so the oldest Samsung observation sets it. A Samsung observation from a superseded firmware build keeps its date until the daily Samsung run re-extracts it, so the window moves only as that queue drains. Past `stale_after` the validators warn by default and exit 0, so a clone keeps validating. The daily public job passes `--freshness fail` and opens an issue labeled `stale-data` when the validators fail, so the first alarm opens the day after `stale_after`. The other ten families are re-checked weekly by the hosted job. Samsung runs daily on the self-hosted runner, and Samsung sets the window. Run this command to see the window:

```bash
python3 -c 'print(*[__import__("json").load(open("generated/android/metadata.json"))[k] for k in ("checks_through", "stale_after")])'
```

## How old the entries behind a fact are

A check date says when automation last confirmed a source. It does not say how old the entries inside that source are. A source checked last week can still carry an APN row last changed in 2010.

So each observation also records the date of the newest upstream entry behind it. An entry is one APN row, one provider block, one CarrierConfig file or block, one Pixel carrier file, one Apple bundle, or one Samsung CSC package. The git-based lanes use the first day they saw the entry's current content, seeded from git history. Apple uses the publish date in the bundle's download URL from Apple's index. Samsung uses the build month in the CSC build string. Every date is the latest possible one, so an age read from it is a minimum. When no date can be found, none is published.

The evidence index publishes the result to the month. `newest_entry` is the newest entry behind a profile. `capability_newest_entries` gives it for each published capability. Both appear only where every supporting observation is dated. Run this command to print the oldest capabilities that are still published:

```bash
python3 -c 'import json; e=json.load(open("generated/evidence-index.json")); print(*sorted((d, k, p["profile_id"]) for p in e["profiles"] for k, d in p.get("capability_newest_entries", {}).items())[:10], sep="\n")'
```

Old is not always wrong. Where an old and a fresh entry spoke about the same fact on 2026-10-03, they agreed on VoLTE 98 percent of the time, but only 88 percent on VoWiFi and 80 percent on video calling. That is why a capability with only old evidence from one source family is published as `unknown`, and why APN rows and CarrierConfig values, which agreed more often, only show their age.

## What the public repo checks

The workflow `Validate carrier data` in `.github/workflows/validate.yml` has two jobs. `validate` runs on push to `main`, on pull requests, and on manual dispatch. It validates the profiles against the stable index and the device catalog in warn mode, runs the test scripts, and regenerates `generated/android/` to confirm nothing drifted. Then it checks `generated/android/apns-conf.xml` with `xmllint` against LineageOS's `apns-conf.xsd`. `tools/lineageos/apns-conf.xsd` is a byte copy of that schema at LineageOS `android_vendor_apn` revision `6e73ba90`, Apache-2.0 like the rest of the tools. It is the required check on `main`. Pull requests, including carrier-data ones, are untrusted input: they run through the `pull_request` trigger with a read-only token (`permissions: contents: read`), and the workflow uses no secrets. `freshness-alarm` runs daily at 04:17 UTC by cron and on manual dispatch. It runs both validators with `--freshness fail`. When they fail it opens one issue labeled `stale-data` with the validator output, and it does not open a second while one is open. When they pass again it closes that issue. It is the only job with `issues: write`, and it never runs on a pull request. The dispatch input `simulate_today` passes `--today` to the validators, so the alarm can be rehearsed before the real date arrives. GitHub disables a public repository's scheduled workflows after 60 days without a commit and emails the owner first. Every data publish is a commit to `main`, so the alarm keeps running while publishes land, and `gh workflow enable validate.yml` turns it back on after a pause.
