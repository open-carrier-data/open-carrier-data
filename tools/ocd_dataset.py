#!/usr/bin/env python3
"""The OCD dataset for the owner's ROM (rule round 30): generate, validate, match.

Rule round 30 (2026-10-25) replaces Google's carrier data on the owner's ROM
with one OCD dataset per commit of main. OcdCarrierSettings reads it, the OCD
Check owner app pulls it, and the ROM pin step bakes it into the build. This
tool writes and checks that dataset from the files of one checkout of main:

  generated/ocd-dataset/manifest.json    the header: digests, file list, counts
  generated/ocd-dataset/profiles.json    the closed key registry, groups A, B
                                         and X6, and every network's profiles
                                         with OCD's match rules, specificity,
                                         values and the Google-lane fill list
  generated/ocd-dataset/google-lane.json the Google lane's values (family
                                         `google`), written by the private
                                         publisher; this tool only re-stamps it
  generated/ocd-dataset/apn-index.json   each apns-conf.xml row's line, key and
                                         profiles
  generated/devices/device-records.json  the per-device records, from
                                         devices/records/
  schemas/carrier-config-keys.json       the closed key registry

The file formats are those of the round 30 dataset spec (S20 project report
"OCD round 30 dataset spec", sections 2 and 4); the schemas under schemas/
(ocd-dataset-*.schema.json, device-records.schema.json) describe them, and
docs/ocd-dataset.md explains them for consumers.

  generate [--root DIR] [--generated-at ISO]
      Writes the dataset. The manifest keeps its generated_at when no file
      changed; otherwise generated_at is now (or --generated-at).
  validate [--root DIR] [--base-manifest FILE]
      The schemas, the reader's checks 4 to 10 of spec 2.12 (manifest,
      digests, strict parse, closed and typed keys, specificity, network
      copies, APN version, APN index), the device-record rules, the privacy
      guard, and a regeneration that must give the same bytes. With
      --base-manifest (main's manifest, on a pull request), a changed dataset
      must carry a later generated_at. Exit 1 on a problem.
  match --mcc MCC --mnc MNC [--spn S] [--imsi I] [--gid1 G] [--gid2 G] [--iccid I]
        [--carrier-id N] [--specific-carrier-id N] [--root DIR]
      The stack, the serving profile and the fill pick for one SIM, as the
      reader computes them (spec 4.2 and 2.5.5). Use synthetic identities.
  ties [--root DIR]
      Pairs of profiles of equal specificity on one network that one SIM can
      match together (spec 4.2 rule 5): the tie report.

Only the standard library is used, as in the other public tools.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable

TOOLS = Path(__file__).resolve().parent

# ---------------------------------------------------------------- constants

SCHEMA_VERSION = 1
FORMAT = "ocd-dataset"
GENERATOR = "open-carrier-data tools/ocd_dataset.py 1"
APN_DATABASE_VERSION = 8
EXPIRE_DAYS = 90
FAMILY = "google"
LANE_STATES = ("public_main", "private_lane_at_build_pin")

DATASET_DIR = "generated/ocd-dataset"
# role -> (local name, path on main, cap in bytes); the manifest lists every
# role but its own, and the pin is written by the fetcher, never here.
FILES = {
    "manifest": ("manifest.json", f"{DATASET_DIR}/manifest.json", 256 * 1024),
    "profiles": ("profiles.json", f"{DATASET_DIR}/profiles.json", 32 * 1024 * 1024),
    "google_lane": ("google-lane.json", f"{DATASET_DIR}/google-lane.json", 8 * 1024 * 1024),
    "device_records": ("device-records.json", "generated/devices/device-records.json", 4 * 1024 * 1024),
    "apn_xml": ("apns-conf.xml", "generated/android/apns-conf.xml", 16 * 1024 * 1024),
    "apn_index": ("apn-index.json", f"{DATASET_DIR}/apn-index.json", 16 * 1024 * 1024),
    # Round 31 (S20 spec R31.7): optional; a reader of protocol 2 refuses a
    # manifest that lists it. Listed once LIST_GROUP_A_READS is true.
    "group_a_reads": ("group-a-reads.json", f"{DATASET_DIR}/group-a-reads.json", 4 * 1024 * 1024),
    "pin": ("pin.json", None, 64 * 1024),
}
TOTAL_CAP = 64 * 1024 * 1024
REGISTRY_PATH = "schemas/carrier-config-keys.json"
RECORDS_DIR = "devices/records"
CONFIGURED_DIR = f"{RECORDS_DIR}/configured"
MEASURED_FILE = f"{RECORDS_DIR}/measured.json"
READS_DIR = f"{RECORDS_DIR}/reads"
KEYS_FILE = f"{RECORDS_DIR}/keys.json"

MAX_STRING_UNITS = 4096
MAX_ARRAY_ITEMS = 1024
MAX_BUNDLE_DEPTH = 3
MAX_INNER_KEY_UNITS = 128
INT_RANGE = (-(2**31), 2**31 - 1)
LONG_RANGE = (-(2**63), 2**63 - 1)
REGISTRY_TYPES = ("bool", "int", "long", "double", "string", "string_array", "int_array", "bundle")
ORIGINS = ("device_record", "google", "ocd_schema")
# Google's Config value fields, as the private lane builder names them.
GOOGLE_TYPE_NAMES = {
    "boolean": "bool", "int": "int", "long": "long", "double": "double", "string": "string",
    "string_array": "string_array", "int_array": "int_array", "bundle": "bundle",
}

# Group A (spec 5.1, the ruling's group A): CarrierSettings's own pattern,
# the two keys the ruling names, and the eight keys of spec 11.4 that the
# owner put into group A on 2026-10-25 ("today's Google-lane value").
GROUP_A_PATTERN = r"emergency|e911|ecbm|(^|[._])ecm([._]|$)|wps|tty|rtt|sos|^imsemergency\."
GROUP_A_RE = re.compile(GROUP_A_PATTERN, re.IGNORECASE)
GROUP_A_RULING_NAMES = ("call_forwarding_blocks_while_roaming_string_array", "ims_reasoninfo_mapping_string_array")
GROUP_A_OWNER_NAMES = (
    "dial_string_replace_string_array",
    "gps.es_extension_sec",
    "international_roaming_dial_string_replace_string_array",
    "rilext.carrier_ignore_clir_when_ecc",
    "rilext.carrier_ignore_sms_for_eims",
    "rilext.exiting_ecc_mode_after_epdn_disconnected_enable",
    "rilext.ims_prefer_apm_normal_ecc_enable",
    "use_only_dialed_sim_ecc_list_bool",
)
GROUP_A_NAMES = tuple(sorted(GROUP_A_RULING_NAMES + GROUP_A_OWNER_NAMES))
GROUP_B_KEYS = ("carrier_metered_apn_types_strings", "carrier_metered_roaming_apn_types_strings")
GROUP_B_MUST_CONTAIN = "default"
X6_KEYS = ("enableGroupMms", "enableMultipartSMS", "smsToMmsTextLengthThreshold", "smsToMmsTextThreshold")
X6_NETWORKS = ("228-01", "228-02", "228-03", "262-01", "262-02", "262-03", "262-07", "262-23", "270-01")
CONFIG_VALUE_DOMAINS = {
    "carrier_default_wfc_ims_mode_int": frozenset({0, 1, 2}),
    "carrier_default_wfc_ims_roaming_mode_int": frozenset({0, 1, 2}),
}
FORBIDDEN_KEYS = frozenset({"carrier_config_version_string"})

# Match dimensions (spec 2.5.4) and the Google MVNO kinds they take.
DIMENSIONS = ("spn", "imsi_prefix_patterns", "gid1_prefixes", "gid2_prefixes", "iccid_prefixes", "android_carrier_ids")
KIND_DIMENSION = {"spn": "spn", "imsi": "imsi_prefix_patterns", "gid1": "gid1_prefixes", "iccid": "iccid_prefixes"}
MVNO_KINDS = tuple(KIND_DIMENSION)
OCD_ID_RE = re.compile(r"open\.[0-9]{5,6}\.[0-9a-f]{12}")
FILL_ID_RE = re.compile(r"fill\.[0-9]{5,6}\.[0-9a-f]{12}")
NETWORK_RE = re.compile(r"([0-9]{3})-([0-9]{2,3})")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
GENERATED_AT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
ROW_KEY_RE = re.compile(r"a:[0-9a-f]{16}")
RECORD_KEY_RE = re.compile(r"r:[0-9a-f]{16}")
# Public main never carries an IMSI pattern of 14 or more characters: a
# full IMSI is 15 digits, and 14 consecutive digits are what the privacy
# guard treats as an identity. OCD's own profiles stay at 5 to 10 (rule 3).
# Google's own entries that no carrier_list rule names; every other entry of
# the published lane is named by a rule.
UNNAMED_LANE_ENTRIES = ("default", "no_sim")
OCD_IMSI_RE = re.compile(r"[0-9xX]{5,10}")
SOURCE_FAMILY_NAMES = {"google_carriersettings": FAMILY, "google_pixel_vendor_carriersettings": FAMILY}

# The private sanitizer's BLOCK_PATTERNS (live-private tools/sanitize_profiles.py,
# rule 3), the guard every published string passes. The private publisher
# leaves out of the Google lane every value that trips it; validate refuses
# a file that still has one. live-private's tests check the two copies agree.
BLOCK_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "long_decimal_identity": re.compile(r"\b\d{14,20}\b"),
    "international_phone": re.compile(r"\+\d{8,15}\b"),
    "secret_word": re.compile(r"(?i)\b(pswd|secret|token|authorization)\b"),
    "raw_vendor_file": re.compile(
        r"(?i)\b(customer\.xml|cscfeature\.xml|imsupdate\.json|omc\.info|"
        r"customer_carrier_feature\.json|carrier_canonical_id_list\.json|"
        r"carrier\.plist|\.ipcc|carrier_settings\.pb|mbn)\b"
    ),
    "raw_vendor_key": re.compile(r"\b(CarrierFeature_|GRASSE-AUTH|SemCarrierFeature|CarrierBundle|CSettingsDir)\b"),
    "gras_payload": re.compile(r"(?i)\b(updateURL|pkgHash|pkgSize|fileDownloadUrl|deviceId|imei)\b"),
    "ims_patch": re.compile(
        r"\b(imsswitch_update|imsprofile_update|globalsettings_update|mnomap_update|"
        r"add_mnomap|remove_mnomap|remove_profile|epdgsettings|iwlansettings|"
        r"vowifisettings|enableIms|enableService[A-Za-z]+|mnoname)\b"
    ),
}

# Round 31 (keys), implementation order step 8: the S20's five
# configured_device records left main once the build with the restored
# device override had passed on the phone. No record is keyed by device
# alone, and every record names a carrier.
LEGACY_DEVICE_ONLY_RECORDS: frozenset[str] = frozenset()

RECORD_KINDS = ("measured",)
# The carrier keys a record may name (round 31): an OCD or fill-only profile,
# or MCC-MNC with GID1 or SPN for a SIM that default or a fill-only profile
# serves.
CARRIER_SCOPES = ("profile", "sim_key")
# Round 31 cell records: generated/devices/device-records.json schema_version
# 2 (schemas/cell-records.schema.json). A measured record belongs to one cell:
# the device, the carrier (profile or SIM key), the ROM family and build line
# with its forks, and the IMS stack with its fork; it also states the build
# incremental and the stack version, which are recorded, not matched. Public
# main serves schema_version 1 (the round 30 format, which every reader on a
# phone today parses); implementation order step 8 dropped the five S20
# records, and SERVED_RECORDS_SCHEMA_VERSION switches to 2 once the readers on
# the phones parse it. The report bot takes schema_version 1 records until the
# switch; a cell record placed in devices/records/measured.json before then is
# checked and waits there unserved.
CELL_RECORDS_SCHEMA_VERSION = 2
SERVED_RECORDS_SCHEMA_VERSION = 1
FORK_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
INCREMENTAL_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}")
CELL_RECORD_MEMBERS = frozenset({
    "record_key", "kind", "device", "rom", "ims_stack", "carrier", "target", "value_kind", "value", "claim", "label",
    "basis", "level", "result", "method", "bearer", "n", "first_measured", "last_measured", "valid_until", "data",
    "tester", "differs_between_sims",
})
IMS_STACK_IDS = ("aosp_imsstack", "other", "phh_ims", "samsung_ims")
VALUE_KINDS = ("android_default", "none", "value")
CLAIMS = ("configured", "measured")
LEVELS = ("L2", "L3", "emergency_data", "no_regression", "sms_both_ways")
RESULTS = (
    "calls_out", "emergency_data_accepted", "emergency_data_refused", "emergency_default_won",
    "no_regression_passed", "no_value_passed", "sms_both_ways", "winner_after_failure", "works",
)
EMERGENCY_RESULTS = ("emergency_data_accepted", "emergency_data_refused", "emergency_default_won")
METHODS = (
    "eims_request", "mailbox_call", "mailbox_call+real_call", "observed", "override_trial", "real_call",
    "real_call+real_call", "self_sms",
)
BEARERS = ("iwlan", "lte", "nr")
READ_SCHEMA = "ocd-group-a-read/1"

# Round 31 (2026-10-28 ruling, `emergencyValues`): a group A value that
# differs from the Google lane is served only after an independent read with
# verdict proceed is on main, for that key, value, source and profile and for
# the ROM family and IMS stack it is served on. A key read whose finding is
# display_only takes the key out of group A. The reads live in
# devices/records/reads/ (ocd-group-a-read/2) and are copied, with the
# candidates still waiting for a read, into generated/ocd-dataset/group-a-reads.json.
GROUP_A_READ_SCHEMA = "ocd-group-a-read/2"
# Rule round 45, item 1: profile IDs are frozen from this day; a record made
# later stores the match-set hash it was made under.
ID_FREEZE_DATE = "2026-10-31"
GROUP_A_EFFECTS = ("call_path", "display_only")
GROUP_A_READS_FILE = f"{DATASET_DIR}/group-a-reads.json"
GROUP_A_PENDING_FILE = f"{DATASET_DIR}/group-a-pending.json"
# Whether the manifest lists group-a-reads.json as the role group_a_reads.
# The round 31 readers (OcdCarrierSettings protocol 3, the OCD Check owner
# app) take it, and a round 30 reader (protocol 2) refuses a manifest that
# lists it. Implementation order step 8 lists it; before that the file sat
# beside the dataset and CarrierSettings served the Google-lane value for
# every group A key.
LIST_GROUP_A_READS = True
# The keys that never leave group A, whatever a read finds (round 31,
# emergencyValues; the S20 spec's R31.7).
GROUP_A_NEVER_LEAVE = frozenset({
    "dial_string_replace_string_array",
    "emergency_number_prefix_string_array",
    "international_roaming_dial_string_replace_string_array",
})
# Companion files of the dataset (round 31). They sit beside the dataset in
# the same commit but are not manifest roles, because a reader refuses an
# unknown role; since implementation order step 8 the manifest also lists
# group-a-reads.json as the role group_a_reads (LIST_GROUP_A_READS). Each
# names the dataset it belongs to (f5-reads.json by the
# APN rows' SHA-256, the others by the data digest); the app takes them
# from the same commit with the blob check and hands them over with the
# stage, and the ROM pin step bakes them (export_ocd_dataset.py bake
# --companions).
#   f5-reads.json          the F5 reads of emergency-line changes (SM6),
#                          written by tools/f5_read.py publish
#   group-a-reads.json     the group A reads and the candidates waiting for
#                          one, written by generate from devices/records/reads/
#   privacy-withheld.json  the Google-lane values the privacy guard leaves
#                          out (SM4), written by the private publisher
F5_READS_FILE = f"{DATASET_DIR}/f5-reads.json"
WITHHELD_FILE = f"{DATASET_DIR}/privacy-withheld.json"
COMPANION_FILES = (F5_READS_FILE, GROUP_A_READS_FILE, GROUP_A_PENDING_FILE, WITHHELD_FILE)
COMPANION_CAP = 4 * 1024 * 1024
# The ROM family and IMS stack OCD runs its reads for today: the stack SM8
# lists as calibrated. Another ROM family's builder asks for its own reads.
GROUP_A_READ_TARGETS = (("lineageos", "aosp_imsstack"),)
ROM_FAMILIES = ("aosp", "lineageos", "other", "stock")


class DatasetError(Exception):
    """The dataset or its inputs break a rule; the message names the file and the rule."""


# ---------------------------------------------------------------- JSON


class StrictJSONError(ValueError):
    pass


def strict_loads(text: str, where: str) -> Any:
    """RFC 8259 JSON with no repeated member, no NaN or Infinity, no U+0000 in a string."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise StrictJSONError(f"{where}: the member {key[:80]!r} appears twice in one object")
            out[key] = value
        return out

    def constant(name: str) -> Any:
        raise StrictJSONError(f"{where}: {name} is not allowed")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except StrictJSONError:
        raise
    except json.JSONDecodeError as error:
        raise StrictJSONError(f"{where}: not valid JSON (line {error.lineno}, column {error.colno}: {error.msg})") from error
    return value


def strict_load_bytes(data: bytes, where: str) -> Any:
    if data.startswith(b"\xef\xbb\xbf"):
        raise StrictJSONError(f"{where}: starts with a byte order mark")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StrictJSONError(f"{where}: not UTF-8 ({error})") from error
    value = strict_loads(text, where)
    if not isinstance(value, dict):
        raise StrictJSONError(f"{where}: the top level is not one object")
    return value


def compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def dump_lines(document: dict[str, Any], split: Iterable[str]) -> bytes:
    """Canonical JSON (sorted keys, no spaces, UTF-8) with each item of the
    SPLIT members on a line of its own, so that a diff shows one network,
    rule, entry, row or record per line. Deterministic for a given value."""
    split = set(split)
    parts = []
    for key in sorted(document):
        value = document[key]
        head = json.dumps(key, ensure_ascii=False) + ":"
        if key in split and isinstance(value, dict) and value:
            body = "{\n" + ",\n".join(json.dumps(k, ensure_ascii=False) + ":" + compact(value[k]) for k in sorted(value)) + "\n}"
        elif key in split and isinstance(value, list) and value:
            body = "[\n" + ",\n".join(compact(item) for item in value) + "\n]"
        else:
            body = compact(value)
        parts.append(head + body)
    return ("{" + ",".join(parts) + "}\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


# ---------------------------------------------------------------- matcher (spec 4.2)


def _simple_upper(char: str) -> str:
    upper = char.upper()
    return upper if len(upper) == 1 else char


def _simple_lower(char: str) -> str:
    lower = char.lower()
    return lower if len(lower) == 1 else char


def java_equals_ignore_case(first: str, second: str) -> bool:
    """Java's String.equalsIgnoreCase: equal length, then char by char equal,
    equal upper case, or equal lower case of the upper case (simple case
    mapping, one char to one char). "Straße" and "STRASSE" differ (vector
    M23), where Python's casefold would join them."""
    if len(first) != len(second):
        return False
    for a, b in zip(first, second):
        if a == b:
            continue
        ua, ub = _simple_upper(a), _simple_upper(b)
        if ua == ub or _simple_lower(ua) == _simple_lower(ub):
            continue
        return False
    return True


def java_starts_with_ignore_case(value: str, prefix: str) -> bool:
    return len(value) >= len(prefix) and java_equals_ignore_case(value[: len(prefix)], prefix)


def imsi_pattern_matches(pattern: str, imsi: str) -> bool:
    """UiccController.imsiMatches: the pattern is no longer than the IMSI, and
    at each of its positions holds x, X or the IMSI's digit."""
    if len(pattern) > len(imsi):
        return False
    return all(p in "xX" or p == c for p, c in zip(pattern, imsi))


def dimension_holds(dimension: str, values: list[Any], sim: dict[str, Any]) -> bool:
    """One match dimension against a SIM; a missing SIM field fails it."""
    if dimension == "spn":
        spn = sim.get("spn")
        return isinstance(spn, str) and any(java_equals_ignore_case(spn, v) for v in values)
    if dimension == "imsi_prefix_patterns":
        imsi = sim.get("imsi")
        return isinstance(imsi, str) and any(imsi_pattern_matches(v, imsi) for v in values)
    if dimension in ("gid1_prefixes", "gid2_prefixes"):
        gid = sim.get("gid1" if dimension == "gid1_prefixes" else "gid2")
        return isinstance(gid, str) and any(java_starts_with_ignore_case(gid, v) for v in values)
    if dimension == "iccid_prefixes":
        iccid = sim.get("iccid")
        return isinstance(iccid, str) and any(iccid.startswith(v) for v in values)
    if dimension == "android_carrier_ids":
        ids = [sim.get(name) for name in ("carrier_id", "specific_carrier_id")]
        return any(isinstance(i, int) and i >= 0 and i in values for i in ids)
    raise ValueError(dimension)


def profile_holds(profile: dict[str, Any], sim: dict[str, Any]) -> bool:
    match = profile["match"]
    if not any(n["mcc"] == sim.get("mcc") and n["mnc"] == sim.get("mnc") for n in match["mccmnc"]):
        return False
    return all(dimension_holds(d, match[d], sim) for d in DIMENSIONS if d in match)


def specificity_of(match: dict[str, Any]) -> int:
    return sum(1 for d in DIMENSIONS if match.get(d))


def stack_order(profile: dict[str, Any]) -> tuple[int, bytes]:
    return (profile["specificity"], profile["id"].encode("utf-8"))


def resolve_stack(network_profiles: list[dict[str, Any]], sim: dict[str, Any]) -> list[dict[str, Any]]:
    """Every profile of the SIM's network that holds, generic to specific
    (specificity, then id in byte order); the last one serves."""
    return sorted((p for p in network_profiles if profile_holds(p, sim)), key=stack_order)


def when_holds(when: dict[str, str] | None, sim: dict[str, Any]) -> bool:
    if when is None:
        return True
    kind, value = when["kind"], when["value"]
    return dimension_holds(KIND_DIMENSION[kind], [value], sim)


def pick_fill(fill: list[dict[str, Any]], sim: dict[str, Any], entries: set[str] | dict[str, Any] | None = None) -> str | None:
    """The reader's pick: the first item whose `when` is null or holds; an
    entry missing from the lane used is skipped (spec 2.7)."""
    for item in fill:
        if entries is not None and item["entry"] not in entries:
            continue
        if when_holds(item["when"], sim):
            return item["entry"]
    return None


# ---------------------------------------------------------------- fill (spec 2.5.5)


def values_overlap(kind: str, w: str, v: str) -> bool:
    """One SIM can satisfy both w (the profile's) and v (the rule's)."""
    if kind == "spn":
        return java_equals_ignore_case(w, v)
    if kind == "gid1":
        return java_starts_with_ignore_case(w, v) or java_starts_with_ignore_case(v, w)
    if kind == "iccid":
        return w.startswith(v) or v.startswith(w)
    if kind == "imsi":
        return all(a in "xX" or b in "xX" or a == b for a, b in zip(w, v))
    raise ValueError(kind)


def value_implies(kind: str, w: str, v: str) -> bool:
    """Every SIM that satisfies w also satisfies v."""
    if kind == "spn":
        return java_equals_ignore_case(w, v)
    if kind == "gid1":
        return java_starts_with_ignore_case(w, v)
    if kind == "iccid":
        return w.startswith(v)
    if kind == "imsi":
        if len(w) < len(v):
            return False
        return all(b in "xX" or (a not in "xX" and a == b) for a, b in zip(w, v))
    raise ValueError(kind)


def compute_fill(match: dict[str, Any], network_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ordered Google-lane fill list of one profile on one network: the
    network's rules in file order; a rule without MVNO data ends the list;
    a compatible MVNO rule is appended with its condition, or without one,
    ending the list, when the profile's values imply it."""
    fill: list[dict[str, Any]] = []
    for rule in network_rules:
        mvno = rule["mvno"]
        if mvno is None:
            fill.append({"entry": rule["canonical_name"], "when": None})
            break
        kind, value = mvno["kind"], mvno["value"]
        own = match.get(KIND_DIMENSION[kind])
        if not own or not any(values_overlap(kind, w, value) for w in own):
            continue
        if all(value_implies(kind, w, value) for w in own):
            fill.append({"entry": rule["canonical_name"], "when": None})
            break
        fill.append({"entry": rule["canonical_name"], "when": {"kind": kind, "value": value}})
    return fill


def fill_only_id(rule: dict[str, Any]) -> str:
    mvno = rule["mvno"]
    text = "\n".join([
        "google-rule", rule["canonical_name"], f"{rule['mcc']}-{rule['mnc']}",
        mvno["kind"] if mvno else "none", mvno["value"] if mvno else "",
    ])
    return f"fill.{rule['mcc']}{rule['mnc']}.{sha256_hex(text.encode('utf-8'))[:12]}"


def rule_match(rule: dict[str, Any]) -> dict[str, Any]:
    match: dict[str, Any] = {"mccmnc": [{"mcc": rule["mcc"], "mnc": rule["mnc"]}]}
    if rule["mvno"] is not None:
        match[KIND_DIMENSION[rule["mvno"]["kind"]]] = [rule["mvno"]["value"]]
    return match


def same_datum(kind: str, a: str, b: str) -> bool:
    """Two selectors that name the same SIMs, as Android compares them."""
    if kind == "spn":
        return java_equals_ignore_case(a, b)
    if kind == "gid1":
        return java_equals_ignore_case(a, b)
    if kind == "imsi":
        return len(a) == len(b) and all((x in "xX" and y in "xX") or x == y for x, y in zip(a, b))
    return a == b


def exact_profile_exists(rule: dict[str, Any], ocd_by_network: dict[str, list[dict[str, Any]]]) -> bool:
    """An OCD profile with exactly the rule's match: the same single network
    and the same single MVNO datum, nothing else (spec 2.6)."""
    for profile in ocd_by_network.get(f"{rule['mcc']}-{rule['mnc']}", []):
        match = profile["match"]
        if match["mccmnc"] != [{"mcc": rule["mcc"], "mnc": rule["mnc"]}]:
            continue
        used = [d for d in DIMENSIONS if d in match]
        if rule["mvno"] is None:
            if not used:
                return True
            continue
        dimension = KIND_DIMENSION[rule["mvno"]["kind"]]
        if used == [dimension] and len(match[dimension]) == 1 and same_datum(rule["mvno"]["kind"], match[dimension][0], rule["mvno"]["value"]):
            return True
    return False


# ---------------------------------------------------------------- typed values (spec 2.3)


def value_problem(value: Any, kind: str, where: str, depth: int = 1) -> str | None:
    """Why VALUE is not a value of registry type KIND, or None."""
    if kind == "bool":
        return None if isinstance(value, bool) else f"{where}: is not a bool"
    if kind in ("int", "long"):
        low, high = INT_RANGE if kind == "int" else LONG_RANGE
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{where}: is not an integer ({kind})"
        return None if low <= value <= high else f"{where}: is outside the {kind} range"
    if kind == "double":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{where}: is not a number (double)"
        return None if math.isfinite(value) else f"{where}: is not finite"
    if kind == "string":
        return string_problem(value, where)
    if kind == "string_array":
        if not isinstance(value, list) or len(value) > MAX_ARRAY_ITEMS:
            return f"{where}: is not an array of at most {MAX_ARRAY_ITEMS} strings"
        for index, item in enumerate(value):
            problem = string_problem(item, f"{where}[{index}]")
            if problem:
                return problem
        return None
    if kind == "int_array":
        if not isinstance(value, list) or len(value) > MAX_ARRAY_ITEMS:
            return f"{where}: is not an array of at most {MAX_ARRAY_ITEMS} integers"
        for index, item in enumerate(value):
            problem = value_problem(item, "int", f"{where}[{index}]")
            if problem:
                return problem
        return None
    if kind == "bundle":
        if depth > MAX_BUNDLE_DEPTH:
            return f"{where}: bundles nest deeper than {MAX_BUNDLE_DEPTH}"
        if not isinstance(value, dict):
            return f"{where}: is not a bundle object"
        for inner, item in value.items():
            if utf16_units(inner) > MAX_INNER_KEY_UNITS or "\0" in inner:
                return f"{where}: an inner key is longer than {MAX_INNER_KEY_UNITS} units or holds U+0000"
            if not isinstance(item, dict) or set(item) != {"type", "value"} or item["type"] not in REGISTRY_TYPES:
                return f"{where}.{inner[:60]}: an inner item must be {{\"type\", \"value\"}} with a registry type"
            problem = value_problem(item["value"], item["type"], f"{where}.{inner[:60]}", depth + 1)
            if problem:
                return problem
        return None
    return f"{where}: unknown registry type {kind}"


def string_problem(value: Any, where: str) -> str | None:
    if not isinstance(value, str):
        return f"{where}: is not a string"
    if "\0" in value:
        return f"{where}: holds U+0000"
    if utf16_units(value) > MAX_STRING_UNITS:
        return f"{where}: is longer than {MAX_STRING_UNITS} UTF-16 units"
    return None


def domain_problem(key: str, value: Any, where: str) -> str | None:
    if key in FORBIDDEN_KEYS:
        return f"{where}: no value may be set for {key}"
    domain = CONFIG_VALUE_DOMAINS.get(key)
    if domain is not None and value not in domain:
        return f"{where}: {key} must be one of {sorted(domain)}"
    return None


def strings_of(value: Any) -> Iterable[str]:
    """Every string in a value, bundle inner keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings_of(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_of(item)


def privacy_hits(value: Any) -> list[str]:
    """The BLOCK_PATTERNS rules any string of VALUE trips."""
    hits = []
    for text in strings_of(value):
        for name, pattern in BLOCK_PATTERNS.items():
            if pattern.search(text):
                hits.append(name)
    return sorted(set(hits))


# ---------------------------------------------------------------- inputs


def read_json_file(path: Path) -> Any:
    try:
        return strict_load_bytes(path.read_bytes(), str(path))
    except OSError as error:
        raise DatasetError(f"{path}: cannot be read ({error})") from error
    except StrictJSONError as error:
        raise DatasetError(str(error)) from error


def load_module(name: str, path: Path) -> Any:
    """A public tool from ROOT/tools, imported from that tree (a pinned
    commit's own generator for a bake, this tree's otherwise)."""
    spec = importlib.util.spec_from_file_location(f"{name}_{hashlib.sha1(str(path).encode()).hexdigest()[:8]}", path)
    if spec is None or spec.loader is None:
        raise DatasetError(f"{path}: cannot be imported")
    module = importlib.util.module_from_spec(spec)
    directory = path.parent.resolve()
    # The tool's own imports (carrier_config_types, lineageos_apns, ...) must
    # come from its tree, not from a module of the same name loaded earlier
    # from another tree (the private repo has its own carrier_config_types).
    local = {p.stem for p in directory.glob("*.py")}
    stashed = {n: sys.modules.pop(n) for n in list(sys.modules) if n in local}
    saved = list(sys.path)
    sys.path.insert(0, str(directory))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
        for n in local:
            sys.modules.pop(n, None)
        sys.modules.update(stashed)
    return module


def apns_header_digest(xml: bytes) -> str | None:
    match = re.search(rb"(?m)^    data_digest: (sha256:[0-9a-f]{64})$", xml[:4096])
    return match.group(1).decode("ascii") if match else None


def schema_config_keys(root: Path) -> dict[str, str]:
    """The public schema's CarrierConfig keys with their types (the 117 keys)."""
    schema = read_json_file(root / "schemas/carrier-profile.schema.json")
    types = load_module("carrier_config_types", root / "tools/carrier_config_types.py")
    keys = schema["properties"]["android_carrier_config"]["propertyNames"]["enum"]
    return {key: types.expected_config_type(key) for key in keys}


def lane_rule_within_limits(rule: dict[str, Any]) -> bool:
    """Rule 3, which rule round 32 applies to every published file: a Google
    rule's IMSI or ICCID datum passes the same subscriber_prefix_ok as every
    other published selector (an IMSI pattern of 5 to 10 digits or x, an
    ICCID prefix of 5 to 13 digits)."""
    mvno = rule.get("mvno")
    if not mvno or mvno.get("kind") not in ("imsi", "iccid"):
        return True
    return carrier_validator().subscriber_prefix_ok(mvno["kind"], str(mvno.get("value", "")))


_CARRIER_VALIDATOR: list[Any] = []


def carrier_validator() -> Any:
    """The public validator module, loaded once: its subscriber_prefix_ok is
    the one rule 3 check every published selector passes."""
    if not _CARRIER_VALIDATOR:
        _CARRIER_VALIDATOR.append(load_module("validate_public_carrier_data", TOOLS / "validate_public_carrier_data.py"))
    return _CARRIER_VALIDATOR[0]


def within_prefix_limits(lane: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The Google lane without the rules whose selector breaks rule 3's
    limits and without the entries only those rules named, and the rules left
    out by entry, network, kind and length only, never the value. A SIM such
    a rule named gets the network's next fill item, or default."""
    kept, left_out = [], []
    for rule in lane.get("rules", []):
        if lane_rule_within_limits(rule):
            kept.append(rule)
        else:
            left_out.append({"canonical_name": rule["canonical_name"], "network": f"{rule['mcc']}-{rule['mnc']}",
                             "kind": rule["mvno"]["kind"], "characters": len(str(rule["mvno"]["value"]))})
    if not left_out:
        return lane, []
    named = {rule["canonical_name"] for rule in kept} | set(UNNAMED_LANE_ENTRIES)
    entries = {name: entry for name, entry in lane.get("entries", {}).items() if name in named}
    return {**lane, "rules": kept, "entries": entries}, left_out


class Inputs:
    """The files of one checkout of main that the dataset is made from."""

    def __init__(self, root: Path) -> None:
        self.root = root
        generated = root / "generated"
        self.metadata = read_json_file(generated / "android/metadata.json")
        self.data_digest = self.metadata.get("data_digest")
        if not isinstance(self.data_digest, str) or not DIGEST_RE.fullmatch(self.data_digest):
            raise DatasetError("generated/android/metadata.json: data_digest is missing or malformed")
        self.lookup = read_json_file(generated / "android/lookup.json")
        self.apn_xml = (generated / "android/apns-conf.xml").read_bytes()
        evidence_path = generated / "evidence-index.json"
        self.evidence = read_json_file(evidence_path) if evidence_path.is_file() else {"profiles": []}
        lane_path = root / FILES["google_lane"][1]
        self.lane = read_json_file(lane_path) if lane_path.is_file() else None
        self.lane_rules_left_out: list[dict[str, Any]] = []
        if self.lane is not None:
            self.lane, self.lane_rules_left_out = within_prefix_limits(self.lane)
        registry_path = root / REGISTRY_PATH
        self.registry_file = read_json_file(registry_path) if registry_path.is_file() else None
        self.schema_keys = schema_config_keys(root)
        self.records_root = root / RECORDS_DIR

    def carrier_profile(self, path: str) -> dict[str, Any]:
        return read_json_file(self.root / path)


# ---------------------------------------------------------------- device records


def record_carrier_text(carrier: dict[str, Any]) -> str:
    if carrier["scope"] == "all":
        return "all"
    if carrier["scope"] == "profile":
        return f"profile:{carrier['profile_id']}"
    network = f"{carrier['mcc']}-{carrier['mnc']}"
    if "gid1" in carrier:
        return f"sim:{network}:gid1={carrier['gid1'].upper()}"
    return f"sim:{network}:spn={carrier['spn']}"


def record_target_text(target: dict[str, Any]) -> str:
    if target["type"] == "config":
        return f"config:{target['key']}"
    if target["type"] == "apn":
        return f"apn:{target['row_key']}"
    return f"emergency_data:{target['row_key'] or 'default'}"


def record_key_of(record: dict[str, Any]) -> str:
    """r: and the first 16 hex digits of SHA-256 over the nine identity lines (spec 2.10)."""
    lines = [
        record["kind"], record["device"]["codename"], record["device"]["model"].upper(),
        record["rom"]["family"], record["rom"]["line"], record["ims_stack"]["id"],
        record["ims_stack"]["fork"] or "", record_carrier_text(record["carrier"]), record_target_text(record["target"]),
    ]
    return "r:" + sha256_hex("\n".join(lines).encode("utf-8"))[:16]


def is_cell_record(record: Any) -> bool:
    """A round 31 cell record (schema_version 2): its ROM names its forks."""
    return isinstance(record, dict) and isinstance(record.get("rom"), dict) and "forks" in record["rom"]


def cell_record_key_of(record: dict[str, Any]) -> str:
    """r: and the first 16 hex digits of SHA-256 over the ten cell lines,
    joined with \n: kind, device codename, upper-cased model, ROM family,
    ROM line, the ROM forks joined with commas (empty for none), IMS stack
    id, IMS stack fork (or empty), the carrier text and the target text.
    The build incremental and the stack version are not part of it."""
    lines = [
        record["kind"], record["device"]["codename"], record["device"]["model"].upper(),
        record["rom"]["family"], record["rom"]["line"], ",".join(record["rom"]["forks"]), record["ims_stack"]["id"],
        record["ims_stack"]["fork"] or "", record_carrier_text(record["carrier"]), record_target_text(record["target"]),
    ]
    return "r:" + sha256_hex("\n".join(lines).encode("utf-8"))[:16]


def cell_record_problems(record: Any, registry: dict[str, dict[str, Any]], where: str) -> list[str]:
    """What a schema cannot say about one cell record (round 31): its cell
    and key, the carrier key, the kind, the ROM forks and incremental, the
    group rules, the value against the registry and the privacy scan."""
    if not isinstance(record, dict) or set(record) != CELL_RECORD_MEMBERS:
        return [f"{where}: a cell record holds exactly {', '.join(sorted(CELL_RECORD_MEMBERS))}"]
    carrier = record.get("carrier")
    if not isinstance(carrier, dict) or carrier.get("scope") not in CARRIER_SCOPES:
        return [f"{where}: a cell record names its carrier, a profile or a SIM key (record_no_carrier)"]
    if carrier["scope"] == "sim_key" and ("gid1" in carrier) == ("spn" in carrier):
        return [f"{where}: a SIM key names exactly one of gid1 and spn"]
    if record["kind"] != "measured" or record["claim"] != "measured":
        return [f"{where}: a cell record is of kind measured and claims measured (record_kind)"]
    rom = record["rom"]
    if not isinstance(rom, dict) or set(rom) != {"family", "line", "forks", "incremental"}:
        return [f"{where}: rom holds exactly family, line, forks and incremental"]
    out: list[str] = []
    if rom["family"] not in ROM_FAMILIES:
        out.append(f"{where}: rom.family is one of {', '.join(ROM_FAMILIES)}")
    forks = rom["forks"]
    if not isinstance(forks, list) or not all(isinstance(f, str) and FORK_RE.fullmatch(f) for f in forks) or forks != sorted(set(forks)):
        out.append(f"{where}: rom.forks is a sorted list of distinct fork names")
    if not isinstance(rom["incremental"], str) or not INCREMENTAL_RE.fullmatch(rom["incremental"]):
        out.append(f"{where}: rom.incremental is the build's Build.VERSION.INCREMENTAL")
    if out:
        return out
    if cell_record_key_of(record) != record["record_key"]:
        return [f"{where}: record_key is not the hash of its cell lines (expected {cell_record_key_of(record)})"]
    if record["last_measured"] is None or record["first_measured"] is None:
        out.append(f"{where}: a cell record names the days it was measured")
    elif record["valid_until"] != (date.fromisoformat(record["last_measured"]) + timedelta(days=EXPIRE_DAYS)).isoformat():
        out.append(f"{where}: valid_until must be last_measured + {EXPIRE_DAYS} days")
    elif record["first_measured"] > record["last_measured"]:
        out.append(f"{where}: first_measured is after last_measured")
    target = record["target"]
    value_kind = record["value_kind"]
    if value_kind != "value" and record["value"] is not None:
        out.append(f"{where}: only value_kind value carries a value")
    if target["type"] == "config":
        key = target["key"]
        entry = registry.get(key)
        if entry is None:
            return out + [f"{where}: {key} is not in the key registry (unknown_key)"]
        if entry["fork"] is not None and record["ims_stack"]["fork"] != entry["fork"]:
            out.append(f"{where}: {key} exists only in the {entry['fork']} fork; ims_stack.fork must name it")
        if key in GROUP_B_KEYS:
            out.append(f"{where}: {key} is group B, whose records could never be served (record_group_b)")
        if entry["group"] == "A" or key in GROUP_A_NAMES:
            out.append(f"{where}: {key} is group A; group A values enter only as carrier values with a read (record_group_a)")
        if value_kind == "value":
            problem = value_problem(record["value"], entry["type"], f"{where}.value") or domain_problem(key, record["value"], f"{where}.value")
            if problem:
                out.append(problem)
        elif value_kind == "none" and record["result"] != "no_value_passed":
            out.append(f"{where}: a config record without a value is a no_value_passed result")
    else:
        if value_kind != "none":
            out.append(f"{where}: an APN or emergency data record holds no value (value_kind none)")
        if target["type"] == "emergency_data" and record["result"] not in EMERGENCY_RESULTS:
            out.append(f"{where}: an emergency data record has an emergency data result")
        if target["type"] == "apn" and record["result"] == "emergency_default_won":
            out.append(f"{where}: Android's default winning is an emergency_data record")
    if record["result"] in EMERGENCY_RESULTS and (target["type"] != "emergency_data" or record["level"] != "emergency_data"):
        out.append(f"{where}: an emergency data result belongs to an emergency_data target at level emergency_data")
    for text in strings_of({k: record[k] for k in ("basis", "label") if record[k] is not None}):
        for name, pattern in BLOCK_PATTERNS.items():
            if pattern.search(text):
                out.append(f"{where}: basis or label looks like private data ({name})")
    return out


def any_record_problems(record: Any, registry: dict[str, dict[str, Any]], reads: dict[str, dict[str, Any]], where: str) -> list[str]:
    """A round 30 record or a round 31 cell record, each by its own rules."""
    if is_cell_record(record):
        return cell_record_problems(record, registry, where)
    return record_problems(record, registry, reads, where)


def served_records(records: list[dict[str, Any]], version: int | None = None) -> list[dict[str, Any]]:
    """The records device-records.json carries in schema_version VERSION
    (SERVED_RECORDS_SCHEMA_VERSION by default): round 30 records in 1, cell
    records in 2. A cell record waits for 2; a round 30 record does not
    carry over into 2, because its cell lacks the ROM forks and incremental."""
    version = SERVED_RECORDS_SCHEMA_VERSION if version is None else version
    return [r for r in records if is_cell_record(r) == (version == CELL_RECORDS_SCHEMA_VERSION)]


def read_record_sources(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """(records, declared keys, reads) from devices/records/: every
    configured/*.json, measured.json (written by the report bot), keys.json
    (the registry entries of keys only records use) and reads/*.json (the
    second-agent reads group A records need)."""
    base = root / RECORDS_DIR
    records: list[dict[str, Any]] = []
    for path in sorted((base / "configured").glob("*.json")) if (base / "configured").is_dir() else []:
        document = read_json_file(path)
        if set(document) != {"schema_version", "description", "records"} or document["schema_version"] != 1:
            raise DatasetError(f"{path}: must hold exactly schema_version 1, description and records")
        records.extend(document["records"])
    measured = base / "measured.json"
    if measured.is_file():
        document = read_json_file(measured)
        if set(document) != {"schema_version", "description", "as_of", "records"} or document["schema_version"] != 1:
            raise DatasetError(f"{measured}: must hold exactly schema_version 1, description, as_of and records")
        for item in document["records"]:
            # Rule round 45, item 1: an item may carry the canonical match-set
            # hash its record was made under (measured_match_set_hashes).
            if not isinstance(item, dict) or set(item) - {"match_set_hash"} != {"issue", "record"}:
                raise DatasetError(f"{measured}: each item must hold exactly issue and record, and may hold match_set_hash")
            records.append(item["record"])
    keys: dict[str, dict[str, Any]] = {}
    if (base / "keys.json").is_file():
        document = read_json_file(base / "keys.json")
        if set(document) != {"schema_version", "description", "keys"} or document["schema_version"] != 1:
            raise DatasetError(f"{base / 'keys.json'}: must hold exactly schema_version 1, description and keys")
        keys = document["keys"]
    reads: dict[str, dict[str, Any]] = {}
    for folder in (base / "reads", base / "reads" / "group-a"):
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            reads[path.relative_to(root).as_posix()] = read_json_file(path)
    return records, keys, reads


def current_match_set_hashes(root: Path, lookup: dict[str, Any]) -> dict[str, str] | None:
    """Rule round 45, item 1: profile ID -> the canonical match-set hash of
    its current match set (tools/profile_ids.py), for every profile in
    lookup.json. None for a tree from before frozen IDs, where every ID is
    still that hash and no record can lapse."""
    path = root / "tools/profile_ids.py"
    if not path.is_file():
        return None
    ids = load_module("profile_ids", path)
    return {entry["profile_id"]: ids.match_set_hash(entry["match"]) for entry in lookup["profiles"]}


def made_under(stored: Any, profile_id: str) -> str | None:
    """The match-set hash a record keyed by PROFILE_ID was made under: the one
    it stores, else (made before the freeze) its open ID's hash part; None for
    a fill-only profile, whose ID changes with its rule."""
    if isinstance(stored, str) and re.fullmatch(r"[0-9a-f]{12}", stored):
        return stored
    found = re.fullmatch(r"open\.[0-9]{5,6}\.([0-9a-f]{12})", profile_id)
    return found.group(1) if found else None


def under_current_match_set(profile_id: str, stored: Any, current: dict[str, str] | None) -> bool:
    """Whether a record keyed by PROFILE_ID may serve as a value: only while
    its profile's current match-set hash is the one the record was made
    under. A record that lapses never serves; a group A read needs a new
    read, and a measured or cell record is only the first candidate for the
    next test (round 31)."""
    if current is None:
        return True
    made = made_under(stored, profile_id)
    return made is None or current.get(profile_id) == made


def measured_match_set_hashes(root: Path) -> dict[str, str]:
    """record_key -> match_set_hash of the measured.json items that carry one."""
    path = root / MEASURED_FILE
    if not path.is_file():
        return {}
    document = read_json_file(path)
    return {item["record"]["record_key"]: item["match_set_hash"]
            for item in document.get("records", []) if isinstance(item, dict) and "match_set_hash" in item}


def record_serves(record: dict[str, Any], stored: dict[str, str], current: dict[str, str] | None) -> bool:
    carrier = record.get("carrier") or {}
    if carrier.get("scope") != "profile":
        return True
    return under_current_match_set(carrier["profile_id"], stored.get(record["record_key"]), current)


def read_problems(read: dict[str, Any], where: str) -> list[str]:
    required = {"schema", "record_key", "key", "value", "reader", "read_at", "sources_read", "findings", "verdict", "notes"}
    if not isinstance(read, dict) or set(read) != required:
        return [f"{where}: a read record holds exactly {', '.join(sorted(required))}"]
    out = []
    if read["schema"] != READ_SCHEMA:
        out.append(f"{where}: schema must be {READ_SCHEMA}")
    if not isinstance(read["record_key"], str) or not RECORD_KEY_RE.fullmatch(read["record_key"]):
        out.append(f"{where}: record_key must be r:<16 hex>")
    if read["verdict"] not in ("proceed", "hold"):
        out.append(f"{where}: verdict must be proceed or hold")
    if not isinstance(read["reader"], str) or not read["reader"].strip():
        out.append(f"{where}: reader must name the reading agent")
    if not isinstance(read["read_at"], str) or not GENERATED_AT_RE.fullmatch(read["read_at"]):
        out.append(f"{where}: read_at must be an ISO 8601 UTC time with seconds")
    return out


def record_problems(
    record: Any,
    registry: dict[str, dict[str, Any]],
    reads: dict[str, dict[str, Any]],
    where: str,
) -> list[str]:
    """What a schema cannot say about one record: its key, its claim class,
    its value against the registry, the group rules and the privacy scan."""
    out: list[str] = []
    if record_key_of(record) != record["record_key"]:
        return [f"{where}: record_key is not the hash of its identity lines (expected {record_key_of(record)})"]
    kind = record["kind"]
    if record["carrier"]["scope"] not in CARRIER_SCOPES and record["record_key"] not in LEGACY_DEVICE_ONLY_RECORDS:
        return [f"{where}: a record names its carrier, a profile or a SIM key (round 31: no record is keyed by device alone; record_no_carrier)"]
    if kind != "measured" and record["record_key"] not in LEGACY_DEVICE_ONLY_RECORDS:
        return [f"{where}: the record kind is measured only (round 31: configured_device ends; record_kind)"]
    if kind == "configured_device":
        if record["claim"] != "configured" or record["valid_until"] is not None:
            out.append(f"{where}: a configured_device record claims configured and has no valid_until")
    else:
        if record["claim"] != "measured":
            out.append(f"{where}: a measured record claims measured")
        if record["last_measured"] is None or record["valid_until"] != (date.fromisoformat(record["last_measured"]) + timedelta(days=EXPIRE_DAYS)).isoformat():
            out.append(f"{where}: valid_until must be last_measured + {EXPIRE_DAYS} days")
    first, last = record["first_measured"], record["last_measured"]
    if first is not None and last is not None and first > last:
        out.append(f"{where}: first_measured is after last_measured")
    target = record["target"]
    value_kind = record["value_kind"]
    if value_kind != "value" and record["value"] is not None:
        out.append(f"{where}: only value_kind value carries a value")
    if target["type"] == "config":
        key = target["key"]
        entry = registry.get(key)
        if entry is None:
            out.append(f"{where}: {key} is not in the key registry (unknown_key)")
            return out
        if entry["fork"] is not None and record["ims_stack"]["fork"] != entry["fork"]:
            out.append(f"{where}: {key} exists only in the {entry['fork']} fork; ims_stack.fork must name it")
        if key in GROUP_B_KEYS:
            out.append(f"{where}: {key} is group B, whose records could never be served (record_group_b)")
        if value_kind == "value":
            problem = value_problem(record["value"], entry["type"], f"{where}.value") or domain_problem(key, record["value"], f"{where}.value")
            if problem:
                out.append(problem)
        elif value_kind == "none" and record["result"] != "no_value_passed":
            out.append(f"{where}: a config record without a value is a no_value_passed result")
        group_a = entry["group"] == "A" or bool(GROUP_A_RE.search(key))
        read = record["second_agent_read"]
        if read is not None:
            if not group_a:
                out.append(f"{where}: only a group A record carries a second_agent_read")
            target_read = reads.get(read["reference"])
            if target_read is None:
                out.append(f"{where}: second_agent_read.reference names no read record under {READS_DIR}/")
            elif target_read.get("verdict") != "proceed" or target_read.get("record_key") != record["record_key"] \
                    or target_read.get("key") != key or compact(target_read.get("value")) != compact(record["value"]) \
                    or target_read.get("reader") != read["reader"] or target_read.get("read_at") != read["read_at"]:
                out.append(f"{where}: second_agent_read must point at a read of this record, key and value with verdict proceed")
        if group_a and kind == "measured":
            out.append(f"{where}: a measured record for a group A key enters only through a second-agent read (record_group_a)")
    else:
        if value_kind != "none":
            out.append(f"{where}: an APN or emergency data record holds no value (value_kind none)")
        if record["second_agent_read"] is not None:
            out.append(f"{where}: only a group A config record carries a second_agent_read")
        if target["type"] == "emergency_data" and record["result"] not in EMERGENCY_RESULTS:
            out.append(f"{where}: an emergency data record has an emergency data result")
        if target["type"] == "apn" and record["result"] == "emergency_default_won":
            out.append(f"{where}: Android's default winning is an emergency_data record")
    if record["result"] in EMERGENCY_RESULTS and (target["type"] != "emergency_data" or record["level"] != "emergency_data"):
        out.append(f"{where}: an emergency data result belongs to an emergency_data target at level emergency_data")
    for text in strings_of({k: record[k] for k in ("basis", "label") if record[k] is not None}):
        for name, pattern in BLOCK_PATTERNS.items():
            if pattern.search(text):
                out.append(f"{where}: basis or label looks like private data ({name})")
    return out


# ---------------------------------------------------------------- registry and groups


def group_of(key: str, left_group_a: frozenset[str] | set[str] = frozenset()) -> str | None:
    if key in GROUP_B_KEYS:
        return "B"
    if key in X6_KEYS:
        return "X6"
    if (GROUP_A_RE.search(key) or key in GROUP_A_NAMES) and key not in left_group_a:
        return "A"
    return None


def left_group_a_keys(reads: dict[str, dict[str, Any]]) -> set[str]:
    """The keys a key read with verdict proceed found display_only (round
    31): they leave group A, except GROUP_A_NEVER_LEAVE."""
    return {r["key"] for r in reads.values() if isinstance(r, dict) and r.get("schema") == GROUP_A_READ_SCHEMA
            and r.get("subject") == "key" and r.get("verdict") == "proceed" and r.get("effect") == "display_only"
            and r.get("key") not in GROUP_A_NEVER_LEAVE}


def lane_value_types(lane: dict[str, Any] | None, registry_file: dict[str, Any] | None) -> dict[str, str]:
    """The registry types of the Google lane's keys. google-lane.json carries
    plain values, so a key's type comes from the registry the private
    publisher wrote with the lane (Google's Config field names it)."""
    if lane is None:
        return {}
    known = (registry_file or {}).get("keys", {})
    out = {}
    for name, entry in lane["entries"].items():
        for key in entry["values"]:
            if key not in known or "google" not in known[key].get("origin", []):
                raise DatasetError(f"{REGISTRY_PATH}: the Google-lane key {key} (entry {name}) has no registry type; the private publisher writes it with the lane")
            out[key] = known[key]["type"]
    return out


def build_registry(inputs: Inputs, records: list[dict[str, Any]], declared: dict[str, dict[str, Any]],
                   left_group_a: set[str] | frozenset[str] = frozenset()) -> dict[str, dict[str, Any]]:
    """The closed key list (spec 2.5.1): the public schema's keys, every key
    of the Google lane, and the keys of the device records, each with its
    type, group, origin and fork."""
    lane_types = lane_value_types(inputs.lane, inputs.registry_file)
    record_keys = {r["target"]["key"] for r in records if r.get("target", {}).get("type") == "config"}
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(set(inputs.schema_keys) | set(lane_types) | record_keys | set(declared)):
        origins = []
        types = set()
        if key in inputs.schema_keys:
            origins.append("ocd_schema")
            types.add(inputs.schema_keys[key])
        if key in lane_types:
            origins.append("google")
            types.add(lane_types[key])
        fork = None
        if key in record_keys or key in declared:
            origins.append("device_record")
            if key in declared:
                types.add(declared[key]["type"])
                fork = declared[key]["fork"]
        if key in record_keys and not types:
            raise DatasetError(f"{KEYS_FILE}: the record key {key} is in neither the schema nor the Google lane; declare its type there")
        if len(types) != 1:
            raise DatasetError(f"the key {key} has conflicting types {sorted(types)} (schema, Google lane, {KEYS_FILE})")
        out[key] = {"type": types.pop(), "group": group_of(key, left_group_a), "origin": sorted(origins), "fork": fork}
    return out


# ---------------------------------------------------------------- group A reads (round 31, emergencyValues)


def google_variants(profile: dict[str, Any], entries: dict[str, Any]) -> list[dict[str, Any]]:
    """The Google-lane bundles (steps 2 and 3) a SIM that PROFILE serves on
    this network copy can get: `default` with each fill entry in order, and
    `default` alone when no fill item may hold. A fill entry the lane lacks
    is skipped, as the reader does."""
    default = entries.get("default", {}).get("values", {})
    out = []
    for item in profile["fill"]:
        entry = entries.get(item["entry"])
        if entry is None:
            continue
        out.append({**default, **entry["values"]})
        if item["when"] is None:
            return out
    out.append(dict(default))
    return out


def group_a_keys(profiles: dict[str, Any]) -> set[str]:
    """Group A as CarrierSettings takes it: the dataset's marking, the
    pattern over the registry and the named keys (spec 5.1)."""
    groups = profiles["groups"]["A"]
    return set(groups["keys"]) | set(groups["names"]) | {k for k, meta in profiles["keys"].items() if GROUP_A_RE.search(k) and meta["group"] == "A"}


def group_a_candidates(profiles: dict[str, Any], lane: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every group A value that differs from the Google lane (round 31,
    emergencyValues): per key and value, the profiles whose own values hold
    it and the source families behind it. A value differs when the step-4
    overlay of a profile's stack serves it and some Google bundle that
    profile's SIMs can get holds another value or none."""
    entries = (lane or {}).get("entries", {})
    keys = group_a_keys(profiles)
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for network in profiles["networks"].values():
        items = network["profiles"]
        for profile in items:
            stack = profile_stack(items, profile)
            served: dict[str, tuple[Any, dict[str, Any]]] = {}
            for q in stack:
                for key, value in q["values"].items():
                    if key in keys:
                        served[key] = (value, q)
            if not served:
                continue
            variants = google_variants(profile, entries)
            for key, (value, carrier) in served.items():
                text = compact(value)
                if all(key in bundle and compact(bundle[key]) == text for bundle in variants):
                    continue
                slot = found.setdefault((key, text), {"key": key, "value": value, "profiles": {}})
                slot["profiles"][carrier["id"]] = sorted(carrier["sources"].get(key, []))
    out = []
    for (key, text), slot in sorted(found.items()):
        families = sorted({f for fams in slot["profiles"].values() for f in fams})
        out.append({"key": key, "value": slot["value"], "families": families,
                    "profiles": {p: slot["profiles"][p] for p in sorted(slot["profiles"])}})
    return out


def group_a_read_problems(read: Any, where: str) -> list[str]:
    """A round 31 group A read (ocd-group-a-read/2), beyond its schema."""
    required = {"schema", "subject", "key", "value", "families", "profiles", "rom_family", "ims_stack", "effect",
                "reader", "builder", "read_at", "sources_read", "findings", "verdict", "notes"}
    if not isinstance(read, dict) or set(read) - {"match_set_hashes"} != required:
        return [f"{where}: a group A read holds exactly {', '.join(sorted(required))}, and may hold match_set_hashes"]
    out = []
    # Rule round 45, item 1: the canonical match-set hash of each open
    # profile the read covers, as it was when read; a read made after the
    # freeze names one for every open profile it lists.
    hashes = read.get("match_set_hashes")
    if hashes is not None and (not isinstance(hashes, dict) or not all(
            isinstance(k, str) and k in (read.get("profiles") or []) and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{12}", v)
            for k, v in hashes.items())):
        out.append(f"{where}: match_set_hashes maps profiles the read lists to 12 hex digits")
    elif isinstance(read.get("read_at"), str) and read["read_at"][:10] > ID_FREEZE_DATE and read.get("subject") == "value":
        named = set(hashes or {})
        unnamed = [p for p in read.get("profiles") or [] if isinstance(p, str) and OCD_ID_RE.fullmatch(p) and p not in named]
        if unnamed:
            out.append(f"{where}: a read made after {ID_FREEZE_DATE} names the match-set hash of every open profile it lists (match_set_hashes)")
    if read["subject"] not in ("value", "key"):
        out.append(f"{where}: subject is value or key")
    if read["effect"] not in GROUP_A_EFFECTS:
        out.append(f"{where}: effect is one of {', '.join(GROUP_A_EFFECTS)}")
    if read["verdict"] not in ("proceed", "hold"):
        out.append(f"{where}: verdict must be proceed or hold")
    if read["rom_family"] not in ROM_FAMILIES or read["ims_stack"] not in IMS_STACK_IDS:
        out.append(f"{where}: rom_family and ims_stack name a ROM family and an IMS stack of the cell schema")
    for name in ("reader", "builder"):
        if not isinstance(read[name], str) or not read[name].strip():
            out.append(f"{where}: {name} must be named")
    if isinstance(read["reader"], str) and isinstance(read["builder"], str) and read["reader"].strip().casefold() == read["builder"].strip().casefold():
        out.append(f"{where}: the reader must not be the value's builder")
    if not isinstance(read["read_at"], str) or not GENERATED_AT_RE.fullmatch(read["read_at"]):
        out.append(f"{where}: read_at must be an ISO 8601 UTC time with seconds")
    if not isinstance(read["sources_read"], list) or not read["sources_read"] or not all(isinstance(s, str) and s for s in read["sources_read"]):
        out.append(f"{where}: sources_read lists the sources the reader read")
    if not isinstance(read["findings"], dict) or set(read["findings"]) != {"effect", "basis", "risk"} \
            or not all(isinstance(v, str) and v.strip() for v in read["findings"].values()):
        out.append(f"{where}: findings hold exactly effect, basis and risk, each a sentence")
    if read["subject"] == "value":
        if not isinstance(read["profiles"], list) or not read["profiles"] or not all(isinstance(p, str) and (OCD_ID_RE.fullmatch(p) or FILL_ID_RE.fullmatch(p)) for p in read["profiles"]):
            out.append(f"{where}: a value read lists the profiles whose value it read")
        if not isinstance(read["families"], list) or not all(isinstance(f, str) and f for f in read["families"]):
            out.append(f"{where}: families lists the value's source families")
    else:
        if read["value"] is not None or read["families"] != [] or read["profiles"] != []:
            out.append(f"{where}: a key read holds no value, families or profiles")
        if read["verdict"] == "proceed" and read["effect"] != "display_only":
            out.append(f"{where}: a key read proceeds only on a display_only finding (the key leaves group A)")
    if not isinstance(read["notes"], str) or not read["notes"].strip():
        out.append(f"{where}: notes say what the read found")
    for text in strings_of({k: read[k] for k in ("findings", "notes")}):
        for name, pattern in BLOCK_PATTERNS.items():
            if name in ("email", "long_decimal_identity", "international_phone", "secret_word") and pattern.search(text):
                out.append(f"{where}: findings or notes look like private data ({name})")
    return out


def group_a_read_id(reference: str, profile_id: str, family: str) -> str:
    """gar: and the first 16 hex digits of SHA-256 over the read record's
    path, the profile and the source family, joined with \\n."""
    return "gar:" + sha256_hex(f"{reference}\n{profile_id}\n{family}".encode("utf-8"))[:16]


def group_a_documents(inputs_digest: str, profiles: dict[str, Any], lane: dict[str, Any] | None,
                      reads: dict[str, dict[str, Any]],
                      current: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(group-a-reads.json, group-a-pending.json) from the round 31 group A
    reads on main (devices/records/reads/group-a/).

    group-a-reads.json is the S20 spec's R31.7 file, as OcdCarrierSettings
    reads it: one item per read, profile and source family (a read admits
    the value of `profile_id` only when the profile's sources for the key
    name `family`), and the display_only key findings. A profile whose value
    has no recorded source family gets no item: no read can admit it, and
    its SIMs keep the Google-lane value.

    group-a-pending.json is the status beside it: every candidate (a group A
    value that differs from the Google lane) no read covers yet, the values
    a read covered whose basis is not recorded, every key read, and the keys
    that left group A."""
    registry = profiles["keys"]
    value_reads, key_reads = [], []
    for path, read in sorted(reads.items()):
        if read.get("schema") != GROUP_A_READ_SCHEMA:
            continue
        if read["subject"] == "value":
            meta = registry.get(read["key"])
            if meta is None:
                continue  # a key the registry no longer has is never served; its read is moot
            problem = value_problem(read["value"], meta["type"], f"{path}: value")
            if problem:
                raise DatasetError(problem)
            value_reads.append((path, read))
        else:
            key_reads.append((path, read))
    left = sorted(left_group_a_keys(dict(key_reads)))
    candidates = group_a_candidates(profiles, lane)
    by_value = {(c["key"], compact(c["value"])): c for c in candidates}
    # Rule round 45, item 1: a read covers a profile only while the profile's
    # match set is the one it was read under (CURRENT, from
    # current_match_set_hashes); otherwise it lapses and the value waits for
    # a new read in group-a-pending.json.
    def covers(read: dict[str, Any], profile_id: str) -> bool:
        return profile_id in read["profiles"] and under_current_match_set(
            profile_id, (read.get("match_set_hashes") or {}).get(profile_id), current)

    items, unrecorded = [], []
    for path, read in value_reads:
        candidate = by_value.get((read["key"], compact(read["value"])), {"profiles": {}})
        for profile_id in sorted(read["profiles"]):
            families = candidate["profiles"].get(profile_id)
            if families is None:
                continue  # the profile no longer carries this value
            if not covers(read, profile_id):
                continue  # read under another match set: lapsed
            covered = [f for f in families if f in read["families"]]
            if not families:
                unrecorded.append({"key": read["key"], "value": read["value"], "profile_id": profile_id, "reference": path})
            for family in covered:
                items.append({
                    "read_id": group_a_read_id(path, profile_id, family), "key": read["key"], "value": read["value"],
                    "family": family, "profile_id": profile_id, "rom_family": read["rom_family"], "ims_stack": read["ims_stack"],
                    "ims_stack_fork": None, "verdict": read["verdict"], "reader": read["reader"], "read_at": read["read_at"], "reference": path,
                })
    findings = [{"key": read["key"], "finding": "display_only", "verdict": read["verdict"], "reader": read["reader"],
                 "read_at": read["read_at"], "reference": path}
                for path, read in key_reads if read["effect"] == "display_only"]
    pending = []
    for candidate in candidates:
        if candidate["key"] in left:
            continue
        for target in GROUP_A_READ_TARGETS:
            covering = [r for _, r in value_reads if r["key"] == candidate["key"] and compact(r["value"]) == compact(candidate["value"])
                        and (r["rom_family"], r["ims_stack"]) == target]
            waiting = {p: fams for p, fams in candidate["profiles"].items()
                       if not any(covers(r, p) and set(fams) <= set(r["families"]) for r in covering)}
            if waiting:
                pending.append({"key": candidate["key"], "value": candidate["value"], "rom_family": target[0], "ims_stack": target[1],
                                "families": sorted({f for fams in waiting.values() for f in fams}), "profiles": sorted(waiting)})
    reads_document = {
        "schema_version": SCHEMA_VERSION,
        "based_on_data_digest": inputs_digest,
        "reads": sorted(items, key=lambda r: (r["key"], compact(r["value"]), r["profile_id"], r["family"], r["read_id"])),
        "key_findings": sorted(findings, key=lambda f: (f["key"], f["reference"])),
    }
    pending_document = {
        "schema_version": SCHEMA_VERSION,
        "based_on_data_digest": inputs_digest,
        "targets": [{"rom_family": f, "ims_stack": st} for f, st in GROUP_A_READ_TARGETS],
        "pending": pending,
        "unrecorded_basis": sorted(unrecorded, key=lambda u: (u["key"], compact(u["value"]), u["profile_id"])),
        "key_reads": sorted(({"key": r["key"], "effect": r["effect"], "verdict": r["verdict"], "reference": path} for path, r in key_reads),
                            key=lambda k: (k["key"], k["reference"])),
        "left_group_a": left,
    }
    return reads_document, pending_document


def withheld_document_of(root: Path, lane: dict[str, Any], data_digest: str) -> bytes | None:
    """privacy-withheld.json as generate keeps it: the publisher's list,
    restamped with this data digest and narrowed to the entries the
    published Google lane carries (rule 3 can leave entries out after the
    publisher listed them). None when the publisher wrote no list."""
    path = root / WITHHELD_FILE
    if not path.is_file():
        return None
    document = read_json_file(path)
    items = sorted((i for i in document.get("withheld", []) if i.get("entry") in lane["entries"]), key=lambda i: (i["entry"], i["key"]))
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item["key"]] += 1
    return dump_lines({**document, "based_on_data_digest": data_digest, "withheld": items, "by_key": dict(sorted(counts.items()))}, ("withheld",))


def withheld_problems(root: Path, lane: dict[str, Any] | None, data_digest: str | None) -> list[str]:
    """privacy-withheld.json (SM4), when the publisher wrote one: its shape,
    its data digest, and that every value it names is absent from the
    Google lane's entry, so the list says exactly which keys a SIM of that
    entry takes from Google's default or from Android's default instead."""
    path = root / WITHHELD_FILE
    if not path.is_file():
        return []
    document = read_json_file(path)
    out = schema_check(root, document, "ocd-dataset-privacy-withheld.schema.json", WITHHELD_FILE)
    if out:
        return out
    if document["based_on_data_digest"] != data_digest:
        out.append(f"{WITHHELD_FILE}: based_on_data_digest is not metadata.json's")
    if lane is None:
        return out + [f"{WITHHELD_FILE}: there is no Google lane to withhold values from"]
    seen = set()
    for item in document["withheld"]:
        pair = (item["entry"], item["key"])
        if pair in seen:
            out.append(f"{WITHHELD_FILE}: {item['entry']} {item['key']} is listed twice")
        seen.add(pair)
        entry = lane["entries"].get(item["entry"])
        if entry is None:
            out.append(f"{WITHHELD_FILE}: {item['entry']} is not an entry of the Google lane")
        elif item["key"] in entry["values"]:
            out.append(f"{WITHHELD_FILE}: {item['entry']} {item['key']} is listed as withheld but the lane carries it")
    if [(i["entry"], i["key"]) for i in document["withheld"]] != sorted(seen):
        out.append(f"{WITHHELD_FILE}: withheld is not sorted by entry and key")
    counts: dict[str, int] = defaultdict(int)
    for item in document["withheld"]:
        counts[item["key"]] += 1
    if document["by_key"] != dict(sorted(counts.items())):
        out.append(f"{WITHHELD_FILE}: by_key does not count withheld")
    return out


def build_groups(registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "A": {"pattern": GROUP_A_PATTERN, "names": list(GROUP_A_NAMES), "keys": sorted(k for k, v in registry.items() if v["group"] == "A")},
        "B": {"keys": list(GROUP_B_KEYS), "must_contain": GROUP_B_MUST_CONTAIN},
        "X6": {"keys": list(X6_KEYS), "networks": list(X6_NETWORKS)},
    }


# ---------------------------------------------------------------- APN index (spec 2.9)

XML_APN_LINE = re.compile(r'^  <apn((?: [A-Za-z_][A-Za-z0-9_]*="[^"<>]*")*) />$')
XML_ATTRIBUTE = re.compile(r' ([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')
XML_UNESCAPE = (("&quot;", '"'), ("&#9;", "\t"), ("&#10;", "\n"), ("&#13;", "\r"), ("&lt;", "<"), ("&gt;", ">"), ("&apos;", "'"), ("&amp;", "&"))


def xml_unescape(text: str) -> str:
    out = []
    index = 0
    while index < len(text):
        if text[index] == "&":
            for entity, char in XML_UNESCAPE:
                if text.startswith(entity, index):
                    out.append(char)
                    index += len(entity)
                    break
            else:
                raise DatasetError(f"apns-conf.xml: an attribute holds an unknown entity near {text[index:index + 12]!r}")
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def parse_apn_rows(xml: bytes) -> tuple[int, list[tuple[int, dict[str, str]]]]:
    """(version, [(line, attributes)]) of apns-conf.xml under the three
    invariants of spec 2.9: root <apns version="N">, no DOCTYPE or entity,
    the data_digest header line, every <apn .../> alone on its line and no
    other element."""
    try:
        text = xml.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DatasetError(f"apns-conf.xml: not UTF-8 ({error})") from error
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise DatasetError("apns-conf.xml: holds a DOCTYPE or an entity declaration")
    if apns_header_digest(xml) is None:
        raise DatasetError("apns-conf.xml: the header comment has no data_digest line")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    version = None
    rows: list[tuple[int, dict[str, str]]] = []
    in_comment = False
    closed = False
    for number, line in enumerate(lines, start=1):
        if closed:
            raise DatasetError(f"apns-conf.xml: line {number} follows </apns>")
        if in_comment:
            if "-->" in line:
                if line.strip() != "-->":
                    raise DatasetError(f"apns-conf.xml: line {number}: the header comment must close on a line of its own")
                in_comment = False
            continue
        if number == 1 and line == '<?xml version="1.0" encoding="utf-8"?>':
            continue
        if line == "<!--" and version is None:
            in_comment = True
            continue
        if version is None:
            match = re.fullmatch(r'<apns version="([0-9]{1,3})">', line)
            if not match:
                raise DatasetError(f"apns-conf.xml: line {number}: the root must be <apns version=\"N\">")
            version = int(match.group(1))
            continue
        if line == "</apns>":
            closed = True
            continue
        match = XML_APN_LINE.match(line)
        if not match:
            raise DatasetError(f"apns-conf.xml: line {number} is not one <apn .../> element alone on its line")
        attributes: dict[str, str] = {}
        for name, value in XML_ATTRIBUTE.findall(match.group(1)):
            if name in attributes:
                raise DatasetError(f"apns-conf.xml: line {number} repeats the attribute {name}")
            attributes[name] = xml_unescape(value)
        rows.append((number, attributes))
    if version is None or not closed:
        raise DatasetError("apns-conf.xml: no complete <apns> root")
    return version, rows


def row_key_of(attributes: dict[str, str]) -> str:
    text = "\n".join(f"{name}={attributes[name]}" for name in sorted(attributes))
    return "a:" + sha256_hex(text.encode("utf-8"))[:16]


def attribute_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def row_projection(attributes: dict[str, str], defaults: dict[str, Any]) -> str:
    """What TelephonyProvider stores for a row except its label and types,
    as the written attribute texts with the column defaults dropped: rows of
    several profiles that the generator wrote as one element share it."""
    kept = {
        name: text for name, text in attributes.items()
        if name not in ("carrier", "type") and not (name in defaults and attribute_text(defaults[name]) == text)
    }
    return compact(kept)


def build_apn_index(inputs: Inputs, generator: Any, lineage: Any, profiles: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    """Every row of apns-conf.xml in file order with its line, row key and the
    profiles the generator wrote it for: each profile's own rows, made by the
    generator's apn_records and kept by its schema filter, are projected the
    way the generator merges rows, and each written row takes the profiles
    whose projections it carries."""
    defaults = generator.ANDROID_APN_DEFAULTS
    by_projection: dict[str, set[str]] = defaultdict(set)
    for lookup_entry, carrier in profiles:
        for record in generator.apn_records(carrier, None):
            for name, value in generator.SCHEMA_OMITTED_DEFAULTS.items():
                if record.get(name) == value:
                    del record[name]
            if not lineage.fits_lineageos_schema(record):
                continue
            written = {name: attribute_text(value) for name, value in generator.written_attributes(record).items()}
            by_projection[row_projection(written, defaults)].add(lookup_entry["profile_id"])
    version, rows = parse_apn_rows(inputs.apn_xml)
    out = []
    for ordinal, (line, attributes) in enumerate(rows):
        owners = by_projection.get(row_projection(attributes, defaults))
        if not owners:
            raise DatasetError(f"apns-conf.xml: line {line} matches no profile's rows")
        out.append({"ordinal": ordinal, "line": line, "row_key": row_key_of(attributes), "profiles": sorted(owners)})
    return {
        "schema_version": SCHEMA_VERSION,
        "based_on_data_digest": inputs.data_digest,
        "apn_xml_sha256": sha256_hex(inputs.apn_xml),
        "rows": out,
    }, version


# ---------------------------------------------------------------- profiles (spec 2.5, 2.6)


def lookup_match(match: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"mccmnc": [{"mcc": code[:3], "mnc": code[3:]} for code in match["mccmnc"]]}
    for dimension in DIMENSIONS:
        if match.get(dimension):
            out[dimension] = list(match[dimension])
    return out


def evidence_sources(evidence: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for profile in evidence.get("profiles", []):
        keys = {}
        for fact in profile.get("fact_sources", []):
            if fact.get("section") == "android_carrier_config":
                keys[fact["key"]] = sorted({SOURCE_FAMILY_NAMES.get(s, s) for s in fact.get("sources", [])})
        out[profile["profile_id"]] = keys
    return out


def lane_rules_by_network(lane: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in (lane or {}).get("rules", []):
        out[f"{rule['mcc']}-{rule['mnc']}"].append(rule)
    return out


def build_profiles(
    inputs: Inputs, registry: dict[str, dict[str, Any]], apn_counts: dict[str, int], carriers: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, int]]:
    sources = evidence_sources(inputs.evidence)
    rules_by_network = lane_rules_by_network(inputs.lane)
    base: dict[str, dict[str, Any]] = {}
    ocd_by_network: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in inputs.lookup["profiles"]:
        profile_id = entry["profile_id"]
        carrier = carriers[profile_id]
        values = dict(carrier.get("android_carrier_config") or {})
        for key, value in values.items():
            meta = registry.get(key)
            if meta is None:
                raise DatasetError(f"{entry['path']}: {key} is not in the key registry (unknown_key)")
            problem = value_problem(value, meta["type"], f"{entry['path']}: {key}") or domain_problem(key, value, f"{entry['path']}: {key}")
            if problem:
                raise DatasetError(problem)
        match = lookup_match(entry["match"])
        own_sources = sources.get(profile_id, {})
        profile = {
            "id": profile_id,
            "kind": "ocd",
            "name": entry["display_name"],
            "match": match,
            "specificity": specificity_of(match),
            "values": values,
            # The evidence index names the families behind a value only where
            # observations give exactly that value; a value without such an
            # entry has no sources listed here.
            "sources": {key: own_sources[key] for key in sorted(values) if own_sources.get(key)},
            "alternatives": {},
            "apn_rows": apn_counts.get(profile_id, 0),
        }
        base[profile_id] = profile
        for network in match["mccmnc"]:
            ocd_by_network[f"{network['mcc']}-{network['mnc']}"].append(profile)
    fill_only: dict[str, dict[str, Any]] = {}
    kinds = {"imsi": 0, "network": 0, "spn": 0, "gid1": 0, "iccid": 0}
    for rule in (inputs.lane or {}).get("rules", []):
        if exact_profile_exists(rule, ocd_by_network):
            continue
        profile_id = fill_only_id(rule)
        match = rule_match(rule)
        # A later rule with the same match as an earlier fill-only one never
        # applies in Google's first-match order; it gets no profile of its own.
        if profile_id in fill_only or any(
            exact_profile_exists(rule, {f"{rule['mcc']}-{rule['mnc']}": [p]}) for p in fill_only.values()
        ):
            continue
        fill_only[profile_id] = {
            "id": profile_id,
            "kind": "fill_only",
            "name": rule["canonical_name"],
            "match": match,
            "specificity": specificity_of(match),
            "values": {},
            "sources": {},
            "alternatives": {},
            "apn_rows": 0,
        }
        kinds[rule["mvno"]["kind"] if rule["mvno"] else "network"] += 1
    networks: dict[str, dict[str, Any]] = {}
    everyone = list(base.values()) + list(fill_only.values())
    for profile in everyone:
        for network in profile["match"]["mccmnc"]:
            key = f"{network['mcc']}-{network['mnc']}"
            slot = networks.setdefault(key, {"mcc": network["mcc"], "mnc": network["mnc"], "profiles": []})
            copy = dict(profile)
            copy["fill"] = compute_fill(profile["match"], rules_by_network.get(key, []))
            slot["profiles"].append(copy)
    for slot in networks.values():
        slot["profiles"].sort(key=stack_order)
    document = {
        "schema_version": SCHEMA_VERSION,
        "based_on_data_digest": inputs.data_digest,
        "keys": registry,
        "groups": build_groups(registry),
        "reserved": {
            "default": {"fill": [{"entry": "default", "when": None}]},
            "no_sim": {"fill": [{"entry": "no_sim", "when": None}]},
        },
        "networks": dict(sorted(networks.items())),
    }
    counts = {"networks": len(networks), "profiles": len(everyone), "fill_only_profiles": len(fill_only), **{f"fill_only_{k}": v for k, v in kinds.items()}}
    return document, counts


# ---------------------------------------------------------------- generate


def lane_document(inputs: Inputs) -> dict[str, Any]:
    lane = dict(inputs.lane)
    lane["based_on_data_digest"] = inputs.data_digest
    return lane


def records_document(inputs: Inputs, records: list[dict[str, Any]], version: int | None = None) -> dict[str, Any]:
    version = SERVED_RECORDS_SCHEMA_VERSION if version is None else version
    return {
        "schema_version": version,
        "based_on_data_digest": inputs.data_digest,
        "expire_days": EXPIRE_DAYS,
        "records": sorted(records, key=lambda r: r["record_key"]),
    }


def registry_document(registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "description": (
            "OCD's closed CarrierConfig key list (rule round 30): the public schema's keys (origin ocd_schema), every "
            "key of the Google lane (google) and the keys of the per-device records (device_record), each with its "
            "type, its group (A: the emergency-call keys no test can decide; B: the metered lists; X6: the SMS-to-MMS "
            "keys of the MMS-ended networks) and the IMS stack fork it exists in. generated/ocd-dataset/profiles.json "
            "carries a copy as `keys`. Written by tools/ocd_dataset.py generate; Google-lane types come from the "
            "private publisher."
        ),
        "keys": registry,
    }


def manifest_document(
    data_digest: str, files: dict[str, bytes], generated_at: str, counts: dict[str, int]
) -> dict[str, Any]:
    entries = []
    for role in sorted(files, key=lambda r: FILES[r][0].encode("utf-8")):
        name, path, _ = FILES[role]
        entries.append({"role": role, "name": name, "path": path, "bytes": len(files[role]), "sha256": sha256_hex(files[role])})
    return {
        "schema_version": SCHEMA_VERSION,
        "format": FORMAT,
        "data_digest": data_digest,
        "generated_at": generated_at,
        "generator": GENERATOR,
        "apn_database_version": APN_DATABASE_VERSION,
        "google_lane": "included" if "google_lane" in files else "absent",
        "files": entries,
        "dataset_digest": dataset_digest(entries),
        "counts": counts,
    }


def dataset_digest(entries: list[dict[str, Any]]) -> str:
    text = "".join(f"{e['name']}\n{e['sha256']}\n{e['bytes']}\n" for e in sorted(entries, key=lambda e: e["name"].encode("utf-8")))
    return "sha256:" + sha256_hex(text.encode("utf-8"))


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate(root: Path, generated_at: str | None = None, previous_manifest: dict[str, Any] | None = None,
             lane_override: dict[str, Any] | None = None, records_override: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every dataset file of ROOT as bytes, keyed by repository path, with a
    report. The manifest keeps PREVIOUS_MANIFEST's generated_at when no file
    changed. LANE_OVERRIDE replaces google-lane.json (a bake from a commit
    without one), RECORDS_OVERRIDE the records of devices/records/."""
    inputs = Inputs(root)
    if lane_override is not None:
        inputs.lane, inputs.lane_rules_left_out = within_prefix_limits(lane_override)
    if inputs.lane is None:
        raise DatasetError(f"{FILES['google_lane'][1]}: missing; the private publisher writes the Google lane (round 30)")
    generator = load_module("generate_android_outputs", root / "tools/generate_android_outputs.py")
    lineage = load_module("lineageos_apns", root / "tools/lineageos_apns.py")
    records, declared, reads = read_record_sources(root)
    if records_override is not None:
        records = records_override
    registry = build_registry(inputs, records, declared, left_group_a_keys(reads))
    carriers = {e["profile_id"]: inputs.carrier_profile(e["path"]) for e in inputs.lookup["profiles"]}
    apn_index, version = build_apn_index(inputs, generator, lineage, [(e, carriers[e["profile_id"]]) for e in inputs.lookup["profiles"]])
    if version != APN_DATABASE_VERSION:
        raise DatasetError(f"apns-conf.xml: <apns version=\"{version}\">, the dataset needs {APN_DATABASE_VERSION} (apn_version)")
    apn_counts: dict[str, int] = defaultdict(int)
    for row in apn_index["rows"]:
        for profile_id in row["profiles"]:
            apn_counts[profile_id] += 1
    profiles_doc, profile_counts = build_profiles(inputs, registry, apn_counts, carriers)
    lane = lane_document(inputs)
    current = current_match_set_hashes(root, inputs.lookup)
    stored = measured_match_set_hashes(root)
    served = [r for r in served_records(records) if record_serves(r, stored, current)]
    group_a, group_a_pending = group_a_documents(inputs.data_digest, profiles_doc, lane_document(inputs), reads, current)
    group_a_bytes = dump_lines(group_a, ("key_findings", "reads"))
    files_by_role = {
        "profiles": dump_lines(profiles_doc, ("keys", "networks")),
        "google_lane": dump_lines(lane, ("entries", "rules")),
        "device_records": dump_lines(records_document(inputs, served), ("records",)),
        "apn_xml": inputs.apn_xml,
        "apn_index": dump_lines(apn_index, ("rows",)),
    }
    if LIST_GROUP_A_READS:
        files_by_role["group_a_reads"] = group_a_bytes
    counts = {
        "networks": profile_counts["networks"],
        "profiles": profile_counts["profiles"],
        "fill_only_profiles": profile_counts["fill_only_profiles"],
        "google_entries": len(lane["entries"]),
        "apn_rows": len(apn_index["rows"]),
        "records": len(served),
    }
    keep = None
    if previous_manifest is not None:
        trial = manifest_document(inputs.data_digest, files_by_role, "1970-01-01T00:00:00Z", counts)
        if trial["dataset_digest"] == previous_manifest.get("dataset_digest") and trial["data_digest"] == previous_manifest.get("data_digest") \
                and trial["counts"] == previous_manifest.get("counts") and isinstance(previous_manifest.get("generated_at"), str) \
                and GENERATED_AT_RE.fullmatch(previous_manifest["generated_at"]):
            keep = previous_manifest["generated_at"]
    manifest = manifest_document(inputs.data_digest, files_by_role, keep or generated_at or now_utc(), counts)
    out = {FILES[role][1]: data for role, data in files_by_role.items()}
    out[FILES["manifest"][1]] = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    out[REGISTRY_PATH] = (json.dumps(registry_document(registry), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    if not LIST_GROUP_A_READS:
        out[GROUP_A_READS_FILE] = group_a_bytes
    withheld = withheld_document_of(root, lane, inputs.data_digest)
    if withheld is not None:
        out[WITHHELD_FILE] = withheld
    out[GROUP_A_PENDING_FILE] = dump_lines(group_a_pending, ("key_reads", "pending", "unrecorded_basis"))
    return {"files": out, "manifest": manifest, "counts": {**profile_counts, **counts}, "registry": registry, "reads": reads,
            "group_a": {"read_items": len(group_a["reads"]), "proceed_items": sum(r["verdict"] == "proceed" for r in group_a["reads"]),
                        "key_findings": len(group_a["key_findings"]), "left_group_a": group_a_pending["left_group_a"],
                        "pending": len(group_a_pending["pending"]), "pending_profiles": sum(len(p["profiles"]) for p in group_a_pending["pending"]),
                        "listed_in_manifest": LIST_GROUP_A_READS},
            "records_waiting": len(records) - len(served), "lane_rules_left_out": inputs.lane_rules_left_out}


def previous_manifest_of(root: Path) -> dict[str, Any] | None:
    path = root / FILES["manifest"][1]
    if not path.is_file():
        return None
    try:
        return strict_load_bytes(path.read_bytes(), str(path))
    except StrictJSONError:
        return None


def write_files(root: Path, files: dict[str, bytes]) -> list[str]:
    changed = []
    for relative, data in sorted(files.items()):
        path = root / relative
        if path.is_file() and path.read_bytes() == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        changed.append(relative)
    return changed


# ---------------------------------------------------------------- validate


def load_schema_file(root: Path, name: str) -> dict[str, Any]:
    validator = load_module("validate_public_carrier_data", root / "tools/validate_public_carrier_data.py")
    return validator.load_schema(name, root / "schemas"), validator


def schema_check(root: Path, value: Any, name: str, where: str) -> list[str]:
    schema, validator = load_schema_file(root, name)
    problem = validator.schema_problem(value, schema, schema, "$")
    return [f"{where}: does not match schemas/{name}: {problem}"] if problem else []


def check_dataset_files(files: dict[str, bytes], expected_digest: str | None = None) -> tuple[list[str], dict[str, Any]]:
    """The reader's checks 4 to 10 (spec 2.12) over dataset files keyed by
    role: manifest, sizes, SHA-256 and dataset digest, data digest
    agreement, strict parse and known schema versions, closed and typed
    keys with their domains, specificity, network copies, the APN version
    and the APN index. Returns (problems, parsed documents)."""
    out: list[str] = []
    parsed: dict[str, Any] = {}
    if "manifest" not in files:
        return ["manifest.json: missing"], parsed
    total = 0
    for role, data in files.items():
        name, _, cap = FILES[role]
        total += len(data)
        if len(data) > cap:
            out.append(f"{name}: {len(data)} bytes, over its cap of {cap} (too_large)")
    if total > TOTAL_CAP:
        out.append(f"the dataset is {total} bytes, over {TOTAL_CAP} (too_large)")
    try:
        manifest = strict_load_bytes(files["manifest"], "manifest.json")
    except StrictJSONError as error:
        return out + [f"{error} (parse_error)"], parsed
    parsed["manifest"] = manifest
    keys = {"schema_version", "format", "data_digest", "generated_at", "generator", "apn_database_version", "google_lane", "files", "dataset_digest", "counts"}
    if set(manifest) != keys:
        return out + [f"manifest.json: must hold exactly {', '.join(sorted(keys))} (schema_unknown)"], parsed
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["format"] != FORMAT:
        return out + ["manifest.json: unknown schema_version or format (schema_unknown)"], parsed
    digest = manifest["data_digest"]
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        out.append("manifest.json: data_digest is malformed")
    if expected_digest is not None and digest != expected_digest:
        out.append(f"manifest.json: data_digest {digest} is not the checkout's {expected_digest} (data_digest_disagree)")
    if not isinstance(manifest["generated_at"], str) or not GENERATED_AT_RE.fullmatch(manifest["generated_at"]):
        out.append("manifest.json: generated_at must be ISO 8601 UTC with seconds")
    if manifest["apn_database_version"] != APN_DATABASE_VERSION:
        out.append(f"manifest.json: apn_database_version must be {APN_DATABASE_VERSION}")
    listed = {}
    for entry in manifest["files"] if isinstance(manifest["files"], list) else []:
        if not isinstance(entry, dict) or set(entry) != {"role", "name", "path", "bytes", "sha256"} or entry.get("role") not in FILES or entry["role"] in ("manifest", "pin"):
            out.append("manifest.json: a files entry must hold exactly role, name, path, bytes and sha256 of a dataset file")
            continue
        if (entry["name"], entry["path"]) != FILES[entry["role"]][:2]:
            out.append(f"manifest.json: {entry['role']} must be named {FILES[entry['role']][0]} at {FILES[entry['role']][1]}")
        listed[entry["role"]] = entry
    wanted = {"profiles", "device_records", "apn_xml", "apn_index"} | ({"google_lane"} if manifest["google_lane"] == "included" else set()) \
        | ({"group_a_reads"} if "group_a_reads" in listed else set())
    if manifest["google_lane"] not in ("included", "absent"):
        out.append("manifest.json: google_lane must be included or absent")
    if set(listed) != wanted:
        out.append(f"manifest.json: lists {sorted(listed)}, the dataset needs {sorted(wanted)}")
    for role in wanted:
        if role not in files:
            out.append(f"{FILES[role][0]}: missing (bad_request)")
        elif role in listed and (len(files[role]) != listed[role]["bytes"] or sha256_hex(files[role]) != listed[role]["sha256"]):
            out.append(f"{FILES[role][0]}: size or SHA-256 differs from the manifest (sha256_mismatch)")
    if listed and manifest["dataset_digest"] != dataset_digest(list(listed.values())):
        out.append("manifest.json: dataset_digest is not the digest of its files (dataset_digest_mismatch)")
    if out:
        return out, parsed
    # 6. data digest agreement, 7. strict parse.
    header = apns_header_digest(files["apn_xml"])
    if header != digest:
        out.append("apns-conf.xml: the header's data_digest is not the manifest's (data_digest_disagree)")
    shapes = {
        "profiles": {"schema_version", "based_on_data_digest", "keys", "groups", "reserved", "networks"},
        "google_lane": {"schema_version", "based_on_data_digest", "family", "provenance", "rules", "entries"},
        "device_records": {"schema_version", "based_on_data_digest", "expire_days", "records"},
        "apn_index": {"schema_version", "based_on_data_digest", "apn_xml_sha256", "rows"},
        "group_a_reads": {"schema_version", "based_on_data_digest", "reads", "key_findings"},
    }
    for role in sorted(wanted - {"apn_xml"}):
        try:
            document = strict_load_bytes(files[role], FILES[role][0])
        except StrictJSONError as error:
            out.append(f"{error} (parse_error)")
            continue
        if set(document) != shapes[role] or document.get("schema_version") != SCHEMA_VERSION:
            out.append(f"{FILES[role][0]}: must hold exactly {', '.join(sorted(shapes[role]))} with schema_version 1 (schema_unknown)")
            continue
        if document["based_on_data_digest"] != digest:
            out.append(f"{FILES[role][0]}: based_on_data_digest is not the manifest's (data_digest_disagree)")
        parsed[role] = document
    if out:
        return out, parsed
    out += registry_and_value_problems(parsed)
    # 9. APN version, 10. APN index.
    try:
        version, rows = parse_apn_rows(files["apn_xml"])
    except DatasetError as error:
        return out + [f"{error} (parse_error)"], parsed
    if version != APN_DATABASE_VERSION or version != manifest["apn_database_version"]:
        out.append(f"apns-conf.xml: <apns version=\"{version}\"> is not {APN_DATABASE_VERSION} (apn_version)")
    index = parsed["apn_index"]
    if index["apn_xml_sha256"] != sha256_hex(files["apn_xml"]):
        out.append("apn-index.json: apn_xml_sha256 is not the XML's (apn_index_mismatch)")
    if len(index["rows"]) != len(rows):
        out.append(f"apn-index.json: {len(index['rows'])} rows, the XML has {len(rows)} (apn_index_mismatch)")
    else:
        for ordinal, ((line, attributes), row) in enumerate(zip(rows, index["rows"])):
            if row.get("ordinal") != ordinal or row.get("line") != line or row.get("row_key") != row_key_of(attributes):
                out.append(f"apn-index.json: row {ordinal} does not agree with the XML line {line} (apn_index_mismatch)")
                break
    known = {p["id"] for network in parsed["profiles"]["networks"].values() for p in network["profiles"]}
    unknown = sorted({p for row in index["rows"] for p in row["profiles"]} - known)
    if unknown:
        out.append(f"apn-index.json: names profiles profiles.json lacks: {unknown[:5]}")
    counted: dict[str, int] = defaultdict(int)
    for row in index["rows"]:
        for p in row["profiles"]:
            counted[p] += 1
    for network in parsed["profiles"]["networks"].values():
        for profile in network["profiles"]:
            if profile["apn_rows"] != counted.get(profile["id"], 0):
                out.append(f"profiles.json: {profile['id']} says apn_rows {profile['apn_rows']}, apn-index.json gives {counted.get(profile['id'], 0)}")
                break
    if "google_lane" in parsed:
        entries = parsed["google_lane"]["entries"]
        missing = sorted({item["entry"] for network in parsed["profiles"]["networks"].values() for p in network["profiles"] for item in p["fill"]} - set(entries))
        if missing:
            out.append(f"profiles.json: fill entries the Google lane lacks: {missing[:5]} (fill_missing)")
        for reserved in ("default", "no_sim"):
            if reserved not in entries:
                out.append(f"google-lane.json: has no {reserved} entry")
    counts = manifest["counts"]
    expected = {
        "networks": len(parsed["profiles"]["networks"]),
        "profiles": len(known),
        "fill_only_profiles": sum(1 for p in known if p.startswith("fill.")),
        "google_entries": len(parsed["google_lane"]["entries"]) if "google_lane" in parsed else counts.get("google_entries"),
        "apn_rows": len(rows),
        "records": len(parsed["device_records"]["records"]),
    }
    if counts != expected:
        out.append(f"manifest.json: counts {counts} are not the files' {expected}")
    return out, parsed


def registry_and_value_problems(parsed: dict[str, Any]) -> list[str]:
    """Check 8: every key used is in the registry with its type, every value
    is typed and in its domain, specificity agrees, network copies agree."""
    out: list[str] = []
    profiles = parsed["profiles"]
    registry = profiles["keys"]
    for key, meta in registry.items():
        if not isinstance(meta, dict) or set(meta) != {"type", "group", "origin", "fork"} or meta["type"] not in REGISTRY_TYPES \
                or meta["group"] not in ("A", "B", "X6", None):
            out.append(f"profiles.json: the registry entry of {key} is malformed (wrong_type)")
    if out:
        return out

    def check_values(values: dict[str, Any], where: str) -> None:
        for key, value in values.items():
            meta = registry.get(key)
            if meta is None:
                out.append(f"{where}: {key} is not in the registry (unknown_key)")
                continue
            problem = value_problem(value, meta["type"], f"{where}: {key}") or domain_problem(key, value, f"{where}: {key}")
            if problem:
                out.append(f"{problem} (wrong_type)" if "domain" not in problem else f"{problem} (invalid_value)")

    seen: dict[str, str] = {}
    for network_key, network in profiles["networks"].items():
        match = NETWORK_RE.fullmatch(network_key)
        if not match or (network.get("mcc"), network.get("mnc")) != match.groups():
            out.append(f"profiles.json: network {network_key} is not <mcc>-<mnc> with its own mcc and mnc")
            continue
        last = None
        for profile in network["profiles"]:
            where = f"profiles.json: {profile['id']} on {network_key}"
            if specificity_of(profile["match"]) != profile["specificity"]:
                out.append(f"{where}: specificity is not the number of dimensions besides mccmnc (invalid_value)")
            if not any((n["mcc"], n["mnc"]) == match.groups() for n in profile["match"]["mccmnc"]):
                out.append(f"{where}: its match does not list this network")
            order = stack_order(profile)
            if last is not None and order <= last:
                out.append(f"{where}: profiles are not in specificity and id order")
            last = order
            check_values(profile["values"], where)
            for key, alternatives in profile["alternatives"].items():
                for alternative in alternatives:
                    check_values({key: alternative["value"]}, where + " alternatives")
            copy = compact({k: v for k, v in profile.items() if k != "fill"})
            if profile["id"] in seen and seen[profile["id"]] != copy:
                out.append(f"{where}: differs from its copy under another network (invalid_value)")
            seen[profile["id"]] = copy
    lane = parsed.get("google_lane")
    if lane is not None:
        for name, entry in lane["entries"].items():
            check_values(entry["values"], f"google-lane.json: {name}")
    for index, read in enumerate(parsed.get("group_a_reads", {}).get("reads", [])):
        meta = registry.get(read.get("key"))
        if meta is None:
            out.append(f"group-a-reads.json: read {index} names {read.get('key')}, not in the registry (unknown_key)")
        else:
            problem = value_problem(read.get("value"), meta["type"], f"group-a-reads.json: read {index}")
            if problem:
                out.append(f"{problem} (wrong_type)")
    for index, record in enumerate(parsed["device_records"]["records"]):
        target = record.get("target", {})
        if target.get("type") == "config":
            key = target.get("key")
            if key not in registry:
                out.append(f"device-records.json: record {index} targets {key}, not in the registry (unknown_key)")
            elif record.get("value_kind") == "value":
                problem = value_problem(record.get("value"), registry[key]["type"], f"device-records.json: record {index}")
                if problem:
                    out.append(f"{problem} (wrong_type)")
    return out[:200]


def validate(root: Path, base_manifest: dict[str, Any] | None = None, regenerate: bool = True) -> list[str]:
    """Every rule the dataset of ROOT must keep; an empty list when it does."""
    out: list[str] = []
    files: dict[str, bytes] = {}
    for role, (name, path, _) in FILES.items():
        if path and (root / path).is_file():
            files[role] = (root / path).read_bytes()
    if "manifest" not in files:
        return [f"{FILES['manifest'][1]}: missing; run tools/ocd_dataset.py generate"]
    metadata = read_json_file(root / "generated/android/metadata.json")
    problems, parsed = check_dataset_files(files, metadata.get("data_digest"))
    out += problems
    variants = root / "generated/devices/carrier-variants.json"
    if variants.is_file():
        digest = read_json_file(variants).get("data_digest")
        if digest is not None and digest != metadata.get("data_digest"):
            out.append("generated/devices/carrier-variants.json: data_digest is not metadata.json's (F1)")
    if out:
        return out
    names = {
        "profiles": "ocd-dataset-profiles.schema.json",
        "google_lane": "ocd-dataset-google-lane.schema.json",
        "apn_index": "ocd-dataset-apn-index.schema.json",
        "device_records": "device-records.schema.json",
        "manifest": "ocd-dataset-manifest.schema.json",
        "group_a_reads": "ocd-dataset-group-a-reads.schema.json",
    }
    for role, schema in names.items():
        if role in parsed:
            out += schema_check(root, parsed[role], schema, FILES[role][1])
    registry_file = read_json_file(root / REGISTRY_PATH) if (root / REGISTRY_PATH).is_file() else None
    out += schema_check(root, registry_file, "carrier-config-keys.schema.json", REGISTRY_PATH) if registry_file is not None else [f"{REGISTRY_PATH}: missing"]
    if registry_file is not None and registry_file.get("keys") != parsed["profiles"]["keys"]:
        out.append(f"{REGISTRY_PATH}: differs from profiles.json's keys")
    lane = parsed.get("google_lane")
    if lane is not None:
        if lane["provenance"].get("state") != "public_main":
            out.append("google-lane.json: provenance.state on main must be public_main")
        for index, rule in enumerate(lane["rules"]):
            mvno = rule["mvno"]
            if not lane_rule_within_limits(rule):
                out.append(f"google-lane.json: rule {index} has an {mvno['kind']} selector outside rule 3's prefix limits, which public main never carries")
        for name, entry in lane["entries"].items():
            for key, value in entry["values"].items():
                hits = privacy_hits(value)
                if hits:
                    out.append(f"google-lane.json: {name} {key} trips the privacy guard ({', '.join(hits)}); the publisher leaves such values out")
        names_with_rules = {rule["canonical_name"] for rule in lane["rules"]}
        missing = sorted(names_with_rules - set(lane["entries"]))
        if missing:
            out.append(f"google-lane.json: rules name entries it lacks: {missing[:5]}")
        unnamed = sorted(set(lane["entries"]) - names_with_rules - set(UNNAMED_LANE_ENTRIES))
        if unnamed:
            out.append(f"google-lane.json: {len(unnamed)} entries no rule names, which public main never carries")
    for network in parsed["profiles"]["networks"].values():
        for profile in network["profiles"]:
            if profile["kind"] == "ocd":
                if not OCD_ID_RE.fullmatch(profile["id"]):
                    out.append(f"profiles.json: {profile['id']} is not an OCD profile id")
                for pattern in profile["match"].get("imsi_prefix_patterns", []):
                    if not OCD_IMSI_RE.fullmatch(pattern):
                        out.append(f"profiles.json: {profile['id']} has an IMSI pattern outside OCD's 5 to 10 characters")
            elif not FILL_ID_RE.fullmatch(profile["id"]):
                out.append(f"profiles.json: {profile['id']} is not a fill-only profile id")
    records, declared, reads = read_record_sources(root)
    for path, read in reads.items():
        if isinstance(read, dict) and read.get("schema") == GROUP_A_READ_SCHEMA:
            problems = group_a_read_problems(read, path)
            out += problems or schema_check(root, read, "group-a-read.schema.json", path)
        else:
            out += read_problems(read, path)
    registry = parsed["profiles"]["keys"]
    seen_keys: set[str] = set()
    for index, record in enumerate(parsed["device_records"]["records"]):
        where = f"device-records.json: record {index}"
        if record["record_key"] in seen_keys:
            out.append(f"{where}: record_key {record['record_key']} appears twice")
        seen_keys.add(record["record_key"])
        out += any_record_problems(record, registry, reads, where)
    for index, record in enumerate(r for r in records if r not in served_records(records)):
        where = f"{MEASURED_FILE}: waiting cell record {index}"
        problems = cell_record_problems(record, registry, where)
        out += problems or schema_check(root, {"schema_version": CELL_RECORDS_SCHEMA_VERSION, "based_on_data_digest": metadata.get("data_digest"),
                                                "expire_days": EXPIRE_DAYS, "records": [record]}, "cell-records.schema.json", where)
    group_a_path = root / GROUP_A_READS_FILE
    if group_a_path.is_file() and "group_a_reads" not in parsed:
        out += schema_check(root, read_json_file(group_a_path), "ocd-dataset-group-a-reads.schema.json", GROUP_A_READS_FILE)
    if (root / GROUP_A_PENDING_FILE).is_file():
        out += schema_check(root, read_json_file(root / GROUP_A_PENDING_FILE), "ocd-dataset-group-a-pending.schema.json", GROUP_A_PENDING_FILE)
    listed_roles = {entry["role"] for entry in parsed["manifest"]["files"]}
    if ("group_a_reads" in listed_roles) != LIST_GROUP_A_READS:
        out.append(f"manifest.json: group_a_reads is {'not ' if LIST_GROUP_A_READS else ''}listed; this tool's LIST_GROUP_A_READS says otherwise")
    out += withheld_problems(root, parsed.get("google_lane"), metadata.get("data_digest"))
    if base_manifest is not None:
        if base_manifest.get("dataset_digest") != parsed["manifest"]["dataset_digest"] and \
                not str(parsed["manifest"]["generated_at"]) > str(base_manifest.get("generated_at", "")):
            out.append("manifest.json: the dataset changed but generated_at is not later than main's (spec 2.8)")
    if out or not regenerate:
        return out
    again = generate(root, previous_manifest=parsed["manifest"])
    for relative, data in sorted(again["files"].items()):
        path = root / relative
        if not path.is_file() or path.read_bytes() != data:
            out.append(f"{relative}: is not what tools/ocd_dataset.py generate writes from this checkout; run it and commit the result")
    return out


# ---------------------------------------------------------------- stacks


def implied_match(specific: dict[str, Any], generic: dict[str, Any]) -> bool:
    """Every SIM that SPECIFIC matches on a shared network also matches GENERIC."""
    kinds = {"spn": "spn", "imsi_prefix_patterns": "imsi", "gid1_prefixes": "gid1", "gid2_prefixes": "gid1", "iccid_prefixes": "iccid"}
    for dimension in DIMENSIONS:
        if dimension not in generic:
            continue
        if dimension not in specific:
            return False
        if dimension == "android_carrier_ids":
            if not set(specific[dimension]) <= set(generic[dimension]):
                return False
            continue
        kind = kinds[dimension]
        if not all(any(value_implies(kind, w, v) for v in generic[dimension]) for w in specific[dimension]):
            return False
    return True


def profile_stack(network_profiles: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    """The stack a SIM that PROFILE matches always has: the less specific
    profiles of the network that every such SIM also matches, then PROFILE."""
    stack = [q for q in network_profiles if q is profile or q["id"] == profile["id"]
             or (q["specificity"] < profile["specificity"] and implied_match(profile["match"], q["match"]))]
    return sorted(stack, key=stack_order)


# ---------------------------------------------------------------- ties


def selectors_can_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether one SIM can satisfy both matches on a shared network."""
    for dimension in DIMENSIONS:
        if dimension in a and dimension in b:
            if dimension == "android_carrier_ids":
                continue  # carrier ID and specific carrier ID can differ on one SIM
            kind = {"spn": "spn", "imsi_prefix_patterns": "imsi", "gid1_prefixes": "gid1", "gid2_prefixes": "gid1", "iccid_prefixes": "iccid"}[dimension]
            if not any(values_overlap(kind, x, y) for x in a[dimension] for y in b[dimension]):
                return False
    return True


def tie_report(profiles: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key, network in profiles["networks"].items():
        items = network["profiles"]
        for i, first in enumerate(items):
            for second in items[i + 1:]:
                if second["specificity"] != first["specificity"]:
                    break
                if first["specificity"] and selectors_can_overlap(first["match"], second["match"]):
                    shared = sorted(d for d in DIMENSIONS if d in first["match"] and d in second["match"])
                    out.append({"network": key, "specificity": first["specificity"], "first": first["id"], "serves": second["id"], "shared": shared})
    return out


# ---------------------------------------------------------------- CLI


def load_dataset_dir(root: Path) -> dict[str, Any]:
    profiles = read_json_file(root / FILES["profiles"][1])
    lane_path = root / FILES["google_lane"][1]
    lane = read_json_file(lane_path) if lane_path.is_file() else None
    return {"profiles": profiles, "lane": lane}


def explain_sim(profiles: dict[str, Any], lane: dict[str, Any] | None, sim: dict[str, Any]) -> dict[str, Any]:
    network = profiles["networks"].get(f"{sim.get('mcc')}-{sim.get('mnc')}")
    stack = resolve_stack(network["profiles"], sim) if network else []
    serving = stack[-1] if stack else None
    fill = serving["fill"] if serving else []
    pick = pick_fill(fill, sim, lane["entries"] if lane else None)
    return {
        "network": f"{sim.get('mcc')}-{sim.get('mnc')}",
        "stack": [{"id": p["id"], "specificity": p["specificity"], "kind": p["kind"], "name": p["name"]} for p in stack],
        "serving": serving["id"] if serving else "default",
        "fill": fill,
        "fill_pick": pick,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--root", type=Path, default=TOOLS.parent)
    gen.add_argument("--generated-at", help="ISO 8601 UTC time for a changed dataset (default: now)")
    val = sub.add_parser("validate")
    val.add_argument("--root", type=Path, default=TOOLS.parent)
    val.add_argument("--base-manifest", type=Path, help="main's manifest.json, on a pull request")
    val.add_argument("--no-regenerate", action="store_true", help="skip the regeneration check")
    mat = sub.add_parser("match")
    mat.add_argument("--root", type=Path, default=TOOLS.parent)
    for name in ("mcc", "mnc"):
        mat.add_argument(f"--{name}", required=True)
    for name in ("spn", "imsi", "gid1", "gid2", "iccid"):
        mat.add_argument(f"--{name}")
    mat.add_argument("--carrier-id", type=int, default=-1)
    mat.add_argument("--specific-carrier-id", type=int, default=-1)
    tie = sub.add_parser("ties")
    tie.add_argument("--root", type=Path, default=TOOLS.parent)
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            result = generate(args.root, args.generated_at, previous_manifest_of(args.root))
            changed = write_files(args.root, result["files"])
            counts = result["counts"]
            size = sum(entry["bytes"] for entry in result["manifest"]["files"]) + len(result["files"][FILES["manifest"][1]])
            print(
                f"ocd dataset: {counts['networks']} networks, {counts['profiles']} profiles ({counts['fill_only_profiles']} fill-only: "
                f"{counts['fill_only_imsi']} IMSI, {counts['fill_only_network']} network, {counts['fill_only_spn']} SPN, "
                f"{counts['fill_only_gid1']} GID1, {counts['fill_only_iccid']} ICCID), {counts['google_entries']} Google entries, "
                f"{counts['apn_rows']} APN rows, {counts['records']} records, {len(result['registry'])} registry keys; "
                f"{size} bytes; dataset_digest {result['manifest']['dataset_digest']}; "
                + (f"wrote {', '.join(changed)}" if changed else "nothing changed")
            )
            left_out = result["lane_rules_left_out"]
            if left_out:
                by_network: dict[str, int] = defaultdict(int)
                for rule in left_out:
                    by_network[rule["network"]] += 1
                print(f"ocd dataset: {len(left_out)} Google rule(s) left out for rule 3's prefix limits: "
                      + ", ".join(f"{network} {count}" for network, count in sorted(by_network.items())))
            return 0
        if args.command == "validate":
            base = None
            if args.base_manifest and args.base_manifest.is_file() and args.base_manifest.stat().st_size:
                base = read_json_file(args.base_manifest)
            problems = validate(args.root, base, regenerate=not args.no_regenerate)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            if not problems:
                manifest = read_json_file(args.root / FILES["manifest"][1])
                print(f"ocd dataset: valid, {manifest['counts']}, {manifest['dataset_digest']}")
            return 1 if problems else 0
        if args.command == "match":
            data = load_dataset_dir(args.root)
            sim = {k: getattr(args, k) for k in ("mcc", "mnc", "spn", "imsi", "gid1", "gid2", "iccid") if getattr(args, k) is not None}
            sim.update(carrier_id=args.carrier_id, specific_carrier_id=args.specific_carrier_id)
            print(json.dumps(explain_sim(data["profiles"], data["lane"], sim), indent=2, ensure_ascii=False))
            return 0
        if args.command == "ties":
            report = tie_report(read_json_file(args.root / FILES["profiles"][1]))
            for item in report:
                how = "overlapping " + "+".join(item["shared"]) if item["shared"] else "different dimensions"
                print(f"{item['network']} specificity {item['specificity']}: {item['first']} < {item['serves']} (the later one serves; {how})")
            same = sum(1 for item in report if item["shared"])
            print(f"{len(report)} tie(s): {same} with overlapping selectors of one dimension, {len(report) - same} only for a SIM that carries both selectors")
            return 0
    except DatasetError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
