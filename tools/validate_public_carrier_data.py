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
from lineageos_apns import fits_lineageos_schema


STALE_AFTER_DAYS = 180
FRESHNESS_MODES = ("warn", "fail")
# The early alarm for a stopped pipeline. stale_after says when the data is too
# old to ship, about six months after the oldest check. A pipeline that stops
# shows much sooner: the weekly import re-checks every source, and each check
# reaches this repo with a publish. When a source's last check, or the last
# data publish, is older than this many days, three weekly runs in a row were
# missed.
LIVENESS_MAX_AGE_DAYS = 21
# Lanes that run daily get a shorter limit, so one dead lane shows on its own
# instead of hiding behind the others' fresh checks. Samsung's lanes run daily
# on the self-hosted runner; a healthy manifest's checked_at can lag up to six
# days, because an unchanged revision is rewritten only once a week.
LANE_LIVENESS_MAX_AGE_DAYS = {
    "samsung_carrier_config": 10,
    "samsung_ims": 10,
    "samsung_omc": 10,
}
# Samsung's IMS and CarrierConfig values come from one tracked firmware. When
# Samsung ships a new build of it and the lane has not rebuilt the indexes yet,
# the previous build's values keep publishing for up to this many days after
# the build was last confirmed current, listed in the evidence index as
# vendor_build_grace. Mirrors SAMSUNG_BUILD_GRACE_DAYS in the private sanitizer.
VENDOR_BUILD_GRACE_DAYS = 30
VENDOR_BUILD_GRACE_KEYS = {"sources", "model", "region", "build", "confirmed_at", "grace_until"}
LIVENESS_MODES = ("off", "warn", "fail")
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
    "android/lookup.json",
    "android/metadata.json",
    "devices/README.md",
    "devices/android-carrier-artifacts.json",
    "devices/android.json",
    "devices/apple-carrier-artifacts.json",
    "devices/apple.json",
    "devices/index.json",
}

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


def source_checks(evidence_index_path: Path) -> dict[str, date]:
    """Each source snapshot's checked_at in the evidence index, by source name."""
    if not evidence_index_path.exists():
        return {}
    return {
        snapshot["source_name"]: date.fromisoformat(snapshot["checked_at"])
        for snapshot in load_json(evidence_index_path).get("source_snapshots", [])
        if isinstance(snapshot, dict)
        and isinstance(snapshot.get("source_name"), str)
        and isinstance(snapshot.get("checked_at"), str)
    }


def lane_liveness_limit(source_name: str) -> int:
    return LANE_LIVENESS_MAX_AGE_DAYS.get(source_name, LIVENESS_MAX_AGE_DAYS)


def vendor_build_grace(evidence_index_path: Path) -> list[dict[str, Any]]:
    """The evidence index's vendor_build_grace items, already validated."""
    if not evidence_index_path.exists():
        return []
    items = load_json(evidence_index_path).get("vendor_build_grace", [])
    return items if isinstance(items, list) else []


def check_liveness(
    checks: dict[str, date],
    last_publish: date | None,
    mode: str,
    grace: list[dict[str, Any]] | None = None,
) -> None:
    """Warn, or fail, when any source's last check is older than its lane's
    limit (LANE_LIVENESS_MAX_AGE_DAYS, otherwise LIVENESS_MAX_AGE_DAYS) or the
    last data publish is more than LIVENESS_MAX_AGE_DAYS old.

    A vendor build in its grace (vendor_build_grace) always warns: its lane
    runs but has not confirmed the values it publishes. Its last confirmation
    counts as the lane's check, so it fails like a stopped lane once that is
    older than the lane's limit, while the values still publish."""
    if mode == "off":
        return
    today = utc_today()
    late = [
        f"source {name} was last checked on {day}, {(today - day).days} days ago "
        f"(more than {lane_liveness_limit(name)} days)"
        for name, day in sorted(checks.items())
        if (today - day).days > lane_liveness_limit(name)
    ]
    for item in grace or []:
        confirmed = date.fromisoformat(item["confirmed_at"])
        age = (today - confirmed).days
        limit = min(lane_liveness_limit(name) for name in item["sources"])
        successor = f" (superseded by {item['superseded_by']})" if item.get("superseded_by") else ""
        description = (
            f"{', '.join(item['sources'])} values of {item['model']} {item['region']} "
            f"build {item['build']}{successor} publish under the vendor build grace: "
            f"last confirmed current on {confirmed}, {age} days ago; they drop on "
            f"{item['grace_until']} unless the lane rebuilds them from the current build"
        )
        if age > limit:
            late.append(f"{description} (more than {limit} days)")
        else:
            print(f"warning: {description}", file=sys.stderr)
    if last_publish is not None and (today - last_publish).days > LIVENESS_MAX_AGE_DAYS:
        late.append(
            f"the last data publish was on {last_publish}, "
            f"{(today - last_publish).days} days ago (more than {LIVENESS_MAX_AGE_DAYS} days)"
        )
    if not late:
        return
    message = "the pipeline looks stopped: " + "; ".join(late)
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


# Mobile country codes ITU-T E.212 assigns, the same list as ASSIGNED_MCCS in
# the private tools/lab_networks.py: the 238 codes annexed to ITU Operational
# Bulletin No. 1117 (position on 1 February 2017, updated by amendments in
# later bulletins), 902 (MulteFire Alliance, MNC list of OB 1280, 2023) and
# 991 (trials, ITU-T E.212 Amendment 2 (06/2020)), plus 001 (test networks) and
# 999 (private networks). A profile whose every network code has another MCC
# can match no SIM, and the sanitizer leaves it out (unassigned_mcc).
ASSIGNED_MCCS = frozenset(
    {
        "202", "204", "206", "208", "212", "213", "214", "216", "218", "219", "220", "221",
        "222", "225", "226", "228", "230", "231", "232", "234", "235", "238", "240", "242",
        "244", "246", "247", "248", "250", "255", "257", "259", "260", "262", "266", "268",
        "270", "272", "274", "276", "278", "280", "282", "283", "284", "286", "288", "290",
        "292", "293", "294", "295", "297", "302", "308", "310", "311", "312", "313", "314",
        "315", "316", "330", "332", "334", "338", "340", "342", "344", "346", "348", "350",
        "352", "354", "356", "358", "360", "362", "363", "364", "365", "366", "368", "370",
        "372", "374", "376", "400", "401", "402", "404", "405", "406", "410", "412", "413",
        "414", "415", "416", "417", "418", "419", "420", "421", "422", "424", "425", "426",
        "427", "428", "429", "430", "431", "432", "434", "436", "437", "438", "440", "441",
        "450", "452", "454", "455", "456", "457", "460", "461", "466", "467", "470", "472",
        "502", "505", "510", "514", "515", "520", "525", "528", "530", "536", "537", "539",
        "540", "541", "542", "543", "544", "545", "546", "547", "548", "549", "550", "551",
        "552", "553", "554", "555", "602", "603", "604", "605", "606", "607", "608", "609",
        "610", "611", "612", "613", "614", "615", "616", "617", "618", "619", "620", "621",
        "622", "623", "624", "625", "626", "627", "628", "629", "630", "631", "632", "633",
        "634", "635", "636", "637", "638", "639", "640", "641", "642", "643", "645", "646",
        "647", "648", "649", "650", "651", "652", "653", "654", "655", "657", "658", "659",
        "702", "704", "706", "708", "710", "712", "714", "716", "722", "724", "730", "732",
        "734", "736", "738", "740", "742", "744", "746", "748", "750", "901",
        "902",
        "991",
        "001",
        "999",
    }
)


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
    if all(str(code)[:3] not in ASSIGNED_MCCS for code in match["mccmnc"]):
        raise ValidationError(
            f"{path}: no MCC/MNC of the match has an MCC ITU-T E.212 assigns"
        )
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


RESOLUTION_ITEM_KEYS = {"kind", "section", "key", "observed_value_count", "resolution"}
APN_FACT_KEY_RE = re.compile(r"sha256:[0-9a-f]{16}")


def validate_resolution_items(
    path: Path,
    items: Any,
    expected_kind: str,
    name: str,
    sources: list[str] | None = None,
) -> None:
    require_type(path, items, list, name)
    for index, item in enumerate(items):
        require_type(path, item, dict, f"{name}[{index}]")
        label = f"{name}[{index}]"
        if set(item) - {"variant_sources"} != RESOLUTION_ITEM_KEYS:
            raise ValidationError(f"{path}: {label} has invalid keys")
        if item["kind"] != expected_kind:
            raise ValidationError(f"{path}: {label}.kind is invalid")
        validate_string(path, item["section"], f"{label}.section", 80)
        validate_string(path, item["key"], f"{label}.key", 160)
        count = item["observed_value_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValidationError(f"{path}: {label}.observed_value_count is invalid")
        if item["resolution"] not in {"conditional", "omitted_from_stable", "published_variants"}:
            raise ValidationError(f"{path}: {label}.resolution is invalid")
        if "variant_sources" in item:
            validate_variant_sources(path, item, label, sources)


def validate_variant_sources(
    path: Path, item: dict[str, Any], label: str, sources: list[str] | None
) -> None:
    """variant_sources names, for each variant of an APN conflict, the profile
    sources that gave it: one entry per variant, keyed by the APN fact key of
    the variant (data-model.md), sorted by key."""
    if (
        item["kind"] != "conflict"
        or item["section"] != "android_apns"
        or item["resolution"] != "published_variants"
    ):
        raise ValidationError(f"{path}: {label}.variant_sources belongs only to APN variants")
    variants = item["variant_sources"]
    require_type(path, variants, list, f"{label}.variant_sources")
    if len(variants) != item["observed_value_count"]:
        raise ValidationError(
            f"{path}: {label}.variant_sources must name every observed variant"
        )
    keys: list[str] = []
    for variant_index, variant in enumerate(variants):
        variant_label = f"{label}.variant_sources[{variant_index}]"
        require_type(path, variant, dict, variant_label)
        if set(variant) != {"key", "sources"}:
            raise ValidationError(f"{path}: {variant_label} has invalid keys")
        if not isinstance(variant["key"], str) or not APN_FACT_KEY_RE.fullmatch(variant["key"]):
            raise ValidationError(f"{path}: {variant_label}.key is not an APN fact key")
        keys.append(variant["key"])
        validate_canonical_list(path, variant["sources"], f"{variant_label}.sources")
        if not variant["sources"] or (
            sources is not None and not set(variant["sources"]) <= set(sources)
        ):
            raise ValidationError(f"{path}: {variant_label}.sources is invalid")
    if keys != sorted(set(keys)):
        raise ValidationError(f"{path}: {label}.variant_sources must be sorted and unique")


def validate_entry_dates(
    path: Path,
    evidence: dict[str, Any],
    index: int,
    capabilities: dict[str, str] | None,
) -> None:
    """newest_entry and capability_newest_entries are optional; each appears
    only where every supporting observation carries an entry date. A
    capability is dated whether or not the profile publishes it: a value a
    gate withheld keeps its date, so it must be one capability_sources
    names."""
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
        sourced = isinstance(evidence.get("capability_sources"), dict) and key in evidence[
            "capability_sources"
        ]
        if capabilities is not None and capabilities.get(key, "unknown") == "unknown" and not sourced:
            raise ValidationError(
                f"{path}: {label}.{key} dates a capability no source gives a value"
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


# A capability that rests on one source family whose newest entry is more than
# five years old, withheld for its age alone.
STALE_CAPABILITY_GATE = "stale_single_source_entry"
# The same kind of old single-family value, withheld on evidence instead of age:
# only a frozen copy of a source gives it (frozen_source_only), or no
# observation with an entry inside the five-year window covers the profile's
# own scope, its network code or its SIM selector (unseen_scope).
FROZEN_SOURCE_ONLY_GATE = "frozen_source_only"
UNSEEN_SCOPE_GATE = "unseen_scope"
# An off that one source family alone gives, which is not the operator's own
# configuration: the capability is published as unknown, and a false
# capability-gating CarrierConfig key is left out.
SINGLE_FAMILY_OFF_GATE = "single_family_off"
# The gates that withhold an old single-family value. Since 2026-10-06 the
# capability-gating CarrierConfig key of a capability they withhold is left
# out with the label, so no profile publishes a switch next to such a label.
WITHHOLDING_CAPABILITY_GATES = {
    STALE_CAPABILITY_GATE,
    FROZEN_SOURCE_ONLY_GATE,
    UNSEEN_SCOPE_GATE,
}
# The gates that publish a capability as unknown although a source gives it.
UNKNOWN_CAPABILITY_GATES = {
    STALE_CAPABILITY_GATE,
    FROZEN_SOURCE_ONLY_GATE,
    UNSEEN_SCOPE_GATE,
    SINGLE_FAMILY_OFF_GATE,
}
# The vendor sources whose observations are dated by firmware build, which an
# APN fact's old_build_sources may name.
OLD_BUILD_SOURCES = {"samsung_omc", "samsung_ims"}
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
# APN rows LineageOS removed from its list, left out of a profile because no
# source gives them with an entry newer than the removal. The key names the
# android_vendor_apn commit first seen without the rows; the count is the rows
# left out of this profile.
LINEAGEOS_APN_REMOVED_GATE = "lineageos_apn_removed"
LINEAGEOS_APN_REMOVED_RE = re.compile(rf"{LINEAGEOS_APN_REMOVED_GATE}:[0-9a-f]{{40}}")


# Why LineageOS removed the rows of one commit, per row, as the private
# tombstone state records it: a cited shutdown or merger (defunct), an old
# value replaced by a new one (superseded), an extra network code cleaned up
# while the operator's main code keeps its APNs (extra_code), a row moved to
# another code or selector (moved), old WAP APNs removed as a policy (policy),
# a row deleted because one maker's ROM no longer has it (vendor_rom_absent),
# and a removal nobody classified yet (unclassified).
APN_REMOVAL_REASONS = frozenset(
    {
        "defunct",
        "superseded",
        "extra_code",
        "moved",
        "policy",
        "vendor_rom_absent",
        "unclassified",
    }
)
APN_REMOVAL_COMMIT_KEYS = {"commit", "removed_on", "reasons"}


def apn_removal_commits_of(gates: list[dict[str, Any]]) -> set[str]:
    return {
        gate["key"].partition(":")[2]
        for gate in gates
        if isinstance(gate, dict)
        and isinstance(gate.get("key"), str)
        and gate["key"].partition(":")[0] == LINEAGEOS_APN_REMOVED_GATE
    }


def validate_apn_removal_commits(path: Path, items: Any, referenced: set[str]) -> None:
    """apn_removal_commits is optional. Each item names one android_vendor_apn
    commit that a lineageos_apn_removed gate of a profile or a withdrawn
    profile names, with its date, the sorted reasons of the rows it leaves
    out (APN_REMOVAL_REASONS), and optionally its LineageOS Gerrit change
    number. Items are sorted by commit, and every referenced commit is listed
    exactly once."""
    label = "apn_removal_commits"
    require_type(path, items, list, label)
    commits: list[str] = []
    for index, item in enumerate(items):
        item_label = f"{label}[{index}]"
        require_type(path, item, dict, item_label)
        if set(item) - {"gerrit_change"} != APN_REMOVAL_COMMIT_KEYS:
            raise ValidationError(f"{path}: {item_label} has invalid keys")
        if not isinstance(item["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", item["commit"]):
            raise ValidationError(f"{path}: {item_label}.commit is invalid")
        try:
            removed_on = date.fromisoformat(item["removed_on"])
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{path}: {item_label}.removed_on is invalid") from exc
        if removed_on > utc_today():
            raise ValidationError(f"{path}: {item_label}.removed_on is future-dated")
        reasons = item["reasons"]
        validate_canonical_list(path, reasons, f"{item_label}.reasons")
        if not reasons or not set(reasons) <= APN_REMOVAL_REASONS:
            raise ValidationError(f"{path}: {item_label}.reasons is invalid")
        if "gerrit_change" in item:
            change = item["gerrit_change"]
            if not isinstance(change, int) or isinstance(change, bool) or not 0 < change < 10**8:
                raise ValidationError(f"{path}: {item_label}.gerrit_change is invalid")
        commits.append(item["commit"])
    if commits != sorted(set(commits)):
        raise ValidationError(f"{path}: {label} must be sorted by commit and unique")
    if set(commits) != referenced:
        raise ValidationError(
            f"{path}: {label} must list exactly the commits the lineageos_apn_removed gates name"
        )


WITHDRAWN_PROFILE_KEYS = {"profile_id", "sources", "quality_gates"}


def validate_withdrawn_profiles(
    path: Path, items: Any, published_ids: set[str]
) -> list[dict[str, Any]]:
    """withdrawn_profiles is optional. Each item is a profile that sources give
    but that publishes no fact because quality gates removed every fact it
    had, such as APN rows LineageOS removed or a capability withheld: its
    profile_id, which no published profile has, its sources, and its quality
    gates, each an omission. Items are sorted by profile_id and unique.
    Returns the gates of every item."""
    label = "withdrawn_profiles"
    require_type(path, items, list, label)
    if not items:
        raise ValidationError(f"{path}: {label} is empty")
    ids: list[str] = []
    gates: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        item_label = f"{label}[{index}]"
        require_type(path, item, dict, item_label)
        if set(item) != WITHDRAWN_PROFILE_KEYS:
            raise ValidationError(f"{path}: {item_label} has invalid keys")
        profile_id = validate_string(path, item["profile_id"], f"{item_label}.profile_id", 96)
        if not re.fullmatch(r"open\.[0-9a-z]+\.[0-9a-f]{12}", profile_id):
            raise ValidationError(f"{path}: {item_label}.profile_id is invalid")
        if profile_id in published_ids:
            raise ValidationError(f"{path}: {item_label} names a published profile")
        ids.append(profile_id)
        sources = item["sources"]
        validate_canonical_list(path, sources, f"{item_label}.sources")
        if not sources or not all(
            isinstance(name, str) and re.fullmatch(r"[a-z0-9_]{2,64}", name) for name in sources
        ):
            raise ValidationError(f"{path}: {item_label}.sources is invalid")
        item_gates = item["quality_gates"]
        validate_resolution_items(
            path, item_gates, "quality_gate", f"{item_label}.quality_gates", sources
        )
        if not item_gates or any(gate["resolution"] != "omitted_from_stable" for gate in item_gates):
            raise ValidationError(f"{path}: {item_label}.quality_gates must name omissions")
        validate_apn_removal_gates(path, item_gates, index)
        validate_stale_capability_gates(path, item_gates, index, None, None)
        gates.extend(item_gates)
    if ids != sorted(set(ids)):
        raise ValidationError(f"{path}: {label} must be sorted by profile_id and unique")
    return gates


def validate_apn_removal_gates(path: Path, gates: list[dict[str, Any]], index: int) -> None:
    """A lineageos_apn_removed gate names one full android_vendor_apn commit,
    once, in the APN section, as an omission."""
    seen: set[str] = set()
    for gate_index, gate in enumerate(gates):
        if gate["key"].partition(":")[0] != LINEAGEOS_APN_REMOVED_GATE:
            continue
        label = f"profiles[{index}].quality_gates[{gate_index}]"
        if (
            not LINEAGEOS_APN_REMOVED_RE.fullmatch(gate["key"])
            or gate["section"] != "android_apns"
            or gate["resolution"] != "omitted_from_stable"
        ):
            raise ValidationError(f"{path}: {label} is not a valid {LINEAGEOS_APN_REMOVED_GATE} gate")
        if gate["key"] in seen:
            raise ValidationError(f"{path}: {label} repeats a removal commit")
        seen.add(gate["key"])


def validate_stale_capability_gates(
    path: Path,
    gates: list[dict[str, Any]],
    index: int,
    capabilities: dict[str, str] | None,
    config_keys: set[str] | None = None,
) -> None:
    """A capability withheld because its only source family's newest entry is
    over five years old (for its age alone, or because only a frozen copy
    gives it, or because no fresh observation covers the profile's scope), or
    because one source family alone turns it off, names a real capability
    that the profile publishes as unknown. The profile publishes no
    capability-gating key of a capability the first three gates withhold: a
    withheld label takes its switch with it. A single-family gate on a
    CarrierConfig key names a capability-gating key the profile does not
    publish."""
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
        if name in WITHHOLDING_CAPABILITY_GATES and config_keys is not None:
            switches = sorted(
                config_key
                for config_key, capability in CAPABILITY_GATING_CONFIG_KEYS.items()
                if capability == key and config_key in config_keys
            )
            if switches:
                raise ValidationError(
                    f"{path}: {label} withholds {key}, but the profile publishes its switch "
                    f"{', '.join(switches)}"
                )


def validate_capability_sources(
    path: Path,
    evidence: dict[str, Any],
    index: int,
    sources: list[str],
    capabilities: dict[str, str] | None,
) -> None:
    """capability_sources maps every capability that a source gives a value to
    the profile sources that turn it on, turn it off, or call it conditional,
    and it agrees with the published value: supported has only on, unsupported
    only off, conditional two kinds or conditional, and unknown names the gate
    that withheld it. It covers every published capability, so a profile that
    publishes one needs it."""
    if "capability_sources" not in evidence:
        if capabilities is not None and any(
            value != "unknown" for value in capabilities.values()
        ):
            raise ValidationError(
                f"{path}: profiles[{index}] publishes capabilities without capability_sources"
            )
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


# Informational flags on a profile's facts. They withhold nothing.
# old_single_source: the capability's value rests on one source family whose
# newest entry behind it is more than five years old; capability_newest_entries
# gives the month. Until 2026-10-06 capability_label_withheld marked a
# capability-gating CarrierConfig key published next to a withheld label;
# such a key is now left out, and the flag is refused.
FLAG_SECTIONS = {
    "old_single_source": "capabilities",
}


def validate_flags(
    path: Path,
    evidence: dict[str, Any],
    index: int,
    capabilities: dict[str, str] | None,
    config_keys: set[str] | None,
) -> None:
    """flags is optional: a non-empty list of section, key and flag, sorted and
    unique. old_single_source names a capability that capability_sources names
    and capability_newest_entries dates."""
    if "flags" not in evidence:
        return
    label = f"profiles[{index}].flags"
    items = evidence["flags"]
    require_type(path, items, list, label)
    if not items:
        raise ValidationError(f"{path}: {label} is empty")
    keys: list[tuple[str, str, str]] = []
    for item_index, item in enumerate(items):
        item_label = f"{label}[{item_index}]"
        require_type(path, item, dict, item_label)
        if set(item) != {"section", "key", "flag"}:
            raise ValidationError(f"{path}: {item_label} has invalid keys")
        flag, section, key = item["flag"], item["section"], item["key"]
        if FLAG_SECTIONS.get(flag) != section:
            raise ValidationError(f"{path}: {item_label} is not a valid flag")
        if (
            key not in CAPABILITY_KEYS
            or key not in (evidence.get("capability_sources") or {})
            or key not in (evidence.get("capability_newest_entries") or {})
        ):
            raise ValidationError(f"{path}: {item_label} flags an undated or unsourced capability")
        keys.append((section, key, flag))
    if keys != sorted(set(keys)):
        raise ValidationError(f"{path}: {label} must be sorted and unique")


# What a capability value rests on where a source's on says less than a
# configuration that turns the feature on. Each basis belongs to one capability
# and one source: Samsung OMC's vonr means Samsung's settings offer the VoNR
# switch for the carrier on the listed models, not that VoNR is on by default.
CAPABILITY_BASES = {
    "samsung_vonr_switch": {"capability": "vonr", "source": "samsung_omc"},
}
# Up to this many models are listed by name; more are given as the SHA-256 of
# their sorted names joined by newlines.
MAX_LISTED_BASIS_MODELS = 24
SALES_CODE_RE = re.compile(r"[A-Z0-9]{2,8}")


def validate_capability_basis(
    path: Path,
    evidence: dict[str, Any],
    index: int,
    sources: list[str],
) -> None:
    """capability_basis is optional. It maps a capability to what its value
    rests on, one of CAPABILITY_BASES: the basis, its source (a profile source
    that turns the capability on in capability_sources), the sales codes and
    the number of models behind it, and either the models (sorted, unique, at
    most MAX_LISTED_BASIS_MODELS, all in observed_scope.models) or the SHA-256
    of their sorted names. The sales codes are in observed_scope.sales_codes."""
    if "capability_basis" not in evidence:
        return
    label = f"profiles[{index}].capability_basis"
    value = evidence["capability_basis"]
    require_type(path, value, dict, label)
    if not value:
        raise ValidationError(f"{path}: {label} is empty")
    scope = evidence.get("observed_scope") if isinstance(evidence.get("observed_scope"), dict) else {}
    capability_sources = evidence.get("capability_sources")
    if not isinstance(capability_sources, dict):
        capability_sources = {}
    for key, basis in value.items():
        item_label = f"{label}.{key}"
        if key not in CAPABILITY_KEYS:
            raise ValidationError(f"{path}: {label} names an unknown capability")
        require_type(path, basis, dict, item_label)
        listed = "models" in basis
        expected_keys = {"basis", "source", "sales_codes", "model_count"} | (
            {"models"} if listed else {"models_sha256"}
        )
        if set(basis) != expected_keys:
            raise ValidationError(f"{path}: {item_label} has invalid keys")
        kind = CAPABILITY_BASES.get(basis["basis"])
        if kind is None or kind["capability"] != key:
            raise ValidationError(f"{path}: {item_label}.basis is invalid")
        source = basis["source"]
        if source != kind["source"] or source not in sources:
            raise ValidationError(f"{path}: {item_label}.source is invalid")
        if source not in (capability_sources.get(key) or {}).get("on", []):
            raise ValidationError(
                f"{path}: {item_label} rests on a source that does not turn {key} on"
            )
        sales_codes = basis["sales_codes"]
        validate_canonical_list(path, sales_codes, f"{item_label}.sales_codes")
        if (
            not sales_codes
            or not all(isinstance(code, str) and SALES_CODE_RE.fullmatch(code) for code in sales_codes)
            or not set(sales_codes) <= set(scope.get("sales_codes", []))
        ):
            raise ValidationError(f"{path}: {item_label}.sales_codes is invalid")
        count = basis["model_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValidationError(f"{path}: {item_label}.model_count is invalid")
        if listed:
            models = basis["models"]
            validate_canonical_list(path, models, f"{item_label}.models")
            if (
                len(models) != count
                or count > MAX_LISTED_BASIS_MODELS
                or not set(models) <= set(scope.get("models", []))
            ):
                raise ValidationError(f"{path}: {item_label}.models is invalid")
        else:
            digest = basis["models_sha256"]
            if (
                not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or count <= MAX_LISTED_BASIS_MODELS
                or count > len(scope.get("models", []))
            ):
                raise ValidationError(f"{path}: {item_label}.models_sha256 is invalid")


SCOPE_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+() -]{0,119}")


def validate_vendor_build_grace(
    path: Path, items: Any, window: FreshnessWindow | None
) -> None:
    """vendor_build_grace is optional. Each item names a tracked vendor
    firmware whose values still publish although the vendor has a newer build:
    the sources whose values it carries, the model, region and build, and
    optionally the build that superseded it (superseded_by); confirmed_at, the
    last day the build was confirmed current, not before checks_through; and
    grace_until, the day the values drop, 1 to VENDOR_BUILD_GRACE_DAYS days
    later. Items are sorted and unique."""
    label = "vendor_build_grace"
    require_type(path, items, list, label)
    if not items:
        raise ValidationError(f"{path}: {label} is empty")
    keys: list[tuple[Any, ...]] = []
    for index, item in enumerate(items):
        item_label = f"{label}[{index}]"
        require_type(path, item, dict, item_label)
        if set(item) - {"superseded_by"} != VENDOR_BUILD_GRACE_KEYS:
            raise ValidationError(f"{path}: {item_label} has invalid keys")
        sources = item["sources"]
        validate_canonical_list(path, sources, f"{item_label}.sources")
        if not sources or not all(
            isinstance(name, str) and re.fullmatch(r"[a-z0-9_]{2,64}", name) for name in sources
        ):
            raise ValidationError(f"{path}: {item_label}.sources is invalid")
        for key in ("model", "region", "build", "superseded_by"):
            if key in item and (
                not isinstance(item[key], str) or not SCOPE_VALUE_RE.fullmatch(item[key])
            ):
                raise ValidationError(f"{path}: {item_label}.{key} is invalid")
        try:
            confirmed = date.fromisoformat(item["confirmed_at"])
            until = date.fromisoformat(item["grace_until"])
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{path}: {item_label} has an invalid date") from exc
        if confirmed > utc_today():
            raise ValidationError(f"{path}: {item_label}.confirmed_at is future-dated")
        if window is not None and confirmed < window.checks_through:
            raise ValidationError(f"{path}: {item_label}.confirmed_at is before checks_through")
        if not 1 <= (until - confirmed).days <= VENDOR_BUILD_GRACE_DAYS:
            raise ValidationError(
                f"{path}: {item_label}.grace_until must be 1 to {VENDOR_BUILD_GRACE_DAYS} "
                "days after confirmed_at"
            )
        keys.append((tuple(sources), item["model"], item["region"], item["build"]))
    if keys != sorted(set(keys)):
        raise ValidationError(f"{path}: {label} must be sorted and unique")


def validate_evidence_index(
    path: Path,
    expected_profile_ids: set[str],
    index_window: FreshnessWindow | None = None,
    profile_capabilities: dict[str, dict[str, str]] | None = None,
    profile_config_keys: dict[str, set[str]] | None = None,
) -> FreshnessWindow | None:
    data = load_json(path)
    require_type(path, data, dict, "evidence index")
    if set(data) - FRESHNESS_KEYS - {
        "vendor_build_grace",
        "withdrawn_profiles",
        "apn_removal_commits",
    } != {
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
    if "vendor_build_grace" in data:
        validate_vendor_build_grace(path, data["vendor_build_grace"], window)
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
        "capability_basis",
        "flags",
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
            if set(fact) - {"old_build_sources"} != {"section", "key", "sources"}:
                raise ValidationError(f"{path}: {label} has invalid keys")
            section = fact.get("section")
            # Capabilities are in capability_sources, with on and off lists.
            if section not in {
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
            old_builds = fact.get("old_build_sources")
            if old_builds is not None:
                # The vendor sources that give an APN fact only from firmware
                # builds more than three years old; the APN ranking does not
                # count them as current vendors.
                validate_canonical_list(path, old_builds, f"{label}.old_build_sources")
                if (
                    section != "android_apns"
                    or not old_builds
                    or not set(old_builds) <= set(fact_source_names) & OLD_BUILD_SOURCES
                ):
                    raise ValidationError(f"{path}: {label}.old_build_sources is invalid")
            elif fact_source_names == sources:
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
                path,
                evidence["conflicts"],
                "conflict",
                f"profiles[{index}].conflicts",
                sources,
            )
        if "quality_gates" in evidence:
            validate_resolution_items(
                path,
                evidence["quality_gates"],
                "quality_gate",
                f"profiles[{index}].quality_gates",
                sources,
            )
            validate_apn_removal_gates(path, evidence["quality_gates"], index)
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
        validate_capability_basis(path, evidence, index, sources)
        validate_flags(
            path,
            evidence,
            index,
            None if profile_capabilities is None else profile_capabilities.get(profile_id),
            None if profile_config_keys is None else profile_config_keys.get(profile_id),
        )
    if actual_profile_ids != sorted(actual_profile_ids):
        raise ValidationError(f"{path}: profiles must be sorted by profile_id")
    if set(actual_profile_ids) != expected_profile_ids or len(actual_profile_ids) != len(
        expected_profile_ids
    ):
        raise ValidationError(f"{path}: profile IDs do not match the stable database")
    withdrawn_gates = (
        validate_withdrawn_profiles(path, data["withdrawn_profiles"], set(actual_profile_ids))
        if "withdrawn_profiles" in data
        else []
    )
    if "apn_removal_commits" in data:
        referenced = apn_removal_commits_of(withdrawn_gates)
        for evidence in profiles:
            referenced |= apn_removal_commits_of(evidence.get("quality_gates", []))
        validate_apn_removal_commits(path, data["apn_removal_commits"], referenced)
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
    if set(metadata) - FRESHNESS_KEYS != {
        "schema_version",
        "target",
        "output",
        "omissions",
        "data_digest",
    }:
        raise ValidationError(f"{metadata_path}: metadata has invalid keys")
    digest = metadata["data_digest"]
    if not isinstance(digest, str) or not DATA_DIGEST_RE.fullmatch(digest):
        raise ValidationError(f"{metadata_path}: data_digest is invalid")
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
    # carrier-config-list.xml carries no gid1, gid2 or ICCID filter; profiles
    # that need one are left out and listed under omissions.
    if set(target) != {
        "apn_database_version",
        "carrier_config_gid_matching",
        "carrier_config_iccid_matching",
    } or (target["carrier_config_gid_matching"], target["carrier_config_iccid_matching"]) != (
        "omitted",
        "omitted",
    ):
        raise ValidationError(f"{metadata_path}: CarrierConfig GID and ICCID policy is invalid")

    try:
        apn_root = ET.parse(generated_dir / "android" / "apns-conf.xml").getroot()
        config_root = ET.parse(generated_dir / "android" / "carrier-config-list.xml").getroot()
    except ET.ParseError as exc:
        raise ValidationError(f"{generated_dir}: invalid generated Android XML: {exc}") from exc
    if apn_root.tag != "apns" or apn_root.attrib.get("version") != str(version):
        raise ValidationError(f"{metadata_path}: APN XML version does not match metadata")
    for name in ("apns-conf.xml", "carrier-config-list.xml"):
        validate_provenance_header(generated_dir / "android" / name, metadata)
    if config_root.tag != "carrier_config_list":
        raise ValidationError(f"{generated_dir}: invalid CarrierConfig XML root")
    validate_apn_schema(generated_dir, apn_root)
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
        "ia_types_left_out_not_vendor_current",
    }
    if set(omissions) != expected_omission_keys:
        raise ValidationError(f"{metadata_path}: omission fields are invalid")
    for key, what in (
        ("apn_rows_rejected_by_lineageos_schema", "rejected APN row count"),
        ("ia_types_left_out_not_vendor_current", "count of rows without their attach type"),
    ):
        count = omissions[key]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValidationError(f"{metadata_path}: {what} is invalid")
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


DATA_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
HEADER_FIELD_RE = re.compile(r"\s*(data_digest|checks_through|stale_after): (\S+)\s*")


def provenance_header_fields(path: Path) -> dict[str, str]:
    """The key: value lines of the comment that follows the XML declaration."""
    text = path.read_text(encoding="utf-8")
    declaration = '<?xml version="1.0" encoding="utf-8"?>\n<!--\n'
    if not text.startswith(declaration) or "\n-->\n" not in text:
        raise ValidationError(f"{path}: the provenance comment is missing")
    comment = text[len(declaration) : text.index("\n-->\n")]
    if "SPDX-License-Identifier: CC0-1.0" not in comment:
        raise ValidationError(f"{path}: the provenance comment names no CC0-1.0 licence")
    fields: dict[str, str] = {}
    for line in comment.split("\n"):
        found = HEADER_FIELD_RE.fullmatch(line)
        if found:
            if found.group(1) in fields:
                raise ValidationError(f"{path}: the provenance comment repeats {found.group(1)}")
            fields[found.group(1)] = found.group(2)
    return fields


def validate_provenance_header(path: Path, metadata: dict[str, Any]) -> None:
    """A generated XML file names the data digest and freshness window of
    metadata.json in its provenance comment."""
    fields = provenance_header_fields(path)
    expected = {
        key: metadata[key]
        for key in ("data_digest", "checks_through", "stale_after")
        if key in metadata
    }
    if fields != expected:
        raise ValidationError(
            f"{path}: the provenance comment does not match metadata.json: "
            f"{fields} != {expected}"
        )


def validate_lookup(generated_dir: Path, expected_profile_ids: set[str]) -> None:
    """lookup.json lists every profile once. newest_entry, where present,
    repeats the month the evidence index publishes for that profile, and is
    present exactly where the evidence index has one."""
    path = generated_dir / "android" / "lookup.json"
    lookup = load_json(path)
    require_type(path, lookup, dict, "lookup")
    if set(lookup) != {"schema_version", "resolution_order", "match_semantics", "profiles"}:
        raise ValidationError(f"{path}: lookup has invalid keys")
    profiles = lookup["profiles"]
    require_type(path, profiles, list, "profiles")
    evidence_path = generated_dir / "evidence-index.json"
    newest_entries = {
        item["profile_id"]: item["newest_entry"]
        for item in load_json(evidence_path).get("profiles", [])
        if "newest_entry" in item
    } if evidence_path.exists() else {}
    seen: set[str] = set()
    allowed = {
        "profile_id",
        "display_name",
        "path",
        "match",
        "specificity",
        "capabilities",
        "android_apn_count",
        "has_android_carrier_config",
        "checks_through",
        "stale_after",
        "newest_entry",
    }
    for index, record in enumerate(profiles):
        label = f"profiles[{index}]"
        require_type(path, record, dict, label)
        if set(record) - allowed:
            raise ValidationError(f"{path}: {label} has unknown keys")
        profile_id = record.get("profile_id")
        if profile_id in seen or profile_id not in expected_profile_ids:
            raise ValidationError(f"{path}: {label}.profile_id is unknown or repeated")
        seen.add(profile_id)
        parse_freshness_window(path, record)
        if "newest_entry" in record:
            parse_entry_month(path, record["newest_entry"], f"{label}.newest_entry")
        if record.get("newest_entry") != newest_entries.get(profile_id):
            raise ValidationError(
                f"{path}: {label}.newest_entry does not match the evidence index"
            )
    if seen != expected_profile_ids:
        raise ValidationError(f"{path}: lookup does not list every profile")


def validate_apn_schema(generated_dir: Path, apn_root: ET.Element) -> None:
    """apns-conf.xml holds no row LineageOS's apns-conf.xsd rejects."""
    for index, row in enumerate(apn_root.findall("apn")):
        if not fits_lineageos_schema(row.attrib):
            raise ValidationError(
                f"{generated_dir / 'android' / 'apns-conf.xml'}: row {index + 1} "
                "fails LineageOS's apns-conf.xsd"
            )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("carriers_dir", nargs="?", type=Path, default=Path("carriers"))
    parser.add_argument(
        "index_path", nargs="?", type=Path, default=Path("generated/index.json")
    )
    parser.add_argument("--freshness", choices=FRESHNESS_MODES, default="warn")
    parser.add_argument(
        "--liveness",
        choices=LIVENESS_MODES,
        default="off",
        help=f"warn or fail when a source's last check is older than its lane's limit "
        f"(10 days for Samsung, otherwise {LIVENESS_MAX_AGE_DAYS}) or --last-publish is more "
        f"than {LIVENESS_MAX_AGE_DAYS} days old (default: off)",
    )
    parser.add_argument(
        "--last-publish",
        type=date.fromisoformat,
        default=None,
        help="the date of the last data publish, for --liveness",
    )
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
    validate_lookup(index_path.parent, seen_ids)
    if window is not None:
        check_freshness(window, args.freshness)
    check_liveness(
        source_checks(index_path.parent / "evidence-index.json")
        if args.liveness != "off"
        else {},
        args.last_publish,
        args.liveness,
        vendor_build_grace(index_path.parent / "evidence-index.json"),
    )
    print(f"validated {len(profile_paths)} public carrier profile(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
