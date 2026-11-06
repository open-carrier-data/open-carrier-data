# The OCD dataset

Rule round 30 (2026-10-25) replaced Google's carrier data on the owner's ROM with OCD's own dataset. Rule round 31 (2026-10-28) opens it to every ROM whose builder chooses it, once the build meets the ship minimum SM1 to SM11 ([rom-builders.md](rom-builders.md)), keys records by cell, and publishes the F5 and group A reads with each commit. OcdCarrierSettings reads the dataset, the ROM's own build of the OCD Android app pulls it from validated `main` pinned per commit, and the ROM pin step bakes it into the build as the last resort. A ROM bakes it at a validated `main` commit. Today the owner's S20 is the only ROM that ships it.

`tools/ocd_dataset.py` writes and checks it from one checkout of `main`. The private publisher writes the Google lane first, then runs it on every publish. `validate` checks every file on every pull request.

## The files

One set per commit of `main`:

| Role | Path | What it holds | Cap |
|---|---|---|---|
| manifest | `generated/ocd-dataset/manifest.json` | the data digest, `generated_at`, every other file with its size and SHA-256, the dataset digest, counts | 256 KiB |
| profiles | `generated/ocd-dataset/profiles.json` | the closed key registry, groups A, B and X6, and every network's profiles with OCD's match rules, values and Google-lane fill | 32 MiB |
| google_lane | `generated/ocd-dataset/google-lane.json` | the Google lane's values as source family `google` | 8 MiB |
| device_records | `generated/devices/device-records.json` | an empty role: no result of any account is served on another phone (rule round 47) | 4 MiB |
| apn_xml | `generated/android/apns-conf.xml` | OCD's APN file, unchanged | 16 MiB |
| apn_index | `generated/ocd-dataset/apn-index.json` | each APN row's line, key and profiles | 16 MiB |

The whole set, with the `pin.json` a fetcher writes beside it, stays under 64 MiB. On 2026-10-25 it was about 14 MB: 3,147 networks, 6,440 profiles (66 of them fill-only), 1,314 Google entries, 25,103 APN rows and 5 records. On 2026-10-28, after rule 3's limits came to the Google lane (below), it had 3,146 networks, 6,394 profiles (20 of them fill-only) and 1,312 Google entries. Files are plain UTF-8 JSON with sorted keys. The large members (`networks`, `keys`, `rules`, `entries`, `rows`, `records`) have one item per line, so a diff shows one network, rule or row per line.

- **Digests.** Every file but the manifest names `based_on_data_digest`, and the manifest names `data_digest`. Both are OCD's data digest of the publish, the same value as in `generated/android/metadata.json` and the `apns-conf.xml` header. `dataset_digest` is SHA-256 over, for each listed file in byte order of its name, the three lines `name`, `sha256` and `bytes`.
- **Order.** Of two datasets with different `dataset_digest`, the one with the later `generated_at` is newer. `generated_at` changes only when a file changes; on a pull request, `validate` refuses a changed dataset whose `generated_at` is not later than `main`'s.
- **The pin.** A file cannot name the commit that contains it. Whoever fetches the set writes `pin.json` beside it, with the commit and each file's git blob SHA-1: the app for a download, the ROM pin step for the build. It is never on `main`.
- **Strict reading.** A repeated member, NaN or Infinity, an unknown member, an unknown `schema_version`, a key outside the registry or a value of another type makes the whole set unreadable. `tools/ocd_dataset.py validate` runs the reader's checks 4 to 10 of the spec: manifest, sizes, SHA-256, dataset digest, data digest agreement, strict parse, closed and typed keys with their domains, specificity, network copies, APN version 8 and the APN index. It also runs the conflict checker of rule round 45 (below).

## How a phone takes new data

Rule round 47 (item 3): a phone takes data straight from `main`, with no ROM build or release in between. "No pin" means no step between `main` and the phone; the ROM pin exists only for the baked copy. Phones cannot be pushed to, so the fastest path is the next check.

- **The check.** On an unmetered network one periodic job runs at WorkManager's 15-minute floor. It reads `generated/ocd-dataset/manifest.json` from `main` on the raw host with a conditional request and compares `dataset_digest` and `data_digest` with the installed set. It stores the ETag only after a pull for that digest finished, so a commit still in `validate` is tried again. On a metered network the check runs every 6 hours. The branch read is a hint: no data is taken from it.
- **The pull.** Only a difference starts the normal pull by commit SHA, through the API. On a metered network at most one full pull a day, and none while roaming or with Data Saver on. When CarrierSettings asks again (`status.pullAgain`), only the daily limit lifts.
- **Backoff.** On 403 or 429 from either host the app honours Retry-After, backs off and doubles up to 6 hours. Unauthenticated API reads are limited per address, and phones can share one.
- **What stays on the phone: F1 to F5.** F1, one commit SHA per pull. F2, only a commit whose `validate` passed. F3, an unknown schema is refused and the last good set stays. F4, only changed values make checks due. F5, the emergency-line read published with the commit. A set never moves back.
- **Activation.** If a SIM's served values and APN rows are unchanged, OcdCarrierSettings records the commit and skips both the notify and the proof for that SIM. If they changed, it activates at the first moment with every Guard refusal clear, not roaming, with the screen off and no media or VoIP audio.
- **Older ROMs.** An app on a ROM without skip-notify keeps the old daily pull, told by the provider's protocol version.

A bad commit that passes the checks reaches phones sooner, and the fix is the next commit. So this ships only in the ROM build that also has SM7 on every phone, the real-call watch and skip-notify, with no separate switch-on step. The baked copy keeps all its roles: app disabled, voice-loss hold and stop, crash guard, corrupt data ([rom-builders.md](rom-builders.md#how-new-data-reaches-a-phone)).

## Profiles

`networks` is keyed `<mcc>-<mnc>`, with the MNC as the SIM reports it: `302-37` and `302-370` are different networks. A profile that lists several networks appears in full under each, with its own fill list per network. Each network's profiles are listed by specificity, then `id` in byte order. That is only the file's order: since rule round 45 the reader sorts a SIM's stack by the resolution order below, which it computes from `match` and `kind`, so the file and its count-valued `specificity` stay as they were.

A profile carries:

- `match`: OCD's match rules as `lookup.json` gives them, with each network as `{"mcc", "mnc"}`. Values are OR within a dimension and AND between dimensions.
- `specificity`: the number of dimensions used besides the network.
- `values`: OCD's published CarrierConfig values for this profile alone, as `carriers/open/` gives them, not overlaid with broader profiles. A SIM's values are the overlay of its stack, generic to specific.
- `sources`: the source families behind each value, with Google's two lanes named `google`. A value whose exact source the evidence index does not record has no entry.
- `alternatives`: OCD's other current values per key and family. It is empty until the private lanes publish per-family values.
- `apn_rows`: how many rows `apn-index.json` gives the profile.
- `fill`: the Google-lane fill list, below.

**Matching** follows TelephonyProvider and the spec:

1. MCC and MNC compare exactly, as strings. A profile never matches on a prefix of the IMSI.
2. SPN compares with Java's `equalsIgnoreCase`: "Straße" and "STRASSE" differ.
3. An IMSI pattern matches when it is no longer than the IMSI and each position is `x` or the IMSI's digit.
4. GID1 and GID2 are prefixes, ignoring case. An ICCID is a prefix. A carrier ID is the SIM's carrier ID or specific carrier ID.
5. Any selector that does not hold rejects the profile. The profiles that hold form the SIM's stack, generic to specific in the resolution order, and the last one serves. With none, `default` serves, and with no SIM, `no_sim`.

**The resolution order** (rule round 45, item 3) sorts the stack by, in this order:

1. **Android's weight**, the score Android's `CarrierResolver` gives a carrier ID rule: MCC/MNC 256, IMSI prefix 128, ICCID prefix 64, GID1 32, GID2 16, PLMN 8, access rule 4, SPN 2, APN 1, for the fields the profile pins. A carrier-ID selector stays a match condition against the SIM's carrier ID; it adds the fields of Android's rules behind that ID on the SIM's network, the lowest-weight rule when the ID has several there. At equal weight a profile with a carrier-ID selector ranks above one without. The phone reads those rules from its own carrier ID table (`content://carrier_id/all`); when the read fails, or the ID has no rule on that network, the selector counts at the MCC/MNC-only weight and the phone logs it. The public tools read the same rules from `tools/aosp/carrier-id-table.json`, Android's table from the AOSP carrier list of the ROM's Android version (version 134217778, TelephonyProvider `7a49c7eb`, the S20's LineageOS 24.0 tree).
2. **Longer prefix or more fixed digits**, the selector types in weight order: IMSI (the digits other than `x`), ICCID, GID1, GID2, each the shortest of the profile's values.
3. **An OCD profile above a fill-only one.**
4. **Fewer list values.**
5. **Fewer network codes.**
6. **The profile `id`** in byte order, the later one above. It only makes the order total: the conflict checker makes sure it never decides between profiles whose served values differ.

OCD's own LIDL SIM on 262-02 does not move. On `main` of 2026-10-31 the order flips 9,768 pairs of profiles one SIM can match, nearly all only for a SIM that carries both profiles' selectors (an SPN of one MVNO and a GID1 of another, say).

**The conflict checker.** `validate` fails when two profiles one SIM can match tie up to the profile `id` and such a SIM would be served differently: a CarrierConfig key both set to different values, a different Google fill pick, or a different APN coupling. A new or changed tie of that kind blocks the publish until a source settles which profile applies; there is no baseline. On `main` of 2026-10-31 one pair ties up to the `id`, `302-720`'s IMSI patterns `302720x84` and `30272098`, and a SIM of both is served the same.

`python3 tools/ocd_dataset.py match --mcc 001 --mnc 01 --gid1 ABCD2025` shows the stack with each profile's weight, the serving profile, the step that made it serve and the fill a synthetic SIM on the test network 001-01 gets; `--imsi` takes a synthetic IMSI the same way. `python3 tools/ocd_dataset.py ties` lists the pairs that tie up to the profile `id`, what a SIM of both would be served differently, and how many pairs each step of the order puts apart.

**Golden vectors.** `tests/vectors/resolution-order.json` holds synthetic SIMs with the stack, serving profile, reason (the step of the order that made it serve) and fill pick they must get: the spec's 27 matcher vectors, the owner's SIM groups, a SIM of every profile on 262-01, 262-02, 262-03 and 262-07, every SIM case the dry run of rule round 45 lists, the remaining tie and a carrier ID without a rule. It pins the carrier ID table's version and carries the rows its carrier IDs need. `tools/order_vectors.py check` runs it against this tool and `tools/resolve_carrier_profiles.py --order android`; OcdCarrierSettings and the OCD Android app run the same file. Every SIM value in it is built from published selectors: an IMSI or ICCID is a published pattern or prefix padded with zeros and a final 1.

### The Google-lane fill

For the keys a profile does not publish, the phone takes the value of the Google entry whose rule matches the profile's selector. `fill` is the ordered list of the Google entries compatible with the profile on that network, computed from Google's own rule order:

1. A rule without MVNO data ends the list.
2. An MVNO rule is skipped unless the profile uses the same dimension with a value one SIM could also satisfy.
3. A compatible rule is added with its condition (`when`). When every SIM the profile matches also satisfies it, it is added without a condition, and the list ends there.
4. A profile that pins `iccid` and no `spn` also takes an SPN rule whose value equals the profile's name (compared as `java_equals_ignore_case` does), with its condition, and the list goes on (rule round 58). Such a SIM takes that entry only when it shows that SPN, as a Pixel does, and any other SIM stays where it was.

The phone takes the first item whose `when` is null or holds for the SIM. MTS Mobility's profile on 302-370 (GID1 `2C` or `4D`), for example, gets `mts_ca` for GID1 `2C` SIMs and `fido_ca` for the rest.

### Fill-only profiles

Every Google rule without an OCD profile of exactly its match (the same single network and the same single selector) becomes a fill-only profile. Its `id` is `fill.<mcc><mnc>.` plus the first 12 hex digits of SHA-256 over `google-rule\n<name>\n<mcc>-<mnc>\n<kind or "none">\n<value or "">`. It has no values and no APN rows. Where the weight, the prefix and nothing else tell them apart, an OCD profile ranks above a fill-only one (step 3 of the resolution order). On 2026-10-25 there were 66: 46 IMSI rules, 14 network rules (test PLMNs among them), 5 SPN rules and 1 GID1 rule. Since 2026-10-28 there are 20, with no IMSI rule: all 46 had IMSI patterns of 11 to 13 characters, which rule 3 does not allow (below).

## The Google lane

`google-lane.json` holds Google's CarrierSettings data for one Pixel (`provenance`: the device, the build, the carrier list and `others` versions, the adevtool snapshot) as OCD's source family `google`, like Samsung or Apple:

- `rules` is Google's `carrier_list` in file order, one item per carrier ID, without Google's `000000` default rule.
- `entries` holds each entry's CarrierConfig values, `default` and `no_sim` included.

These are derived values, not Google's files (rule 2). Rule 3 still holds for them:

- A rule whose IMSI or ICCID datum breaks rule 3's prefix limits is left out: an IMSI pattern is 5 to 10 digits or `x` once trailing `x` are stripped, an ICCID prefix 5 to 13 digits. It is the same `subscriber_prefix_ok` as for every other published selector (rule round 32, which applies the limits to every published file, and the judged ruling of 2026-10-28). Until then the lane kept IMSI patterns of up to 13 characters. On 2026-10-28 the limit left out 46 rules: 206-01 3, 214-10 1, 222-01 18, 234-50 23 and 313-260 1. A SIM such a rule named gets the network's next fill item, or `default`. An entry that only left-out rules named leaves the lane too; every other entry but `default` and `no_sim` is named by a rule. Nothing is kept in a left-out rule's place, and no published file, log or report gives its value or its fill-only profile id.
- A value that trips the privacy guard (the sanitizer's `BLOCK_PATTERNS`: e-mail shapes, international phone numbers, long digit runs, secret words) is left out for that entry. On 2026-10-25 that was 207 values in 179 entries, of 7 keys:
  - `imsvoice.conference_factory_uri_string` (149 entries);
  - `default_vm_number_string` (29) and `default_vm_number_roaming_string` (2);
  - `dial_string_replace_string_array` (15) and `international_roaming_dial_string_replace_string_array` (3);
  - `httpParams` (5);
  - `wifi.network_profiles_string_array` (4).

  For those keys the phone takes Google's `default` value or Android's default instead. The private publish log lists every value left out.

Each value has its key's type in `schemas/carrier-config-keys.json`.

## Keys and groups

`schemas/carrier-config-keys.json`, copied into `profiles.json` as `keys`, is OCD's closed key list:

- the public schema's 117 keys (`ocd_schema`);
- every key of the Google lane (`google`);
- the keys of the per-device records (`device_record`).

Each key has its type, its group and the IMS stack fork it exists in (`fork`). A record for a fork key is served only on a build whose IMS stack names that fork.

**Group A** holds the emergency-call keys no test can decide. They are the keys matching `emergency|e911|ecbm|(^|[._])ecm([._]|$)|wps|tty|rtt|sos|^imsemergency\.` (ignoring case), and ten named keys:

- the ruling's `call_forwarding_blocks_while_roaming_string_array` and `ims_reasoninfo_mapping_string_array`;
- the eight keys the owner added on 2026-10-25: `use_only_dialed_sim_ecc_list_bool`, the four `rilext.*` ECC and EIMS keys, `gps.es_extension_sec`, `dial_string_replace_string_array` and `international_roaming_dial_string_replace_string_array`.

Rule round 31 changes their source order (see [Group A reads](#group-a-reads)): a value that differs from the Google lane, from any OCD source family, is served once an independent read with verdict `proceed` covers it; else the Google lane's value in the newest dataset; else Android's default. A key leaves group A only on a read's finding that it changes what is shown or logged and never how an emergency, TTY, RTT or priority call, or an emergency SMS, is placed, routed, held or called back.

Rule round 31 lets group A update like other values (being built). A value that differs from the Google lane, from any OCD source family, is served once an independent read with the verdict `proceed` is on `main` for that key, value, source and profile, and for the ROM family and IMS stack it is served on. Else the newest Google-lane value serves, else Android's default. The read starts as soon as such a value appears. Keys a read finds change only what is shown or logged leave group A. OCD publishes no emergency number list, and `emergency_number_prefix_string_array` and `dial_string_replace_string_array` stay in group A.

**Group B** holds the metered lists, `carrier_metered_apn_types_strings` and `carrier_metered_roaming_apn_types_strings`. The phone serves the first of these that contains `default`: OCD's value, the Google value, Android's default.

**X6** holds the SMS-to-MMS keys on the networks that ended MMS (262-01, 262-02, 262-03, 262-07, 262-23, 228-01 to 228-03, 270-01).

OcdCarrierSettings enforces groups A, B and X6 with its own compiled-in copy as well, whatever the data says.

## Records by cell (rule round 31)

Rule round 47 (item 2) ended published records: no result of any account is served on another phone, `generated/devices/device-records.json` stays empty, and `validate` refuses a record in it. A cell stays the key of a phone's own local results, which never leave it. The format below is what readers still parse.

Rule round 31 (2026-10-28) keys records by cell. OCD is carrier data: its index is the carrier profile, and where a fact also depends on the device, the index is the device and the carrier together. No OCD record is keyed by device alone. A value whose reason holds on every carrier is a device quirk and belongs in the ROM's device tree ([rom-builders.md](rom-builders.md#device-quirks-stay-in-your-device-tree)); a value a test measured on a device with a carrier is a cell record, kept on that phone. The S20's four served values move back into its `carrier_config_override.xml`, and the bearer-wait key stays unset.

A cell record ([`schemas/cell-records.schema.json`](../schemas/cell-records.schema.json), `device-records.json` with `schema_version` 2) belongs to one cell:

- the device: `device.codename` (`Build.DEVICE`) and `device.model`;
- the carrier: an OCD or fill-only profile (`{"scope": "profile", "profile_id"}`), or for a SIM without one, MCC-MNC plus GID1 or SPN (`{"scope": "sim_key", ...}`);
- the ROM: `rom.family` (`aosp`, `lineageos`, `stock` or `other`), `rom.line` (for example `24.0`) and `rom.forks`, the sorted names of the builder's forks the result can depend on, as the build declares them;
- the IMS stack: `ims_stack.id` with `ims_stack.fork`.

It also states `rom.incremental` (`Build.VERSION.INCREMENTAL`) and `ims_stack.version`. These are recorded, not matched. The kind is `measured` only, and so is the claim; there is no `second_agent_read`, because group A and group B keys are refused in a cell record.

`record_key` is `r:` plus the first 16 hex digits of SHA-256 over ten lines joined with `\n`: kind, device codename, upper-cased model, ROM family, ROM line, the ROM forks joined with commas (empty for none), IMS stack id, IMS stack fork (empty for none), the carrier text (`profile:<id>`, `sim:<mcc>-<mnc>:gid1=<upper GID1>` or `sim:<mcc>-<mnc>:spn=<SPN>`) and the target text (`config:<key>`, `apn:<row_key>` or `emergency_data:<row_key or default>`). Two vectors:

| Cell | Target | `record_key` |
|---|---|---|
| x1s, SM-G981B, lineageos 24.0, forks `ocd`, aosp_imsstack fork `ocd`, `profile:open.26207.c07dcc040b58` | `config:carrier_volte_available_bool` | `r:3e3c08bfd829cafe` |
| x1s, SM-G981B, lineageos 24.0, no forks, aosp_imsstack without fork, `sim:262-02:gid1=FF` | `apn:a:f3b816097ac0ee1b` | `r:282f49c73c83c8bb` |

Serving:

- A phone serves its own record as a value only in its exact cell.
- In a neighbouring cell (same device and carrier, another ROM family, line, forks or stack), it may only be tried as the first candidate of a repair after a measured failure. It is never served there without a test.
- The app tries no candidates, and keeps no record, for a key the ROM's device override sets on that phone.
- Last, after carrier values and the phone's own records, the ROM applies LineageOS's fixed key and its device override (`carrier_config_override.xml`), also when the dataset fails to load.

**Since step 8.** `validate` refuses every record without a carrier key and every `configured_device` record (`record_no_carrier`, `record_kind`), and the record schema knows the kind `measured` only. The S20's five round 30 records, valid for every carrier, left `main` once the build with the restored device override had passed on the phone (round 31, implementation order step 8); their four values now come from the S20's `carrier_config_override.xml`, and builds without it are no longer rollback targets. Public main still serves `device-records.json` in `schema_version` 1, the format the readers on the phones parse; the file holds no records in either format.

## Per-device records (round 30)

`generated/devices/device-records.json` ([`schemas/device-records.schema.json`](../schemas/device-records.schema.json)) stays in the set with no records. Removing the role would make current apps refuse the whole pull. Nothing writes to it: the report bot's `measured.json` ended with rule round 47. `devices/records/` keeps:

- `keys.json`, the registry entries of keys records used;
- `reads/`, the reads: round 30's second-agent reads of group A records, and round 31's group A reads in `reads/group-a/`.

A round 30 record is keyed by its device, ROM line, IMS stack with its fork, carrier and target, and its `record_key` is `r:` plus the first 16 hex digits of SHA-256 over those nine lines. It never holds a phone number, IMSI, ICCID, IMEI, SIP URI or IP address.

Until round 31's step 8, `configured/x1s.json` held the S20's five `configured_device` records (x1s, SM-G981B, LineageOS 24.0, AOSP ImsStack, every carrier): `imsvoice.voice_on_default_bearer_supported_bool` true, `imsvoice.voice_on_default_bearer_in_roaming_without_qos_bool` true (fork `ocd`), `imsvoice.audio_evs_support_bool` false, `gps.longterm_psds_server_1` empty, and the group A `imsemergency.skip_audio_dedicated_bearer_wait_timer_for_emergency_bool` true, which was never served: its independent read of 2026-10-25 (`devices/records/reads/r-937a114148bf73b8.json`) says `hold`, and the S20's override leaves the key unset.

## Group A reads

Rule round 31 (`emergencyValues`): group A values update like every other value. Each dataset brings the Google lane's newest emergency settings with no read. A value that differs from the Google lane, from any other OCD source, is served once an independent read of that value has passed. No test can place an emergency call, so this read is the only check there is. Emergency numbers are not OCD data: OCD publishes no emergency number list and serves no number.

- **Candidates.** `tools/ocd_dataset.py` lists every group A value that differs from the Google lane: per key and value, the profiles whose own values hold it (the step-4 overlay of a profile's stack against every Google bundle its SIMs can get) and the source families behind it.
- **The read.** An agent other than the value's builder reads the key's effect in the platform and IMS stack source for that ROM family and stack, and the value's basis. It records `proceed` or `hold` with the sources it read in `devices/records/reads/group-a/<key>.<12 hex>.json` ([`schemas/group-a-read.schema.json`](../schemas/group-a-read.schema.json), `ocd-group-a-read/2`): key, value, families, profiles, ROM family, IMS stack, effect, reader, builder, time, sources read, findings (effect, basis, risk), verdict and notes.
- **Serving.** A read covers its key and value for its profiles and source families on its ROM family and IMS stack. A hold keeps the Google-lane value. A new value, a new profile, another source family or another stack needs its own read.
- **Frozen IDs (rule round 45, item 1).** Profile IDs are kept when a profile's match set changes, so a read no longer lapses by itself when its profile's selectors change. A read therefore records, in `match_set_hashes`, the canonical match-set hash of each open profile it covers (`match_set_hash` in `tools/profile_ids.py`; a read made before 2026-11-01 takes it from the profile ID, which then was that hash). It covers a profile only while the profile's current match set has that hash: otherwise its item leaves `group-a-reads.json`, the value is pending again in `group-a-pending.json`, and it needs a new read. The served files gain no member: the hash stays in the read record.
- **Leaving group A.** A key read (`subject` `key`) with effect `display_only` and verdict `proceed` takes the key out of group A: its registry `group` becomes null, and it follows OCD under the no-regression check. `emergency_number_prefix_string_array`, `dial_string_replace_string_array` and `international_roaming_dial_string_replace_string_array` never leave. OcdCarrierSettings still unions the data's marking with its own pattern, so it takes the exits from `group-a-reads.json`.
- **The served file.** `generated/ocd-dataset/group-a-reads.json` ([schema](../schemas/ocd-dataset-group-a-reads.schema.json)) is the S20 spec's R31.7 file, as OcdCarrierSettings protocol 3 reads it: one item per read, profile and source family (`read_id` `gar:<16 hex>`, key, value, family, profile, ROM family, IMS stack and fork, verdict, reader, time, reference), and the `display_only` key findings. CarrierSettings admits the value of the profile that sets the key only where a `proceed` item names its key, value, profile and one of the families its `sources` list, and this phone's ROM family and stack. A profile whose value has no recorded source family therefore gets no item, and its SIMs keep the Google-lane value. It is an optional dataset role (`group_a_reads`), which the manifest lists since implementation order step 8 (`LIST_GROUP_A_READS` in `tools/ocd_dataset.py`); a reader of protocol 2 refuses such a manifest.
- **The status file.** `generated/ocd-dataset/group-a-pending.json` ([schema](../schemas/ocd-dataset-group-a-pending.schema.json)) lists `pending`, every candidate no read covers yet on the ROM families and stacks OCD reads for (today LineageOS with the AOSP ImsStack), the read values whose profile has no recorded basis, every key read, and the keys that left group A.
- **Who reads, and when.** OCD's checks run on free GitHub runners, where no agent runs. So the publisher lists a new candidate in `pending` (and in its pull request) the moment the data offers it, and an agent session on the owner's PC reads it (the round 30 reads were done the same way). A read is redone when the value, its basis or the stack changes.
- **Claims.** Records and screens say "configured, not tested" for a Google-lane value and "read, not tested" for a value a read admitted. They never say that emergency calls work.

On 2026-10-28 the reads ran for every non-Google group A value on `main` (32 values of 15 keys over 732 profile values) and as key reads for five display-only candidates and two named keys, on LineageOS (the 24.0 tree) with the AOSP ImsStack: 36 value reads, 27 of them `proceed`, and 7 key reads. They give 640 served items, 535 of them `proceed`; 158 profile values have no recorded basis. `allow_emergency_numbers_in_call_log_bool` and `always_show_emergency_alert_onoff_bool` left group A; `broadcast_emergency_call_state_changes_bool`, `wfc_emergency_address_carrier_app_string`, `hide_tty_hco_vco_with_rtt`, `ims_reasoninfo_mapping_string_array` and `call_forwarding_blocks_while_roaming_string_array` stay.

By 2026-11-05 the data had brought 7 pending items: 107 profile values of `allow_hold_call_during_emergency_bool`, `rtt_supported_bool`, `rtt_supported_while_roaming_bool` and `ims_reasoninfo_mapping_string_array`. That day's reads (rule round 56) cover all of them in 18 records, so `pending` is empty until the data brings a new value. An independent second read turned one of them, `rtt_supported_bool` true on 311-560, 311-670, 312-130, 312-480 and 313-380, from `proceed` to `hold`, which leaves 9 `proceed` over 36 profile values and 9 `hold` over 71. The served file holds 680 items, 566 of them `proceed`, and 217 profile values have no recorded basis. 11 of the values rest only on blocks no LineageOS build applied (`unapplied_on_lineage_build`, see [the data model](data-model.md#values-a-lineageos-build-did-not-apply)), so they got a `hold`. The tooling refuses a `proceed` read on such a value, and a `proceed` already on file admits nothing. Since rule round 57 the same refusal covers `no_open_reader_match`, a value that rests only on `iccid` blocks of the device overlays or of Sony Open Devices (see [the data model](data-model.md#values-only-ocds-own-matcher-reaches)).

Since rule round 58 the same refusal covers `unapplied_on_sony_build`, a value that rests only on Sony Open Devices blocks whose build loses the `mnc`'s leading zero (see [the data model](data-model.md#values-a-sony-open-devices-build-did-not-apply)). Sony's 26 blocks whose `mnc` is a comma list give no observation since that round, so the plain rule that covered them until then has nothing left to cover. That change brought one pending value, `carrier_use_ims_first_for_emergency_bool` false on 240-01, and its read of 2026-11-06 says `hold`, so `pending` is empty again. The served file holds 508 items, 408 of them `proceed`, and 210 profile values have no recorded basis.

Rule round 61, item 4: AOSP's CarrierConfig assets are a source for a read, and they are not read on an OCD ROM. OCD's overlay points `platform_carrier_config_package` at `com.android.carriersettings`, so the assets are no lower layer and serve nothing there. Ten reads that named them as shipped or in the tree carry a dated correction in `notes`, with `read_at` and `findings` as first written. A hold on an `aosp`-family value says that its SIMs fall to the Google lane or Android's default. The 28 profiles of read `rtt_supported_bool.76ac4b69f950` with no recorded source family moved to hold `rtt_supported_bool.1381f3aecbc2`, whose `families` is empty: if a later export records a family for one of them, the value gets no item and waits in `pending` for a read. That read served nothing there, so nothing served moved.

Rule round 61, items 1 to 3: read `rtt_supported_bool.76ac4b69f950` split after a fresh read. `proceed` stands on 29 of its profiles, and 61 went to three holds: `rtt_supported_bool.5f8e0803b132` (37 profiles, 98 bundles: one maker or one file, with no Google entry or operator statement), `rtt_supported_bool.af4be128cd2a` (2 profiles, 3 bundles: against Google's own false on `fi_tmo_us` and `u264a_us`) and `rtt_supported_bool.da4a3f78a281` (22 profiles, 96 bundles: another Google entry's value on SIMs whose own entry sets nothing). On these 197 bundles the value is not admitted on this stack, and the phone reads Android's default false, on 3 of them Google's own false. No harm was found, and nothing shows these networks lack RTT. Only a Google entry or an operator statement read in full releases a held profile of the first hold. The served file holds 508 items, 347 of them `proceed`, `pending` holds one value on one profile, and 209 profile values have no recorded basis.

## F5 reads

Rule round 31, SM6: OCD's publisher runs F5's independent read for each `main` commit that changes emergency lines, and publishes the read with that commit. Build pins and runtime installs take an emergency-line change only with that read. On a phone of a device family whose emergency data test first use has passed (SM10), only a change to the APN name or the roaming protocol of a matched emergency row needs it.

The read is `tools/f5_read.py`: a deterministic, documented check that anyone can rerun, and that public `validate` reruns on every pull request and push. Free GitHub runners run no agent. Its lines are round 29's F5 lines: the phone-level guard's emergency items (an emergency lead gained, lost or changed, a network type left without an emergency profile, an emergency profile missing under an APN set, an emergency-named APN becoming a data lead), plus the emergency lead of a scope only one side has, against what its SIMs get on the other side. Each line is decided by the first rule that applies:

| Rule | Verdict | When |
|---|---|---|
| `android_default` | proceed | the new lead is Android's default EIMS request (`sos`, IPV4V6 both ways), or a row asking exactly that |
| `unreachable_scope` | proceed | no SIM of that MCC reports a network code of this length (Google's carrier list names at least 3 networks of the MCC, all of the other length) |
| `gap` | hold | a network type or APN set loses its emergency profile, or an emergency APN leads data |
| `foreign_name` | hold | the APN name ends in a country label Google's carrier list uses for other MCCs and never for this one (the 302/37 class) |
| `stated` | proceed | a current vendor or LineageOS's own list states this row for emergency on the scope it belongs to; for a gone MVNO scope, the network's plain scope its SIMs fall back to |
| `not_stated` | hold | anything else |

`generated/ocd-dataset/f5-reads.json` ([schema](../schemas/ocd-dataset-f5-reads.schema.json)) is the chain of reads since `since`: one entry per change of the APN rows on `main`, oldest first, each with its base and head named by the SHA-256 of the APN file's `<apn>` lines (the header, which names the data digest, is left out), its lines, their digest (the first 16 hex digits of SHA-256 over the sorted lines, each ending with a newline, as the pin step computes it), one finding per line, and the verdict: `proceed`, `hold` or `no_lines`.

- **The publisher** appends the read of its change. A hold holds the publish as a draft, as a phone-guard trip does, unless an independent agent's `proceed` read of exactly those lines is committed in the private repository's `state/f5-reads/<lines digest>.json`; the read then records `method` `agent`. `validate` refuses a hold on `main`.
- **A consumer** that has APN rows R0 and takes rows Rn walks the chain back from Rn to R0 and takes the change only when every read on the way proceeds or has no lines (`python3 tools/f5_read.py chain --from R0`, with `--gate narrow --networks 262-02,262-03` after the first use). A chain that does not pass R0 refuses. The ROM pin step runs the same walk with `export_ocd_dataset.py sm6` in the private repository, which also recomputes each read's lines from the two commits.
- **A runtime install** hands OcdCarrierSettings the read its emergency gate asks for (`f5_read`, round 29's `x1s-ocd-f5-read.v1`): the app walks the staged commit's chain from the installed APN rows and, when the walk takes the change, sends `base_commit` (the installed commit), `head_commit` (the staged commit), `lines_digest` (the digest of every line on the path, sorted, as above), `reader` (the chain's reader, `ocd-f5-check: …`, never the app), `read_at` (the newest read's), `verdict` `proceed` and `notes` naming the reads walked.
- The chain starts at `8cb64d63`, the commit of `data-2026.10`, so a consumer on that release can walk to any later commit. Rule round 46 moved the start back from `5358c259`, the first round 30 build's pin, with a bridge: `tools/f5_read.py backfill --onto` put the reads of the two changes between them in front of the chain and left the chain's own reads as they were. `validate` takes such a bridge only when each new read proceeds or has no lines. The two reads have 39 lines, all `proceed`: 22 by `android_default`, 16 by `stated` and 1 by `unreachable_scope`, the 302/37 row. Those commits carry no Google lane, so the rules read the carrier list of `a4675ce8`, the first commit that has one (`--lane-from`). The seven changes after `5358c259` were read when the chain was published (rules 2), all `proceed` or `no_lines`. Publish #321 (`c8811304`) went out before the publisher ran the read: rules 1 held its 8 lines (digest `a65c163bac29db48`), because they looked for the stated row of 310/240 GID 554d's fallback under the gone scope itself. An independent agent then read them (`devices/records/reads/f5/a65c163bac29db48.json`): proceed. The SIMs of that Ultra Mobile family code now take T-Mobile US's own `sos` IPV6/IPV4V6 row with `always_on`, which T-Mobile's current Google CarrierSettings and LineageOS state. Rules 2 read the fallback scope's row and give the same verdict.

## Privacy-withheld keys

Rule round 31, SM4: a build from public validated `main` alone gives every SIM its full bundle, the Google-lane keys included, and the build check lists every key that falls to Android's default because OCD withholds it for privacy. `generated/ocd-dataset/privacy-withheld.json` ([schema](../schemas/ocd-dataset-privacy-withheld.schema.json)) names each Google-lane value the privacy guard leaves out, by entry, key and guard rule, never the value. The private exporter's `check-build` reads it and lists the keys that fall to Android's default for some SIM. On 2026-10-28 those were six of the seven withheld keys: the voicemail numbers, the conference URI, both dial-string replacements and the Wi-Fi network profiles. `httpParams` is served from Google's default entry.

## Run it

```bash
python3 tools/ocd_dataset.py generate      # writes the dataset from this checkout
python3 tools/ocd_dataset.py validate      # schemas, the reader's checks 4 to 10, records, privacy, regeneration
python3 tools/test_ocd_dataset.py          # the spec's 27 matcher vectors, every published selector, the tie report
python3 tools/f5_read.py check             # the F5 chain ends at this checkout's APN rows
python3 tools/test_f5_read.py              # the F5 rules, the chain and a consumer's walk
```

The ROM pin step bakes the set at its pinned commit with the private exporter (`tools/export_ocd_dataset.py bake` in the private repository). For a commit from before the dataset existed, it generates the set from that commit's own files with this tool.
