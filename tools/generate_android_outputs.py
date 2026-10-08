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
    "_support", the sources behind it per type, and "_current", the current
    vendors among them (apn_row_current), which only order rows and are never
    written."""
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
            base["_current"] = apn_row_current(apn, profile_evidence)
            shared = apn_row_shared(apn, profile_evidence)
            if shared:
                base["_shared"] = shared

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
# first. So within a scope a value a current vendor ships comes first, then
# the row most sources back. The evidence index names the sources behind every
# published APN fact.

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
# Sources whose maker confirms their files are current: Google's CarrierSettings
# lane is checked against Google's update service and Samsung's firmware lanes
# against Samsung's firmware service, so a value they give is one a current
# Pixel or Galaxy ships. Apple's index keeps retired bundles, the TheMuppets
# Pixel files and Sony's and Fairphone's trees are frozen copies, and
# LineageOS's list keeps whatever nobody removed, so none of them is in it.
# Apple's index date is the day a bundle was re-issued, not the day its
# content was written: measured on 2026-10-06, its newest bundles carry
# APNs made for iPhones and old names forward, and agree with the Android
# vendors less often than older ones (private rule decisions of 2026-10-06).
# Two exceptions, both named per APN fact by the evidence index:
# - Samsung's service also confirms the last build of a phone it stopped
#   updating years ago, so a Samsung value does not count where the fact's
#   old_build_sources names the source: every observation of it behind the
#   fact comes from a build more than three years old.
# - Google's update service confirms its shared "others" file as a whole, not
#   each entry: in two years 5 of its 688 entries changed. A Google value
#   that comes only from that file counts only where a maintained
#   per-carrier source (a Google per-carrier file, or a Samsung build at most
#   three years old) gives the same APN value for the type on the same
#   network code, or where Google's frozen Pixel copies (TheMuppets) show
#   that Google edited the entry's values for that type: a copy gives a value
#   for the type that the current file no longer gives. Otherwise the fact's
#   shared_file_sources names Google. The private sanitizer decides; this
#   generator only reads the mark.
CURRENT_VENDOR_APN_SOURCES = frozenset({"google_carriersettings", "samsung_omc", "samsung_ims"})
# APN values that name no network: a list writes them where it knows no APN.
PLACEHOLDER_APNS = frozenset({"default"})
# An APN name is labels of letters, digits and hyphens joined by dots (3GPP
# TS 23.003, section 9.1); underscores are tolerated, as networks use them. A
# value with any other character, such as "mms/airtel mms" or
# "http://mms.pepephone.com", is not an APN a phone can attach to.
APN_VALUE_RE = re.compile(r"[A-Za-z0-9._-]+")


def placeholder_apn(apn: Any) -> bool:
    """Whether an APN value names no network: a placeholder such as
    "default", or a malformed value (APN_VALUE_RE)."""
    value = str(apn)
    return value.casefold() in PLACEHOLDER_APNS or not APN_VALUE_RE.fullmatch(value)


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
# TelephonyProvider's CARRIERS_UNIQUE_FIELDS as XML attributes, with the value
# a row without the attribute gets (LineageOS 23.2, TelephonyProvider.java:
# 276-417; numeric is mcc and mnc, and owned_by is no XML attribute). Rows
# equal on all of them are one row to Android: loadApns inserts rows in file
# order, and a row that conflicts with an earlier one goes to
# mergeFieldsAndUpdateDb, which keeps the earlier row's _id and so its place,
# unites the types, merges the bearer and network type bitmasks, and lets
# every attribute the later row writes overwrite (putAll). mvno_type and
# mvno_match_data count only when a row has both.
ANDROID_UNIQUE_DEFAULTS: dict[str, str] = {
    "mcc": "",
    "mnc": "",
    "apn": "",
    "proxy": "",
    "port": "",
    "mmsproxy": "",
    "mmsport": "",
    "mmsc": "",
    "carrier_enabled": "1",
    "bearer": "0",
    "mvno_type": "",
    "mvno_match_data": "",
    "profile_id": "0",
    "protocol": "IP",
    "roaming_protocol": "IP",
    "user_editable": "1",
    "apn_set_id": "0",
    "carrier_id": "-1",
    "infrastructure_bitmask": "3",
    "esim_bootstrap_provisioning": "0",
}
INFRASTRUCTURE_BITS = {"cellular": 1, "satellite": 2}


class ProfileEvidence(NamedTuple):
    sources: frozenset[str]
    apn_fact_sources: dict[str, frozenset[str]]
    # Per APN fact, the vendor sources that give it only from old builds.
    apn_fact_old_build_sources: dict[str, frozenset[str]]
    # Per APN fact, the vendor sources that give it only from a shared file
    # no maintained per-carrier source confirms.
    apn_fact_shared_file_sources: dict[str, frozenset[str]] = {}


class ApnRows(NamedTuple):
    records: list[dict[str, Any]]
    schema_rejected: int
    ia_left_out: int = 0
    mms_left_out: int = 0
    # Stored rows leave_out_absorbed_mms left out, every file row of them.
    mms_absorbed_left_out: tuple[dict[str, Any], ...] = ()


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
        apn_facts = [
            fact for fact in profile.get("fact_sources", []) if fact.get("section") == "android_apns"
        ]
        evidence[profile["profile_id"]] = ProfileEvidence(
            frozenset(profile.get("sources", [])),
            {fact["key"]: frozenset(fact["sources"]) for fact in apn_facts},
            {
                fact["key"]: frozenset(fact["old_build_sources"])
                for fact in apn_facts
                if fact.get("old_build_sources")
            },
            {
                fact["key"]: frozenset(fact["shared_file_sources"])
                for fact in apn_facts
                if fact.get("shared_file_sources")
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


def apn_row_current(
    apn: dict[str, Any], profile_evidence: ProfileEvidence | None
) -> dict[str, frozenset[str]]:
    """The current vendors behind each type of a profile row: its sources in
    CURRENT_VENDOR_APN_SOURCES, less the Samsung sources that give the fact
    only from builds more than three years old (old_build_sources) and the
    Google source that gives it only from its unconfirmed shared file
    (shared_file_sources)."""
    if profile_evidence is None:
        return {}
    current: dict[str, frozenset[str]] = {}
    for apn_type in apn.get("types", []):
        key = apn_fact_key(apn, apn_type)
        sources = profile_evidence.apn_fact_sources.get(key, profile_evidence.sources)
        vendors = (
            (sources & CURRENT_VENDOR_APN_SOURCES)
            - profile_evidence.apn_fact_old_build_sources.get(key, frozenset())
            - profile_evidence.apn_fact_shared_file_sources.get(key, frozenset())
        )
        for served in ANDROID_WILDCARD_TYPES if apn_type == "*" else (apn_type,):
            current[served] = current.get(served, frozenset()) | vendors
    return current


def apn_row_shared(
    apn: dict[str, Any], profile_evidence: ProfileEvidence | None
) -> dict[str, frozenset[str]]:
    """The sources behind each type of a profile row that give it only from
    an unconfirmed shared file (shared_file_sources). Only --explain reads
    them."""
    if profile_evidence is None:
        return {}
    shared: dict[str, frozenset[str]] = {}
    for apn_type in apn.get("types", []):
        sources = profile_evidence.apn_fact_shared_file_sources.get(
            apn_fact_key(apn, apn_type), frozenset()
        )
        if not sources:
            continue
        for served in ANDROID_WILDCARD_TYPES if apn_type == "*" else (apn_type,):
            shared[served] = shared.get(served, frozenset()) | sources
    return shared


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
    them. The first row in fallback order gives the label. Rows that differ in
    other attributes stay apart here, but TelephonyProvider still stores them
    as one when they are equal on its unique fields (android_unique_key): one
    row at the first row's place, each later row's written attributes
    overwriting, types united and bitmasks merged. write_android_groups_best_last
    writes the best-ranked of them last so its values win."""
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
        for field in ("_support", "_current", "_shared"):
            if field in kept or field in record:
                merged_field = dict(kept.get(field, {}))
                for apn_type, sources in record.get(field, {}).items():
                    merged_field[apn_type] = merged_field.get(apn_type, frozenset()) | sources
                kept[field] = merged_field
    return list(merged.values())


def android_unique_key(record: dict[str, Any]) -> tuple[str, ...]:
    """The row's values of ANDROID_UNIQUE_DEFAULTS as TelephonyProvider
    compares them: exact strings, not case-folded, booleans as 1 or 0, the
    infrastructure names as bits, and the default for a missing attribute.
    Rows with the same key are stored as one row."""
    attributes = written_attributes(record)
    has_mvno = "mvno_type" in attributes and "mvno_match_data" in attributes
    key: list[str] = []
    for field, default in ANDROID_UNIQUE_DEFAULTS.items():
        value = attributes.get(field)
        if field in {"mvno_type", "mvno_match_data"} and not has_mvno:
            value = None
        if value is None:
            key.append(default)
        elif isinstance(value, bool):
            key.append("1" if value else "0")
        elif field == "infrastructure_bitmask":
            bits = 0
            for name in str(value).split("|"):
                bits |= INFRASTRUCTURE_BITS.get(name.strip(), 0)
            key.append(str(bits))
        elif field in {"carrier_enabled", "user_editable", "esim_bootstrap_provisioning"}:
            key.append({"true": "1", "false": "0"}.get(str(value).lower(), str(value)))
        else:
            key.append(str(value))
    return tuple(key)


def write_android_groups_best_last(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Write the rows of a ranked scope that TelephonyProvider stores as one
    (android_unique_key) next to each other, once, at the place of the
    group's best-ranked row, with the best-ranked row last and the others
    before it in reverse rank order. TelephonyProvider keeps the first row's
    place, unites the types and merges the bitmasks, and lets each later row's
    written attributes overwrite, so the best row's values win and it takes
    from the others only what it leaves unset. Rows written before their
    group's best row are marked "_stored_with_best_row", which is never
    written. No row is removed and no value changes; rows of other groups
    keep their order. Exception on the phone: for the networks of
    persist_apns_for_plmn (20404, 310004, 310120, 311480, TelephonyProvider's
    res/values/config.xml), separateRowsNeeded does not merge two such rows
    whose types differ only by "dun", so there the earlier row keeps its
    values (204/04 IMSI 204047960 leads with the frozen internet.mvno.mobi
    row and mvno/mvno). Not handled here; documented in consume.md."""
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in ranked:
        groups[android_unique_key(record)].append(record)
    written: list[dict[str, Any]] = []
    done: set[tuple[str, ...]] = set()
    for record in ranked:
        key = android_unique_key(record)
        if key in done:
            continue
        done.add(key)
        best, *others = groups[key]
        for other in reversed(others):
            other["_stored_with_best_row"] = True
            written.append(other)
        written.append(best)
    return written


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


class RowRank(NamedTuple):
    """Why a row sits where it does in its scope, for its lead type: the first
    type of APN_TYPE_PRIORITY it serves (None when it serves none of them).
    The sources are those that give this APN value for the lead type anywhere
    in the scope, and those that back this exact row; the current ones are the
    current vendors among them (apn_row_current)."""

    lead_type: str | None
    placeholder: bool
    value_sources: frozenset[str]
    row_sources: frozenset[str]
    value_current: frozenset[str] = frozenset()
    row_current: frozenset[str] = frozenset()
    # The sources that give this APN value for the lead type in the scope
    # only from an unconfirmed shared file. They do not order rows.
    value_shared: frozenset[str] = frozenset()
    # The row leads with "default" and carries an HTTP proxy ("proxy"; an MMS
    # proxy never counts).
    proxied: bool = False

    def sort_key(self) -> tuple[Any, ...]:
        lead = (
            APN_TYPE_PRIORITY.index(self.lead_type)
            if self.lead_type is not None
            else len(APN_TYPE_PRIORITY)
        )
        if self.lead_type is None:
            return (lead, ())
        return (
            lead,
            (
                self.placeholder,
                not self.value_current,
                # A proxy-free internet row before a proxied one. Android makes
                # an APN's proxy the data network's HTTP proxy (DataNetwork),
                # and without a preferred APN it tries the internet rows in
                # file order and keeps the first that connects as the
                # preferred APN (DataProfileManager), so a proxied first row
                # that connects stays preferred even where its WAP gateway is
                # dead. Behind a proxy-free row the proxied one stays in the
                # list as a fallback. Vendors order their files the same way:
                # measured on 2026-10-06, 42 of the 44 Google per-carrier
                # entries with a proxied default row also ship a proxy-free
                # one, first in raw file order in 10 of 11 files, and so do
                # 24 of 28 such entries of Samsung builds of three years or
                # less. The key comes after the current-vendor key, so a
                # current vendor's only internet value still leads with its
                # proxy (Orange Mali 61002, "wap").
                self.proxied,
                -len(source_families(self.value_sources)),
                not self.value_sources & PRIMARY_APN_SOURCES,
                not self.row_current,
                -len(source_families(self.row_sources)),
                not self.row_sources & PRIMARY_APN_SOURCES,
                -len(self.row_sources),
            ),
        )


def scope_row_ranks(
    records: list[dict[str, Any]], lead_type: str | None = None
) -> list[RowRank]:
    """The RowRank of each row of one scope, in the order given. With
    lead_type, every row is read for that type (put_vendor_mms_first)."""
    forced_lead = lead_type
    apn_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    apn_current: dict[tuple[str, str], set[str]] = defaultdict(set)
    apn_shared: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        apn = str(record["apn"]).casefold()
        for apn_type, sources in record.get("_support", {}).items():
            apn_sources[(apn, apn_type)].update(sources)
        for apn_type, sources in record.get("_current", {}).items():
            apn_current[(apn, apn_type)].update(sources)
        for apn_type, sources in record.get("_shared", {}).items():
            apn_shared[(apn, apn_type)].update(sources)
    ranks: list[RowRank] = []
    for record in records:
        types = set(apn_row_types(record["type"]))
        lead_type = forced_lead or next(
            (apn_type for apn_type in APN_TYPE_PRIORITY if apn_type in types), None
        )
        apn = str(record["apn"]).casefold()
        placeholder = placeholder_apn(record["apn"])
        if lead_type is None:
            ranks.append(RowRank(None, placeholder, frozenset(), frozenset()))
            continue
        ranks.append(
            RowRank(
                lead_type,
                placeholder,
                frozenset(apn_sources.get((apn, lead_type), set())),
                frozenset(record.get("_support", {}).get(lead_type, frozenset())),
                frozenset(apn_current.get((apn, lead_type), set())),
                frozenset(record.get("_current", {}).get(lead_type, frozenset())),
                frozenset(apn_shared.get((apn, lead_type), set())),
                lead_type == "default" and bool(str(record.get("proxy") or "").strip()),
            )
        )
    return ranks


def rank_scope(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the rows of one scope so the best-backed row comes first. A row's
    lead type is the first type of APN_TYPE_PRIORITY it serves, so every row
    that serves the internet leads with "default". Rows are grouped by lead
    type in that order. Within a group, for the lead type:

    1. a real APN before a placeholder such as "default" or a malformed
       value (placeholder_apn),
    2. an APN value a current vendor (apn_row_current) gives for that type in
       this scope before one no current vendor gives; a Samsung value from
       an old build only, or a Google value from its shared file only that
       no maintained per-carrier source confirms, does not count,
    3. a row without an HTTP proxy before one with a proxy, only among the
       rows that lead with "default"; an MMS proxy never counts, and rows
       that lead with another type never move for it,
    4. the APN value more source families give for that type in this scope,
    5. an APN value a primary APN source gives,
    6. a row a current vendor backs, so among the variants of one value the
       one a current Pixel or Galaxy ships comes first,
    7. the row more source families back,
    8. a row a primary APN source backs,
    9. the row more sources back.

    A row is backed for a type by the sources whose observations support it.
    Rows still tied keep the fallback order: APN, types, label.
    scope_row_ranks gives the reasons, which the resolver's --explain prints.

    Android stores rows equal on TelephonyProvider's unique fields as one row,
    at the first row's place, each later row's written attributes
    overwriting, types united and bitmasks merged. So apn_xml_rows then
    writes such rows together at the best row's place with the best row last
    (write_android_groups_best_last), and it takes from the others only what
    it leaves unset."""
    ranked = zip(scope_row_ranks(records), records)
    return [
        record
        for _rank, record in sorted(
            ranked, key=lambda item: (*item[0].sort_key(), fallback_order_key(item[1]))
        )
    ]


def leave_out_stale_attach(records: list[dict[str, Any]]) -> int:
    """Take the "ia" type off the rows of one scope whose APN value no current
    vendor gives, when a current vendor gives a real APN for "default" or "ia"
    there. Android attaches with the first row that serves "ia", whatever the
    ranking says, so an old copy's attach row would otherwise beat the APN a
    current Pixel or Galaxy attaches with. A row keeps "ia" when a current
    vendor gives its APN value for any type in the scope, or when "ia" is its
    only type. The row itself stays, with its other types. Each changed row is
    marked "_ia_left_out", which is never written. Returns the rows changed."""
    vendor_apns: set[str] = set()
    covered = False
    for record in records:
        apn = str(record["apn"]).casefold()
        for apn_type, sources in record.get("_current", {}).items():
            if not sources:
                continue
            vendor_apns.add(apn)
            if apn_type in {"default", "ia"} and not placeholder_apn(record["apn"]):
                covered = True
    if not covered:
        return 0
    changed = 0
    for record in records:
        types = record["type"].split(",")
        if "ia" not in types or types == ["ia"]:
            continue
        if str(record["apn"]).casefold() in vendor_apns:
            continue
        record["type"] = ",".join(apn_type for apn_type in types if apn_type != "ia")
        record["_ia_left_out"] = True
        changed += 1
    return changed


# Network types (TelephonyManager.NETWORK_TYPE_*) of a RIL radio technology
# in "bearer_bitmask" (ServiceState.rilRadioTechnologyToNetworkType).
# TelephonyProvider.getRow reads "network_type_bitmask" when a row has it and
# converts "bearer_bitmask" otherwise; neither means every network type.
RIL_RADIO_TECH_NETWORK_TYPES = {
    1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 6: 7, 7: 5, 8: 6, 9: 8, 10: 9, 11: 10,
    12: 12, 13: 14, 14: 13, 15: 15, 16: 16, 17: 17, 18: 18, 19: 19, 20: 20,
}
# The 3GPP data network types a phone reports: GPRS, EDGE, UMTS, HSDPA, HSUPA,
# HSPA, LTE, HSPA+ and NR. LTE_CA is reported as LTE
# (NetworkRegistrationInfo.setAccessNetworkTechnology), GSM carries no data,
# IWLAN is Wi-Fi, and TD-SCDMA and the CDMA types are retired networks.
MMS_NETWORK_TYPES = frozenset({1, 2, 3, 8, 9, 10, 13, 15, 20})


def apn_row_network_types(record: dict[str, Any]) -> frozenset[int]:
    """The network types a row serves, as TelephonyProvider reads them, cut
    to MMS_NETWORK_TYPES. A row without a bitmask serves all of them."""
    def parse(value: Any) -> set[int]:
        return {int(part) for part in str(value).split("|") if part.strip().isdigit()}

    if str(record.get("network_type_bitmask") or "").strip():
        types = parse(record["network_type_bitmask"])
    elif str(record.get("bearer_bitmask") or "").strip():
        types = {RIL_RADIO_TECH_NETWORK_TYPES.get(bearer, 0) for bearer in parse(record["bearer_bitmask"])}
    else:
        return MMS_NETWORK_TYPES
    return frozenset(types) & MMS_NETWORK_TYPES if types - {0} else MMS_NETWORK_TYPES


def vendor_mms_row(record: dict[str, Any]) -> bool:
    """A vendor MMS row: a row a current vendor backs for "mms" (_current),
    with a real APN and an MMSC, that serves a 3GPP data network type
    (apn_row_network_types). put_vendor_mms_first and leave_out_absorbed_mms
    use this one predicate."""
    return (
        bool(record.get("_current", {}).get("mms"))
        and not placeholder_apn(record["apn"])
        and bool(str(record.get("mmsc") or "").strip())
        and bool(apn_row_network_types(record))
    )


def put_vendor_mms_first(ranked: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """MMS goes to a current vendor's MMS row. A vendor MMS row is a row a
    current vendor backs for "mms" (_current), with a real APN and an MMSC,
    that serves a 3GPP data network type (apn_row_network_types); it counts
    only for the network types it serves, so a Wi-Fi-only row (bearer 18) or
    a CDMA-only row never counts.

    1. Stop unless the scope has a vendor MMS row.
    2. When the first internet row serves "mms" and no current vendor backs
       it for "mms", take "mms" off it, but only when the vendor MMS rows
       together serve every network type it serves. Otherwise it keeps "mms",
       because Android sends MMS over the internet network when its APN serves
       "mms" (DataNetworkController 1372 and 1429) and else over the first
       profile that serves "mms" on the current network type
       (DataProfileManager 726-800): a type no vendor MMS row serves would be
       left without MMS (302/630 and 302/640 GID 40 and 42, where Google's
       only MMS row, apps.bell.ca, is Wi-Fi only).
    3. Stop when the first row that serves "mms" is that internet row or a
       vendor MMS row.
    4. Move the best vendor MMS row that serves neither "default" nor "ia"
       (RowRank read for "mms", then fallback_order_key) to just before it.

    Only the first internet row is retyped; retyping every row no vendor
    backs lets DataProfileManager merge EE's stale T-Mobile rows in 234/30.
    MmsService then reads the MMSC from the APN of the network that carries
    MMS (MmsRequest 209-231). Rule decisions of 2026-10-06, round 6, change
    18, which replaces change 15: measured on 2026-10-08 (public 575632c1),
    change 15 without the network types left 302/630 and 302/640 GID 40 and
    42 without MMS on every mobile network, because apps.bell.ca is Wi-Fi
    only; with them, phone MMS moves to a current vendor's exact MMS setting
    in 31 scopes on LTE, NR, HSPA, UMTS and EDGE (34 on all 11 network
    types), no scope loses MMS, and no internet or attach row changes.
    The coverage test of step 2 kept "mms" in no scope that day; a kept row
    is marked "_mms_kept_no_vendor_coverage" for --explain.
    Returns the rows and 1 when a row was retyped."""
    def serves(record: dict[str, Any], apn_type: str) -> bool:
        return apn_type in apn_row_types(record["type"])

    vendor = [record for record in ranked if vendor_mms_row(record)]
    if not vendor:
        return ranked, 0
    retyped = 0
    internet = next((record for record in ranked if serves(record, "default")), None)
    if (
        internet is not None
        and serves(internet, "mms")
        and not internet.get("_current", {}).get("mms")
    ):
        if apn_row_network_types(internet) <= frozenset().union(
            *(apn_row_network_types(record) for record in vendor)
        ):
            internet["type"] = ",".join(t for t in apn_row_types(internet["type"]) if t != "mms")
            internet["_mms_left_out"] = True
            retyped = 1
        else:
            internet["_mms_kept_no_vendor_coverage"] = True
    first = next((record for record in ranked if serves(record, "mms")), None)
    if first is None or first is internet or vendor_mms_row(first):
        return ranked, retyped
    candidates = [
        record for record in vendor if not serves(record, "default") and not serves(record, "ia")
    ]
    if not candidates:
        return ranked, retyped
    ranks = scope_row_ranks(ranked, lead_type="mms")
    position = {id(record): index for index, record in enumerate(ranked)}
    best = min(
        candidates,
        key=lambda record: (*ranks[position[id(record)]].sort_key(), fallback_order_key(record)),
    )
    moved = [record for record in ranked if record is not best]
    moved.insert(next(i for i, record in enumerate(moved) if record is first), best)
    best["_vendor_mms_ahead"] = True
    return moved, retyped


# ApnSetting.similar (ApnSetting.java:1427-1458), which
# DataProfileManager.dedupeDataProfiles (DataProfileManager.java:877-897)
# uses to merge two stored rows into one profile at the earlier row's place:
# the same APN, no shared type, neither serving dun, these fields unset on one
# side or equal, the auth type equal as ApnSetting resolves it
# (android_auth_type), and the rest equal.
ANDROID_SIMILAR_UNSET_OR_EQUAL = (
    "proxy", "port", "mmsc", "mmsproxy", "mmsport", "user", "password", "mtu", "mtu_v4", "mtu_v6",
)
ANDROID_SIMILAR_EQUAL = (
    "protocol", "roaming_protocol", "carrier_enabled", "bearer_bitmask",
    "network_type_bitmask", "lingering_network_type_bitmask", "profile_id", "modem_cognitive",
    "apn_set_id", "carrier_id", "skip_464xlat", "always_on", "infrastructure_bitmask",
    "esim_bootstrap_provisioning",
)


def android_auth_type(record: dict[str, Any]) -> int:
    """The auth type as ApnSetting's constructor resolves it
    (ApnSetting.java:1054-1058): an explicit value stays, an unset one (-1)
    becomes 0 without a username and 3 (PAP or CHAP) with one."""
    try:
        value = int(record.get("authtype", -1))
    except (TypeError, ValueError):
        value = -1
    if value != -1:
        return value
    return 3 if str(record.get("user") or "") else 0


def android_stored_rows(written: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[int]]]:
    """What TelephonyProvider stores from one written scope: per
    android_unique_key, in the order of its first row, the written attributes
    of its rows in file order, each overwriting the earlier ones, with the
    types united and the bitmasks merged (an absent bitmask means every
    network), and the indices of its rows."""
    stored: dict[tuple[str, ...], tuple[dict[str, Any], list[int]]] = {}
    for index, record in enumerate(written):
        key = android_unique_key(record)
        attributes = written_attributes(record)
        if key not in stored:
            stored[key] = (dict(attributes), [index])
            continue
        row, indices = stored[key]
        types = row["type"].split(",")
        types += [apn_type for apn_type in attributes["type"].split(",") if apn_type not in types]
        for field in ("bearer_bitmask", "network_type_bitmask"):
            old, new = row.get(field), attributes.get(field)
            attributes[field] = (
                None
                if old is None or new is None
                else "|".join(sorted(set(str(old).split("|")) | set(str(new).split("|")), key=int))
            )
        row.update(attributes)
        row["type"] = ",".join(types)
        indices.append(index)
    return list(stored.values())


def android_similar(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """ApnSetting.similar on two stored rows (ANDROID_SIMILAR_*)."""
    first_types = set(apn_row_types(first["type"]))
    second_types = set(apn_row_types(second["type"]))
    if "dun" in first_types | second_types or first_types & second_types:
        return False
    if first["apn"] != second["apn"]:
        return False
    if android_auth_type(first) != android_auth_type(second):
        return False
    for field in ANDROID_SIMILAR_UNSET_OR_EQUAL:
        a, b = first.get(field), second.get(field)
        if a not in (None, "", 0, "0") and b not in (None, "", 0, "0") and str(a) != str(b):
            return False
    for field in ANDROID_SIMILAR_EQUAL:
        default = ANDROID_APN_DEFAULTS.get(field, ANDROID_UNIQUE_DEFAULTS.get(field))
        if str(first.get(field, default)) != str(second.get(field, default)):
            return False
    return True


def mms_setting(record: dict[str, Any]) -> tuple[str, ...]:
    """Where an MMS goes: APN, MMSC, MMS proxy and MMS port."""
    return tuple(str(record.get(field, "")) for field in ("apn", "mmsc", "mmsproxy", "mmsport"))


def leave_out_absorbed_mms(written: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Leave out of one written scope a stored row (every file row of one
    android_unique_key, android_stored_rows) when all of these hold:

    1. it serves only "mms";
    2. its MMS setting (APN, MMSC, MMS proxy, MMS port) is no vendor MMS
       row's (vendor_mms_row) in the scope;
    3. the vendor MMS rows together serve every 3GPP network type it serves
       (apn_row_network_types);
    4. ApnSetting.similar holds between it and an earlier stored row of the
       scope (android_similar, auth types resolved).

    Android never keeps such a row as a profile of its own.
    DataProfileManager.dedupeDataProfiles reads the earlier row once (`first`,
    DataProfileManager.java:880) and merges every later similar row with it
    as it was read (mergeDataProfiles, 960-1040), so the merged profile takes
    the stale MMSC at the earlier row's place, ahead of the vendor's MMS row,
    and when several rows are similar to one row the last one wins and
    replaces the merges before it. Rule decisions of 2026-10-06, round 6,
    change 19: measured on 2026-10-08 on public 575632c1 with change 18, 50
    rows in 39 scopes, all absorbed or replaced on the phone; phone MMS moves
    to a current vendor's exact setting in 15 more scopes on all 11 network
    types and no scope loses a profile. The vendor rows already serve every
    network the row served, so this stays right if Android stops merging.
    Profile JSON keeps these rows; only apns-conf.xml leaves them out.
    Returns the rows kept and the rows left out, each marked
    "_absorbed_mms_left_out" for --explain."""
    vendor = [record for record in written if vendor_mms_row(record)]
    if not vendor:
        return written, []
    settings = {mms_setting(record) for record in vendor}
    covered = frozenset().union(*(apn_row_network_types(record) for record in vendor))
    left_out: set[int] = set()
    stored = android_stored_rows(written)
    for position, (row, indices) in enumerate(stored):
        if set(apn_row_types(row["type"])) != {"mms"} or mms_setting(row) in settings:
            continue
        if not apn_row_network_types(row) <= covered:
            continue
        if any(android_similar(earlier, row) for earlier, _ in stored[:position]):
            left_out.update(indices)
    for index in left_out:
        written[index]["_absorbed_mms_left_out"] = True
    return (
        [record for index, record in enumerate(written) if index not in left_out],
        [record for index, record in enumerate(written) if index in left_out],
    )


def apn_xml_rows(
    profiles: list[dict[str, Any]],
    evidence: dict[str, ProfileEvidence] | None = None,
) -> ApnRows:
    """Every APN XML row of these profiles in file order: rows LineageOS's
    apns-conf.xsd rejects left out, duplicates to Android collapsed, scopes in
    network code and MVNO selector order, a stale attach type left out
    (leave_out_stale_attach), each scope ranked by its evidence, MMS sent to a
    current vendor's MMS row that serves a mobile network
    (put_vendor_mms_first), the rows Android stores as one written together
    with the best-ranked one last (write_android_groups_best_last), and last
    a stale MMS-only row Android merges into another row left out
    (leave_out_absorbed_mms). TelephonyProvider stores such rows as
    one at the first row's place, each later row's written attributes
    overwrite, types unite and bitmasks merge, so the best row goes last and
    takes from the others only what it leaves unset. A group's first row in
    the file is therefore not what the phone uses; its last row's values are."""
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
    ia_left_out = 0
    mms_left_out = 0
    mms_absorbed: list[dict[str, Any]] = []
    for scope in sorted(scopes):
        ia_left_out += leave_out_stale_attach(scopes[scope])
        ranked, retyped = put_vendor_mms_first(rank_scope(scopes[scope]))
        mms_left_out += retyped
        kept, absorbed = leave_out_absorbed_mms(write_android_groups_best_last(ranked))
        ordered.extend(kept)
        mms_absorbed.extend(absorbed)
    return ApnRows(ordered, schema_rejected, ia_left_out, mms_left_out, tuple(mms_absorbed))


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
    ia_types_left_out: int = 0,
    mms_types_left_out: int = 0,
    mms_rows_left_out_absorbed: int = 0,
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
            # Rows of apns-conf.xml whose "ia" type leave_out_stale_attach
            # took off: no current vendor gives their APN value in a scope
            # where one gives the attach APN. Profile JSON keeps the type.
            "ia_types_left_out_not_vendor_current": ia_types_left_out,
            # First internet rows of apns-conf.xml whose "mms" type
            # put_vendor_mms_first took off: no current vendor backs them for
            # MMS, and current vendors' MMS rows serve every mobile network
            # type they serve. Profile JSON keeps the type.
            "mms_types_left_out_not_vendor_backed": mms_types_left_out,
            # Rows of apns-conf.xml leave_out_absorbed_mms left out: stale
            # MMS-only rows Android merges into an earlier row, whose MMS
            # setting no current vendor gives. Profile JSON keeps them.
            "mms_rows_left_out_absorbed_by_android": mms_rows_left_out_absorbed,
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
        apn_rows.ia_left_out,
        apn_rows.mms_left_out,
        len(apn_rows.mms_absorbed_left_out),
    )
    config_count = sum(1 for profile in profiles if profile.get("android_carrier_config"))
    print(
        f"generated Android output for {len(profiles)} profile(s): "
        f"{apn_count} APN row(s), {config_count} CarrierConfig profile(s), "
        f"{config_xml_count} CarrierConfig XML block(s), "
        f"{rows_schema_rejected} APN row(s) left out because LineageOS's schema rejects them, "
        f"{apn_rows.ia_left_out} APN row(s) without the attach type no current vendor gives, "
        f"{apn_rows.mms_left_out} first internet row(s) without the MMS type no current vendor backs, "
        f"{len(apn_rows.mms_absorbed_left_out)} stale MMS-only row(s) Android merges into another row left out"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
