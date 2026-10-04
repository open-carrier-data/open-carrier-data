#!/usr/bin/env python3
"""Generate Android-facing output from public carrier profiles."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple
from xml.sax.saxutils import escape

from carrier_config_types import config_value_has_expected_type, expected_config_type
from lineageos_apns import fits_lineageos_schema
from validate_public_carrier_data import STALE_AFTER_DAYS


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def profile_paths(carriers_dir: Path) -> list[Path]:
    return sorted(path for path in carriers_dir.rglob("*.json") if path.is_file())


# An XML parser turns a raw tab, line feed or carriage return inside an
# attribute into a space, so they are written as character references. Other
# control characters cannot appear in XML 1.0 at all.
ATTRIBUTE_ENTITIES = {'"': "&quot;", "\t": "&#9;", "\n": "&#10;", "\r": "&#13;"}
XML_FORBIDDEN_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def attr(name: str, value: Any) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    if XML_FORBIDDEN_RE.search(text):
        raise ValueError(f"{name} holds a control character XML cannot carry: {text!r}")
    return f' {name}="{escape(text, ATTRIBUTE_ENTITIES)}"'


def label_text(profile: dict[str, Any], apn: dict[str, Any]) -> str:
    apn_name = str(apn.get("name") or "").strip()
    if apn_name:
        return apn_name[:120]
    return str(profile["display_name"]).strip()[:120]


def profile_apn_mvnos(match: dict[str, Any]) -> list[tuple[str, str] | None]:
    if match.get("gid2_prefixes"):
        return []

    dimensions: list[list[tuple[str, str]]] = []
    imsies = [
        pattern.lower()
        for pattern in match.get("imsi_prefix_patterns", [])
        if isinstance(pattern, str) and pattern
    ]
    if imsies:
        dimensions.append([("imsi", pattern) for pattern in imsies])
    spns = [spn for spn in match.get("spn", []) if isinstance(spn, str) and spn]
    if spns:
        dimensions.append([("spn", spn) for spn in spns])
    gids = [
        gid.upper()
        for gid in match.get("gid1_prefixes", [])
        if isinstance(gid, str) and gid
    ]
    if gids:
        dimensions.append([("gid", gid) for gid in gids])
    iccids = [
        iccid
        for iccid in match.get("iccid_prefixes", [])
        if isinstance(iccid, str) and iccid
    ]
    if iccids:
        dimensions.append([("iccid", iccid) for iccid in iccids])

    if not dimensions:
        return [None]
    if len(dimensions) > 1:
        return []
    return dimensions[0]


def profile_carrier_ids(match: dict[str, Any]) -> list[int]:
    return sorted(
        {
            value
            for value in match.get("android_carrier_ids", [])
            if isinstance(value, int) and not isinstance(value, bool)
        }
    )


def matching_mvno(
    apn: dict[str, Any],
    profile_mvnos: list[tuple[str, str] | None],
) -> list[tuple[str, str] | None]:
    apn_type = apn.get("mvno_type")
    apn_value = apn.get("mvno_match_data")
    if not apn_type and not apn_value:
        return profile_mvnos
    if not isinstance(apn_type, str) or not isinstance(apn_value, str):
        return []
    if profile_mvnos == [None]:
        return [(apn_type, apn_value)]
    normalized = (apn_type.casefold(), apn_value.casefold())
    if normalized not in {
        (mvno_type.casefold(), mvno_value.casefold())
        for item in profile_mvnos
        if item is not None
        for mvno_type, mvno_value in [item]
    }:
        return []
    return [(apn_type, apn_value)]


def apn_records(
    profile: dict[str, Any],
    evidence: dict[str, ProfileEvidence] | None = None,
) -> list[dict[str, Any]]:
    """The APN XML rows of one profile. With evidence, each row also carries
    "_support", the sources behind it per type, which only orders rows and is
    never written."""
    records: list[dict[str, Any]] = []
    match = profile.get("match", {})
    mccmncs = match.get("mccmnc", [])
    profile_mvnos = profile_apn_mvnos(match)
    if not profile_mvnos:
        return records
    carrier_ids = profile_carrier_ids(match)
    profile_evidence = (evidence or {}).get(str(profile.get("profile_id")))

    valid_mccmncs = [
        value
        for value in mccmncs
        if isinstance(value, str) and len(value) in {5, 6}
    ]
    for apn in profile.get("android_apns", []) or []:
        if not isinstance(apn, dict):
            continue
        apn_carrier_id = apn.get("carrier_id")
        if apn_carrier_id is not None and (
            not isinstance(apn_carrier_id, int) or isinstance(apn_carrier_id, bool)
        ):
            continue
        selector_carrier_id = (
            apn_carrier_id
            if isinstance(apn_carrier_id, int) and apn_carrier_id >= 0
            else None
        )
        if (
            selector_carrier_id is not None
            and carrier_ids
            and selector_carrier_id not in carrier_ids
        ):
            continue
        effective_carrier_ids = (
            [selector_carrier_id]
            if selector_carrier_id is not None
            else carrier_ids
        )

        base: dict[str, Any] = {
            "carrier": label_text(profile, apn),
            "apn": apn["apn"],
            "type": ",".join(apn["types"]),
        }
        for key in (
            "mmsc",
            "mmsproxy",
            "mmsport",
            "protocol",
            "roaming_protocol",
            "user",
            "password",
            "authtype",
            "proxy",
            "port",
            "server",
            "bearer",
            "bearer_bitmask",
            "network_type_bitmask",
            "lingering_network_type_bitmask",
            "infrastructure_bitmask",
            "mtu",
            "mtu_v4",
            "mtu_v6",
            "user_visible",
            "user_editable",
            "carrier_enabled",
            "profile_id",
            "apn_set_id",
            "skip_464xlat",
            "modem_cognitive",
            "always_on",
            "esim_bootstrap_provisioning",
            "max_conns",
            "max_conns_time",
            "wait_time",
        ):
            if key in apn:
                base[key] = apn[key]
        if apn_carrier_id == -1:
            base["carrier_id"] = -1
        if evidence is not None:
            base["_support"] = apn_row_support(apn, profile_evidence)

        if not valid_mccmncs:
            for carrier_id in effective_carrier_ids:
                record = dict(base)
                record["carrier_id"] = carrier_id
                records.append(record)
            continue

        mvnos = matching_mvno(apn, profile_mvnos)
        if not mvnos:
            continue
        for mccmnc in valid_mccmncs:
            network_base = dict(base)
            network_base["mcc"] = mccmnc[:3]
            network_base["mnc"] = mccmnc[3:]
            for mvno in mvnos:
                record = dict(network_base)
                if mvno:
                    record["mvno_type"] = mvno[0]
                    record["mvno_match_data"] = mvno[1]
                if not effective_carrier_ids:
                    records.append(record)
                    continue
                for carrier_id in effective_carrier_ids:
                    carrier_record = dict(record)
                    carrier_record["carrier_id"] = carrier_id
                    records.append(carrier_record)
    return records


# How APN rows are ordered. Android 16 gives a SIM the rows of its scope (its
# network code and, when rows name one, its MVNO selector) in file order, and
# without a preferred APN it tries the first row that can serve a request
# first. So within a scope the row most sources back comes first. The
# evidence index names the sources behind every published APN fact.

# Lanes that copy one upstream list count as one source family, as in the
# display-name vote: the two Google lanes; the LineageOS, Sony and Fairphone
# lists, which descend from AOSP's list; and Samsung's two firmware lanes.
APN_SOURCE_FAMILIES = {
    "google_pixel_vendor_carriersettings": "google_carriersettings",
    "lineageos": "aosp_apn_lists",
    "sony_open_devices_aosp": "aosp_apn_lists",
    "fairphone_official_source": "aosp_apn_lists",
    "samsung_ims": "samsung_omc",
}
# Sources whose rows are the complete APN list a phone ships. The others add
# rows for one purpose: GNOME's mobile-broadband-provider-info is a menu users
# pick from, and the AOSP, LineageOS device overlay and Samsung IMS lanes add
# CarrierConfig or IMS facts.
PRIMARY_APN_SOURCES = frozenset(
    {
        "android_carrier_app",
        "apple_carrier_bundles",
        "fairphone_official_source",
        "google_carriersettings",
        "google_pixel_vendor_carriersettings",
        "lineageos",
        "samsung_omc",
        "sony_open_devices_aosp",
    }
)
# APN values that name no network: a list writes them where it knows no APN.
PLACEHOLDER_APNS = frozenset({"default"})
# One file order serves every request type, so types are ranked in this order:
# rows that serve the internet come first, best backed first, then the rest.
APN_TYPE_PRIORITY = (
    "default",
    "ia",
    "mms",
    "ims",
    "supl",
    "dun",
    "xcap",
    "emergency",
    "cbs",
    "fota",
    "hipri",
    "mcx",
    "vsim",
    "bip",
    "enterprise",
    "rcs",
)
# ApnSetting.TYPE_ALL, what Android reads from a "*" type.
ANDROID_WILDCARD_TYPES = ("default", "hipri", "mms", "supl", "dun", "fota", "ims", "cbs")
# TelephonyProvider's column defaults. An attribute with this value means the
# same as no attribute.
ANDROID_APN_DEFAULTS: dict[str, Any] = {
    "protocol": "IP",
    "roaming_protocol": "IP",
    "authtype": -1,
    "carrier_enabled": True,
    "bearer": 0,
    "profile_id": 0,
    "user_visible": True,
    "user_editable": True,
    "apn_set_id": 0,
    "skip_464xlat": -1,
    "mtu": 0,
    "mtu_v4": 0,
    "mtu_v6": 0,
    "max_conns": 0,
    "max_conns_time": 0,
    "wait_time": 0,
    "modem_cognitive": False,
    "always_on": False,
    "esim_bootstrap_provisioning": False,
}
# Defaults LineageOS's apns-conf.xsd does not accept as values. They are left
# out of the row, which TelephonyProvider reads the same way.
SCHEMA_OMITTED_DEFAULTS = {"authtype": -1, "skip_464xlat": -1}


class ProfileEvidence(NamedTuple):
    sources: frozenset[str]
    apn_fact_sources: dict[str, frozenset[str]]


class ApnRows(NamedTuple):
    records: list[dict[str, Any]]
    schema_rejected: int


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def apn_fact_key(apn: dict[str, Any], apn_type: str) -> str:
    """The evidence index key of one APN fact: one row with one type, its
    label left out."""
    fact = {key: value for key, value in apn.items() if key != "name"}
    fact["types"] = [apn_type]
    return "sha256:" + hashlib.sha256(canonical_json(fact).encode("utf-8")).hexdigest()[:16]


def load_apn_evidence(evidence_index_path: Path | None) -> dict[str, ProfileEvidence] | None:
    """Per profile, its sources and the sources of each APN fact that rests on
    fewer of them. None when there is no evidence index."""
    if evidence_index_path is None or not evidence_index_path.exists():
        return None
    evidence: dict[str, ProfileEvidence] = {}
    for profile in load_json(evidence_index_path).get("profiles", []):
        evidence[profile["profile_id"]] = ProfileEvidence(
            frozenset(profile.get("sources", [])),
            {
                fact["key"]: frozenset(fact["sources"])
                for fact in profile.get("fact_sources", [])
                if fact.get("section") == "android_apns"
            },
        )
    return evidence


def apn_row_types(types: str | list[str]) -> list[str]:
    values = types.split(",") if isinstance(types, str) else list(types)
    if "*" in values:
        return sorted(set(ANDROID_WILDCARD_TYPES) | (set(values) - {"*"}))
    return values


def apn_row_support(
    apn: dict[str, Any], profile_evidence: ProfileEvidence | None
) -> dict[str, frozenset[str]]:
    """The sources behind each type of a profile row. A fact the evidence
    index does not list rests on every source of its profile."""
    if profile_evidence is None:
        return {}
    support: dict[str, frozenset[str]] = {}
    for apn_type in apn.get("types", []):
        sources = profile_evidence.apn_fact_sources.get(
            apn_fact_key(apn, apn_type), profile_evidence.sources
        )
        for served in ANDROID_WILDCARD_TYPES if apn_type == "*" else (apn_type,):
            support[served] = support.get(served, frozenset()) | sources
    return support


def source_families(sources: frozenset[str] | set[str]) -> set[str]:
    return {APN_SOURCE_FAMILIES.get(source, source) for source in sources}


def written_attributes(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def android_settings_key(record: dict[str, Any]) -> str:
    """Everything TelephonyProvider stores for a row except its label and
    types, with its column defaults filled in. Rows with the same key are the
    same APN to Android."""
    return canonical_json(
        {
            key: value
            for key, value in written_attributes(record).items()
            if key not in {"carrier", "type"}
            and not (key in ANDROID_APN_DEFAULTS and ANDROID_APN_DEFAULTS[key] == value)
        }
    )


def collapse_android_duplicates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows that differ only in their label, in a type set, or in an attribute
    that repeats TelephonyProvider's default become one row with the union of
    their types, which is what TelephonyProvider makes of them when it loads
    them. The first row in fallback order gives the label."""
    merged: dict[str, dict[str, Any]] = {}
    for record in sorted(records, key=fallback_order_key):
        key = android_settings_key(record)
        kept = merged.get(key)
        if kept is None:
            merged[key] = dict(record)
            continue
        kept["type"] = ",".join(
            sorted(set(kept["type"].split(",")) | set(record["type"].split(",")))
        )
        if "_support" in kept or "_support" in record:
            support = dict(kept.get("_support", {}))
            for apn_type, sources in record.get("_support", {}).items():
                support[apn_type] = support.get(apn_type, frozenset()) | sources
            kept["_support"] = support
    return list(merged.values())


def fallback_order_key(record: dict[str, Any]) -> tuple[Any, ...]:
    """The order before ranking, and among rows ranking cannot separate."""
    return (
        record.get("apn", ""),
        record.get("type", ""),
        record.get("carrier", ""),
        canonical_json(written_attributes(record)),
    )


def apn_scope_key(record: dict[str, Any]) -> tuple[Any, ...]:
    """Which SIMs see a row. A carrier id on a row with a network code does not
    restrict it in Android 16, so only rows without a network code are scoped
    by their carrier id. SPN and GID matches ignore letter case."""
    if "mcc" not in record:
        return ("", "", "", "", record.get("carrier_id", -1))
    return (
        record["mcc"],
        record["mnc"],
        str(record.get("mvno_type", "")).casefold(),
        str(record.get("mvno_match_data", "")).casefold(),
        -1,
    )


def rank_scope(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the rows of one scope so the best-backed row comes first. A row's
    lead type is the first type of APN_TYPE_PRIORITY it serves, so every row
    that serves the internet leads with "default". Rows are grouped by lead
    type in that order. Within a group, for the lead type:

    1. a real APN before a placeholder such as "default",
    2. the APN value more source families give for that type in this scope,
    3. an APN value a primary APN source gives,
    4. the row more source families back,
    5. a row a primary APN source backs,
    6. the row more sources back.

    A row is backed for a type by the sources whose observations support it.
    Rows still tied keep the fallback order: APN, types, label."""
    apn_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        apn = str(record["apn"]).casefold()
        for apn_type, sources in record.get("_support", {}).items():
            apn_sources[(apn, apn_type)].update(sources)

    def type_rank(record: dict[str, Any], apn_type: str) -> tuple[Any, ...]:
        apn = str(record["apn"]).casefold()
        value_sources = apn_sources.get((apn, apn_type), set())
        row_sources = record.get("_support", {}).get(apn_type, frozenset())
        return (
            apn in PLACEHOLDER_APNS,
            -len(source_families(value_sources)),
            not value_sources & PRIMARY_APN_SOURCES,
            -len(source_families(row_sources)),
            not row_sources & PRIMARY_APN_SOURCES,
            -len(row_sources),
        )

    def row_rank(record: dict[str, Any]) -> tuple[Any, ...]:
        types = set(apn_row_types(record["type"]))
        lead = next(
            (index for index, apn_type in enumerate(APN_TYPE_PRIORITY) if apn_type in types),
            len(APN_TYPE_PRIORITY),
        )
        evidence = (
            type_rank(record, APN_TYPE_PRIORITY[lead]) if lead < len(APN_TYPE_PRIORITY) else ()
        )
        return (lead, evidence, fallback_order_key(record))

    return sorted(records, key=row_rank)


def apn_xml_rows(
    profiles: list[dict[str, Any]],
    evidence: dict[str, ProfileEvidence] | None = None,
) -> ApnRows:
    """Every APN XML row of these profiles in file order: rows LineageOS's
    apns-conf.xsd rejects left out, duplicates to Android collapsed, scopes in
    network code and MVNO selector order, and each scope ranked by its
    evidence."""
    records: list[dict[str, Any]] = []
    schema_rejected = 0
    for profile in profiles:
        for record in apn_records(profile, evidence):
            for key, value in SCHEMA_OMITTED_DEFAULTS.items():
                if record.get(key) == value:
                    del record[key]
            if not fits_lineageos_schema(record):
                schema_rejected += 1
                continue
            records.append(record)
    scopes: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in collapse_android_duplicates(records):
        scopes[apn_scope_key(record)].append(record)
    ordered: list[dict[str, Any]] = []
    for scope in sorted(scopes):
        ordered.extend(rank_scope(scopes[scope]))
    return ApnRows(ordered, schema_rejected)


def apn_xml_records(
    profiles: list[dict[str, Any]],
    evidence: dict[str, ProfileEvidence] | None = None,
) -> list[dict[str, Any]]:
    return apn_xml_rows(profiles, evidence).records


def apn_row_line(record: dict[str, Any]) -> str:
    attributes = written_attributes(record)
    attrs = "".join(attr(key, attributes[key]) for key in sorted(attributes))
    return f"  <apn{attrs} />"


# Every XML file the generator writes starts with this comment: what the file
# is, the data licence, the digest of everything it was built from, and the
# freshness window. The publish commit cannot be named, because it is made
# after the file is written and squash-merged into a new commit, and the
# public check regenerates the file and fails on any difference. The digest is
# stable instead: SHA-256 over the profile files, the evidence index, and the
# generator's own source, so it names one snapshot, and metadata.json repeats
# it, so `git log -S <digest> -- generated/android/metadata.json` finds the
# commit that published it.
PROJECT_URL = "https://github.com/open-carrier-data/open-carrier-data"
DATA_LICENSE = "CC0-1.0"
DIGEST_TOOLS = ("generate_android_outputs.py", "carrier_config_types.py", "lineageos_apns.py")


def data_digest(
    carriers_dir: Path, paths: list[Path], evidence_index_path: Path | None
) -> str:
    """SHA-256 over the inputs of the generated files, each named by its path
    in the repository: the profile files, generated/evidence-index.json, and
    the generator's source."""
    digest = hashlib.sha256()

    def add(name: str, data: bytes) -> None:
        digest.update(f"{name}\n{hashlib.sha256(data).hexdigest()}\n".encode("utf-8"))

    for path in sorted(paths, key=lambda item: item.relative_to(carriers_dir.parent).as_posix()):
        add(path.relative_to(carriers_dir.parent).as_posix(), path.read_bytes())
    if evidence_index_path is not None and evidence_index_path.exists():
        add("generated/evidence-index.json", evidence_index_path.read_bytes())
    tools = Path(__file__).resolve().parent
    for name in DIGEST_TOOLS:
        add(f"tools/{name}", (tools / name).read_bytes())
    return "sha256:" + digest.hexdigest()


def provenance_header(what: str, digest: str | None, freshness: dict[str, str]) -> list[str]:
    """The XML declaration and the provenance comment of a generated file."""
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<!--",
        f"    {what} from Open Carrier Data",
        f"    {PROJECT_URL}",
        f"    SPDX-License-Identifier: {DATA_LICENSE}",
        "    The project waives its rights in these derived facts; DATA-LICENSE.md",
        "    in the repository records each source's own terms.",
    ]
    if digest is not None:
        lines.append(f"    data_digest: {digest}")
    for key in ("checks_through", "stale_after"):
        if freshness.get(key):
            lines.append(f"    {key}: {freshness[key]}")
    lines.append("-->")
    return lines


def write_apn_rows(
    path: Path,
    records: list[dict[str, Any]],
    version: int,
    header: list[str] | None = None,
) -> int:
    lines = [
        *(header or ['<?xml version="1.0" encoding="utf-8"?>']),
        f'<apns version="{version}">',
    ]
    lines.extend(apn_row_line(record) for record in records)
    lines.append("</apns>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(records)


def write_apns(
    path: Path,
    profiles: list[dict[str, Any]],
    version: int,
    evidence: dict[str, ProfileEvidence] | None = None,
) -> int:
    return write_apn_rows(path, apn_xml_records(profiles, evidence), version)


SNAPSHOTS_BY_PROFILE_SOURCE = {
    "aosp": ("aosp_carrier_config", "aosp_carrier_ids"),
    "lineageos_device_overlays": ("lineageos_device_carrier_overlays",),
}


def profile_windows(evidence_index_path: Path) -> dict[str, dict[str, str]]:
    """The freshness window of each profile on its own: the oldest check behind
    that profile's sources and observations, plus 180 days."""
    if not evidence_index_path.exists():
        return {}
    evidence = load_json(evidence_index_path)
    checked = {
        snapshot["source_name"]: snapshot["checked_at"]
        for snapshot in evidence.get("source_snapshots", [])
        if isinstance(snapshot, dict) and snapshot.get("checked_at")
    }
    windows: dict[str, dict[str, str]] = {}
    for profile in evidence.get("profiles", []):
        dates: list[str] = []
        for source in profile.get("sources", []):
            for snapshot_name in SNAPSHOTS_BY_PROFILE_SOURCE.get(source, (source,)):
                if snapshot_name in checked:
                    dates.append(checked[snapshot_name])
        reviewed = profile.get("reviewed_range")
        if isinstance(reviewed, dict) and reviewed.get("oldest"):
            dates.append(reviewed["oldest"])
        if not dates:
            continue
        checks_through = min(date.fromisoformat(value) for value in dates)
        windows[profile["profile_id"]] = {
            "checks_through": checks_through.isoformat(),
            "stale_after": (checks_through + timedelta(days=STALE_AFTER_DAYS)).isoformat(),
        }
    return windows


def profile_newest_entries(evidence_index_path: Path) -> dict[str, str]:
    """The month of the newest upstream entry behind each profile, as the
    evidence index publishes it, for the profiles where it is known."""
    if not evidence_index_path.exists():
        return {}
    return {
        profile["profile_id"]: profile["newest_entry"]
        for profile in load_json(evidence_index_path).get("profiles", [])
        if isinstance(profile.get("newest_entry"), str)
    }


def write_lookup(
    path: Path,
    carriers_dir: Path,
    profile_items: list[tuple[Path, dict[str, Any]]],
    windows: dict[str, dict[str, str]] | None = None,
    newest_entries: dict[str, str] | None = None,
) -> None:
    profiles = []
    for profile_path, profile in profile_items:
        record = lookup_record(carriers_dir, profile_path, profile)
        window = (windows or {}).get(profile["profile_id"])
        if window:
            record["checks_through"] = window["checks_through"]
            record["stale_after"] = window["stale_after"]
        newest = (newest_entries or {}).get(profile["profile_id"])
        if newest:
            record["newest_entry"] = newest
        profiles.append(record)
    value = {
        "schema_version": 1,
        "resolution_order": "generic_to_specific",
        "match_semantics": "OR within a match list; AND between match dimensions",
        "profiles": profiles,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def match_specificity(match: dict[str, Any]) -> int:
    return sum(
        1
        for key in (
            "gid1_prefixes",
            "gid2_prefixes",
            "iccid_prefixes",
            "imsi_prefix_patterns",
            "spn",
            "android_carrier_ids",
        )
        if match.get(key)
    )


def lookup_record(carriers_dir: Path, profile_path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": profile["profile_id"],
        "display_name": profile["display_name"],
        "path": profile_path.relative_to(carriers_dir.parent).as_posix(),
        "match": profile["match"],
        "specificity": match_specificity(profile["match"]),
        "capabilities": profile["capabilities"],
        "android_apn_count": len(profile.get("android_apns", []) or []),
        "has_android_carrier_config": bool(profile.get("android_carrier_config")),
    }


def java_regex_literal(value: str) -> str:
    return r"\Q" + value.replace(r"\E", r"\E\\E\Q") + r"\E"


def imsi_xpattern_to_regex(value: str) -> str:
    parts = ["[0-9]" if char.lower() == "x" else char for char in value]
    return "".join(parts) + "[0-9]*"


def config_filter_records(profile: dict[str, Any]) -> list[dict[str, str]]:
    match = profile.get("match", {})
    if not isinstance(match, dict):
        return []
    if (
        match.get("gid1_prefixes")
        or match.get("gid2_prefixes")
        or match.get("iccid_prefixes")
    ):
        return []

    mccmncs = sorted(
        {
            item
            for item in match.get("mccmnc", [])
            if isinstance(item, str) and len(item) in {5, 6}
        }
    )
    if not mccmncs:
        return []

    carrier_ids = sorted(
        {
            item
            for item in match.get("android_carrier_ids", [])
            if isinstance(item, int) and not isinstance(item, bool)
        }
    ) or [None]
    spns = sorted({item for item in match.get("spn", []) if isinstance(item, str) and item}) or [
        None
    ]
    imsis = sorted(
        {
            item.lower()
            for item in match.get("imsi_prefix_patterns", [])
            if isinstance(item, str) and item
        }
    ) or [None]

    records: list[dict[str, str]] = []
    display_name = str(profile["display_name"]).strip()[:120]
    for mccmnc in mccmncs:
        base = {
            "mcc": mccmnc[:3],
            "mnc": mccmnc[3:],
            "name": display_name,
        }
        for carrier_id in carrier_ids:
            for spn in spns:
                for imsi in imsis:
                    record = dict(base)
                    if carrier_id is not None:
                        record["cid"] = str(carrier_id)
                    if spn is not None:
                        record["spn"] = java_regex_literal(spn)
                    if imsi is not None:
                        record["imsi"] = imsi_xpattern_to_regex(imsi)
                    records.append(record)
    records.sort(
        key=lambda item: (
            item.get("cid", ""),
            item.get("mcc", ""),
            item.get("mnc", ""),
            item.get("spn", ""),
            item.get("gid1", ""),
            item.get("imsi", ""),
        )
    )
    return records


def config_xml_lines(config: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in sorted(config):
        value = config[key]
        expected = expected_config_type(key)
        if not config_value_has_expected_type(key, value):
            raise ValueError(f"CarrierConfig {key} must be {expected}")
        if isinstance(value, bool):
            lines.append(f"    <boolean{attr('name', key)}{attr('value', value)} />")
        elif isinstance(value, int) and not isinstance(value, bool):
            lines.append(f"    <int{attr('name', key)}{attr('value', value)} />")
        elif isinstance(value, str):
            lines.append(f"    <string{attr('name', key)}>{escape(value)}</string>")
        elif isinstance(value, list):
            lines.append(f"    <string-array{attr('name', key)}{attr('num', len(value))}>")
            for item in value:
                lines.append(f"      <item{attr('value', item)} />")
            lines.append("    </string-array>")
    return lines


def write_carrier_config_xml(
    path: Path, profiles: list[dict[str, Any]], header: list[str] | None = None
) -> int:
    blocks: list[tuple[int, str, dict[str, str], list[str]]] = []
    for profile in profiles:
        config = profile.get("android_carrier_config")
        if not isinstance(config, dict) or not config:
            continue
        config_lines = config_xml_lines(config)
        if not config_lines:
            continue
        for filters in config_filter_records(profile):
            specificity = sum(
                key in filters for key in ("cid", "spn", "imsi", "gid1", "gid2")
            )
            blocks.append(
                (specificity, str(profile["profile_id"]), filters, config_lines)
            )

    blocks.sort(
        key=lambda item: (
            item[0],
            item[2].get("mcc", ""),
            item[2].get("mnc", ""),
            item[2].get("cid", ""),
            item[2].get("spn", ""),
            item[2].get("gid1", ""),
            item[1],
        )
    )
    lines = [
        *(header or ['<?xml version="1.0" encoding="utf-8"?>']),
        "<carrier_config_list>",
    ]
    for _specificity, profile_id, filters, config_lines in blocks:
        lines.append(f"  <!-- {escape(profile_id)} -->")
        attrs = "".join(attr(key, filters[key]) for key in sorted(filters))
        lines.append(f"  <carrier_config{attrs}>")
        lines.extend(config_lines)
        lines.append("  </carrier_config>")
    lines.append("</carrier_config_list>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(blocks)


def freshness_window(evidence_index_path: Path) -> dict[str, str]:
    if not evidence_index_path.exists():
        return {}
    evidence = load_json(evidence_index_path)
    if "checks_through" in evidence and "stale_after" in evidence:
        return {
            "checks_through": evidence["checks_through"],
            "stale_after": evidence["stale_after"],
        }
    dates = [snapshot["checked_at"] for snapshot in evidence.get("source_snapshots", [])]
    dates += [
        profile["reviewed_range"]["oldest"]
        for profile in evidence.get("profiles", [])
        if profile.get("reviewed_range")
    ]
    if not dates:
        return {}
    checks_through = min(date.fromisoformat(value) for value in dates)
    return {
        "checks_through": checks_through.isoformat(),
        "stale_after": (checks_through + timedelta(days=STALE_AFTER_DAYS)).isoformat(),
    }


def write_metadata(
    path: Path,
    profiles: list[dict[str, Any]],
    apn_version: int,
    apn_count: int,
    config_xml_count: int,
    freshness: dict[str, str],
    apn_rows_schema_rejected: int = 0,
    digest: str | None = None,
) -> None:
    apn_unrepresentable_ids = sorted(
        str(profile["profile_id"])
        for profile in profiles
        if profile.get("android_apns") and not apn_records(profile)
    )
    config_unrepresentable_ids = sorted(
        str(profile["profile_id"])
        for profile in profiles
        if profile.get("android_carrier_config") and not config_filter_records(profile)
    )
    value = {
        "schema_version": 1,
        # carrier-config-list.xml has no gid1, gid2 or ICCID filter: a profile
        # whose match needs a GID or ICCID prefix is left out of it and listed
        # under omissions, because Android's vendor.xml can match GID1 only
        # exactly and profiles carry prefixes.
        "target": {
            "apn_database_version": apn_version,
            "carrier_config_gid_matching": "omitted",
            "carrier_config_iccid_matching": "omitted",
        },
        "output": {
            "apn_row_count": apn_count,
            "carrier_config_xml_block_count": config_xml_count,
        },
        "omissions": {
            "apn_profile_ids_with_unrepresentable_match": apn_unrepresentable_ids,
            "apn_profiles_with_unrepresentable_match": len(apn_unrepresentable_ids),
            "apn_rows_rejected_by_lineageos_schema": apn_rows_schema_rejected,
            "carrier_config_profile_ids_with_unrepresentable_match": (
                config_unrepresentable_ids
            ),
            "carrier_config_profiles_with_unrepresentable_match": len(
                config_unrepresentable_ids
            ),
        },
        **freshness,
    }
    if digest is not None:
        value["data_digest"] = digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("carriers_dir", nargs="?", type=Path, default=Path("carriers"))
    parser.add_argument("generated_dir", nargs="?", type=Path, default=Path("generated"))
    parser.add_argument(
        "--apn-version",
        type=int,
        default=8,
        help="APN XML version expected by the target Android build (default: 8)",
    )
    parser.add_argument(
        "--evidence-index",
        type=Path,
        help="the evidence index that orders APN rows and dates the profiles "
        "(default: GENERATED_DIR/evidence-index.json)",
    )
    args = parser.parse_args(argv[1:])
    if args.apn_version < 1:
        parser.error("--apn-version must be a positive integer")
    carriers_dir = args.carriers_dir
    generated_dir = args.generated_dir
    evidence_index_path = args.evidence_index or generated_dir / "evidence-index.json"
    profile_items = [(path, load_json(path)) for path in profile_paths(carriers_dir)]
    profiles = [profile for _, profile in profile_items]
    evidence = load_apn_evidence(evidence_index_path)
    if evidence is None:
        print(
            f"warning: {evidence_index_path} is missing, so APN rows are ordered "
            "without their sources",
            file=sys.stderr,
        )
    freshness = freshness_window(evidence_index_path)
    digest = data_digest(
        carriers_dir, [path for path, _ in profile_items], evidence_index_path
    )
    apn_rows = apn_xml_rows(profiles, evidence)
    apn_count = write_apn_rows(
        generated_dir / "android" / "apns-conf.xml",
        apn_rows.records,
        args.apn_version,
        provenance_header("Android APN list", digest, freshness),
    )
    rows_schema_rejected = apn_rows.schema_rejected
    write_lookup(
        generated_dir / "android" / "lookup.json",
        carriers_dir,
        profile_items,
        profile_windows(evidence_index_path),
        profile_newest_entries(evidence_index_path),
    )
    config_xml_count = write_carrier_config_xml(
        generated_dir / "android" / "carrier-config-list.xml",
        profiles,
        provenance_header("Android CarrierConfig list (vendor.xml format)", digest, freshness),
    )
    write_metadata(
        generated_dir / "android" / "metadata.json",
        profiles,
        args.apn_version,
        apn_count,
        config_xml_count,
        freshness,
        rows_schema_rejected,
        digest,
    )
    config_count = sum(1 for profile in profiles if profile.get("android_carrier_config"))
    print(
        f"generated Android output for {len(profiles)} profile(s): "
        f"{apn_count} APN row(s), {config_count} CarrierConfig profile(s), "
        f"{config_xml_count} CarrierConfig XML block(s), "
        f"{rows_schema_rejected} APN row(s) left out because LineageOS's schema rejects them"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
