# The OCD dataset

Rule round 30 (2026-10-25) replaced Google's carrier data on the owner's ROM with OCD's own dataset. Rule round 31 (2026-10-28) opens it to every ROM whose builder chooses it, once the build meets the ship minimum SM1 to SM12 ([rom-builders.md](rom-builders.md)). OcdCarrierSettings reads the dataset, the ROM's own build of the OCD Check app pulls it from validated `main` pinned per commit, and the ROM pin step bakes it into the build as the last resort. It is not a release asset: a ROM bakes it at a validated `main` commit or at a release's commit. Today the owner's S20 is the only ROM that ships it.

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

For them the phone serves a record entered after a second-agent read, else the Google-lane value, else Android's default. OCD's other vendor values for them stay published but are not served.

Rule round 31 lets group A update like other values (being built). A value that differs from the Google lane, from any OCD source family, is served once an independent read with the verdict `proceed` is on `main` for that key, value, source and profile, and for the ROM family and IMS stack it is served on. Else the newest Google-lane value serves, else Android's default. The read starts as soon as such a value appears. Keys a read finds change only what is shown or logged leave group A. OCD publishes no emergency number list, and `emergency_number_prefix_string_array` and `dial_string_replace_string_array` stay in group A.

**Group B** holds the metered lists, `carrier_metered_apn_types_strings` and `carrier_metered_roaming_apn_types_strings`. The phone serves the first of these that contains `default`: OCD's value, the Google value, Android's default.

**X6** holds the SMS-to-MMS keys on the networks that ended MMS (262-01, 262-02, 262-03, 262-07, 262-23, 228-01 to 228-03, 270-01).

OcdCarrierSettings enforces groups A, B and X6 with its own compiled-in copy as well, whatever the data says.

## Per-device records

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

**What rule round 31 changes here** (being built). OCD holds carrier data, and device quirks belong in the ROM's device tree ([rom-builders.md](rom-builders.md#device-quirks-stay-in-your-device-tree)). The S20's four served values move back into its `carrier_config_override.xml`, and the bearer-wait key stays unset. Once the S20 build with that override has passed on the phone, `main` drops the five records and the `configured_device` kind. From then on every record belongs to one cell (the device, the carrier profile or SIM key, the ROM family and build line with its forks, and the IMS stack with its fork), its kind is `measured`, and the validator refuses a record without a carrier key. A record is served as a value only in its exact cell.

## Run it

```bash
python3 tools/ocd_dataset.py generate      # writes the dataset from this checkout
python3 tools/ocd_dataset.py validate      # schemas, the reader's checks 4 to 10, records, privacy, regeneration
python3 tools/test_ocd_dataset.py          # the spec's 27 matcher vectors, every published selector, the tie report
```

The ROM pin step bakes the set at its pinned commit with the private exporter (`tools/export_ocd_dataset.py bake` in the private repository). For a commit from before the dataset existed, it generates the set from that commit's own files with this tool.
