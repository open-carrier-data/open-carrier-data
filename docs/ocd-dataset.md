# The OCD dataset for the owner's ROM

Rule round 30 (2026-10-25) replaces Google's carrier data on the owner's ROM with OCD's own dataset. Rule round 31 (2026-10-28) opens it to every ROM whose builder chooses it, keys records by cell, and publishes the F5 and group A reads with each commit. OcdCarrierSettings in the owner's build reads it, the OCD Check owner app pulls it from validated `main` pinned per commit, and the ROM pin step bakes it into the build as the last resort. For every other consumer it is reference data: it is not a release asset, and AV2 and T1 are unchanged for anyone else's ROM.

`tools/ocd_dataset.py` writes and checks it from one checkout of `main`. The private publisher writes the Google lane first, then runs it on every publish; the report bot runs it when the owner's measured records change. `validate` checks every file on every pull request.

## The files

One set per commit of `main`:

| Role | Path | What it holds | Cap |
|---|---|---|---|
| manifest | `generated/ocd-dataset/manifest.json` | the data digest, `generated_at`, every other file with its size and SHA-256, the dataset digest, counts | 256 KiB |
| profiles | `generated/ocd-dataset/profiles.json` | the closed key registry, groups A, B and X6, and every network's profiles with OCD's match rules, values and Google-lane fill | 32 MiB |
| google_lane | `generated/ocd-dataset/google-lane.json` | the Google lane's values as source family `google` | 8 MiB |
| device_records | `generated/devices/device-records.json` | the per-device records of the owner's devices | 4 MiB |
| apn_xml | `generated/android/apns-conf.xml` | OCD's APN file, unchanged | 16 MiB |
| apn_index | `generated/ocd-dataset/apn-index.json` | each APN row's line, key and profiles | 16 MiB |

The whole set, with the `pin.json` a fetcher writes beside it, stays under 64 MiB. On 2026-10-25 it was about 14 MB: 3,147 networks, 6,440 profiles (66 of them fill-only), 1,314 Google entries, 25,103 APN rows and 5 records. Files are plain UTF-8 JSON with sorted keys. The large members (`networks`, `keys`, `rules`, `entries`, `rows`, `records`) have one item per line, so a diff shows one network, rule or row per line.

- **Digests.** Every file but the manifest names `based_on_data_digest`, and the manifest names `data_digest`. Both are OCD's data digest of the publish, the same value as in `generated/android/metadata.json` and the `apns-conf.xml` header. `dataset_digest` is SHA-256 over, for each listed file in byte order of its name, the three lines `name`, `sha256` and `bytes`.
- **Order.** Of two datasets with different `dataset_digest`, the one with the later `generated_at` is newer. `generated_at` changes only when a file changes; on a pull request, `validate` refuses a changed dataset whose `generated_at` is not later than `main`'s.
- **The pin.** A file cannot name the commit that contains it. Whoever fetches the set writes `pin.json` beside it, with the commit and each file's git blob SHA-1: the owner app for a download, the ROM pin step for the build. It is never on `main`.
- **Strict reading.** A repeated member, NaN or Infinity, an unknown member, an unknown `schema_version`, a key outside the registry or a value of another type makes the whole set unreadable. `tools/ocd_dataset.py validate` runs the reader's checks 4 to 10 of the spec: manifest, sizes, SHA-256, dataset digest, data digest agreement, strict parse, closed and typed keys with their domains, specificity, network copies, APN version 8 and the APN index.

## Profiles

`networks` is keyed `<mcc>-<mnc>`, with the MNC as the SIM reports it: `302-37` and `302-370` are different networks. A profile that lists several networks appears in full under each, with its own fill list per network. Each network's profiles are in OCD's resolve order: specificity, then `id` in byte order.

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
5. The most specific profile that holds serves. With none, `default` serves, and with no SIM, `no_sim`.

`python3 tools/ocd_dataset.py match --mcc 262 --mnc 07 --imsi 262075000000001` shows the stack, the serving profile and the fill a synthetic SIM gets. `python3 tools/ocd_dataset.py ties` lists the profiles of equal specificity that one SIM can match together; the later `id` serves.

### The Google-lane fill

For the keys a profile does not publish, the phone takes the value of the Google entry whose rule matches the profile's selector. `fill` is the ordered list of the Google entries compatible with the profile on that network, computed from Google's own rule order:

1. A rule without MVNO data ends the list.
2. An MVNO rule is skipped unless the profile uses the same dimension with a value one SIM could also satisfy.
3. A compatible rule is added with its condition (`when`). When every SIM the profile matches also satisfies it, it is added without a condition, and the list ends there.

The phone takes the first item whose `when` is null or holds for the SIM. MTS Mobility's profile on 302-370 (GID1 `2C` or `4D`), for example, gets `mts_ca` for GID1 `2C` SIMs and `fido_ca` for the rest.

### Fill-only profiles

Every Google rule without an OCD profile of exactly its match (the same single network and the same single selector) becomes a fill-only profile. Its `id` is `fill.<mcc><mnc>.` plus the first 12 hex digits of SHA-256 over `google-rule\n<name>\n<mcc>-<mnc>\n<kind or "none">\n<value or "">`. It has no values and no APN rows. At equal specificity an OCD profile wins, because `fill.` sorts before `open.`. On 2026-10-25 there were 66: 46 IMSI rules, 14 network rules (test PLMNs among them), 5 SPN rules and 1 GID1 rule.

## The Google lane

`google-lane.json` holds Google's CarrierSettings data for one Pixel (`provenance`: the device, the build, the carrier list and `others` versions, the adevtool snapshot) as OCD's source family `google`, like Samsung or Apple:

- `rules` is Google's `carrier_list` in file order, one item per carrier ID, without Google's `000000` default rule.
- `entries` holds each entry's CarrierConfig values, `default` and `no_sim` included.

These are derived values, not Google's files (rule 2). Rule 3 still holds for them:

- An IMSI rule of 14 or more characters is left out: a full IMSI is 15 digits. On 2026-10-25 that was one rule, `cellcomroaming_gb` on 234-50.
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

**Group B** holds the metered lists, `carrier_metered_apn_types_strings` and `carrier_metered_roaming_apn_types_strings`. The phone serves the first of these that contains `default`: OCD's value, the Google value, Android's default.

**X6** holds the SMS-to-MMS keys on the networks that ended MMS (262-01, 262-02, 262-03, 262-07, 262-23, 228-01 to 228-03, 270-01).

OcdCarrierSettings enforces groups A, B and X6 with its own compiled-in copy as well, whatever the data says.

## Records by cell (rule round 31)

Rule round 31 (2026-10-28) keys records by cell. OCD is carrier data: its index is the carrier profile, and where a fact also depends on the device, the index is the device and the carrier together. No OCD record is keyed by device alone. A value whose reason holds on every carrier is a device quirk and belongs in the ROM's device tree; a value a test measured on a device with a carrier is an OCD cell record.

A cell record ([`schemas/cell-records.schema.json`](../schemas/cell-records.schema.json), `device-records.json` with `schema_version` 2) belongs to one cell:

- the device: `device.codename` (`Build.DEVICE`) and `device.model`;
- the carrier: an OCD or fill-only profile (`{"scope": "profile", "profile_id"}`), or for a SIM without one, MCC-MNC plus GID1 or SPN (`{"scope": "sim_key", ...}`);
- the ROM: `rom.family` (`aosp`, `lineageos`, `stock` or `other`), `rom.line` (for example `24.0`) and `rom.forks`, the sorted names of the builder's forks the result can depend on, as the build declares them;
- the IMS stack: `ims_stack.id` with `ims_stack.fork`.

It also states `rom.incremental` (`Build.VERSION.INCREMENTAL`) and `ims_stack.version`. These are recorded, not matched: a changed incremental or stack version makes the record due for a test at once on a phone with the tester. The kind is `measured` only, and so is the claim; there is no `second_agent_read`, because group A and group B keys are refused in a cell record.

`record_key` is `r:` plus the first 16 hex digits of SHA-256 over ten lines joined with `\n`: kind, device codename, upper-cased model, ROM family, ROM line, the ROM forks joined with commas (empty for none), IMS stack id, IMS stack fork (empty for none), the carrier text (`profile:<id>`, `sim:<mcc>-<mnc>:gid1=<upper GID1>` or `sim:<mcc>-<mnc>:spn=<SPN>`) and the target text (`config:<key>`, `apn:<row_key>` or `emergency_data:<row_key or default>`). Two vectors:

| Cell | Target | `record_key` |
|---|---|---|
| x1s, SM-G981B, lineageos 24.0, forks `ocd`, aosp_imsstack fork `ocd`, `profile:open.26207.c07dcc040b58` | `config:carrier_volte_available_bool` | `r:3e3c08bfd829cafe` |
| x1s, SM-G981B, lineageos 24.0, no forks, aosp_imsstack without fork, `sim:262-02:gid1=FF` | `apn:a:f3b816097ac0ee1b` | `r:282f49c73c83c8bb` |

Serving:

- A record is served as a value only in its exact cell.
- In a neighbouring cell (same device and carrier, another ROM family, line, forks or stack), it may only be tried as the first candidate, and only where a tester runs. It is never served there without a test.
- The app tries no candidates, and writes no record, for a key the ROM's device override sets on that phone.
- Last, after carrier values and cell records, the ROM applies LineageOS's fixed key and its device override (`carrier_config_override.xml`), also when the dataset fails to load.

**The transition.** `validate` refuses every record without a carrier key and every `configured_device` record (`record_no_carrier`, `record_kind`), with one exception: the S20's five round 30 records below stay until the build with the restored device override has passed on the phone (round 31, implementation order step 8). Public main serves `device-records.json` in `schema_version` 1 until then, because every reader on a phone today parses that format; cell records the owner build sends meanwhile wait in `devices/records/measured.json`. A prepared change drops the five records and the kind at step 8, and the switch to `schema_version` 2 follows once the readers on the phones parse it. A round 30 measured record does not carry over into `schema_version` 2: its cell lacks the ROM forks and the incremental, so it is due for a new test anyway.

## Per-device records (round 30)

`generated/devices/device-records.json` ([`schemas/device-records.schema.json`](../schemas/device-records.schema.json)) is written from `devices/records/`:

- `configured/*.json` holds the owner's devices' fixes, valid for every carrier (`configured_device`). It is changed only by reviewed pull requests.
- `measured.json` holds the owner's measured records, written by the report bot from the owner's `ocd-device-record` issues, one record per issue, from user ID 122638570 only ([community/README.md](../community/README.md#the-owners-measured-records)), each for 90 days after its last measurement.
- `keys.json` gives the registry entries of the keys records use.
- `reads/` holds the second-agent reads that group A records need.

A record is keyed by its device, ROM line, IMS stack with its fork, carrier scope and target, and its `record_key` is `r:` plus the first 16 hex digits of SHA-256 over those nine lines. It never holds a phone number, IMSI, ICCID, IMEI, SIP URI or IP address.

The S20's five records (x1s, SM-G981B, LineageOS 24.0, AOSP ImsStack, every carrier):

| Record | Key | Value | Served |
|---|---|---|---|
| `r:40ee9931e862c76c` | `imsvoice.voice_on_default_bearer_supported_bool` | true | yes |
| `r:63d82c4e3fa3a0ae` | `imsvoice.voice_on_default_bearer_in_roaming_without_qos_bool` (fork `ocd`) | true | yes |
| `r:5e72fea0c8d2f885` | `imsvoice.audio_evs_support_bool` | false | yes |
| `r:e41c807e9f154e6a` | `gps.longterm_psds_server_1` | "" | yes |
| `r:937a114148bf73b8` | `imsemergency.skip_audio_dedicated_bearer_wait_timer_for_emergency_bool` | true | no: group A |

The fifth record is group A. It is served only with a `second_agent_read` that names a read with verdict `proceed`. The independent read of 2026-10-25 (`devices/records/reads/r-937a114148bf73b8.json`) says `hold`, for three reasons:

- the key only removes the 8 s timeout and does not stop the wait for the bearer;
- on this device the default-bearer keys already apply before it;
- where it does act, a 112 call could stay in setup instead of falling back to CS.

So the record has no `second_agent_read`, and the phone serves ImsStack's default for the key. `validate` refuses a `second_agent_read` that points at a read with another verdict, record, key or value.

## Group A reads

Rule round 31 (`emergencyValues`): group A values update like every other value. Each dataset brings the Google lane's newest emergency settings with no read. A value that differs from the Google lane, from any other OCD source, is served once an independent read of that value has passed. No test can place an emergency call, so this read is the only check there is. Emergency numbers are not OCD data: OCD publishes no emergency number list and serves no number.

- **Candidates.** `tools/ocd_dataset.py` lists every group A value that differs from the Google lane: per key and value, the profiles whose own values hold it (the step-4 overlay of a profile's stack against every Google bundle its SIMs can get) and the source families behind it.
- **The read.** An agent other than the value's builder reads the key's effect in the platform and IMS stack source for that ROM family and stack, and the value's basis. It records `proceed` or `hold` with the sources it read in `devices/records/reads/group-a/<key>.<12 hex>.json` ([`schemas/group-a-read.schema.json`](../schemas/group-a-read.schema.json), `ocd-group-a-read/2`): key, value, families, profiles, ROM family, IMS stack, effect, reader, builder, time, sources read, findings (effect, basis, risk), verdict and notes.
- **Serving.** A read covers its key and value for its profiles and source families on its ROM family and IMS stack. A hold keeps the Google-lane value. A new value, a new profile, another source family or another stack needs its own read.
- **Leaving group A.** A key read (`subject` `key`) with effect `display_only` and verdict `proceed` takes the key out of group A: its registry `group` becomes null, and it follows OCD under the no-regression check. `emergency_number_prefix_string_array`, `dial_string_replace_string_array` and `international_roaming_dial_string_replace_string_array` never leave. OcdCarrierSettings still unions the data's marking with its own pattern, so it takes the exits from `group-a-reads.json`.
- **The served file.** `generated/ocd-dataset/group-a-reads.json` ([schema](../schemas/ocd-dataset-group-a-reads.schema.json)) is the S20 spec's R31.7 file, as OcdCarrierSettings protocol 3 reads it: one item per read, profile and source family (`read_id` `gar:<16 hex>`, key, value, family, profile, ROM family, IMS stack and fork, verdict, reader, time, reference), and the `display_only` key findings. CarrierSettings admits the value of the profile that sets the key only where a `proceed` item names its key, value, profile and one of the families its `sources` list, and this phone's ROM family and stack. A profile whose value has no recorded source family therefore gets no item, and its SIMs keep the Google-lane value. It is an optional dataset role (`group_a_reads`): a reader of protocol 2 refuses a manifest that lists it, and so does the S20 pin step until it knows the file. Until implementation order step 8 it sits beside the set, unlisted (`LIST_GROUP_A_READS` in `tools/ocd_dataset.py`), so every SIM keeps the Google-lane value for group A; the step 8 change lists it.
- **The status file.** `generated/ocd-dataset/group-a-pending.json` ([schema](../schemas/ocd-dataset-group-a-pending.schema.json)) lists `pending`, every candidate no read covers yet on the ROM families and stacks OCD reads for (today LineageOS with the AOSP ImsStack), the read values whose profile has no recorded basis, every key read, and the keys that left group A.
- **Who reads, and when.** OCD's checks run on free GitHub runners, where no agent runs. So the publisher lists a new candidate in `pending` (and in its pull request) the moment the data offers it, and an agent session on the owner's PC reads it (the round 30 reads were done the same way). A read is redone when the value, its basis or the stack changes.
- **Claims.** Records and screens say "configured, not tested" for a Google-lane value and "read, not tested" for a value a read admitted. They never say that emergency calls work.

On 2026-10-28 the reads ran for every non-Google group A value on `main` (32 values of 15 keys over 732 profile values) and as key reads for five display-only candidates and two named keys, on LineageOS (the 24.0 tree) with the AOSP ImsStack: 36 value reads, 27 of them `proceed`, and 7 key reads. They give 640 served items, 535 of them `proceed`; 158 profile values have no recorded basis. `allow_emergency_numbers_in_call_log_bool` and `always_show_emergency_alert_onoff_bool` left group A; `broadcast_emergency_call_state_changes_bool`, `wfc_emergency_address_carrier_app_string`, `hide_tty_hco_vco_with_rtt`, `ims_reasoninfo_mapping_string_array` and `call_forwarding_blocks_while_roaming_string_array` stay. Nothing is pending.

## F5 reads

Rule round 31, SM6: OCD's publisher runs F5's independent read for each `main` commit that changes emergency lines, and publishes the read with that commit. Build pins and runtime installs take an emergency-line change only with that read. On a phone of a device family whose emergency data test first use has passed (SM10), only a change to the APN name or the roaming protocol of a matched emergency row needs it. Releases keep their draft read.

The read is `tools/f5_read.py`: a deterministic, documented check that anyone can rerun, and that public `validate` reruns on every pull request and push. Free GitHub runners run no agent. Its lines are round 29's F5 lines: the phone-level guard's emergency items (an emergency lead gained, lost or changed, a network type left without an emergency profile, an emergency profile missing under an APN set, an emergency-named APN becoming a data lead), plus the emergency lead of a scope only one side has, against what its SIMs get on the other side. Each line is decided by the first rule that applies:

| Rule | Verdict | When |
|---|---|---|
| `android_default` | proceed | the new lead is Android's default EIMS request (`sos`, IPV4V6 both ways), or a row asking exactly that |
| `unreachable_scope` | proceed | no SIM of that MCC reports a network code of this length (Google's carrier list names at least 3 networks of the MCC, all of the other length) |
| `gap` | hold | a network type or APN set loses its emergency profile, or an emergency APN leads data |
| `foreign_name` | hold | the APN name ends in a country label Google's carrier list uses for other MCCs and never for this one (the 302/37 class) |
| `stated` | proceed | a current vendor or LineageOS's own list states this row for emergency on this scope |
| `not_stated` | hold | anything else |

`generated/ocd-dataset/f5-reads.json` ([schema](../schemas/ocd-dataset-f5-reads.schema.json)) is the chain of reads since `since`: one entry per change of the APN rows on `main`, oldest first, each with its base and head named by the SHA-256 of the APN file's `<apn>` lines (the header, which names the data digest, is left out), its lines, their digest (the first 16 hex digits of SHA-256 over the sorted lines, each ending with a newline, as the pin step computes it), one finding per line, and the verdict: `proceed`, `hold` or `no_lines`.

- **The publisher** appends the read of its change. A hold holds the publish as a draft, as a phone-guard trip does, unless an independent agent's `proceed` read of exactly those lines is committed in the private repository's `state/f5-reads/<lines digest>.json`; the read then records `method` `agent`. `validate` refuses a hold on `main`.
- **A consumer** that has APN rows R0 and takes rows Rn walks the chain back from Rn to R0 and takes the change only when every read on the way proceeds or has no lines (`python3 tools/f5_read.py chain --from R0`, with `--gate narrow --networks 262-02,262-03` after the first use). A chain that does not pass R0 refuses. The ROM pin step runs the same walk with `export_ocd_dataset.py sm6` in the private repository, which also recomputes each read's lines from the two commits.
- The chain starts at `5358c259`, the first round 30 build's pin; the four changes since then were read when the chain was published, all `proceed` or `no_lines`.

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
