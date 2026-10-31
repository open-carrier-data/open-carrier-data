# Carrier profile data model

This page lists every field of a carrier profile as `schemas/carrier-profile.schema.json` defines it, in schema order. It then lists the fields that the generated indexes add. Each section says which file the field lives in.

A carrier profile is one file at `carriers/open/<mccmnc>.<12 hex>.json`, named after its `profile_id`. Its top-level fields are `schema_version`, `profile_id`, `display_name`, `match`, `capabilities`, `depends_on`, `for_you`, `android_carrier_config`, `addons`, and `android_apns`. The schema allows no other top-level field.

## Top-level fields

The first five fields identify the profile and say when it applies.

| Field | Required | Type | Rule |
| --- | --- | --- | --- |
| `schema_version` | yes | integer | always `1` |
| `profile_id` | yes | string | `open.<mccmnc>.<12 hex>`, matches the file name; `<mccmnc>` is one of the profile's network codes. Since rule round 45 (item 1) an ID is assigned once and kept. A new match set gets the first 12 hex digits of a SHA-256 over it (`hash_id` in `tools/profile_ids.py`, hashed again with a counter when that equals a live or retired ID). The ID stays while the profile covers exactly the same SIMs, or across a change an accepted continuity entry allows; any other change of its SIMs, and every split or merge, retires it into `aliases/ids.json` with the profile or profiles its SIMs match now ([Profile ID aliases](#profile-id-aliases)). Until then the ID was the hash of the current match set, so a change of selectors replaced IDs: when Samsung's networks moved from network-name SPN selectors to Samsung's own SIM rules (change 32), 2,149 profiles keyed by a network name left, 512 profiles under Samsung's rules were added, and the profile count fell from 7,997 to 6,360 (dry run of 2026-10-13) |
| `display_name` | yes | string | 1 to 120 characters |
| `match` | yes | object | see the match selector table |
| `capabilities` | yes | object | see the capabilities table: what the phone should be set up to try (the configure answer) |
| `depends_on` | no | object | why a `conditional` capability is not single (rule round 45, item 4); see [Two answers per feature](#two-answers-per-feature) |
| `for_you` | no | object | whether this customer has the feature, as an admitted operator or brand statement states it (rule round 45, item 4); see [Two answers per feature](#two-answers-per-feature) |
| `android_carrier_config` | no | object | see the carrier config section |
| `addons` | no | object | see the add-ons section |
| `android_apns` | no | array | see the APN row table |

## Match selector fields

`match` holds the SIM and network facts a profile applies to. Within one list, any value matches. Between fields, every populated field must match. The resolver in `tools/resolve_carrier_profiles.py` implements this rule.

| Field | Required | Item type | Rule |
| --- | --- | --- | --- |
| `mccmnc` | yes | string | 5 or 6 digits, at least one, unique |
| `gid1_prefixes` | no | string | 1 to 32 hex characters, unique |
| `gid2_prefixes` | no | string | 1 to 32 hex characters, unique |
| `iccid_prefixes` | no | string | 5 to 13 digits, unique |
| `imsi_prefix_patterns` | no | string | 5 to 10 characters from digits and `x`, unique, starting with one of the profile's `mccmnc` (`x` matches any digit) |
| `spn` | no | string | 1 to 80 characters, unique |
| `android_carrier_ids` | no | integer | 0 to 1000000, unique |

`lookup.json` derives `specificity` from these fields. It counts how many of the six optional fields are populated. A profile with only `mccmnc` has specificity 0. It also derives `weight`, Android's weight of the profile on each of its network codes (below).

## Capability names and values

`capabilities` maps each capability name to one status. The schema allows these ten names and no others.

| Capability | Meaning |
| --- | --- |
| `volte` | voice over LTE |
| `vowifi` | Wi-Fi calling |
| `vonr` | voice over 5G NR |
| `video_calling` | IMS video calls |
| `sms_over_ims` | SMS carried over IMS |
| `mms` | multimedia messaging |
| `rcs` | rich communication services |
| `esim` | embedded SIM support. No source gives it today, so it is `unknown` in every profile |
| `ims_conference` | IMS conference calls |
| `wifi_calling_roaming` | Wi-Fi calling while roaming |

Every capability takes one of four values. A value says what carrier tables configure for the SIM. It is a configuration, not a test result and not a statement that the operator still offers the service: no profile has been checked on a phone, and carrier tables can keep a service long after the operator ends it.

| Value | Meaning |
| --- | --- |
| `supported` | at least one phone maker's or OS carrier table turns the feature on for this SIM, or for Samsung VoNR offers the user its switch (`capability_basis` names that weaker basis), and no source whose off counts turns it off. The switch counts only where the pack serves the carrier: on a KT phone only for KT's networks, and never from Samsung's open-market US pack (XAA). Samsung's and Apple's offs never count, including a Samsung carrier pack that switches a feature off on some phone models. It is a configuration, not a test result: the feature may still be off on a given phone, or on phones the carrier has not approved. For `volte`, `vowifi` and `video_calling` it is also published against an off that one non-operator family alone gives, when every such off is an `off` record in `generated/devices/carrier-variants.json`, at least one record there says `on`, and the on would publish standing alone; `capability_sources` keeps the off, the gate `single_family_off:<capability>` names it, and `capability_newest_entries` gives the on side's month. Such a `supported` says that some phone models' own files turn the feature on and that the device file lists every model whose own file turns it off; it never says that every model, or yours, has it on ([Device records](#device-records)) |
| `unsupported` | the operator's own configuration turns it off, or at least two independent source families turn it off and none turns it on. Since rule round 32, for `mms` only, also an admitted operator statement that MMS ended network-wide, with `operator_statement` as the off source (below) |
| `conditional` | sources disagree, also between the current devices of one source; Google's frozen Pixel copies do not count where Google's current file gives a value. For `volte`, `vowifi` and `video_calling` an on against one family's off stays `conditional` only where that off is not visible in the device records (older than five years, a codename two catalog devices share, two files of one device that disagree), no device record says `on` (the on comes only from a carrier-wide table, such as Samsung's IMS table or Apple's bundles, or from device files older than five years), or the on would not publish standing alone |
| `unknown` | no usable source. That includes a single maker or maintainer turning the feature off, and a capability whose only source family's newest entry is older than five years, withheld for its age or, for VoLTE, VoWiFi, MMS and Wi-Fi calling while roaming, on the evidence [how-it-is-built.md](how-it-is-built.md) describes |

Samsung's and Apple's offs never count. Both write an off almost always as a missing entry: 3,622 of 3,674 offs in Samsung's tracked IMS table, and most iPhone bundles. Their written offs describe phones or defaults, not the carrier: measured on 2026-10-09, Samsung's written table offs agreed with another family's off in 2 of 9 comparable cases, Samsung's phone-pack offs in 0 of 31, and Apple's written falses in 0 of 12. Source names that copy one origin count as one family: the LineageOS, Sony and Fairphone APN lists, the two Google lanes, and Samsung's three lanes (OMC, IMS and CarrierConfig). The operator's own configuration is Google's settings for its Google Fi service and an AOSP CarrierConfig file the carrier itself submitted; [how-it-is-built.md](how-it-is-built.md) lists them. `capability_sources` in the evidence index names, for each capability, the source families that turn it on and those that turn it off.

Rule round 32 makes two changes to these values:

- **`operator_statement`** (since rule round 32, first published on 2026-10-28 for Vodafone 26202, Telefónica 26203 and 26207, 1&1 26223, Salt 22803, Sunrise 22802, POST 27001 and Maxis 50212). Where the operator states on its own page or PDF, read in full and checked by a second reader, that MMS ended network-wide on a day that has passed, `mms` is `unsupported`, `capability_sources` lists `operator_statement` under `off`, the `mms` conflict item has the resolution `operator_statement`, and `android_carrier_config` publishes `enabledMMS` false with that source. It means the operator states MMS ended, not that a table turns it off. It counts toward neither the five-year rule nor the family count. When a statement is not confirmed for 180 days, the value becomes `unknown` with the gate `operator_statement_lapsed:mms` where the tables alone give `supported` or `conditional`, and `enabledMMS` false is left out. Statements about other services never set a value.
- **Old-only offs** (published since 2026-10-28). For `volte`, `vowifi` and `video_calling`, a single family's off whose every counted observation is older than five years no longer keeps the value `conditional` when a published device record says `on` and the on publishes standing alone. The value is `supported`, `capability_sources` keeps the off, and the gate `single_family_off:<capability>` carries the reason `off_older_than_five_years` and `off_newest_entry`, the month of the off's newest entry. The device file then has no `off` record for the value, because rule 7 withholds every off behind it, and it has at least one `on` record. The validators check both.

Samsung OMC's `vonr` says less than a table that turns VoNR on. It comes from Samsung's carrier pack (OMC): when the pack's Mobile networks menu feature carries the token `+vonrcall`, Samsung's settings offer a "VoNR (Voice over 5G)" switch for that carrier on that model. So `supported` from Samsung OMC means that Samsung offers the switch on the models the evidence index lists. It does not mean VoNR is on by default, and it is not a field test. A model without the token leaves VoNR `unknown`, not `unsupported`: Vodafone Germany, for one, runs VoNR on Samsung phones that show no switch. Test and lab networks (MCC 001, the documented lab codes, test equipment and lab entries) and private networks (MCC 999) get no value, and neither does a SIM that a KT phone dims the switch for, or a network that only Samsung's open-market US pack (XAA) offers it for: an operator's pack lists only that operator's networks and brands, but XAA serves no operator, so there the token describes the phone, not the carrier. The value never becomes a CarrierConfig key, so `carrier-config-list.xml` gets no `vonr_*` key from it. `capability_basis` in the evidence index names this basis with the Samsung sales codes and models behind it. A `vonr` from `samsung_carrier_config` is a table that turns VoNR on: Samsung's own CarrierConfig sets `vonr_enabled_bool` for the carrier. It has no `capability_basis` and adds no `vonr_*` key either.

For `volte`, `vowifi`, `video_calling` and `vonr`, the profile value is a summary: the rules above applied over every source and every device's carrier table. It is never a vote or a count over devices, and no number of devices moves it. Android switches these four features on only where the device and the carrier both allow them, and most phone makers set them per phone model, so a `conditional` here usually means one model's own table differs from others'. `generated/devices/carrier-variants.json` gives one device's own table value, every device value OCD publishes, including those that agree with the profile value; a reader that knows the phone model should show that record next to the profile value ([Device records](#device-records)). Since round 17's second step, a `supported` value of `volte`, `vowifi` or `video_calling` can sit next to device records that say `off`: one family's per-device files turn the feature off, every one of those offs is in the device file, and the device file also has a record that says on. The test is what the device file shows, not how many devices it shows. The off is not hidden: `capability_sources` lists it and `single_family_off:<capability>` names it. A reader that knows the phone model shows that model's record first, as this model's own file, whatever the summary says; a model without a record gets the summary as the carrier's value, never as this phone's. For the model it names, the device record is the more specific configured fact; the summary never overrules an `off` record. A reader that has no record for the phone should say, for such a `supported`, that some phone models' own files turn the feature off. The summary is not a switch: step 2 changed no byte of `apns-conf.xml` or `carrier-config-list.xml` beyond `data_digest`, because the true switch of these values has published since 2026-10-10.

## Two answers per feature

Rule round 45 (item 4) keeps two answers per feature apart. `capabilities` stays what it was: the **configure** answer, what the phone should be set up to try, from vendor and OS carrier tables. It is unchanged byte for byte, and nothing below moves it; its rename to `configure` waits for the later rewrite of every file. Two sibling maps join it, keyed by capability name. `tools/two_answers.py` derives both from published files, the private publisher writes them in its device-records step, `generate_android_outputs.py` copies them into `lookup.json`, and `validate` checks that every profile carries exactly what the tool derives.

**`depends_on`** appears only for capabilities whose value is `conditional`, and says why the value is not single, as a sorted list:

| Reason | When |
| --- | --- |
| `device` | `generated/devices/carrier-variants.json` records an `on` and an `off` for the capability on different devices of one software stack |
| `firmware` | it records one device `on` under one stack and `off` under another (its own firmware against a LineageOS or AOSP tree) |
| `ims_stack` | a record keyed by IMS stack backs the capability; none does yet, so no profile carries it |
| `sources_disagree` | the evidence index records a conflict of source families for the capability, or no record gives another basis |

A reason other than `sources_disagree` is set only where the device records give that basis.

**`for_you`** appears only where an admitted operator or brand statement that has not lapsed (`generated/operators/statements.json`) gives a state. A missing entry means unknown. Each entry has `state`, the `statements` it rests on, and on a plain profile shared with host-only brands `reason` and `brands`:

| State | From |
| --- | --- |
| `ended` | a statement that the service ended |
| `not_offered` | a statement that the brand does not offer it |
| `depends_on_plan` | a statement that the brand offers it: whether the person's plan includes it is not checked. Also the cap on a plain profile shared with host-only brands, with `reason` `brand_not_tellable` |
| `included`, `free_option`, `paid_option` | only a statement whose status says exactly that for that brand; none does yet |

The statements map to capabilities as `wifi_calling` to `vowifi`, `wifi_calling_abroad` to `wifi_calling_roaming`, and `mms`, `volte`, `vonr` and `esim` to themselves; `volte_roaming` and `5g_sa` have no capability. A statement must name every network code of the profile. A network-wide statement (an operator's MMS end) reaches every profile of its network. A brand's statement reaches a profile only when the carrier-identity table maps that profile to that brand alone: the profile has a selector, only that brand's entry lists it, and no other entry has a rule on the same selectors that shares some of its SIMs without being narrower or wider (a SIM both match could be either brand's). On a network where host-only brands ride, such as LIDL Connect on 262-02, a phone cannot tell their SIMs from the host's, so the plain profile never takes the host's or one brand's state: where any of those brands states something, its `for_you` is `depends_on_plan` with `reason` `brand_not_tellable` and the names of the host and the host-only brands. `for_you` never comes from one SIM, an account read or a field record, and it never feeds `capabilities`, CarrierConfig, APN rows, the OCD dataset or a test decision; against the base, `validate` fails a profile whose `capabilities` change with its `for_you` or `depends_on` while its capability evidence does not.

Show `for_you` as what the brand states about availability, with the words that the person's plan is not checked, and `capabilities` as what the phone is set up to try. Neither says that a feature works or is booked.

## Android carrier config

`android_carrier_config` holds a reviewed subset of Android CarrierConfig keys. The schema names 117 allowed keys. Count them with this command:

```bash
python3 -c 'print(len(__import__("json").load(open("schemas/carrier-profile.schema.json"))["properties"]["android_carrier_config"]["propertyNames"]["enum"]))'
```

The value type follows the key suffix.

| Key suffix | Value type |
| --- | --- |
| `_bool` | boolean |
| `_int` | integer |
| `_string` | string |
| `_string_array` | array of strings |
| `_strings` | array of strings |

Thirty keys carry no type suffix. The schema types each of them by name. Examples are `enabledMMS` as boolean, `maxMessageSize` as integer, and `httpParams` as string.

A key whose value Android reads as one of a closed set of constants takes only those values (`CONFIG_VALUE_DOMAINS` in `tools/carrier_config_types.py`). Today that is `carrier_default_wfc_ims_mode_int` and `carrier_default_wfc_ims_roaming_mode_int`: 0 (Wi-Fi only), 1 (cellular preferred) or 2 (Wi-Fi preferred), Android's `ImsMmTelManager.WIFI_MODE_*`. The validator refuses any other value.

## Add-ons

`addons` holds neutral facts that do not map to one Android key. Each namespace is an object. Its keys match `^[a-z][a-z0-9_]{2,80}$`.

| Namespace | Scope |
| --- | --- |
| `emergency_calling` | emergency dial and routing policy |
| `ims` | IMS behaviour beyond CarrierConfig |
| `network_policy` | network selection and display policy |
| `operator_display` | operator name and icon rules |
| `wifi_calling` | Wi-Fi calling branding and style |

An add-on value is a boolean, an integer from -1000000 to 1000000, or a string of 1 to 160 characters. An array of up to 40 such scalars is also allowed.

## APN row fields

`android_apns` is an array of rows. Each row needs `name`, `apn`, and `types`. The schema allows no other keys than the ones below. No string holds a control character or surrounding whitespace. A row that serves `mms`, or `*`, needs an MMSC, its own or one on another `mms` row of the same APN and MVNO selector in the profile. The validator checks both.

| Field | Type | Rule |
| --- | --- | --- |
| `name` | string | 1 to 80 characters, required |
| `apn` | string | 1 to 120 characters, required |
| `types` | array of strings | required, unique, from the type list below |
| `mmsc` | string | up to 240 characters, a URL with a scheme such as `http://` |
| `mmsproxy` | string | up to 120 characters |
| `mmsport` | integer | 1 to 65535 |
| `proxy` | string | up to 120 characters |
| `port` | integer | 1 to 65535 |
| `server` | string | up to 120 characters |
| `user` | string | up to 120 characters |
| `password` | string | up to 120 characters |
| `authtype` | integer | -1 to 3 |
| `bearer` | integer | 0 to 100 |
| `bearer_bitmask` | string | up to 120 characters |
| `network_type_bitmask` | string | up to 120 characters |
| `lingering_network_type_bitmask` | string | up to 120 characters |
| `infrastructure_bitmask` | string | up to 40 characters |
| `mtu` | integer | 0 to 10000 |
| `mtu_v4` | integer | 0 to 10000 |
| `mtu_v6` | integer | 0 to 10000 |
| `carrier_id` | integer | -1 to 1000000 |
| `profile_id` | integer | 0 to 1000000 |
| `apn_set_id` | integer | -1 to 1000000 |
| `skip_464xlat` | integer | -1 to 1 |
| `max_conns` | integer | 0 to 1000000 |
| `max_conns_time` | integer | 0 to 1000000 |
| `wait_time` | integer | 0 to 1000000 |
| `user_visible` | boolean | |
| `user_editable` | boolean | |
| `carrier_enabled` | boolean | |
| `modem_cognitive` | boolean | |
| `always_on` | boolean | |
| `esim_bootstrap_provisioning` | boolean | |
| `mvno_type` | string | `spn`, `gid`, `imsi`, or `iccid` |
| `mvno_match_data` | string | 1 to 120 characters; an `imsi` value starts with one of the profile's `mccmnc` (`x` matches any digit) unless the row has a `carrier_id` |
| `protocol` | string | `IP`, `IPV6`, `IPV4V6`, `PPP`, `NON-IP`, or `UNSTRUCTURED` |
| `roaming_protocol` | string | same values as `protocol` |

The allowed `types` values are `*`, `default`, `mms`, `supl`, `dun`, `hipri`, `fota`, `ims`, `cbs`, `ia`, `emergency`, `mcx`, `xcap`, `vsim`, `bip`, `enterprise`, and `rcs`. `cbs` is Android's type for carrier branded services, not cell broadcast: OCD publishes no emergency-alert (cell broadcast) channels, which Android takes from its own per-country and per-carrier CellBroadcastReceiver configuration.

## Stable index entries

## Profile ID aliases

`aliases/ids.json` ([`schemas/profile-id-aliases.schema.json`](../schemas/profile-id-aliases.schema.json)) is the other half of the ID registry (rule round 45, item 1): the live IDs are the files in `carriers/open`, the retired ones are here. The private sanitizer writes it with `tools/profile_ids.py`, the one ID function every writer and validator uses, and entries are only ever added.

| Field | What it holds |
| --- | --- |
| `aliases` | one entry per retired ID, sorted by `id`: `kind` (`replaced`: one new profile took its SIMs; `split`: several did; `merge`: one new profile took the SIMs of several retired IDs; `withdrawn`: no new profile took them), `to` (the profiles a SIM of the old rule provably matches in the data it was retired in: the most specific covering profiles and every profile that takes part of its SIMs; a rule on other selectors is not counted), `match` (the retired match set), `match_set_hash` and `retired_on` |
| `continued` | one entry per live ID whose match set is not the one it was issued for: `basis` `same_sims` (the same SIMs written differently, proved by the tool) or `continuity_entry` (a continuity entry the tool computed for a replacement and a reviewer accepted in private `state/id-continuity.json`), the hashes before and after, and `since` |

The **canonical match-set hash** of a profile is the hash part of `hash_id` over its normalised match set (lists sorted, without duplicates). For an ID issued from a match set that is still its own, it equals the ID's last 12 hex digits. Every record keyed by a profile ID, a group A read and a measured or cell record, stores the hash it was made under in its source file (`match_set_hashes` in a read under `devices/records/reads/group-a/`, `match_set_hash` in an item of `devices/records/measured.json`); a record made before 2026-11-01 takes it from its profile ID. `tools/ocd_dataset.py` serves such a record only while the profile's current hash is that one: otherwise a group A read lapses and the value waits for a new read in `group-a-pending.json`, and a measured record is left out of `device-records.json` and is only the first candidate for the next test. An alias never carries a record or a value to another profile.

`tools/profile_ids.py check` runs in `validate`: every live ID is the issued hash of its match set or explained under `continued`, no ID is live and retired, every alias points into the registry, and every profile ID a generated file or side file names (`index.json`, `lookup.json`, `metadata.json`, `carrier-config-list.xml`, the evidence index's profiles, `carrier-identity.json`, `carrier-variants.json`, the device and cell records, the OCD dataset and the group A reads) is in the registry. Against the base commit it also checks that every base ID is still live or aliased, that alias entries are only added, that a profile covering the same SIMs as a base profile keeps that ID, that a kept ID covers other SIMs only with an accepted continuity entry, and that a new ID is the issued form for a new match set. `tools/profile_ids.py changes --base-ref <ref>` lists the IDs added and removed, every kept ID whose match set changed, with the old and new selectors, and every new alias entry; the publish pull request and the release notes carry the same list.

`generated/index.json` has `schema_version` and a `profiles` array. Each entry has `profile_id`, `display_name`, and `path`. `path` is the profile file relative to the repo root.

`generated/android/lookup.json` has `schema_version`, `match_semantics`, `resolution_order`, and `profiles`. Each entry repeats `profile_id`, `display_name`, `path`, `match`, and `capabilities`, and `depends_on` and `for_you` where the profile has them (rule round 45, item 4), and adds `specificity`, `weight`, `android_apn_count`, and `has_android_carrier_config`. `weight` (since rule round 45, item 3) maps each network code of the profile's `match` to the score Android's `CarrierResolver` gives the fields the profile pins: MCC/MNC 256, IMSI prefix 128, ICCID prefix 64, GID1 32, GID2 16, SPN 2. A carrier-ID selector adds the fields of the lowest-weight rule Android's carrier list has for that ID on that network (`tools/aosp/carrier-id-table.json`, the AOSP carrier list of the ROM's Android version), or none when it has no rule there. It is step 1 of `lookup.json`'s resolution order. **Since `schema_version` 2** (rule round 45, item 3, announced in `data-2026.11`) the profiles a SIM matches resolve generic to specific by: (1) `weight` for the SIM's network code, and at equal weight a profile with `android_carrier_ids` above one without; (2) the longer prefix or more fixed digits, the selector types in weight order: IMSI (digits other than `x`), ICCID, GID1, GID2, each the shortest of the profile's values; (3) fewer list values in `match`; (4) fewer network codes; (5) `profile_id` in byte order. OCD's dataset adds one step, an OCD profile above a fill-only one, which `lookup.json` never holds ([ocd-dataset.md](ocd-dataset.md#profiles)). Apply them generic to specific; the last one is the most specific. A profile's `android_carrier_ids` match the SIM's carrier ID or its specific carrier ID. Before `schema_version` 2 the order was `specificity`, then `profile_id`. `tests/vectors/resolution-order.json` holds golden vectors any reader can check its code against. An entry whose sources carry a check date also has `checks_through` and `stale_after`, the freshness window of that one profile. A profile's `stale_after` is the earliest day any of its observations could expire; values are not dated one by one. The file-level window in `generated/android/metadata.json` is the oldest of these, so a consumer that keeps only some profiles can read the per-profile dates instead. An entry also has `newest_entry`, the month (`YYYY-MM`) of the newest upstream entry behind the profile, wherever the evidence index publishes one; it tells you how old the profile's data is, which the check dates do not. The validator checks that it matches the evidence index. An entry whose sources carry a check date also has `checks_through` and `stale_after`, the freshness window of that one profile. A profile's `stale_after` is the earliest day any of its observations could expire; values are not dated one by one. The file-level window in `generated/android/metadata.json` is the oldest of these, so a consumer that keeps only some profiles can read the per-profile dates instead. An entry also has `newest_entry`, the month (`YYYY-MM`) of the newest upstream entry behind the profile, wherever the evidence index publishes one; it tells you how old the profile's data is, which the check dates do not. The validator checks that it matches the evidence index.

`generated/android/metadata.json` has `schema_version`, `target`, `output`, `omissions`, `data_digest`, and the file-level `checks_through` and `stale_after`. `target` names the APN database version and says that profiles needing a GID or ICCID match are left out of `carrier-config-list.xml` (`carrier_config_gid_matching` and `carrier_config_iccid_matching` are `omitted`). `omissions` counts what the files leave out: profiles whose match APN XML or CarrierConfig XML cannot express (with their IDs), APN rows LineageOS's schema rejects (`apn_rows_rejected_by_lineageos_schema`), attach and MMS types and absorbed MMS rows `apns-conf.xml` leaves out (`ia_types_left_out_not_vendor_current`, `mms_types_left_out_not_vendor_backed`, `mms_rows_left_out_absorbed_by_android`), the rows whose only effect on a lead's stored row was credentials from Google's superseded Pixel copies (`credential_rows_left_out_superseded_google_copy`, rule round 32, D8 rule 1), and the `emergency` types it leaves out, by reason: an unset protocol (`emergency_types_left_out_unset_protocol`), a row that serves another type (`emergency_types_left_out_combined`), a row no current vendor or LineageOS gives that asks for more than Android's default (`emergency_types_left_out_not_vendor_stated`), and a scope an APN set could strand (`emergency_types_left_out_apn_set`); [how-it-is-built.md](how-it-is-built.md#how-the-android-apn-file-is-ordered) has the rules. `data_digest` is `sha256:` and the SHA-256 over the profile files, `generated/evidence-index.json` and the generator's source; `apns-conf.xml` and `carrier-config-list.xml` repeat it with the licence and the freshness window in the comment they start with.

## Provenance fields in the evidence index

The evidence index is OCD's per-source record: which families give each value. `generated/evidence-index.json` has `schema_version`, `description`, `source_snapshots`, and `profiles`. It may also carry `checks_through` and `stale_after`, the freshness window that `generated/android/metadata.json` republishes, `vendor_build_grace`, `withdrawn_profiles` and `apn_removal_commits`, all described below. It never contains raw source material.

Each `source_snapshots` record describes one source family check.

| Field | Meaning |
| --- | --- |
| `source_name` | source family identifier, such as `lineageos` |
| `upstream_url` | where the source lives |
| `revision` | full Git commit, SHA-256 of the downloaded content, or for Samsung the SHA-256 of the lane's state file |
| `revision_date` | when that revision was published upstream |
| `checked_at` | when automation last fetched the source with success: the lane's liveness, not a statement that the values are current |
| `license_expression` | SPDX expression or `NOASSERTION` |
| `schema_version` | record format version, `2` on 2026-09-23 |

`vendor_build_grace` is present only while a tracked vendor firmware publishes under its grace. Samsung's IMS and CarrierConfig values (`samsung_ims`, `samsung_carrier_config`) come from one tracked firmware. When Samsung ships a new build of it and the lane has not yet rebuilt the indexes from that build, because the download failed or the space check skipped it, the previous build's values keep publishing for up to 30 days after the build was last confirmed current, instead of dropping the same day. Each item has these fields.

| Field | Meaning |
| --- | --- |
| `sources` | the source families whose values the build carries, sorted |
| `model`, `region`, `build` | the tracked firmware and the build the values were read from |
| `superseded_by` | the build Samsung's update service now reports, when it reported one |
| `confirmed_at` | the last day the build was confirmed current; not before `checks_through` |
| `grace_until` | the day the values drop unless the lane rebuilds them, 1 to 30 days after `confirmed_at` |

`withdrawn_profiles` lists the profiles that sources give but that publish no fact, because quality gates removed every fact they had: for example a network code whose only APN rows LineageOS removed, or a profile whose only fact was a withheld capability. Each item has `profile_id` (the ID the profile would have, which no published profile has), `sources`, and `quality_gates`, in the same shape as a profile's, each an omission. Items are sorted by `profile_id`. Without this list such a profile left no public trace.

`apn_removal_commits` names, for every LineageOS commit that a `lineageos_apn_removed:<commit>` gate of a profile or a withdrawn profile names, why the rows it removed are left out. Each item has `commit`, `removed_on` (the commit date), `reasons`, and, when known, `gerrit_change`, the number of the change on review.lineageos.org. `reasons` lists, sorted, the reason classes the private tombstone state records for the commit's rows that are left out: `defunct` (the commit cites a shutdown or merger), `superseded` (an old value replaced by a new one), `extra_code` (an extra network code removed while the operator's main code keeps its APNs), `moved` (moved to another code or selector), `policy` (old WAP APNs removed as a policy), `vendor_rom_absent` (deleted because one maker's ROM no longer has it), and `unclassified` (a weekly removal nobody has looked at yet). Items are sorted by `commit`, and the validator checks that the list names exactly the commits the gates name.

Each `profiles` record describes one carrier profile.

| Field | Present in | Meaning |
| --- | --- | --- |
| `profile_id` | every record | matches the carrier profile |
| `sources` | every record | source families that contributed to this profile |
| `observation_count` | every record | candidate observations merged into this profile |
| `verified_observation_count` | every record | observations confirmed on a device, `0` for every profile on 2026-09-23 |
| `fact_sources` | every record | list of `section`, `key`, `sources` for only the CarrierConfig, APN and add-on facts whose sources are narrower than `sources`, or that carry `old_build_sources`, `data_device_sources`, `superseded_pack_sources` or `shared_file_sources`; a fact without an entry rests on every source in `sources`. A profile whose `sources` lacks `samsung_omc` does not say Samsung has no settings for its network: a Samsung carrier-pack network publishes only under the SIM rules its pack states, and a network without such a rule gives no Samsung record (`how-it-is-built.md`, "Samsung selectors are Samsung's own"). An APN fact is one row with one of its types, and its key is described below the table. The sources of an APN fact are those whose observations give the row: each gives exactly its proxy, port, username and password (a missing value meaning none), for an `mms` fact also its MMS proxy and, when either gives an MMS proxy, its MMS port, and no other attribute with a different value. An APN fact may add `old_build_sources`: the Samsung sources (`samsung_omc`, `samsung_ims`) among its `sources` whose every observation behind the fact comes from a firmware build more than three years old; the APN ranking does not count them as current vendors. An APN fact may add `data_device_sources`, which is always `["samsung_omc"]`: a Samsung tablet's carrier pack (models SM-X, SM-T and SM-P), which configures a data-only device, gives the fact, and no current Samsung phone pack does (every other Samsung OMC observation behind it comes from an older build or a superseded pack); the APN ranking does not count Samsung as a current vendor for it. A fact a current phone build gives too has no such entry. An APN fact may add `superseded_pack_sources`, which is always `["samsung_omc"]`: every Samsung OMC observation behind the fact comes from a superseded carrier pack or from a firmware build more than three years old, and at least one from a superseded pack. A pack is superseded for the fact's type when the newest OMC version (Android major) of its sales code that states its SIM rule states it only under other network names, one of them stated at two or more versions and none reversed for the same rule in another sales code, and that newest version gives the type; the pack's rows stay. The APN ranking does not count Samsung as a current vendor for it. It never appears with `old_build_sources` naming `samsung_omc`. An APN fact may add `shared_file_sources`, which is always `["google_carriersettings"]`: every Google CarrierSettings observation behind the fact comes from Google's shared `others` file, and no maintained per-carrier source (a Google per-carrier file, or a Samsung phone build at most three years old from a pack not superseded for that type) gives the same APN value for that type on any of the profile's network codes, and Google's frozen Pixel copies (TheMuppets) of the same entry do not show that Google edited its values for that type (a copy gives a value for the type that the current file no longer gives); the APN ranking does not count Google as a current vendor for it. The shared file's date is the file's, not the entry's. Capabilities are in `capability_sources` |
| `capability_sources` | some records | capability name to `on`, `off` and `conditional`, each a list of the sources whose observations turn the capability on, turn it off, or call it conditional. It lists every capability a source gives a value, whatever the profile publishes, and is present whenever the profile publishes a capability other than `unknown` |
| `capability_basis` | some records | capability name to what its value rests on, where a source's `on` says less than a table that turns the feature on. Only `vonr` from `samsung_omc` has one, with `basis` `samsung_vonr_switch`; it is described below the table |
| `observed_scope` | some records | device and firmware scope of the observations |
| `observed_model_source_groups` | some records | `models` and `sources` pairs when a model was named by fewer sources than the profile |
| `reviewed_range` | some records | `oldest` and `newest` review dates |
| `newest_entry` | some records | month (`YYYY-MM`) of the newest upstream entry behind the profile, present only when every observation is dated |
| `capability_newest_entries` | some records | capability name to the month of the newest upstream entry behind that capability's value, present only when every supporting observation is dated. It covers every capability `capability_sources` names, also one a gate publishes as `unknown`, so the age of a withheld value stays visible |
| `flags` | some records | informational marks that withhold nothing, each `section`, `key` and `flag`, sorted: `old_single_source` on a capability whose value rests on one source family whose newest entry behind it is more than five years old. A capability the five-year rule withholds never sits next to its capability-gating CarrierConfig key, which is left out with it; the flag `capability_label_withheld`, which marked such a key until 2026-10-06, is refused |
| `conflicts` | some records | facts omitted, made conditional, or published in every variant because sources disagreed; an APN variant conflict also names the sources behind each variant in `variant_sources` |
| `quality_gates` | some records | facts omitted by a gate, such as `uncorroborated_generic_apn`, the `mms` type of a row without an MMSC by `mms_without_mmsc`, a capability published as `unknown` by `stale_single_source_entry:<capability>`, `frozen_source_only:<capability>`, `unseen_scope:<capability>` or `single_family_off:<capability>` (for `volte`, `vowifi` and `video_calling` that gate can also sit next to `supported`, where the off is kept as device records), or a false capability-gating CarrierConfig key left out by `single_family_off:<key>`, or APN rows LineageOS removed from its list by `lineageos_apn_removed:<commit>`, or an APN row that serves `mms` through a proxy no network routes by `mms_proxy_unroutable:<value>` (rule round 40: `9.4.229.46`, which LineageOS's Pixel snapshot gives 24-7 Wireless's four SPN rows on 311/500, is IBM's 9.0.0.0/8 with no route announced, while every sibling row on the same MMSC gives ClearSky Media's `209.4.229.46`; the value is never rewritten, and the rows come back once the source corrects it). `--explain` lists a SIM's APN gates under `apns.quality_gates`. Since rule round 32, `single_family_off:<capability>` can carry the reason `off_older_than_five_years` with `off_newest_entry`. Being built: `operator_statement_lapsed:mms` |
| `source_versions` | some records | per source family, the exact builds, commits, or Apple bundle and iOS versions the observations were read from |

The key of an APN fact in `fact_sources` is `sha256:` and the first 16 hex digits of the SHA-256 of the row as compact JSON: the row without `name`, `types` set to the one type, keys sorted, no spaces, non-ASCII characters escaped. In Python that is `json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`. `apn_fact_key` in `tools/generate_android_outputs.py` computes it, and the generator uses it to order APN rows.

`capability_basis` maps a capability to one object. `basis` is `samsung_vonr_switch`: Samsung's settings offer the VoNR switch for the carrier. `source` is the source family, which `capability_sources` also lists under `on`. `sales_codes` are the Samsung carrier pack codes whose pack carries the switch token, sorted, all in `observed_scope.sales_codes`. `model_count` counts the models whose pack carries it; the profile's other Samsung models leave VoNR unknown. Up to 24 models are named in `models`, sorted, all in `observed_scope.models`; more are given as `models_sha256`, the SHA-256 in hex of the sorted model names joined by newline characters. Like `capability_sources`, it appears whatever the profile publishes, so a `conditional` VoNR still names it. The validator checks all of this.

`observed_scope` can hold `models`, `android_majors`, `firmware_builds`, `firmware_regions`, `sales_codes`, `multi_csc`, `omc_revisions`, `omc_versions`, and `source_layers`. `source_layers` is `firmware_baseline` or `gras_delta`.

`source_versions` is a list with one item per source family, sorted by `source`. `source` names one of the record's `sources`. The other keys are lists, each sorted, unique, and non-empty. An item has at least one.

| Key | Holds | Example |
| --- | --- | --- |
| `builds` | firmware build IDs | `CP3A.260905.009`, `G981BXXSNHYB1` |
| `commits` | full Git commits of the repository a value was read from | `b446f3306fb55d46e6799f3ae76dbb1f40b22193` |
| `bundle_versions` | Apple carrier bundle versions | `31.1` |
| `ios_versions` | the iOS versions Apple's index lists for the bundle | `17.1` |

A family appears only where its observations name a version. The git-based families, `aosp`, `lineageos`, and `mobile_broadband_provider_info`, read one commit per snapshot, which `source_snapshots[].revision` names. The validator rejects any other key and any value outside these patterns, so no URL or path can appear.

Each `conflicts` and `quality_gates` item has `section`, `key`, `kind`, `observed_value_count`, and `resolution`. Since rule round 32, a `single_family_off:<capability>` gate next to a `supported` `volte`, `vowifi` or `video_calling` value can also carry `reason`, `off_older_than_five_years`, and `off_newest_entry`, a `YYYY-MM` month older than five years; the two come together and nowhere else. `resolution` is `omitted_from_stable`, `conditional`, `published_variants`, or `superseded_device_file`, and, being built (rule round 32), `operator_statement` for an `mms` value that an admitted operator statement sets. Also being built: a profile of an old Samsung MVNO scope that Samsung's current packs supersede (rule round 32, D7) is marked `old_selector_superseded`. Its profile file stays, and it is left out of `apns-conf.xml` and `lookup.json`. Only capabilities become `conditional`. `superseded_device_file` is a capability or CarrierConfig conflict that Google's current CarrierSettings file settled: only Google's frozen Pixel copies (`google_pixel_vendor_carriersettings`) disagreed with it, so the current value is published, and `capability_sources` and `capability_newest_entries` leave the frozen copies out for that capability. Only APN rows become `published_variants`, which means every variant was published. `generated/android/apns-conf.xml` orders the variants by the sources behind each row. A `published_variants` conflict can also carry `variant_sources`: one entry per variant, sorted by `key`, each with the variant's APN fact key (described above, the variant as one row with one type) and `sources`, the profile sources whose observations gave exactly that variant. A variant a gate later removed, such as an uncorroborated generic row, is still listed, because a source gave it. A `lineageos_apn_removed:<commit>` gate counts the APN rows left out of the profile because LineageOS removed them from `android_vendor_apn`. `<commit>` is the full LineageOS commit first seen without the rows. A row is left out when its network code, MVNO selector, APN and type set equal a removed LineageOS row and no observation that gives it has an entry newer than the removal; one newer entry keeps the row with all its sources. A `stale_single_source_entry:<capability>`, `frozen_source_only:<capability>`, `unseen_scope:<capability>` or `single_family_off:<capability>` gate names a capability the profile publishes as `unknown`, and a `single_family_off:<key>` gate in `android_carrier_config` names a false capability-gating key the profile does not publish. Since 2026-10-10 such a false of `carrier_volte_available_bool`, `carrier_wfc_ims_available_bool` or `carrier_vt_available_bool` no longer withdraws another observation's true as a conflict, so the key may be published `true` next to the gate, never `false`; the validator checks both. `capability_sources` agrees with the published value: `supported` has only `on`, `unsupported` only `off`, `conditional` two kinds or `conditional`, and an `unknown` with sources names the gate that withheld it. So a `conditional` VoLTE, Wi-Fi calling or video calling value can come with a true switch: the sources still disagree, and the off that one family alone gives does not switch the feature off. [how-it-is-built.md](how-it-is-built.md) explains the rules.

## Device records

`generated/devices/carrier-variants.json` says what one device's own carrier file configures for one carrier profile, for the four switches Android gates per device and per carrier: `volte`, `vowifi`, `video_calling` and `vonr` (rule decisions of 2026-10-17, round 17). It is configuration, not a test result: no record has been checked on a phone, none says the operator offers the service or that your plan includes it, and none says anything about emergency calls. `schemas/carrier-variants.schema.json` describes it and `tools/validate_carrier_variants.py` checks it.

Which scope each kind of data is published at:

| Data | Published per | Where |
| --- | --- | --- |
| APN rows, MMSC and MMS proxy | carrier | `apns-conf.xml`, `android_apns`; per-source APN variants in the evidence index |
| `mms` and the other capabilities | carrier | the profile value |
| CarrierConfig keys, the three gating keys among them, and add-ons | carrier | `carrier-config-list.xml`, `android_carrier_config` |
| `volte`, `vowifi`, `video_calling`, `vonr` | carrier and device | the profile value as the summary; device records in `generated/devices/carrier-variants.json` |

The file is compact JSON with sorted keys, like the evidence index. Its top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `description` | what the file is |
| `based_on_data_digest` | the `data_digest` of `generated/android/metadata.json` the records were built with. The file is not part of that digest, so adding it changes no other file |
| `checks_through`, `stale_after` | the freshness window of `generated/index.json` |
| `capabilities` | `["video_calling", "volte", "vonr", "vowifi"]` |
| `profiles` | profile ID to capability to a list of records |

Each record groups the devices whose own files give the same value from the same source, stack and month:

| Field | Meaning |
| --- | --- |
| `state` | `on` or `off` as the device's own file writes it, or `conditional` when two files of the same device disagree (two overlay layers of one LineageOS tree) |
| `source` | the one source family the value comes from, as `capability_sources` names it: `samsung_omc`, `google_carriersettings`, `google_pixel_vendor_carriersettings`, `lineageos_device_overlays`, `sony_open_devices_aosp` or `fairphone_official_source` |
| `stack` | the software the value holds for: `stock` (Samsung, Google, Fairphone firmware), `lineageos` (a LineageOS device tree) or `aosp` (Sony's AOSP tree) |
| `newest_entry` | month (`YYYY-MM`) of the newest upstream entry behind the value; absent when an entry is undated |
| `devices` | sorted. `samsung:<Build.MODEL>` for a Samsung model the device catalog lists, else `android:<device_id>` from `generated/devices/android.json`, whose `device_names` are `Build.DEVICE` values |
| `basis` | only `samsung_vonr_switch`, on `vonr` from `samsung_omc` where `capability_basis` names it: Samsung offers the VoNR switch, as described above |

How a record is made:

- **The same observations as the profile.** Only observations the profile's merge counts become records: quarantine, the test and lab network gate, Samsung's SIM rules, the Samsung VoNR switch rule, and Google's current file over its frozen Pixel copies where the current file gives a value. Only the step that turns disagreeing sources into `conditional` is done per device instead.
- **The newest file per device.** Google's current file wins over a frozen copy of the same Pixel. Samsung's newest Android major counts per model and sales code. A LineageOS file keeps only the last block's value for a SIM, as Android's `putAll` does.
- **Explicit values only.** A key missing from a file is never a record, and a source's own `conditional` is not one either. Samsung's and Apple's offs never publish, so a Samsung record is always `on`. Samsung's IMS table and Samsung's CarrierConfig, which are read from one model's firmware and serve every model of the build, Apple's bundles, which have no per-device split, and the carrier-wide lists (AOSP, LineageOS's APN list, mobile-broadband-provider-info) give no record.
- **Five years per record.** A value whose newest entry is older than five years does not publish, for every capability (stricter than rule 7's evidence test for VoLTE and Wi-Fi calling). On 2026-10-17 that withheld every Sony value.
- **Exact device binding.** A codename or model binds by exact case-folded catalog alias. One that two catalog devices share (a codename sold under two brands) gives no record, and neither does a Samsung model the catalog does not list.
- **Every value listed.** A device value is listed whatever the profile value is, so a record that agrees with the profile value shows that the device's own file was read and agrees (tie-break of 2026-10-17).

What a missing device means: A phone model without a record for a profile and switch has no file OCD reads that sets a value there, or its value is older than five years, or its codename or model does not bind to one catalog device. It never means `off`, and it never means the device agrees with the profile value.

What the records are not:

- **Not confirmed.** Every device value rests on one source family; no device is covered by two families. "Not contradicted" is all a record can say.
- **Not the phone you hold.** A `stock` record holds for that model's stock firmware, a `lineageos` record for that tree's builds. A stock record shown on a LineageOS build of the same model is "this model's stock firmware", not "this phone".
- **Not an export.** Never write an `off` from this file into a phone's CarrierConfig. `carrier-config-list.xml` stays the one CarrierConfig file, per carrier.

The validator checks the field list, that every profile is published and every device is in the catalog, one value per profile, capability, device and stack, that each record's source is listed in the profile's `capability_sources` for that capability under its state, no Samsung `off`, `newest_entry` inside five years of `checks_through`, `basis` exactly where `capability_basis` names it, the digest, the freshness window and canonical bytes. It also checks that every `volte`, `vowifi` or `video_calling` value published `supported` against one family's off has an `off` record here from each off source and at least one `on` record, that a `single_family_off:<capability>` gate next to `supported` names a real off, and fails without the file when such a value exists.

Labels that rest on device records (round 17, step 2). Round 8 (2026-10-10) deferred one change: an on against an off that one maker's or maintainer's per-device files alone give is published `supported`, not `conditional`, for `volte`, `vowifi` and `video_calling` only, and only where the off stays visible. Round 17 made it its second step, after the device records published. The private sanitizer applies it in the merge, from the same device values the builder lists: the off must come from one non-operator family (rule 9's family test, unchanged), no source may call the capability `conditional` itself, the on must publish standing alone under the five-year rule, every off observation the merge counts must become an `off` record of its own source for every device it names, and at least one device record of the same profile and capability must say `on` (round 22, 2026-10-19: the device file shows both sides; an existence test, never a count). An off that is older than five years, that binds to no single catalog device, that is not a per-device file, or whose device's other overlay layer says on keeps the value `conditional`, and so does a value whose ons come only from carrier-wide tables or device files older than five years. The value's `capability_newest_entries` month is then the on side's; the off records carry their own months. On the dry run of 2026-10-18 it published 122 values `supported` in 109 profiles (VoLTE 50, Wi-Fi calling 21, video calling 51) and kept 283 of the same kind `conditional`: 259 because some off is not in the device file (204 with an off older than five years, 68 with a codename two catalog devices share, 3 with a device whose overlay layers disagree; some for more than one reason), 12 because no device record says on, and 12 because the on would not publish standing alone. No CarrierConfig value, APN row or device record changed. The device builder stops the publish when a `supported` value's off is not in the file, or when a `conditional` value of the three should have changed. `mms`, `vonr`, `ims_conference` and every other capability keep the `conditional` rule. CarrierConfig and APN rows do not change: change 33 already publishes the true switch of these values.
