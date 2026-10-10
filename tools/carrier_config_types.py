#!/usr/bin/env python3
"""Expected value types for the public Android CarrierConfig subset."""

from __future__ import annotations

from typing import Any


BOOL_KEYS_WITHOUT_SUFFIX = {
    "allow_add_call_during_video_call",
    "allow_hold_in_ims_call",
    "auto_retry_failed_wifi_emergency_call",
    "enabledMMS",
    "enabledNotifyWapMMSC",
    "enabledTransID",
    "enableGroupMms",
    "enableMMSDeliveryReports",
    "enableMMSReadReports",
    "enableMultipartSMS",
    "enableSMSDeliveryReports",
    "ignore_data_enabled_changed_for_video_calls",
    "ims.use_tel_uri_for_pidf_xml",
    "mmsCloseConnection",
    "rtt_upgrade_supported_for_downgraded_vt_call",
    "sendMultipartSmsAsSeparateMessages",
    "supportMmsContentDisposition",
    "video_calls_can_be_hd_audio",
    "vt_upgrade_supported_for_downgraded_rtt_call",
    "wifi_calls_can_be_hd_audio",
}

INT_KEYS_WITHOUT_SUFFIX = {
    "httpSocketTimeout",
    "maxImageHeight",
    "maxImageWidth",
    "maxMessageSize",
    "maxMessageTextSize",
    "maxSubjectLength",
    "recipientLimit",
    "smsToMmsTextLengthThreshold",
    "smsToMmsTextThreshold",
}

STRING_KEYS_WITHOUT_SUFFIX = {
    "httpParams",
}


def expected_config_type(key: str) -> str:
    if key.endswith("_bool") or key in BOOL_KEYS_WITHOUT_SUFFIX:
        return "bool"
    if key.endswith("_int") or key in INT_KEYS_WITHOUT_SUFFIX:
        return "int"
    if (
        key.endswith("_string_array")
        or key.endswith("_strings")
    ):
        return "string_array"
    if key.endswith("_string") or key in STRING_KEYS_WITHOUT_SUFFIX:
        return "string"
    raise ValueError(f"CarrierConfig key has no declared value type: {key}")


def config_value_has_expected_type(key: str, value: Any) -> bool:
    expected = expected_config_type(key)
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "string_array":
        return isinstance(value, list) and all(
            isinstance(item, str) for item in value
        )
    return False


# Keys whose value Android reads as one of a closed set of constants. A value
# outside the set is not an Android value: Settings, QNS and the IMS service
# have no case for it. The Wi-Fi calling modes are ImsMmTelManager.WIFI_MODE_*
# (0 Wi-Fi only, 1 cellular preferred, 2 Wi-Fi preferred), which
# CarrierConfigManager documents for both keys. Qualcomm-based LineageOS
# device trees write 10, Qualcomm's own "IMS preferred" mode, which only their
# vendor Settings and IMS stack read (rule decisions, round 8, change 34).
CONFIG_VALUE_DOMAINS = {
    "carrier_default_wfc_ims_mode_int": frozenset({0, 1, 2}),
    "carrier_default_wfc_ims_roaming_mode_int": frozenset({0, 1, 2}),
}


def config_value_in_domain(key: str, value: Any) -> bool:
    """Whether value is one Android defines for key; a key without a closed
    set in CONFIG_VALUE_DOMAINS accepts every value of its type."""
    domain = CONFIG_VALUE_DOMAINS.get(key)
    return domain is None or value in domain
