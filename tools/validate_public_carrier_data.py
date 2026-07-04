#!/usr/bin/env python3
"""Validate sanitized public carrier data.

This intentionally uses only the Python standard library so the public repo can
run validation without dependency downloads.
"""

from __future__ import annotations

import json
import hashlib
import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_CONFIG_KEYS = {
    "allow_add_call_during_video_call",
    "allow_adding_apns_bool",
    "allow_emergency_video_calls_bool",
    "allow_hold_call_during_emergency_bool",
    "allow_hold_in_ims_call",
    "allow_hold_video_call_bool",
    "allow_merge_wifi_calls_when_vowifi_off_bool",
    "allow_merging_rtt_calls_bool",
    "allow_non_emergency_calls_in_ecm_bool",
    "always_play_remote_hold_tone_bool",
    "apn_expand_bool",
    "auto_retry_failed_wifi_emergency_call",
    "call_barring_default_service_class_int",
    "call_barring_supports_deactivate_all_bool",
    "call_barring_supports_password_change_bool",
    "call_forwarding_blocks_while_roaming_string_array",
    "call_forwarding_map_non_number_to_voicemail_bool",
    "carrier_allow_transfer_ims_call_bool",
    "carrier_allow_turnoff_ims_bool",
    "carrier_default_wfc_ims_enabled_bool",
    "carrier_default_wfc_ims_mode_int",
    "carrier_default_wfc_ims_roaming_enabled_bool",
    "carrier_default_wfc_ims_roaming_mode_int",
    "carrier_ims_gba_required_bool",
    "carrier_metered_apn_types_strings",
    "carrier_metered_roaming_apn_types_strings",
    "carrier_promote_wfc_on_call_fail_bool",
    "carrier_supports_ss_over_ut_bool",
    "carrier_use_ims_first_for_emergency_bool",
    "carrier_volte_available_bool",
    "carrier_volte_override_wfc_provisioning_bool",
    "carrier_volte_provisioned_bool",
    "carrier_volte_provisioning_required_bool",
    "carrier_volte_tty_supported_bool",
    "carrier_vowifi_tty_supported_bool",
    "carrier_vt_available_bool",
    "carrier_wfc_ims_available_bool",
    "carrier_wfc_supports_wifi_only_bool",
    "cdma_3waycall_flash_delay_int",
    "default_mtu_int",
    "disable_dun_apn_while_roaming_with_preset_apn_bool",
    "drop_video_call_when_answering_audio_call_bool",
    "editable_enhanced_4g_lte_bool",
    "editable_wfc_mode_bool",
    "editable_wfc_roaming_mode_bool",
    "enabledMMS",
    "enabledNotifyWapMMSC",
    "enabledTransID",
    "enableGroupMms",
    "enableMMSDeliveryReports",
    "enableMMSReadReports",
    "enableMultipartSMS",
    "enableSMSDeliveryReports",
    "enhanced_4g_lte_on_by_default_bool",
    "hide_enhanced_4g_lte_bool",
    "hide_ims_apn_bool",
    "httpParams",
    "httpSocketTimeout",
    "ignore_data_enabled_changed_for_video_calls",
    "ims.enable_presence_capability_exchange_bool",
    "ims.enable_presence_publish_bool",
    "ims.rcs_request_forbidden_by_sip_489_bool",
    "ims.sip_over_ipsec_enabled_bool",
    "ims.use_sip_uri_for_presence_subscribe_bool",
    "ims.use_tel_uri_for_pidf_xml",
    "ims_conference_size_limit_int",
    "ims_dtmf_tone_delay_int",
    "ims_reasoninfo_mapping_string_array",
    "imsvoice.conference_factory_uri_string",
    "imsvoice.conference_subscribe_type_int",
    "is_ims_conference_size_enforced_bool",
    "iwlan.epdg_pco_id_ipv4_int",
    "iwlan.epdg_pco_id_ipv6_int",
    "iwlan.epdg_static_address_string",
    "iwlan.handover_to_wifi_release_delay_second_int",
    "maxImageHeight",
    "maxImageWidth",
    "maxMessageSize",
    "maxMessageTextSize",
    "maxSubjectLength",
    "mmsCloseConnection",
    "notify_handover_video_from_lte_to_wifi_bool",
    "notify_handover_video_from_wifi_to_lte_bool",
    "notify_vt_handover_to_wifi_failure_bool",
    "read_only_apn_fields_string_array",
    "read_only_apn_types_string_array",
    "recipientLimit",
    "rtt_supported_bool",
    "rtt_supported_while_roaming_bool",
    "rtt_upgrade_supported_for_downgraded_vt_call",
    "sendMultipartSmsAsSeparateMessages",
    "show_apn_setting_cdma_bool",
    "show_ims_registration_status_bool",
    "show_wifi_calling_icon_in_status_bar_bool",
    "smsToMmsTextLengthThreshold",
    "smsToMmsTextThreshold",
    "sms_requires_destination_number_conversion_bool",
    "support_3gpp_call_forwarding_while_roaming_bool",
    "support_conference_call_bool",
    "support_downgrade_vt_to_audio_bool",
    "support_ims_conference_call_bool",
    "support_ims_conference_event_package_bool",
    "support_pause_ims_video_calls_bool",
    "support_swap_after_merge_bool",
    "support_video_conference_call_bool",
    "support_wps_over_ims_bool",
    "supportMmsContentDisposition",
    "treat_downgraded_video_calls_as_video_calls_bool",
    "video_calls_can_be_hd_audio",
    "volte_5g_limited_alert_dialog_bool",
    "volte_replacement_rat_int",
    "vt_upgrade_supported_for_downgraded_rtt_call",
    "wfc_operator_error_codes_string_array",
    "wfc_data_spn_format_idx_int",
    "wfc_spn_format_idx_int",
    "wifi_calls_can_be_hd_audio",
}

CAPABILITY_KEYS = {
    "volte",
    "vowifi",
    "vonr",
    "video_calling",
    "sms_over_ims",
    "mms",
    "rcs",
    "esim",
    "ims_conference",
    "wifi_calling_roaming",
}

CAPABILITY_VALUES = {
    "supported",
    "unsupported",
    "conditional",
    "unknown",
}

APN_TYPES = {
    "*",
    "default",
    "mms",
    "supl",
    "dun",
    "hipri",
    "fota",
    "ims",
    "cbs",
    "ia",
    "emergency",
    "mcx",
    "xcap",
    "vsim",
    "bip",
    "enterprise",
    "rcs",
}

APN_PROTOCOLS = {
    "IP",
    "IPV6",
    "IPV4V6",
    "PPP",
    "NON-IP",
    "UNSTRUCTURED",
}

APN_STRING_FIELDS = {
    "mmsc": 240,
    "mmsproxy": 120,
    "proxy": 120,
    "server": 120,
    "user": 120,
    "password": 120,
    "bearer_bitmask": 120,
    "network_type_bitmask": 120,
    "lingering_network_type_bitmask": 120,
    "infrastructure_bitmask": 40,
}

APN_PORT_FIELDS = {
    "mmsport",
    "port",
}

APN_INT_FIELDS = {
    "authtype": (-1, 3),
    "bearer": (0, 100),
    "mtu": (0, 10000),
    "mtu_v4": (0, 10000),
    "mtu_v6": (0, 10000),
    "carrier_id": (-1, 1000000),
    "profile_id": (0, 1000000),
    "apn_set_id": (-1, 1000000),
    "skip_464xlat": (-1, 1),
    "max_conns": (0, 1000000),
    "max_conns_time": (0, 1000000),
    "wait_time": (0, 1000000),
}

APN_BOOL_FIELDS = {
    "user_visible",
    "user_editable",
    "carrier_enabled",
    "modem_cognitive",
    "always_on",
    "esim_bootstrap_provisioning",
}

APN_MVNO_TYPES = {
    "spn",
    "gid",
    "imsi",
    "iccid",
}

GENERATED_FILES = {
    "README.md",
    "index.json",
    "android/README.md",
    "android/apns-conf.xml",
    "android/carrier-config-list.xml",
    "android/carrier-config-overrides.json",
    "android/carrier-id-index.json",
    "android/lookup.json",
    "android/mccmnc-index.json",
    "candidate/README.md",
    "candidate/index.json",
    "community/README.md",
    "community/index.json",
}

REQUIRED_GENERATED_FILES = {
    path for path in GENERATED_FILES if not path.endswith("README.md")
}

ADDON_NAMESPACES = {
    "emergency_calling",
    "entitlement",
    "euc",
    "ims",
    "messaging",
    "network_policy",
    "operator_display",
    "presence",
    "provisioning",
    "rcs",
    "wifi_calling",
}

ADDON_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,80}$")


class ValidationError(Exception):
    pass


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path}: invalid JSON: {exc}") from exc


def require_type(path: Path, value: Any, expected: type, name: str) -> None:
    if not isinstance(value, expected):
        raise ValidationError(f"{path}: {name} must be {expected.__name__}")


def validate_string(path: Path, value: Any, name: str, max_len: int = 120) -> str:
    require_type(path, value, str, name)
    if not value or len(value) > max_len:
        raise ValidationError(f"{path}: {name} length is invalid")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_profile_id(match: dict[str, Any]) -> str:
    mccmnc = str(match["mccmnc"][0])
    digest = hashlib.sha256(canonical_json(match).encode("utf-8")).hexdigest()[:12]
    return f"open.{mccmnc}.{digest}"


def public_path_for(profile_id: str) -> Path:
    parts = profile_id.split(".")
    return Path(parts[0]) / f"{'.'.join(parts[1:])}.json"


def validate_canonical_list(path: Path, values: Any, name: str) -> None:
    require_type(path, values, list, name)
    if values != sorted(set(values)):
        raise ValidationError(f"{path}: {name} must be sorted and unique")


def validate_addon_value(path: Path, value: Any, name: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        if -1000000 <= value <= 1000000:
            return
        raise ValidationError(f"{path}: {name} integer value is out of range")
    if isinstance(value, str):
        if value and len(value) <= 160:
            return
        raise ValidationError(f"{path}: {name} string value is invalid")
    if isinstance(value, list):
        if len(value) > 40:
            raise ValidationError(f"{path}: {name} list is too large")
        for index, item in enumerate(value):
            if isinstance(item, list):
                raise ValidationError(
                    f"{path}: {name}[{index}] nested lists are not supported"
                )
            validate_addon_value(path, item, f"{name}[{index}]")
        return
    raise ValidationError(f"{path}: {name} has unsupported value type")


def validate_addons(path: Path, addons: Any) -> None:
    require_type(path, addons, dict, "addons")
    unknown = set(addons) - ADDON_NAMESPACES
    if unknown:
        raise ValidationError(
            f"{path}: addons has unknown namespaces: {sorted(unknown)}"
        )
    for namespace, values in addons.items():
        require_type(path, values, dict, f"addons.{namespace}")
        for key, value in values.items():
            if not ADDON_KEY_RE.fullmatch(key):
                raise ValidationError(
                    f"{path}: addons.{namespace} has invalid key {key!r}"
                )
            validate_addon_value(path, value, f"addons.{namespace}.{key}")


def validate_profile(path: Path) -> dict[str, Any]:
    data = load_json(path)
    return validate_profile_object(path, data)


def validate_profile_object(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    require_type(path, data, dict, "root")

    allowed_root = {
        "schema_version",
        "profile_id",
        "display_name",
        "match",
        "capabilities",
        "android_carrier_config",
        "addons",
        "android_apns",
    }
    extra = set(data) - allowed_root
    if extra:
        raise ValidationError(f"{path}: unknown top-level keys: {sorted(extra)}")

    if data.get("schema_version") != 1:
        raise ValidationError(f"{path}: schema_version must be 1")

    profile_id = validate_string(path, data.get("profile_id"), "profile_id", 96)
    profile_id_chars = set("abcdefghijklmnopqrstuvwxyz0123456789_.-")
    if (
        not 3 <= len(profile_id) <= 97
        or profile_id[0] not in "abcdefghijklmnopqrstuvwxyz0123456789"
        or any(char not in profile_id_chars for char in profile_id)
    ):
        raise ValidationError(f"{path}: profile_id has invalid format")

    validate_string(path, data.get("display_name"), "display_name")

    match = data.get("match")
    require_type(path, match, dict, "match")
    if not match.get("mccmnc"):
        raise ValidationError(f"{path}: match.mccmnc is required")
    if set(match) - {
        "mccmnc",
        "gid1_prefixes",
        "gid2_prefixes",
        "iccid_prefixes",
        "imsi_prefix_patterns",
        "spn",
        "android_carrier_ids",
    }:
        raise ValidationError(f"{path}: match has unknown keys")
    for key, values in match.items():
        validate_canonical_list(path, values, f"match.{key}")
    for code in match.get("mccmnc", []):
        if (
            not isinstance(code, str)
            or len(code) not in {5, 6}
            or any(char not in "0123456789" for char in code)
        ):
            raise ValidationError(f"{path}: invalid MCC/MNC {code!r}")
    for gid in match.get("gid1_prefixes", []):
        if (
            not isinstance(gid, str)
            or not 1 <= len(gid) <= 32
            or any(char not in "0123456789ABCDEFabcdef" for char in gid)
        ):
            raise ValidationError(f"{path}: invalid GID1 prefix {gid!r}")
    for gid in match.get("gid2_prefixes", []):
        if (
            not isinstance(gid, str)
            or not 1 <= len(gid) <= 32
            or any(char not in "0123456789ABCDEFabcdef" for char in gid)
        ):
            raise ValidationError(f"{path}: invalid GID2 prefix {gid!r}")
    for iccid in match.get("iccid_prefixes", []):
        if (
            not isinstance(iccid, str)
            or not 5 <= len(iccid) <= 13
            or any(char not in "0123456789" for char in iccid)
        ):
            raise ValidationError(f"{path}: invalid ICCID prefix {iccid!r}")
    for imsi in match.get("imsi_prefix_patterns", []):
        if (
            not isinstance(imsi, str)
            or not 5 <= len(imsi) <= 10
            or any(char not in "0123456789xX" for char in imsi)
            or all(char in "xX" for char in imsi)
        ):
            raise ValidationError(f"{path}: invalid IMSI prefix pattern {imsi!r}")
    for spn in match.get("spn", []):
        validate_string(path, spn, "match.spn[]", 80)
    android_carrier_ids = match.get("android_carrier_ids", [])
    require_type(path, android_carrier_ids, list, "match.android_carrier_ids")
    for carrier_id in android_carrier_ids:
        if (
            not isinstance(carrier_id, int)
            or isinstance(carrier_id, bool)
            or not 0 <= carrier_id <= 1000000
        ):
            raise ValidationError(f"{path}: invalid Android carrier ID {carrier_id!r}")

    capabilities = data.get("capabilities")
    require_type(path, capabilities, dict, "capabilities")
    unknown_capabilities = set(capabilities) - CAPABILITY_KEYS
    if unknown_capabilities:
        raise ValidationError(
            f"{path}: unknown capability keys: {sorted(unknown_capabilities)}"
        )
    for key, value in capabilities.items():
        if value not in CAPABILITY_VALUES:
            raise ValidationError(f"{path}: invalid capability value for {key}")

    expected_profile_id = canonical_profile_id(match)
    if profile_id != expected_profile_id:
        raise ValidationError(
            f"{path}: profile_id must be canonical {expected_profile_id}"
        )

    config = data.get("android_carrier_config")
    if config is not None:
        require_type(path, config, dict, "android_carrier_config")
        unknown_config = set(config) - ALLOWED_CONFIG_KEYS
        if unknown_config:
            raise ValidationError(
                f"{path}: unreviewed CarrierConfig keys: {sorted(unknown_config)}"
            )
        for key, value in config.items():
            if not isinstance(value, (bool, int, str, list)):
                raise ValidationError(f"{path}: unsupported value type for {key}")
            if isinstance(value, list):
                for item in value:
                    if not isinstance(item, (bool, int, str)):
                        raise ValidationError(
                            f"{path}: unsupported list item type for {key}"
                        )

    addons = data.get("addons")
    if addons is not None:
        validate_addons(path, addons)

    apns = data.get("android_apns")
    if apns is not None:
        require_type(path, apns, list, "android_apns")
        for index, apn in enumerate(apns):
            require_type(path, apn, dict, f"android_apns[{index}]")
            allowed_apn_keys = {
                "name",
                "apn",
                "types",
                "protocol",
                "roaming_protocol",
                "mvno_type",
                "mvno_match_data",
            } | set(APN_STRING_FIELDS) | APN_PORT_FIELDS | set(APN_INT_FIELDS) | APN_BOOL_FIELDS
            if set(apn) - allowed_apn_keys:
                raise ValidationError(f"{path}: android_apns[{index}] has unknown keys")
            validate_string(path, apn.get("name"), f"android_apns[{index}].name", 80)
            validate_string(path, apn.get("apn"), f"android_apns[{index}].apn", 120)
            types = apn.get("types")
            require_type(path, types, list, f"android_apns[{index}].types")
            if not types:
                raise ValidationError(f"{path}: android_apns[{index}].types is empty")
            for apn_type in types:
                if apn_type not in APN_TYPES:
                    raise ValidationError(
                        f"{path}: android_apns[{index}] has invalid type"
                    )
            for key, max_len in APN_STRING_FIELDS.items():
                if key in apn:
                    validate_string(path, apn[key], f"android_apns[{index}].{key}", max_len)
            for key in APN_PORT_FIELDS:
                if key in apn:
                    port = apn[key]
                    if not isinstance(port, int) or not 1 <= port <= 65535:
                        raise ValidationError(f"{path}: android_apns[{index}].{key}")
            for key, (minimum, maximum) in APN_INT_FIELDS.items():
                if key in apn:
                    value = apn[key]
                    if not isinstance(value, int) or not minimum <= value <= maximum:
                        raise ValidationError(f"{path}: android_apns[{index}].{key}")
            for key in APN_BOOL_FIELDS:
                if key in apn and not isinstance(apn[key], bool):
                    raise ValidationError(f"{path}: android_apns[{index}].{key}")
            if "mvno_type" in apn or "mvno_match_data" in apn:
                if apn.get("mvno_type") not in APN_MVNO_TYPES:
                    raise ValidationError(f"{path}: android_apns[{index}].mvno_type")
                validate_string(
                    path,
                    apn.get("mvno_match_data"),
                    f"android_apns[{index}].mvno_match_data",
                    120,
                )
            for key in ("protocol", "roaming_protocol"):
                if key in apn and apn[key] not in APN_PROTOCOLS:
                    raise ValidationError(f"{path}: android_apns[{index}].{key}")

    return data


def validate_index(
    index_path: Path,
    profiles_by_path: dict[str, dict[str, Any]],
) -> None:
    index = load_json(index_path)
    require_type(index_path, index, dict, "index root")
    if index.get("schema_version") != 1:
        raise ValidationError(f"{index_path}: schema_version must be 1")
    profiles = index.get("profiles")
    require_type(index_path, profiles, list, "profiles")

    expected = sorted(f"carriers/{path}" for path in profiles_by_path)
    actual: list[str] = []
    actual_profile_ids: list[str] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    for index_num, entry in enumerate(profiles):
        require_type(index_path, entry, dict, f"profiles[{index_num}]")
        extra = set(entry) - {"profile_id", "display_name", "path"}
        missing = {"profile_id", "display_name", "path"} - set(entry)
        if extra or missing:
            raise ValidationError(
                f"{index_path}: profiles[{index_num}] has invalid keys"
            )
        path_value = validate_string(
            index_path, entry.get("path"), f"profiles[{index_num}].path", 240
        )
        if not path_value.startswith("carriers/open/"):
            raise ValidationError(
                f"{index_path}: profiles[{index_num}].path must be under carriers/open/"
            )
        profile_path = path_value.removeprefix("carriers/")
        profile = profiles_by_path.get(profile_path)
        if profile is None:
            raise ValidationError(
                f"{index_path}: profiles[{index_num}] references missing profile"
            )
        profile_id = validate_string(
            index_path, entry.get("profile_id"), f"profiles[{index_num}].profile_id", 96
        )
        display_name = validate_string(
            index_path,
            entry.get("display_name"),
            f"profiles[{index_num}].display_name",
            120,
        )
        if profile_id != profile["profile_id"]:
            raise ValidationError(
                f"{index_path}: profiles[{index_num}].profile_id does not match file"
            )
        if display_name != profile["display_name"]:
            raise ValidationError(
                f"{index_path}: profiles[{index_num}].display_name does not match file"
            )
        if path_value in seen_paths:
            raise ValidationError(f"{index_path}: duplicate profile path {path_value}")
        if profile_id in seen_ids:
            raise ValidationError(f"{index_path}: duplicate profile_id {profile_id}")
        seen_paths.add(path_value)
        seen_ids.add(profile_id)
        actual.append(path_value)
        actual_profile_ids.append(profile_id)
    if sorted(actual) != expected:
        raise ValidationError(
            f"{index_path}: profile path list does not match carriers directory"
        )
    if actual_profile_ids != sorted(actual_profile_ids):
        raise ValidationError(f"{index_path}: profiles must be sorted by profile_id")


def validate_generated_files(generated_dir: Path) -> None:
    if not generated_dir.exists():
        raise ValidationError(f"{generated_dir}: missing generated directory")
    actual = {
        path.relative_to(generated_dir).as_posix()
        for path in generated_dir.rglob("*")
        if path.is_file()
    }
    extra = actual - GENERATED_FILES
    if extra:
        raise ValidationError(
            f"{generated_dir}: unexpected generated files: {sorted(extra)}"
        )
    missing = REQUIRED_GENERATED_FILES - actual
    if missing:
        raise ValidationError(
            f"{generated_dir}: missing generated files: {sorted(missing)}"
        )


def main(argv: list[str]) -> int:
    carriers_dir = Path(argv[1]) if len(argv) > 1 else Path("carriers")
    index_path = Path(argv[2]) if len(argv) > 2 else Path("generated/index.json")

    if not carriers_dir.exists():
        raise ValidationError(f"{carriers_dir}: missing carriers directory")

    profile_paths = sorted(
        path for path in carriers_dir.rglob("*.json") if path.is_file()
    )
    seen_ids: set[str] = set()
    profiles_by_path: dict[str, dict[str, Any]] = {}
    for path in profile_paths:
        profile = validate_profile(path)
        profile_id = profile["profile_id"]
        if profile_id in seen_ids:
            raise ValidationError(f"{path}: duplicate profile_id {profile_id}")
        seen_ids.add(profile_id)
        expected_path = public_path_for(profile_id).as_posix()
        actual_path = path.relative_to(carriers_dir).as_posix()
        if actual_path != expected_path:
            raise ValidationError(
                f"{path}: public path must be carriers/{expected_path}"
            )
        profiles_by_path[actual_path] = profile

    validate_index(index_path, profiles_by_path)
    validate_generated_files(index_path.parent)
    print(f"validated {len(profile_paths)} public carrier profile(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
