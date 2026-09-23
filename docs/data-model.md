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

The lookup indexes derive `specificity` from these fields. It counts how many of the six optional fields are populated. A profile with only `mccmnc` has specificity 0.

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
| `esim` | embedded SIM support |
| `ims_conference` | IMS conference calls |
| `wifi_calling_roaming` | Wi-Fi calling while roaming |

Every capability takes one of four values.

| Value | Meaning |
| --- | --- |
| `supported` | sources agree the feature works |
| `unsupported` | sources agree the feature is off |
| `conditional` | sources disagree, or the value depends on device scope |
| `unknown` | no source says |

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
| `entitlement` | entitlement server behaviour |
| `euc` | end user consent |
| `ims` | IMS behaviour beyond CarrierConfig |
| `messaging` | SMS and MMS behaviour |
| `network_policy` | network selection and display policy |
| `operator_display` | operator name and icon rules |
| `presence` | presence and capability exchange |
| `provisioning` | provisioning flow facts |
| `rcs` | RCS facts |
| `wifi_calling` | Wi-Fi calling branding and style |

An add-on value is a boolean, an integer from -1000000 to 1000000, or a string of 1 to 160 characters. An array of up to 40 such scalars is also allowed.

## APN row fields

`android_apns` is an array of rows. Each row needs `name`, `apn`, and `types`. The schema allows no other keys than the ones below.

| Field | Type | Rule |
| --- | --- | --- |
| `name` | string | 1 to 80 characters, required |
| `apn` | string | 1 to 120 characters, required |
| `types` | array of strings | required, unique, from the type list below |
| `mmsc` | string | up to 240 characters |
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

The allowed `types` values are `*`, `default`, `mms`, `supl`, `dun`, `hipri`, `fota`, `ims`, `cbs`, `ia`, `emergency`, `mcx`, `xcap`, `vsim`, `bip`, `enterprise`, and `rcs`.

## Stable index entries

`generated/index.json` has `schema_version` and a `profiles` array. Each entry has `profile_id`, `display_name`, and `path`. `path` is the profile file relative to the repo root.

`generated/android/lookup.json` has `schema_version`, `match_semantics`, `resolution_order`, and `profiles`. Each entry repeats `profile_id`, `display_name`, `path`, `match`, and `capabilities`, and adds `specificity`, `android_apn_count`, and `has_android_carrier_config`.

## Provenance fields in the evidence index

`generated/evidence-index.json` has `schema_version`, `description`, `model_source_provenance`, `source_snapshots`, and `profiles`. It may also carry `checks_through` and `stale_after`, the freshness window that `generated/android/metadata.json` republishes. It never contains raw source material.

Each `source_snapshots` record describes one source family check.

| Field | Meaning |
| --- | --- |
| `source_name` | source family identifier, such as `lineageos` |
| `upstream_url` | where the source lives |
| `revision` | full Git commit or SHA-256 of the downloaded content |
| `revision_date` | when that revision was published upstream |
| `checked_at` | when automation last checked the source with success |
| `license_expression` | SPDX expression or `NOASSERTION` |
| `redistribution` | `permitted`, `public_domain`, or `transformed_facts_only` |
| `schema_version` | record format version, `2` on 2026-09-23 |

Each `profiles` record describes one carrier profile.

| Field | Present in | Meaning |
| --- | --- | --- |
| `profile_id` | every record | matches the carrier profile |
| `sources` | every record | source families that contributed to this profile |
| `observation_count` | every record | candidate observations merged into this profile |
| `verified_observation_count` | every record | observations confirmed on a device, `0` for every profile on 2026-09-23 |
| `fact_sources` | every record | list of `section`, `key`, `sources` for each exported fact |
| `observed_scope` | some records | device and firmware scope of the observations |
| `observed_model_source_groups` | some records | `models` and `sources` pairs when a model was named by fewer sources than the profile |
| `reviewed_range` | some records | `oldest` and `newest` review dates |
| `conflicts` | some records | facts omitted or made conditional because sources disagreed |
| `quality_gates` | some records | facts omitted by a gate, such as `uncorroborated_generic_apn` |

`observed_scope` can hold `models`, `android_majors`, `firmware_builds`, `firmware_regions`, `sales_codes`, `multi_csc`, `omc_revisions`, `omc_versions`, and `source_layers`. `source_layers` is `firmware_baseline` or `gras_delta`.

Each `conflicts` and `quality_gates` item has `section`, `key`, `kind`, `observed_value_count`, and `resolution`. `resolution` is `omitted_from_stable` or `conditional`. Only capabilities become `conditional`.
