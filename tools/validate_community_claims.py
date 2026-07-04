#!/usr/bin/env python3
"""Validate public community carrier-data claims.

Community claims are not stable carrier profiles. They are structured facts
that can help diagnose gaps, build opt-in community data, or later become
stable after enough evidence exists.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

import validate_public_carrier_data as public_data


RISK_SCORE = {
    "low": 1,
    "medium": 2,
    "high": 3,
}

RISK_BY_SCORE = {value: key for key, value in RISK_SCORE.items()}

MAX_EXPIRY_DAYS = {
    "low": 365,
    "medium": 180,
    "high": 90,
}

CLAIM_ID_RE = re.compile(r"^claim\.[a-z0-9][a-z0-9_.-]{5,120}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,80}$")
URL_RE = re.compile(r"^https://[A-Za-z0-9][A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{1,500}$")

BLOCK_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "full_iccid_or_imsi": re.compile(r"\b\d{14,22}\b"),
    "phone_number": re.compile(r"\+\d{8,15}\b"),
    "secret": re.compile(r"(?i)\b(password|passwd|pswd|secret|token|authorization|cookie)\b"),
    "raw_vendor_file": re.compile(
        r"(?i)\b(customer\.xml|cscfeature\.xml|imsupdate\.json|omc\.info|"
        r"carrier\.plist|\.ipcc|carrier_settings\.pb|mbn|dumpstate|logcat)\b"
    ),
    "raw_vendor_key": re.compile(
        r"\b(CarrierFeature_|GRASSE-AUTH|SemCarrierFeature|CarrierBundle|CSettingsDir)\b"
    ),
}

LOW_CAPABILITIES = {
    "mms",
    "esim",
}

MEDIUM_CAPABILITIES = {
    "volte",
    "vowifi",
    "vonr",
    "video_calling",
    "sms_over_ims",
    "rcs",
}

HIGH_CAPABILITIES = {
    "ims_conference",
    "wifi_calling_roaming",
}

LOW_CONFIG_KEYS = {
    "allow_adding_apns_bool",
    "apn_expand_bool",
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
    "hide_enhanced_4g_lte_bool",
    "hide_ims_apn_bool",
    "httpParams",
    "httpSocketTimeout",
    "maxImageHeight",
    "maxImageWidth",
    "maxMessageSize",
    "maxMessageTextSize",
    "maxSubjectLength",
    "mmsCloseConnection",
    "read_only_apn_fields_string_array",
    "read_only_apn_types_string_array",
    "recipientLimit",
    "show_apn_setting_cdma_bool",
    "show_ims_registration_status_bool",
    "show_wifi_calling_icon_in_status_bar_bool",
    "smsToMmsTextLengthThreshold",
    "smsToMmsTextThreshold",
    "supportMmsContentDisposition",
}

HIGH_CONFIG_KEY_PARTS = (
    "emergency",
    "entitlement",
    "provision",
    "conference",
    "call_barring",
    "call_forwarding",
    "ss_over_ut",
    "gba",
    "wps",
    "ecm",
    "roaming",
)

HIGH_ADDON_NAMESPACES = {
    "emergency_calling",
    "entitlement",
    "ims",
    "network_policy",
    "provisioning",
    "wifi_calling",
}

MEDIUM_ADDON_NAMESPACES = {
    "euc",
    "messaging",
    "presence",
    "rcs",
}


class ClaimError(Exception):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ClaimError(f"{path}: invalid JSON: {exc}") from exc


def require_type(path: Path, value: Any, expected: type, name: str) -> None:
    if not isinstance(value, expected):
        raise ClaimError(f"{path}: {name} must be {expected.__name__}")


def require_string(path: Path, value: Any, name: str, max_len: int = 240) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise ClaimError(f"{path}: {name} must be a non-empty string")
    return value


def parse_date(path: Path, value: Any, name: str) -> date:
    if not isinstance(value, str):
        raise ClaimError(f"{path}: {name} must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ClaimError(f"{path}: {name} must be YYYY-MM-DD") from exc


def scan_blocked_text(path: Path, value: Any, parts: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ClaimError(f"{path}: object keys must be strings")
            scan_blocked_text(path, key, parts + ("<key>",))
            scan_blocked_text(path, child, parts + (key,))
        return
    if isinstance(value, list):
        for child in value:
            scan_blocked_text(path, child, parts + ("[]",))
        return
    if not isinstance(value, str):
        return

    for name, pattern in BLOCK_PATTERNS.items():
        match = pattern.search(value)
        if match:
            raise ClaimError(
                f"{path}: blocked private/raw pattern {name}: {match.group(0)!r}"
            )


def validate_canonical_list(path: Path, values: Any, name: str) -> None:
    public_data.validate_canonical_list(path, values, name)


def validate_match(path: Path, match: Any) -> dict[str, Any]:
    require_type(path, match, dict, "carrier_match")
    if set(match) - {
        "mccmnc",
        "gid1_prefixes",
        "gid2_prefixes",
        "iccid_prefixes",
        "imsi_prefix_patterns",
        "spn",
        "android_carrier_ids",
    }:
        raise ClaimError(f"{path}: carrier_match has unknown keys")
    if not match.get("mccmnc"):
        raise ClaimError(f"{path}: carrier_match.mccmnc is required")
    for key, values in match.items():
        validate_canonical_list(path, values, f"carrier_match.{key}")

    profile = {
        "schema_version": 1,
        "profile_id": public_data.canonical_profile_id(match),
        "display_name": "Community claim validation",
        "match": match,
        "capabilities": {},
    }
    try:
        public_data.validate_profile_object(path, profile)
    except AttributeError:
        validate_match_fallback(path, match)
    except public_data.ValidationError as exc:
        raise ClaimError(str(exc)) from exc
    return match


def validate_match_fallback(path: Path, match: dict[str, Any]) -> None:
    for code in match.get("mccmnc", []):
        if not isinstance(code, str) or not re.fullmatch(r"\d{5,6}", code):
            raise ClaimError(f"{path}: invalid MCC/MNC {code!r}")
    for key in ("gid1_prefixes", "gid2_prefixes"):
        for value in match.get(key, []):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{1,32}", value):
                raise ClaimError(f"{path}: invalid {key} value {value!r}")
    for value in match.get("iccid_prefixes", []):
        if not isinstance(value, str) or not re.fullmatch(r"\d{5,13}", value):
            raise ClaimError(f"{path}: invalid ICCID prefix {value!r}")
    for value in match.get("imsi_prefix_patterns", []):
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[0-9xX]{5,10}", value)
            or not re.search(r"\d", value)
        ):
            raise ClaimError(f"{path}: invalid IMSI prefix pattern {value!r}")
    for value in match.get("spn", []):
        require_string(path, value, "carrier_match.spn[]", 80)
    for value in match.get("android_carrier_ids", []):
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000000:
            raise ClaimError(f"{path}: invalid Android carrier ID {value!r}")


def validate_changes(path: Path, changes: Any) -> dict[str, Any]:
    require_type(path, changes, dict, "changes")
    allowed = {
        "display_name",
        "match",
        "capabilities",
        "android_apns",
        "android_carrier_config",
        "addons",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ClaimError(f"{path}: changes has unknown keys: {sorted(unknown)}")
    if not changes:
        raise ClaimError(f"{path}: changes must not be empty")

    profile = {
        "schema_version": 1,
        "profile_id": "open.00101.9739cf7d0409",
        "display_name": changes.get("display_name", "Community claim validation"),
        "match": changes.get("match", {"mccmnc": ["00101"]}),
        "capabilities": changes.get("capabilities", {}),
    }
    for key in ("android_apns", "android_carrier_config", "addons"):
        if key in changes:
            profile[key] = changes[key]
    profile["profile_id"] = public_data.canonical_profile_id(profile["match"])
    try:
        public_data.validate_profile_object(path, profile)
    except AttributeError:
        validate_profile_like_fallback(path, profile)
    except public_data.ValidationError as exc:
        raise ClaimError(str(exc)) from exc
    return changes


def validate_profile_like_fallback(path: Path, profile: dict[str, Any]) -> None:
    temp_path = Path(str(path) + " changes")
    data = dict(profile)
    if data.get("display_name") is not None:
        require_string(path, data["display_name"], "changes.display_name", 120)
    validate_match_fallback(path, data["match"])
    capabilities = data.get("capabilities", {})
    require_type(path, capabilities, dict, "changes.capabilities")
    unknown_capabilities = set(capabilities) - public_data.CAPABILITY_KEYS
    if unknown_capabilities:
        raise ClaimError(f"{path}: unknown capability keys: {sorted(unknown_capabilities)}")
    for key, value in capabilities.items():
        if value not in public_data.CAPABILITY_VALUES:
            raise ClaimError(f"{path}: invalid capability value for {key}")
    config = data.get("android_carrier_config")
    if config is not None:
        require_type(path, config, dict, "changes.android_carrier_config")
        unknown_config = set(config) - public_data.ALLOWED_CONFIG_KEYS
        if unknown_config:
            raise ClaimError(f"{path}: unreviewed CarrierConfig keys: {sorted(unknown_config)}")
    apns = data.get("android_apns")
    if apns is not None:
        public_data.validate_profile(temp_path)


def max_risk(*risks: str) -> str:
    score = max(RISK_SCORE[risk] for risk in risks)
    return RISK_BY_SCORE[score]


def match_risk(match: dict[str, Any]) -> str:
    if match.get("android_carrier_ids"):
        return "low"
    specific_keys = {
        key
        for key in ("spn", "gid1_prefixes", "gid2_prefixes", "iccid_prefixes", "imsi_prefix_patterns")
        if match.get(key)
    }
    if "spn" in specific_keys or "gid1_prefixes" in specific_keys or "gid2_prefixes" in specific_keys:
        return "low"
    if "iccid_prefixes" in specific_keys:
        shortest = min(len(value) for value in match["iccid_prefixes"])
        return "low" if shortest >= 7 else "medium"
    if "imsi_prefix_patterns" in specific_keys:
        shortest = min(len(value.replace("x", "").replace("X", "")) for value in match["imsi_prefix_patterns"])
        return "low" if shortest >= 6 else "medium"
    return "medium" if len(match.get("mccmnc", [])) == 1 else "high"


def capability_risk(key: str) -> str:
    if key in LOW_CAPABILITIES:
        return "low"
    if key in MEDIUM_CAPABILITIES:
        return "medium"
    if key in HIGH_CAPABILITIES:
        return "high"
    return "medium"


def apn_risk(apn: dict[str, Any]) -> str:
    types = set(apn.get("types", []))
    if "*" in types or "emergency" in types:
        return "high"
    if types & {"ims", "xcap", "dun", "enterprise", "ia", "mcx", "rcs"}:
        return "medium"
    return "low"


def config_key_risk(key: str) -> str:
    if key in LOW_CONFIG_KEYS:
        return "low"
    if any(part in key for part in HIGH_CONFIG_KEY_PARTS):
        return "high"
    if key.startswith("carrier_default_wfc_") or key.startswith("carrier_wfc_"):
        return "medium"
    if "volte" in key or "vowifi" in key or "ims" in key or "handover" in key:
        return "medium"
    return "medium"


def addon_risk(namespace: str) -> str:
    if namespace in HIGH_ADDON_NAMESPACES:
        return "high"
    if namespace in MEDIUM_ADDON_NAMESPACES:
        return "medium"
    return "low"


def field_risk(changes: dict[str, Any]) -> str:
    risks = ["low"]
    if "match" in changes:
        risks.append("medium")
    for key in changes.get("capabilities", {}):
        risks.append(capability_risk(key))
    for apn in changes.get("android_apns", []) or []:
        risks.append(apn_risk(apn))
    for key in changes.get("android_carrier_config", {}) or {}:
        risks.append(config_key_risk(key))
    for namespace in changes.get("addons", {}) or {}:
        risks.append(addon_risk(namespace))
    return max_risk(*risks)


def change_type_risk(change_type: str) -> str:
    if change_type in {"add", "confirm"}:
        return "low"
    if change_type == "correct":
        return "medium"
    return "high"


def combined_claim_risk(field: str, match: str, change: str) -> str:
    if field == "low":
        if match == "high" or change == "high":
            return "medium"
        return "low"
    return max_risk(field, match, change)


def evidence_confidence(evidence: list[dict[str, Any]]) -> str:
    strong = 0
    medium = 0
    for item in evidence:
        evidence_type = item["type"]
        if evidence_type in {"maintained_source_reference", "maintainer_review"}:
            strong += 1
        elif evidence_type in {"device_test", "carrier_documentation"}:
            medium += 1
    if strong >= 1 or medium >= 2:
        return "high"
    if medium == 1:
        return "medium"
    return "low"


def validate_evidence(path: Path, evidence: Any) -> list[dict[str, Any]]:
    require_type(path, evidence, list, "evidence")
    if not evidence:
        raise ClaimError(f"{path}: evidence must contain at least one item")
    if len(evidence) > 10:
        raise ClaimError(f"{path}: evidence list is too large")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(evidence):
        require_type(path, item, dict, f"evidence[{index}]")
        allowed = {"type", "date", "result", "summary", "url"}
        unknown = set(item) - allowed
        if unknown:
            raise ClaimError(f"{path}: evidence[{index}] has unknown keys: {sorted(unknown)}")
        evidence_type = item.get("type")
        if evidence_type not in {
            "device_test",
            "carrier_documentation",
            "maintained_source_reference",
            "upstream_issue",
            "maintainer_review",
        }:
            raise ClaimError(f"{path}: evidence[{index}].type is invalid")
        evidence_date = parse_date(path, item.get("date"), f"evidence[{index}].date")
        if evidence_date > date.today():
            raise ClaimError(f"{path}: evidence[{index}].date cannot be in the future")
        result = item.get("result")
        if result not in {"works", "fails", "observed", "unknown"}:
            raise ClaimError(f"{path}: evidence[{index}].result is invalid")
        summary = require_string(path, item.get("summary"), f"evidence[{index}].summary", 280)
        clean = {
            "type": evidence_type,
            "date": evidence_date.isoformat(),
            "result": result,
            "summary": summary,
        }
        url = item.get("url")
        if url is not None:
            if not isinstance(url, str) or not URL_RE.fullmatch(url):
                raise ClaimError(f"{path}: evidence[{index}].url must be an https URL")
            clean["url"] = url
        out.append(clean)
    return out


def recommended_channel(
    status: str,
    computed_risk: str,
    confidence: str,
    change_type: str,
    conflicts_with_stable: bool,
) -> str:
    if status != "verified" or conflicts_with_stable:
        return "community"
    if computed_risk == "high":
        return "community"
    if computed_risk == "medium":
        return "candidate" if confidence == "high" and change_type != "override" else "community"
    if confidence in {"medium", "high"} and change_type in {"add", "confirm", "correct"}:
        return "stable_eligible"
    return "community"


def change_areas(changes: dict[str, Any]) -> list[str]:
    areas: set[str] = set()
    for key in changes:
        if key == "capabilities":
            for capability in changes[key]:
                areas.add(f"capabilities.{capability}")
        elif key == "android_carrier_config":
            for config_key in changes[key]:
                areas.add(f"android_carrier_config.{config_key}")
        elif key == "android_apns":
            for apn in changes[key]:
                for apn_type in apn.get("types", []):
                    areas.add(f"android_apns.{apn_type}")
        elif key == "addons":
            for namespace in changes[key]:
                areas.add(f"addons.{namespace}")
        else:
            areas.add(key)
    return sorted(areas)


def validate_claim(path: Path, claims_dir: Path) -> dict[str, Any]:
    data = load_json(path)
    require_type(path, data, dict, "root")
    scan_blocked_text(path, data)

    allowed = {
        "schema_version",
        "claim_id",
        "summary",
        "status",
        "carrier_match",
        "change_type",
        "changes",
        "risk",
        "evidence",
        "last_verified",
        "expires",
        "conflicts_with_stable",
        "notes",
    }
    unknown = set(data) - allowed
    if unknown:
        raise ClaimError(f"{path}: unknown keys: {sorted(unknown)}")
    if data.get("schema_version") != 1:
        raise ClaimError(f"{path}: schema_version must be 1")

    claim_id = require_string(path, data.get("claim_id"), "claim_id", 128)
    if not CLAIM_ID_RE.fullmatch(claim_id):
        raise ClaimError(f"{path}: claim_id must look like claim.<short.slug>")
    summary = require_string(path, data.get("summary"), "summary", 240)

    status = data.get("status")
    if status not in {"proposed", "verified"}:
        raise ClaimError(f"{path}: status must be proposed or verified")

    change_type = data.get("change_type")
    if change_type not in {"add", "confirm", "correct", "remove", "override"}:
        raise ClaimError(f"{path}: change_type is invalid")

    carrier_match = validate_match(path, data.get("carrier_match"))
    changes = validate_changes(path, data.get("changes"))
    evidence = validate_evidence(path, data.get("evidence"))

    last_verified = parse_date(path, data.get("last_verified"), "last_verified")
    expires = parse_date(path, data.get("expires"), "expires")
    today = date.today()
    if last_verified > today:
        raise ClaimError(f"{path}: last_verified cannot be in the future")
    if expires < today:
        raise ClaimError(f"{path}: claim is expired; refresh or remove it")

    field = field_risk(changes)
    effective_match = match_risk(carrier_match)
    if isinstance(changes.get("match"), dict):
        effective_match = max_risk(effective_match, match_risk(changes["match"]))
    computed = combined_claim_risk(
        field,
        effective_match,
        change_type_risk(change_type),
    )
    declared_risk = data.get("risk", computed)
    if declared_risk not in RISK_SCORE:
        raise ClaimError(f"{path}: risk must be low, medium, or high")
    if RISK_SCORE[declared_risk] < RISK_SCORE[computed]:
        raise ClaimError(
            f"{path}: declared risk {declared_risk} is lower than computed risk {computed}"
        )

    max_days = MAX_EXPIRY_DAYS[computed]
    if (expires - last_verified).days > max_days:
        raise ClaimError(
            f"{path}: expires is too far from last_verified for {computed} risk "
            f"(max {max_days} days)"
        )

    conflicts_with_stable = data.get("conflicts_with_stable", False)
    if not isinstance(conflicts_with_stable, bool):
        raise ClaimError(f"{path}: conflicts_with_stable must be boolean")

    notes = data.get("notes")
    if notes is not None:
        require_string(path, notes, "notes", 500)

    confidence = evidence_confidence(evidence)
    channel = recommended_channel(
        status,
        computed,
        confidence,
        change_type,
        conflicts_with_stable,
    )

    rel_path = path.relative_to(claims_dir.parent).as_posix()
    return {
        "claim_id": claim_id,
        "path": rel_path,
        "summary": summary,
        "status": status,
        "computed_risk": computed,
        "declared_risk": declared_risk,
        "confidence": confidence,
        "recommended_channel": channel,
        "change_type": change_type,
        "change_areas": change_areas(changes),
        "carrier_match": carrier_match,
        "last_verified": last_verified.isoformat(),
        "expires": expires.isoformat(),
        "conflicts_with_stable": conflicts_with_stable,
        "evidence_count": len(evidence),
    }


def claim_paths(claims_dir: Path) -> list[Path]:
    if not claims_dir.exists():
        return []
    return sorted(path for path in claims_dir.rglob("*.json") if path.is_file())


def write_indexes(index_root: Path, claims: list[dict[str, Any]]) -> None:
    community_claims = sorted(claims, key=lambda item: item["claim_id"])
    candidate_claims = [
        claim
        for claim in community_claims
        if claim["recommended_channel"] in {"candidate", "stable_eligible"}
    ]
    index_root.mkdir(parents=True, exist_ok=True)
    (index_root / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "description": "All valid non-expired community carrier-data claims.",
                "claims": community_claims,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate_root = index_root.parent / "candidate"
    candidate_root.mkdir(parents=True, exist_ok=True)
    (candidate_root / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "description": (
                    "Community claims with enough evidence to test as candidate "
                    "data. These are not stable defaults."
                ),
                "claims": candidate_claims,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def validate_indexes(index_root: Path, claims: list[dict[str, Any]]) -> None:
    expected_community = {
        "schema_version": 1,
        "description": "All valid non-expired community carrier-data claims.",
        "claims": sorted(claims, key=lambda item: item["claim_id"]),
    }
    expected_candidate = {
        "schema_version": 1,
        "description": (
            "Community claims with enough evidence to test as candidate "
            "data. These are not stable defaults."
        ),
        "claims": [
            claim
            for claim in expected_community["claims"]
            if claim["recommended_channel"] in {"candidate", "stable_eligible"}
        ],
    }
    paths = [
        (index_root / "index.json", expected_community),
        (index_root.parent / "candidate" / "index.json", expected_candidate),
    ]
    for path, expected in paths:
        actual = load_json(path) if path.exists() else None
        if actual != expected:
            raise ClaimError(
                f"{path}: generated claim index is stale; run "
                "python3 tools/validate_community_claims.py --write-index"
            )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claims_dir", nargs="?", default="community/claims")
    parser.add_argument("index_root", nargs="?", default="generated/community")
    parser.add_argument("--write-index", action="store_true")
    args = parser.parse_args(argv[1:])

    claims_dir = Path(args.claims_dir)
    index_root = Path(args.index_root)
    claims: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in claim_paths(claims_dir):
        claim = validate_claim(path, claims_dir)
        claim_id = claim["claim_id"]
        if claim_id in seen_ids:
            raise ClaimError(f"{path}: duplicate claim_id {claim_id}")
        seen_ids.add(claim_id)
        claims.append(claim)

    if args.write_index:
        write_indexes(index_root, claims)
    else:
        validate_indexes(index_root, claims)

    print(
        "validated "
        f"{len(claims)} community claim(s), "
        f"{sum(1 for claim in claims if claim['recommended_channel'] == 'candidate')} candidate, "
        f"{sum(1 for claim in claims if claim['recommended_channel'] == 'stable_eligible')} stable-eligible"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except (ClaimError, public_data.ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
