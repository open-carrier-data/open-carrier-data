#!/usr/bin/env python3
"""Validate sanitized public carrier data.

This intentionally uses only the Python standard library so the public repo can
run validation without dependency downloads.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, NamedTuple

from carrier_config_types import config_value_has_expected_type, expected_config_type
from lineageos_apns import COUNTRY_FILE_NAMES, country_files, fits_lineageos_schema


STALE_AFTER_DAYS = 180
FRESHNESS_MODES = ("warn", "fail")
FRESHNESS_KEYS = {"checks_through", "stale_after"}

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


def load_allowed_config_keys(schema_path: Path = SCHEMA_DIR / "carrier-profile.schema.json") -> frozenset[str]:
    """The reviewed CarrierConfig allowlist, owned by the profile schema."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    keys = schema["properties"]["android_carrier_config"]["propertyNames"]["enum"]
    if not isinstance(keys, list) or not keys or len(set(keys)) != len(keys):
        raise RuntimeError(f"{schema_path}: android_carrier_config key enum is invalid")
    return frozenset(keys)


ALLOWED_CONFIG_KEYS = load_allowed_config_keys()

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

SUBSCRIBER_PREFIX_KINDS = {"iccid", "imsi"}

GENERATED_FILES = {
    "README.md",
    "evidence-index.json",
    "index.json",
    "android/README.md",
    "android/apns-conf.xml",
    "android/carrier-config-list.xml",
    "android/carrier-config-overrides.json",
    "android/carrier-id-index.json",
    "android/lookup.json",
    "android/metadata.json",
    "android/mccmnc-index.json",
    "devices/README.md",
    "devices/android-carrier-artifacts.json",
    "devices/android.json",
    "devices/apple-carrier-artifacts.json",
    "devices/apple.json",
    "devices/index.json",
}

# The per-country APN files, one per country in the layout of LineageOS's
# android_vendor_apn. Which of them exist depends on the data.
COUNTRY_APN_DIR = "android/apns"

REQUIRED_GENERATED_FILES = {
    path
    for path in GENERATED_FILES
    if not path.endswith("README.md") and not path.startswith("devices/")
}

ADDON_NAMESPACES = {
    "emergency_calling",
    "ims",
    "network_policy",
    "operator_display",
    "wifi_calling",
}

ADDON_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,80}$")


class ValidationError(Exception):
    pass


def subscriber_prefix_ok(kind: str, value: Any) -> bool:
    """Accept only a carrier prefix, never a full subscriber identity.

    Mirrors subscriber_prefix_ok in the private sanitizer. An ICCID prefix is
    5 to 13 digits. An IMSI pattern, after trailing x wildcards are stripped,
    is 5 to 10 digits or x wildcards with at least one digit.
    """
    if not isinstance(value, str):
        return False
    if kind == "iccid":
        return re.fullmatch(r"[0-9]{5,13}", value) is not None
    if kind == "imsi":
        stem = value.lower().rstrip("x")
        return (
            re.fullmatch(r"[0-9x]{5,10}", stem) is not None
            and re.search(r"[0-9]", stem) is not None
        )
    raise ValueError(f"unknown subscriber prefix kind {kind!r}")


class FreshnessWindow(NamedTuple):
    checks_through: date
    stale_after: date


TODAY_OVERRIDE: date | None = None


def utc_today() -> date:
    if TODAY_OVERRIDE is not None:
        return TODAY_OVERRIDE
    return datetime.now(timezone.utc).date()


def parse_freshness_window(path: Path, data: dict[str, Any]) -> FreshnessWindow | None:
    present = FRESHNESS_KEYS & set(data)
    if not present:
        return None
    if present != FRESHNESS_KEYS:
        raise ValidationError(
            f"{path}: checks_through and stale_after must be published together"
        )
    try:
        window = FreshnessWindow(
            date.fromisoformat(data["checks_through"]),
            date.fromisoformat(data["stale_after"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{path}: checks_through or stale_after is invalid") from exc
    if window.checks_through > utc_today():
        raise ValidationError(f"{path}: checks_through is future-dated")
    if not 1 <= (window.stale_after - window.checks_through).days <= 366:
        raise ValidationError(
            f"{path}: stale_after must be 1 to 366 days after checks_through"
        )
    return window


ENTRY_MONTH_RE = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")


def parse_entry_month(path: Path, value: Any, name: str) -> tuple[int, int]:
    """A newest-supporting-entry date, published to the month as YYYY-MM."""
    if not isinstance(value, str) or not ENTRY_MONTH_RE.fullmatch(value):
        raise ValidationError(f"{path}: {name} must be YYYY-MM")
    month = (int(value[:4]), int(value[5:]))
    today = utc_today()
    if month > (today.year, today.month):
        raise ValidationError(f"{path}: {name} is future-dated")
    return month


def check_freshness(window: FreshnessWindow, mode: str) -> None:
    if utc_today() <= window.stale_after:
        return
    message = (
        f"snapshot is past stale_after {window.stale_after} "
        f"(checks_through {window.checks_through})"
    )
    if mode == "fail":
        raise ValidationError(message)
    print(f"warning: {message}", file=sys.stderr)


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


# A carrier setting holds no control character and no surrounding whitespace.
# The sanitizer removes them; a parser would turn a carriage return into a
# space and a SIM would no longer match.
CONTROL_CHARACTERS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Android's MMS service opens the MMSC with java.net.URL, which needs a scheme.
MMSC_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/?#\s].*")


def validate_clean_text(path: Path, value: Any, name: str, max_len: int = 120) -> str:
    text = validate_string(path, value, name, max_len)
    if CONTROL_CHARACTERS_RE.search(text) or text != text.strip():
        raise ValidationError(
            f"{path}: {name} has a control character or surrounding whitespace"
        )
    return text


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

    validate_clean_text(path, data.get("display_name"), "display_name")

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
        if not subscriber_prefix_ok("iccid", iccid):
            raise ValidationError(f"{path}: invalid ICCID prefix {iccid!r}")
    for imsi in match.get("imsi_prefix_patterns", []):
        if (
            not subscriber_prefix_ok("imsi", imsi)
            or not 5 <= len(imsi) <= 10
            or any(char not in "0123456789xX" for char in imsi)
        ):
            raise ValidationError(f"{path}: invalid IMSI prefix pattern {imsi!r}")
    for spn in match.get("spn", []):
        validate_clean_text(path, spn, "match.spn[]", 80)
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
            try:
                expected = expected_config_type(key)
            except ValueError as exc:
                raise ValidationError(f"{path}: {exc}") from exc
            if not config_value_has_expected_type(key, value):
                raise ValidationError(
                    f"{path}: android_carrier_config.{key} must be {expected}"
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
            validate_clean_text(path, apn.get("name"), f"android_apns[{index}].name", 80)
            validate_clean_text(path, apn.get("apn"), f"android_apns[{index}].apn", 120)
            types = apn.get("types")
            require_type(path, types, list, f"android_apns[{index}].types")
            if not types:
                raise ValidationError(f"{path}: android_apns[{index}].types is empty")
            if types != sorted(set(types)):
                raise ValidationError(
                    f"{path}: android_apns[{index}].types must be sorted and unique"
                )
            for apn_type in types:
                if apn_type not in APN_TYPES:
                    raise ValidationError(
                        f"{path}: android_apns[{index}] has invalid type"
                    )
            for key, max_len in APN_STRING_FIELDS.items():
                if key in apn:
                    validate_clean_text(
                        path, apn[key], f"android_apns[{index}].{key}", max_len
                    )
            if "mmsc" in apn and not MMSC_RE.fullmatch(apn["mmsc"]):
                raise ValidationError(
                    f"{path}: android_apns[{index}].mmsc is not a URL with a scheme"
                )
            for key in APN_PORT_FIELDS:
                if key in apn:
                    port = apn[key]
                    if (
                        not isinstance(port, int)
                        or isinstance(port, bool)
                        or not 1 <= port <= 65535
                    ):
                        raise ValidationError(f"{path}: android_apns[{index}].{key}")
            for key, (minimum, maximum) in APN_INT_FIELDS.items():
                if key in apn:
                    value = apn[key]
                    if (
                        not isinstance(value, int)
                        or isinstance(value, bool)
                        or not minimum <= value <= maximum
                    ):
                        raise ValidationError(f"{path}: android_apns[{index}].{key}")
            for key in APN_BOOL_FIELDS:
                if key in apn and not isinstance(apn[key], bool):
                    raise ValidationError(f"{path}: android_apns[{index}].{key}")
            if "mvno_type" in apn or "mvno_match_data" in apn:
                if apn.get("mvno_type") not in APN_MVNO_TYPES:
                    raise ValidationError(f"{path}: android_apns[{index}].mvno_type")
                validate_clean_text(
                    path,
                    apn.get("mvno_match_data"),
                    f"android_apns[{index}].mvno_match_data",
                    120,
                )
                mvno_type = apn["mvno_type"]
                if mvno_type in SUBSCRIBER_PREFIX_KINDS and not subscriber_prefix_ok(
                    mvno_type, apn["mvno_match_data"]
                ):
                    raise ValidationError(
                        f"{path}: android_apns[{index}].mvno_match_data is not "
                        f"an {mvno_type.upper()} prefix"
                    )
            for key in ("protocol", "roaming_protocol"):
                if key in apn and apn[key] not in APN_PROTOCOLS:
                    raise ValidationError(f"{path}: android_apns[{index}].{key}")
        validate_mms_rows(path, apns)

    return data


def validate_mms_rows(path: Path, apns: list[dict[str, Any]]) -> None:
    """A row that serves MMS needs an MMSC. Android's MMS service looks it up
    among the SIM's mms rows with the APN its MMS connection uses, so another
    mms row of the same APN and MVNO selector may carry it."""

    def serves_mms(apn: dict[str, Any]) -> bool:
        return "mms" in apn["types"] or "*" in apn["types"]

    def selector(apn: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (apn.get("mvno_type"), apn.get("mvno_match_data"), apn["apn"])

    supplied = {selector(apn) for apn in apns if serves_mms(apn) and apn.get("mmsc")}
    for index, apn in enumerate(apns):
        if serves_mms(apn) and not apn.get("mmsc") and selector(apn) not in supplied:
            raise ValidationError(
                f"{path}: android_apns[{index}] serves mms, and no mms row of its "
                "APN carries an MMSC"
            )


def validate_index(
    index_path: Path,
    profiles_by_path: dict[str, dict[str, Any]],
) -> FreshnessWindow | None:
    index = load_json(index_path)
    require_type(index_path, index, dict, "index root")
    if set(index) - FRESHNESS_KEYS != {"schema_version", "profiles"}:
        raise ValidationError(f"{index_path}: index has invalid keys")
    if index.get("schema_version") != 1:
        raise ValidationError(f"{index_path}: schema_version must be 1")
    window = parse_freshness_window(index_path, index)
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
    return window


def validate_generated_files(generated_dir: Path) -> None:
    if not generated_dir.exists():
        raise ValidationError(f"{generated_dir}: missing generated directory")
    actual = {
        path.relative_to(generated_dir).as_posix()
        for path in generated_dir.rglob("*")
        if path.is_file()
    }
    extra = actual - GENERATED_FILES - {
        f"{COUNTRY_APN_DIR}/{name}" for name in COUNTRY_FILE_NAMES
    }
    if extra:
        raise ValidationError(
            f"{generated_dir}: unexpected generated files: {sorted(extra)}"
        )
    missing = REQUIRED_GENERATED_FILES - actual
    if missing:
        raise ValidationError(
            f"{generated_dir}: missing generated files: {sorted(missing)}"
        )


def validate_resolution_items(path: Path, items: Any, expected_kind: str, name: str) -> None:
    require_type(path, items, list, name)
    for index, item in enumerate(items):
        require_type(path, item, dict, f"{name}[{index}]")
        if set(item) != {
            "kind",
            "section",
            "key",
            "observed_value_count",
            "resolution",
        }:
            raise ValidationError(f"{path}: {name}[{index}] has invalid keys")
        if item["kind"] != expected_kind:
            raise ValidationError(f"{path}: {name}[{index}].kind is invalid")
        validate_string(path, item["section"], f"{name}[{index}].section", 80)
        validate_string(path, item["key"], f"{name}[{index}].key", 160)
        count = item["observed_value_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValidationError(f"{path}: {name}[{index}].observed_value_count is invalid")
        if item["resolution"] not in {"conditional", "omitted_from_stable", "published_variants"}:
            raise ValidationError(f"{path}: {name}[{index}].resolution is invalid")


def validate_entry_dates(
    path: Path,
    evidence: dict[str, Any],
    index: int,
    capabilities: dict[str, str] | None,
) -> None:
    """newest_entry and capability_newest_entries are optional; each appears
    only where every supporting observation carries an entry date."""
    newest_month: tuple[int, int] | None = None
    if "newest_entry" in evidence:
        newest_month = parse_entry_month(
            path, evidence["newest_entry"], f"profiles[{index}].newest_entry"
        )
    if "capability_newest_entries" not in evidence:
        return
    label = f"profiles[{index}].capability_newest_entries"
    entries = evidence["capability_newest_entries"]
    require_type(path, entries, dict, label)
    if not entries:
        raise ValidationError(f"{path}: {label} is empty")
    for key, value in entries.items():
        if key not in CAPABILITY_KEYS:
            raise ValidationError(f"{path}: {label} names an unknown capability")
        month = parse_entry_month(path, value, f"{label}.{key}")
        if newest_month is not None and month > newest_month:
            raise ValidationError(
                f"{path}: {label}.{key} is newer than the profile's newest_entry"
            )
        if capabilities is not None and capabilities.get(key, "unknown") == "unknown":
            raise ValidationError(
                f"{path}: {label}.{key} dates a capability the profile does not publish"
            )


# The exact upstream versions behind a profile, per source family: firmware
# build IDs, full Git commits of the repository a value was read from, and
# Apple carrier bundle and iOS versions. Never URLs, paths, or file names.
SOURCE_VERSION_PATTERNS = {
    "builds": re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,119}"),
    "commits": re.compile(r"[0-9a-f]{40}"),
    "bundle_versions": re.compile(r"[0-9]{1,6}(\.[0-9]{1,6}){0,4}"),
    "ios_versions": re.compile(r"[0-9]{1,3}(\.[0-9]{1,3}){0,3}"),
}
MAX_SOURCE_VERSIONS = 5000


def validate_source_versions(
    path: Path, items: Any, index: int, sources: list[str]
) -> None:
    """source_versions is optional. Each item names one of the profile's
    sources once, in source order, with at least one non-empty, sorted, unique
    list of version identifiers of the kinds in SOURCE_VERSION_PATTERNS."""
    label = f"profiles[{index}].source_versions"
    require_type(path, items, list, label)
    if not items:
        raise ValidationError(f"{path}: {label} is empty")
    named: list[str] = []
    for item_index, item in enumerate(items):
        item_label = f"{label}[{item_index}]"
        require_type(path, item, dict, item_label)
        kinds = set(item) - {"source"}
        if "source" not in item or not kinds or kinds - set(SOURCE_VERSION_PATTERNS):
            raise ValidationError(f"{path}: {item_label} has invalid keys")
        source = item["source"]
        if source not in sources:
            raise ValidationError(f"{path}: {item_label}.source is not a profile source")
        named.append(source)
        for kind in sorted(kinds):
            values = item[kind]
            require_type(path, values, list, f"{item_label}.{kind}")
            if not values or len(values) > MAX_SOURCE_VERSIONS:
                raise ValidationError(f"{path}: {item_label}.{kind} is empty or too long")
            for value in values:
                if not isinstance(value, str) or not SOURCE_VERSION_PATTERNS[kind].fullmatch(
                    value
                ):
                    raise ValidationError(f"{path}: {item_label}.{kind} has an invalid value")
            validate_canonical_list(path, values, f"{item_label}.{kind}")
    if named != sorted(set(named)):
        raise ValidationError(f"{path}: {label} must name each source once, sorted")


STALE_CAPABILITY_GATE = "stale_single_source_entry"
# An off that one source family alone gives, which is not the operator's own
# configuration: the capability is published as unknown, and a false
# capability-gating CarrierConfig key is left out.
SINGLE_FAMILY_OFF_GATE = "single_family_off"
# The gates that publish a capability as unknown although a source gives it.
UNKNOWN_CAPABILITY_GATES = {STALE_CAPABILITY_GATE, SINGLE_FAMILY_OFF_GATE}
# The CarrierConfig keys the importers treat as a capability's Android switch.
# Mirrors CAPABILITY_GATING_CONFIG_KEYS in the private sanitizer.
CAPABILITY_GATING_CONFIG_KEYS = {
    "carrier_volte_available_bool": "volte",
    "carrier_wfc_ims_available_bool": "vowifi",
    "carrier_vt_available_bool": "video_calling",
    "enabledMMS": "mms",
    "imssms.sms_over_ims_supported_bool": "sms_over_ims",
    "support_ims_conference_call_bool": "ims_conference",
    "support_conference_call_bool": "ims_conference",
}
CAPABILITY_SOURCE_KINDS = {"on", "off", "conditional"}


def validate_stale_capability_gates(
    path: Path,
    gates: list[dict[str, Any]],
    index: int,
    capabilities: dict[str, str] | None,
    config_keys: set[str] | None = None,
) -> None:
    """A capability withheld because its only source family's newest entry is
    over five years old, or because one source family alone turns it off,
    names a real capability that the profile publishes as unknown. A
    single-family gate on a CarrierConfig key names a capability-gating key
    the profile does not publish."""
    for gate_index, gate in enumerate(gates):
        name, _, key = gate["key"].partition(":")
        if name not in UNKNOWN_CAPABILITY_GATES:
            continue
        label = f"profiles[{index}].quality_gates[{gate_index}]"
        if gate["resolution"] != "omitted_from_stable":
            raise ValidationError(f"{path}: {label} is not a valid {name} gate")
        if name == SINGLE_FAMILY_OFF_GATE and gate["section"] == "android_carrier_config":
            if key not in CAPABILITY_GATING_CONFIG_KEYS:
                raise ValidationError(f"{path}: {label} names no capability-gating key")
            if config_keys is not None and key in config_keys:
                raise ValidationError(
                    f"{path}: {label} withholds {key}, but the profile publishes it"
                )
            continue
        if gate["section"] != "capabilities" or key not in CAPABILITY_KEYS:
            raise ValidationError(f"{path}: {label} is not a valid {name} gate")
        if capabilities is not None and capabilities.get(key, "unknown") != "unknown":
            raise ValidationError(
                f"{path}: {label} withholds {key}, but the profile publishes it"
            )


def validate_capability_sources(
    path: Path,
    evidence: dict[str, Any],
    index: int,
    sources: list[str],
    capabilities: dict[str, str] | None,
) -> None:
    """capability_sources is optional. It maps every capability that a source
    gives a value to the profile sources that turn it on, turn it off, or call
    it conditional, and it agrees with the published value: supported has only
    on, unsupported only off, conditional two kinds or conditional, and unknown
    names the gate that withheld it. Where it is present it covers every
    published capability, and fact_sources holds no capability entry."""
    if "capability_sources" not in evidence:
        return
    label = f"profiles[{index}].capability_sources"
    value = evidence["capability_sources"]
    require_type(path, value, dict, label)
    if not value:
        raise ValidationError(f"{path}: {label} is empty")
    withheld = {
        gate["key"].partition(":")[2]
        for gate in evidence.get("quality_gates", [])
        if gate["section"] == "capabilities"
        and gate["key"].partition(":")[0] in UNKNOWN_CAPABILITY_GATES
    }
    for key, kinds in value.items():
        if key not in CAPABILITY_KEYS:
            raise ValidationError(f"{path}: {label} names an unknown capability")
        require_type(path, kinds, dict, f"{label}.{key}")
        if not kinds or set(kinds) - CAPABILITY_SOURCE_KINDS:
            raise ValidationError(f"{path}: {label}.{key} has invalid keys")
        for kind, names in kinds.items():
            validate_canonical_list(path, names, f"{label}.{key}.{kind}")
            if not names or not set(names) <= set(sources):
                raise ValidationError(f"{path}: {label}.{key}.{kind} is invalid")
        if capabilities is None:
            continue
        published = capabilities.get(key, "unknown")
        agrees = {
            "supported": set(kinds) == {"on"},
            "unsupported": set(kinds) == {"off"},
            "conditional": len(kinds) >= 2 or "conditional" in kinds,
            "unknown": key in withheld,
        }[published]
        if not agrees:
            raise ValidationError(
                f"{path}: {label}.{key} does not support the published value {published}"
            )
    if capabilities is not None:
        missing = sorted(
            key
            for key, published in capabilities.items()
            if published != "unknown" and key not in value
        )
        if missing:
            raise ValidationError(f"{path}: {label} lacks published {missing}")
    if any(fact["section"] == "capabilities" for fact in evidence["fact_sources"]):
        raise ValidationError(
            f"{path}: profiles[{index}] lists capabilities in both fact_sources and "
            "capability_sources"
        )


def validate_evidence_index(
    path: Path,
    expected_profile_ids: set[str],
    index_window: FreshnessWindow | None = None,
    profile_capabilities: dict[str, dict[str, str]] | None = None,
    profile_config_keys: dict[str, set[str]] | None = None,
) -> FreshnessWindow | None:
    data = load_json(path)
    require_type(path, data, dict, "evidence index")
    if set(data) - FRESHNESS_KEYS != {
        "schema_version",
        "description",
        "source_snapshots",
        "profiles",
    }:
        raise ValidationError(f"{path}: evidence index has invalid keys")
    if data.get("schema_version") != 1:
        raise ValidationError(f"{path}: schema_version must be 1")
    validate_string(path, data.get("description"), "description", 400)
    window = parse_freshness_window(path, data)
    if index_window is not None and window is not None and window != index_window:
        raise ValidationError(f"{path}: freshness window does not match the stable index")
    window = window or index_window
    today = utc_today()
    earliest: date | None = None
    source_snapshots = data.get("source_snapshots")
    require_type(path, source_snapshots, list, "source_snapshots")
    source_names: list[str] = []
    for index, snapshot in enumerate(source_snapshots):
        require_type(path, snapshot, dict, f"source_snapshots[{index}]")
        if set(snapshot) != {
            "schema_version",
            "source_name",
            "upstream_url",
            "revision",
            "revision_date",
            "checked_at",
            "license_expression",
        }:
            raise ValidationError(f"{path}: source_snapshots[{index}] has invalid keys")
        if snapshot.get("schema_version") != 2:
            raise ValidationError(f"{path}: source_snapshots[{index}] has invalid schema")
        source_name = validate_string(
            path, snapshot.get("source_name"), f"source_snapshots[{index}].source_name", 64
        )
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]{1,63}", source_name):
            raise ValidationError(f"{path}: source_snapshots[{index}].source_name is invalid")
        source_names.append(source_name)
        upstream_url = snapshot.get("upstream_url")
        if not isinstance(upstream_url, str) or not re.fullmatch(r"https://[^\s]{3,500}", upstream_url):
            raise ValidationError(f"{path}: source_snapshots[{index}].upstream_url is invalid")
        revision = snapshot.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise ValidationError(f"{path}: source_snapshots[{index}].revision is invalid")
        try:
            revision_date = date.fromisoformat(snapshot.get("revision_date"))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"{path}: source_snapshots[{index}].revision_date is invalid"
            ) from exc
        try:
            checked_at = date.fromisoformat(snapshot.get("checked_at"))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"{path}: source_snapshots[{index}].checked_at is invalid"
            ) from exc
        if checked_at > today:
            raise ValidationError(f"{path}: source_snapshots[{index}] is future-dated")
        if window is not None and checked_at < window.checks_through:
            raise ValidationError(
                f"{path}: source_snapshots[{index}].checked_at is before checks_through"
            )
        earliest = checked_at if earliest is None else min(earliest, checked_at)
        validate_string(
            path,
            snapshot.get("license_expression"),
            f"source_snapshots[{index}].license_expression",
            80,
        )
    if source_names != sorted(set(source_names)):
        raise ValidationError(f"{path}: source snapshots must be sorted and unique")
    profiles = data.get("profiles")
    require_type(path, profiles, list, "profiles")
    actual_profile_ids: list[str] = []
    allowed_keys = {
        "profile_id",
        "observation_count",
        "sources",
        "verified_observation_count",
        "fact_sources",
        "reviewed_range",
        "observed_scope",
        "observed_model_source_groups",
        "conflicts",
        "quality_gates",
        "newest_entry",
        "capability_newest_entries",
        "source_versions",
        "capability_sources",
    }
    scope_keys = {
        "models",
        "multi_csc",
        "sales_codes",
        "android_majors",
        "firmware_regions",
        "firmware_builds",
        "omc_revisions",
        "omc_versions",
        "source_layers",
    }
    for index, evidence in enumerate(profiles):
        require_type(path, evidence, dict, f"profiles[{index}]")
        if set(evidence) - allowed_keys:
            raise ValidationError(f"{path}: profiles[{index}] has unknown keys")
        profile_id = validate_string(
            path, evidence.get("profile_id"), f"profiles[{index}].profile_id", 96
        )
        actual_profile_ids.append(profile_id)
        count = evidence.get("observation_count")
        verified = evidence.get("verified_observation_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValidationError(f"{path}: profiles[{index}].observation_count is invalid")
        if (
            not isinstance(verified, int)
            or isinstance(verified, bool)
            or not 0 <= verified <= count
        ):
            raise ValidationError(
                f"{path}: profiles[{index}].verified_observation_count is invalid"
            )
        sources = evidence.get("sources")
        validate_canonical_list(path, sources, f"profiles[{index}].sources")
        if not sources:
            raise ValidationError(f"{path}: profiles[{index}].sources is empty")
        for source in sources:
            if not isinstance(source, str) or not re.fullmatch(r"[a-z0-9_]{2,64}", source):
                raise ValidationError(f"{path}: profiles[{index}] has unsafe source name")
        fact_sources = evidence.get("fact_sources")
        require_type(path, fact_sources, list, f"profiles[{index}].fact_sources")
        actual_fact_keys: list[tuple[str, str]] = []
        for fact_index, fact in enumerate(fact_sources):
            label = f"profiles[{index}].fact_sources[{fact_index}]"
            require_type(path, fact, dict, label)
            if set(fact) != {"section", "key", "sources"}:
                raise ValidationError(f"{path}: {label} has invalid keys")
            section = fact.get("section")
            if section not in {
                "capabilities",
                "android_carrier_config",
                "android_apns",
                "addons",
            }:
                raise ValidationError(f"{path}: {label}.section is invalid")
            key = validate_string(path, fact.get("key"), f"{label}.key", 180)
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,180}", key):
                raise ValidationError(f"{path}: {label}.key is unsafe")
            fact_source_names = fact.get("sources")
            validate_canonical_list(path, fact_source_names, f"{label}.sources")
            if not fact_source_names or not set(fact_source_names) <= set(sources):
                raise ValidationError(f"{path}: {label}.sources is invalid")
            if fact_source_names == sources:
                # An absent fact means every profile source supports it.
                raise ValidationError(f"{path}: {label} is a redundant override")
            actual_fact_keys.append((section, key))
        if actual_fact_keys != sorted(set(actual_fact_keys)):
            raise ValidationError(
                f"{path}: profiles[{index}].fact_sources must be sorted and unique"
            )
        reviewed_range = evidence.get("reviewed_range")
        if reviewed_range is not None:
            require_type(path, reviewed_range, dict, f"profiles[{index}].reviewed_range")
            if set(reviewed_range) != {"oldest", "newest"}:
                raise ValidationError(f"{path}: profiles[{index}].reviewed_range has invalid keys")
            try:
                oldest = date.fromisoformat(reviewed_range["oldest"])
                newest = date.fromisoformat(reviewed_range["newest"])
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"{path}: profiles[{index}].reviewed_range is invalid"
                ) from exc
            if oldest > newest:
                raise ValidationError(f"{path}: profiles[{index}].reviewed_range is reversed")
            if newest > today:
                raise ValidationError(
                    f"{path}: profiles[{index}].reviewed_range is future-dated"
                )
            if window is not None and oldest < window.checks_through:
                raise ValidationError(
                    f"{path}: profiles[{index}].reviewed_range is before checks_through"
                )
            earliest = oldest if earliest is None else min(earliest, oldest)
        scope = evidence.get("observed_scope")
        if scope is not None:
            require_type(path, scope, dict, f"profiles[{index}].observed_scope")
            if set(scope) - scope_keys:
                raise ValidationError(f"{path}: profiles[{index}].observed_scope has unknown keys")
            for key, values in scope.items():
                validate_canonical_list(path, values, f"profiles[{index}].observed_scope.{key}")
                for value in values:
                    if (
                        not isinstance(value, str)
                        or value != value.strip()
                        or not re.fullmatch(
                            r"[A-Za-z0-9][A-Za-z0-9._+() -]{0,119}", value
                        )
                    ):
                        raise ValidationError(
                            f"{path}: profiles[{index}].observed_scope.{key} is unsafe"
                        )
        model_source_groups = evidence.get("observed_model_source_groups")
        if model_source_groups is not None:
            label = f"profiles[{index}].observed_model_source_groups"
            require_type(path, model_source_groups, list, label)
            if not model_source_groups:
                raise ValidationError(f"{path}: {label} is empty")
            grouped_models: list[str] = []
            group_sort_keys: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
            for group_index, group in enumerate(model_source_groups):
                group_label = f"{label}[{group_index}]"
                require_type(path, group, dict, group_label)
                if set(group) != {"models", "sources"}:
                    raise ValidationError(f"{path}: {group_label} has invalid keys")
                models = group.get("models")
                model_sources = group.get("sources")
                validate_canonical_list(path, models, f"{group_label}.models")
                validate_canonical_list(path, model_sources, f"{group_label}.sources")
                if not models or not model_sources or not set(model_sources) <= set(sources):
                    raise ValidationError(f"{path}: {group_label} is empty or unscoped")
                if model_sources == sources:
                    raise ValidationError(f"{path}: {group_label} is a redundant override")
                grouped_models.extend(models)
                group_sort_keys.append((tuple(model_sources), tuple(models)))
            scoped_models = scope.get("models", []) if isinstance(scope, dict) else []
            if (
                len(grouped_models) != len(set(grouped_models))
                or not set(grouped_models) <= set(scoped_models)
            ):
                raise ValidationError(
                    f"{path}: {label} repeats or scopes an unobserved model"
                )
            if group_sort_keys != sorted(group_sort_keys):
                raise ValidationError(f"{path}: {label} must be canonically sorted")
        if "source_versions" in evidence:
            validate_source_versions(path, evidence["source_versions"], index, sources)
        validate_entry_dates(
            path,
            evidence,
            index,
            None if profile_capabilities is None else profile_capabilities.get(profile_id),
        )
        if "conflicts" in evidence:
            validate_resolution_items(
                path, evidence["conflicts"], "conflict", f"profiles[{index}].conflicts"
            )
        if "quality_gates" in evidence:
            validate_resolution_items(
                path,
                evidence["quality_gates"],
                "quality_gate",
                f"profiles[{index}].quality_gates",
            )
            validate_stale_capability_gates(
                path,
                evidence["quality_gates"],
                index,
                None if profile_capabilities is None else profile_capabilities.get(profile_id),
                None if profile_config_keys is None else profile_config_keys.get(profile_id),
            )
        validate_capability_sources(
            path,
            evidence,
            index,
            sources,
            None if profile_capabilities is None else profile_capabilities.get(profile_id),
        )
    if actual_profile_ids != sorted(actual_profile_ids):
        raise ValidationError(f"{path}: profiles must be sorted by profile_id")
    if set(actual_profile_ids) != expected_profile_ids or len(actual_profile_ids) != len(
        expected_profile_ids
    ):
        raise ValidationError(f"{path}: profile IDs do not match the stable database")
    if window is None and earliest is not None:
        window = FreshnessWindow(earliest, earliest + timedelta(days=STALE_AFTER_DAYS))
    return window


def validate_android_metadata(
    generated_dir: Path,
    expected_profile_ids: set[str],
    window: FreshnessWindow | None = None,
) -> None:
    metadata_path = generated_dir / "android" / "metadata.json"
    metadata = load_json(metadata_path)
    require_type(metadata_path, metadata, dict, "metadata")
    if set(metadata) - FRESHNESS_KEYS != {"schema_version", "target", "output", "omissions"}:
        raise ValidationError(f"{metadata_path}: metadata has invalid keys")
    if metadata.get("schema_version") != 1:
        raise ValidationError(f"{metadata_path}: schema_version must be 1")
    metadata_window = parse_freshness_window(metadata_path, metadata)
    if metadata_window is not None and metadata_window != window:
        raise ValidationError(
            f"{metadata_path}: freshness window does not match the evidence index"
        )
    target = metadata.get("target")
    require_type(metadata_path, target, dict, "target")
    version = target.get("apn_database_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValidationError(f"{metadata_path}: APN database version is invalid")
    if target.get("carrier_config_gid_matching") != "exact_only":
        raise ValidationError(f"{metadata_path}: CarrierConfig GID policy is invalid")

    try:
        apn_root = ET.parse(generated_dir / "android" / "apns-conf.xml").getroot()
        config_root = ET.parse(generated_dir / "android" / "carrier-config-list.xml").getroot()
    except ET.ParseError as exc:
        raise ValidationError(f"{generated_dir}: invalid generated Android XML: {exc}") from exc
    if apn_root.tag != "apns" or apn_root.attrib.get("version") != str(version):
        raise ValidationError(f"{metadata_path}: APN XML version does not match metadata")
    if config_root.tag != "carrier_config_list":
        raise ValidationError(f"{generated_dir}: invalid CarrierConfig XML root")
    validate_country_apns(generated_dir, apn_root)
    output = metadata.get("output")
    require_type(metadata_path, output, dict, "output")
    if output != {
        "apn_row_count": len(apn_root.findall("apn")),
        "carrier_config_xml_block_count": len(config_root.findall("carrier_config")),
    }:
        raise ValidationError(f"{metadata_path}: output counts do not match XML")
    omissions = metadata.get("omissions")
    require_type(metadata_path, omissions, dict, "omissions")
    expected_omission_keys = {
        "apn_profile_ids_with_unrepresentable_match",
        "apn_profiles_with_unrepresentable_match",
        "apn_rows_rejected_by_lineageos_schema",
        "carrier_config_profile_ids_with_unrepresentable_match",
        "carrier_config_profiles_with_unrepresentable_match",
    }
    if set(omissions) != expected_omission_keys:
        raise ValidationError(f"{metadata_path}: omission fields are invalid")
    rejected = omissions["apn_rows_rejected_by_lineageos_schema"]
    if not isinstance(rejected, int) or isinstance(rejected, bool) or rejected < 0:
        raise ValidationError(f"{metadata_path}: rejected APN row count is invalid")
    for prefix in ("apn", "carrier_config"):
        count = omissions[f"{prefix}_profiles_with_unrepresentable_match"]
        profile_ids = omissions[f"{prefix}_profile_ids_with_unrepresentable_match"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValidationError(f"{metadata_path}: omission count is invalid")
        validate_canonical_list(
            metadata_path,
            profile_ids,
            f"omissions.{prefix}_profile_ids_with_unrepresentable_match",
        )
        if len(profile_ids) != count or not set(profile_ids) <= expected_profile_ids:
            raise ValidationError(f"{metadata_path}: omission profile IDs are invalid")


def validate_country_apns(generated_dir: Path, apn_root: ET.Element) -> None:
    """apns-conf.xml holds no row LineageOS's apns-conf.xsd rejects, and the
    per-country files hold exactly its rows whose MCC has a country, each in
    its country's file, in apns-conf.xml order, under the same APN version."""
    expected: dict[str, list[dict[str, str]]] = {}
    for index, row in enumerate(apn_root.findall("apn")):
        if not fits_lineageos_schema(row.attrib):
            raise ValidationError(
                f"{generated_dir / 'android' / 'apns-conf.xml'}: row {index + 1} "
                "fails LineageOS's apns-conf.xsd"
            )
        for name in country_files(row.attrib.get("mcc", "")):
            expected.setdefault(name, []).append(dict(row.attrib))
    directory = generated_dir / COUNTRY_APN_DIR
    actual_names = sorted(path.name for path in directory.glob("*")) if directory.is_dir() else []
    if actual_names != sorted(expected):
        raise ValidationError(
            f"{directory}: per-country APN files do not match apns-conf.xml: "
            f"missing {sorted(set(expected) - set(actual_names))}, "
            f"unexpected {sorted(set(actual_names) - set(expected))}"
        )
    for name in actual_names:
        path = directory / name
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            raise ValidationError(f"{path}: invalid APN XML: {exc}") from exc
        if root.tag != "apns" or root.attrib != apn_root.attrib:
            raise ValidationError(f"{path}: APN XML version does not match apns-conf.xml")
        if [dict(row.attrib) for row in root] != expected[name]:
            raise ValidationError(f"{path}: rows do not match apns-conf.xml")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("carriers_dir", nargs="?", type=Path, default=Path("carriers"))
    parser.add_argument(
        "index_path", nargs="?", type=Path, default=Path("generated/index.json")
    )
    parser.add_argument("--freshness", choices=FRESHNESS_MODES, default="warn")
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    global TODAY_OVERRIDE
    TODAY_OVERRIDE = args.today
    carriers_dir = args.carriers_dir
    index_path = args.index_path

    if not carriers_dir.exists():
        raise ValidationError(f"{carriers_dir}: missing carriers directory")

    profile_paths = sorted(
        path for path in carriers_dir.rglob("*.json") if path.is_file()
    )
    seen_ids: set[str] = set()
    profiles_by_path: dict[str, dict[str, Any]] = {}
    generic_network_profiles: dict[str, str] = {}
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
        match = profile["match"]
        if set(match) == {"mccmnc"}:
            for mccmnc in match["mccmnc"]:
                previous = generic_network_profiles.get(mccmnc)
                if previous is not None:
                    raise ValidationError(
                        f"{path}: broad MCC/MNC {mccmnc} is already owned by {previous}"
                    )
                generic_network_profiles[mccmnc] = profile_id

    index_window = validate_index(index_path, profiles_by_path)
    validate_generated_files(index_path.parent)
    window = validate_evidence_index(
        index_path.parent / "evidence-index.json",
        seen_ids,
        index_window,
        {
            profile["profile_id"]: profile["capabilities"]
            for profile in profiles_by_path.values()
        },
        {
            profile["profile_id"]: set(profile.get("android_carrier_config") or {})
            for profile in profiles_by_path.values()
        },
    )
    validate_android_metadata(index_path.parent, seen_ids, window)
    if window is not None:
        check_freshness(window, args.freshness)
    print(f"validated {len(profile_paths)} public carrier profile(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
