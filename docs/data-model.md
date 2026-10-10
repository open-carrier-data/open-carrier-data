# Carrier profile data model

This page lists every field of a carrier profile as `schemas/carrier-profile.schema.json` defines it, in schema order. It then lists the fields that the generated indexes add. Each section says which file the field lives in.

A carrier profile is one file at `carriers/open/<mccmnc>.<hash>.json`. Its top-level fields are `schema_version`, `profile_id`, `display_name`, `match`, `capabilities`, `android_carrier_config`, `addons`, and `android_apns`. The schema allows no other top-level field.

## Top-level fields

The first five fields identify the profile and say when it applies.

| Field | Required | Type | Rule |
| --- | --- | --- | --- |
| `schema_version` | yes | integer | always `1` |
| `profile_id` | yes | string | `open.<mccmnc>.<12 hex>`, matches the file name |
| `display_name` | yes | string | 1 to 120 characters |
| `match` | yes | object | see the match selector table |
| `capabilities` | yes | object | see the capabilities table |
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
| `imsi_prefix_patterns` | no | string | 5 to 10 characters from digits and `x`, unique |
| `spn` | no | string | 1 to 80 characters, unique |
| `android_carrier_ids` | no | integer | 0 to 1000000, unique |

`lookup.json` derives `specificity` from these fields. It counts how many of the six optional fields are populated. A profile with only `mccmnc` has specificity 0.

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
| `supported` | at least one phone maker's or OS carrier table turns the feature on for this SIM, or for Samsung VoNR offers the user its switch (`capability_basis` names that weaker basis), and no source whose off counts turns it off. The switch counts only where the pack serves the carrier: on a KT phone only for KT's networks, and never from Samsung's open-market US pack (XAA). Samsung's and Apple's offs never count, including a Samsung carrier pack that switches a feature off on some phone models. It is a configuration, not a test result: the feature may still be off on a given phone, or on phones the carrier has not approved |
| `unsupported` | the operator's own configuration turns it off, or at least two independent source families turn it off and none turns it on |
| `conditional` | sources disagree, also between the current devices of one source; Google's frozen Pixel copies do not count where Google's current file gives a value |
| `unknown` | no usable source. That includes a single maker or maintainer turning the feature off, and a capability whose only source family's newest entry is older than five years, withheld for its age or, for VoLTE, VoWiFi, MMS and Wi-Fi calling while roaming, on the evidence [how-it-is-built.md](how-it-is-built.md) describes |

Samsung's and Apple's offs never count. Both write an off almost always as a missing entry: 3,622 of 3,674 offs in Samsung's tracked IMS table, and most iPhone bundles. Their written offs describe phones or defaults, not the carrier: measured on 2026-10-09, Samsung's written table offs agreed with another family's off in 2 of 9 comparable cases, Samsung's phone-pack offs in 0 of 31, and Apple's written falses in 0 of 12. Source names that copy one origin count as one family: the LineageOS, Sony and Fairphone APN lists, the two Google lanes, and Samsung's three lanes (OMC, IMS and CarrierConfig). The operator's own configuration is Google's settings for its Google Fi service and an AOSP CarrierConfig file the carrier itself submitted; [how-it-is-built.md](how-it-is-built.md) lists them. `capability_sources` in the evidence index names, for each capability, the source families that turn it on and those that turn it off.

Samsung OMC's `vonr` says less than a table that turns VoNR on. It comes from Samsung's carrier pack (OMC): when the pack's Mobile networks menu feature carries the token `+vonrcall`, Samsung's settings offer a "VoNR (Voice over 5G)" switch for that carrier on that model. So `supported` from Samsung OMC means that Samsung offers the switch on the models the evidence index lists. It does not mean VoNR is on by default, and it is not a field test. A model without the token leaves VoNR `unknown`, not `unsupported`: Vodafone Germany, for one, runs VoNR on Samsung phones that show no switch. Test and lab networks (MCC 001, the documented lab codes, test equipment and lab entries) and private networks (MCC 999) get no value, and neither does a SIM that a KT phone dims the switch for, or a network that only Samsung's open-market US pack (XAA) offers it for: an operator's pack lists only that operator's networks and brands, but XAA serves no operator, so there the token describes the phone, not the carrier. The value never becomes a CarrierConfig key, so `carrier-config-list.xml` gets no `vonr_*` key from it. `capability_basis` in the evidence index names this basis with the Samsung sales codes and models behind it. A `vonr` from `samsung_carrier_config` is a table that turns VoNR on: Samsung's own CarrierConfig sets `vonr_enabled_bool` for the carrier. It has no `capability_basis` and adds no `vonr_*` key either.

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
| `mvno_match_data` | string | 1 to 120 characters |
| `protocol` | string | `IP`, `IPV6`, `IPV4V6`, `PPP`, `NON-IP`, or `UNSTRUCTURED` |
| `roaming_protocol` | string | same values as `protocol` |

The allowed `types` values are `*`, `default`, `mms`, `supl`, `dun`, `hipri`, `fota`, `ims`, `cbs`, `ia`, `emergency`, `mcx`, `xcap`, `vsim`, `bip`, `enterprise`, and `rcs`. `cbs` is Android's type for carrier branded services, not cell broadcast: OCD publishes no emergency-alert (cell broadcast) channels, which Android takes from its own per-country and per-carrier CellBroadcastReceiver configuration.

## Stable index entries

`generated/index.json` has `schema_version` and a `profiles` array. Each entry has `profile_id`, `display_name`, and `path`. `path` is the profile file relative to the repo root.

`generated/android/lookup.json` has `schema_version`, `match_semantics`, `resolution_order`, and `profiles`. Each entry repeats `profile_id`, `display_name`, `path`, `match`, and `capabilities`, and adds `specificity`, `android_apn_count`, and `has_android_carrier_config`. An entry whose sources carry a check date also has `checks_through` and `stale_after`, the freshness window of that one profile. A profile's `stale_after` is the earliest day any of its observations could expire; values are not dated one by one. The file-level window in `generated/android/metadata.json` is the oldest of these, so a consumer that keeps only some profiles can read the per-profile dates instead. An entry also has `newest_entry`, the month (`YYYY-MM`) of the newest upstream entry behind the profile, wherever the evidence index publishes one; it tells you how old the profile's data is, which the check dates do not. The validator checks that it matches the evidence index.

`generated/android/metadata.json` has `schema_version`, `target`, `output`, `omissions`, `data_digest`, and the file-level `checks_through` and `stale_after`. `target` names the APN database version and says that profiles needing a GID or ICCID match are left out of `carrier-config-list.xml` (`carrier_config_gid_matching` and `carrier_config_iccid_matching` are `omitted`). `data_digest` is `sha256:` and the SHA-256 over the profile files, `generated/evidence-index.json` and the generator's source; `apns-conf.xml` and `carrier-config-list.xml` repeat it with the licence and the freshness window in the comment they start with.

## Provenance fields in the evidence index

`generated/evidence-index.json` has `schema_version`, `description`, `source_snapshots`, and `profiles`. It may also carry `checks_through` and `stale_after`, the freshness window that `generated/android/metadata.json` republishes, `vendor_build_grace`, `withdrawn_profiles` and `apn_removal_commits`, all described below. It never contains raw source material.

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
| `fact_sources` | every record | list of `section`, `key`, `sources` for only the CarrierConfig, APN and add-on facts whose sources are narrower than `sources`, or that carry `old_build_sources` or `shared_file_sources`; a fact without an entry rests on every source in `sources`. An APN fact is one row with one of its types, and its key is described below the table. The sources of an APN fact are those whose observations give the row: each gives exactly its proxy, port, username and password (a missing value meaning none), for an `mms` fact also its MMS proxy and, when either gives an MMS proxy, its MMS port, and no other attribute with a different value. An APN fact may add `old_build_sources`: the Samsung sources (`samsung_omc`, `samsung_ims`) among its `sources` whose every observation behind the fact comes from a firmware build more than three years old; the APN ranking does not count them as current vendors. An APN fact may add `shared_file_sources`, which is always `["google_carriersettings"]`: every Google CarrierSettings observation behind the fact comes from Google's shared `others` file, and no maintained per-carrier source (a Google per-carrier file, or a Samsung build at most three years old) gives the same APN value for that type on any of the profile's network codes, and Google's frozen Pixel copies (TheMuppets) of the same entry do not show that Google edited its values for that type (a copy gives a value for the type that the current file no longer gives); the APN ranking does not count Google as a current vendor for it. The shared file's date is the file's, not the entry's. Capabilities are in `capability_sources` |
| `capability_sources` | some records | capability name to `on`, `off` and `conditional`, each a list of the sources whose observations turn the capability on, turn it off, or call it conditional. It lists every capability a source gives a value, whatever the profile publishes, and is present whenever the profile publishes a capability other than `unknown` |
| `capability_basis` | some records | capability name to what its value rests on, where a source's `on` says less than a table that turns the feature on. Only `vonr` from `samsung_omc` has one, with `basis` `samsung_vonr_switch`; it is described below the table |
| `observed_scope` | some records | device and firmware scope of the observations |
| `observed_model_source_groups` | some records | `models` and `sources` pairs when a model was named by fewer sources than the profile |
| `reviewed_range` | some records | `oldest` and `newest` review dates |
| `newest_entry` | some records | month (`YYYY-MM`) of the newest upstream entry behind the profile, present only when every observation is dated |
| `capability_newest_entries` | some records | capability name to the month of the newest upstream entry behind that capability's value, present only when every supporting observation is dated. It covers every capability `capability_sources` names, also one a gate publishes as `unknown`, so the age of a withheld value stays visible |
| `flags` | some records | informational marks that withhold nothing, each `section`, `key` and `flag`, sorted: `old_single_source` on a capability whose value rests on one source family whose newest entry behind it is more than five years old. A capability the five-year rule withholds never sits next to its capability-gating CarrierConfig key, which is left out with it; the flag `capability_label_withheld`, which marked such a key until 2026-10-06, is refused |
| `conflicts` | some records | facts omitted, made conditional, or published in every variant because sources disagreed; an APN variant conflict also names the sources behind each variant in `variant_sources` |
| `quality_gates` | some records | facts omitted by a gate, such as `uncorroborated_generic_apn`, the `mms` type of a row without an MMSC by `mms_without_mmsc`, a capability published as `unknown` by `stale_single_source_entry:<capability>`, `frozen_source_only:<capability>`, `unseen_scope:<capability>` or `single_family_off:<capability>`, or a false capability-gating CarrierConfig key left out by `single_family_off:<key>`, or APN rows LineageOS removed from its list by `lineageos_apn_removed:<commit>` |
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

Each `conflicts` and `quality_gates` item has `section`, `key`, `kind`, `observed_value_count`, and `resolution`. `resolution` is `omitted_from_stable`, `conditional`, `published_variants`, or `superseded_device_file`. Only capabilities become `conditional`. `superseded_device_file` is a capability or CarrierConfig conflict that Google's current CarrierSettings file settled: only Google's frozen Pixel copies (`google_pixel_vendor_carriersettings`) disagreed with it, so the current value is published, and `capability_sources` and `capability_newest_entries` leave the frozen copies out for that capability. Only APN rows become `published_variants`, which means every variant was published. `generated/android/apns-conf.xml` orders the variants by the sources behind each row. A `published_variants` conflict can also carry `variant_sources`: one entry per variant, sorted by `key`, each with the variant's APN fact key (described above, the variant as one row with one type) and `sources`, the profile sources whose observations gave exactly that variant. A variant a gate later removed, such as an uncorroborated generic row, is still listed, because a source gave it. A `lineageos_apn_removed:<commit>` gate counts the APN rows left out of the profile because LineageOS removed them from `android_vendor_apn`. `<commit>` is the full LineageOS commit first seen without the rows. A row is left out when its network code, MVNO selector, APN and type set equal a removed LineageOS row and no observation that gives it has an entry newer than the removal; one newer entry keeps the row with all its sources. A `stale_single_source_entry:<capability>`, `frozen_source_only:<capability>`, `unseen_scope:<capability>` or `single_family_off:<capability>` gate names a capability the profile publishes as `unknown`, and a `single_family_off:<key>` gate in `android_carrier_config` names a capability-gating key the profile does not publish; the validator checks both. `capability_sources` agrees with the published value: `supported` has only `on`, `unsupported` only `off`, `conditional` two kinds or `conditional`, and an `unknown` with sources names the gate that withheld it. [how-it-is-built.md](how-it-is-built.md) explains the rules.
