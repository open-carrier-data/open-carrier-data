#!/usr/bin/env python3
"""Validate generated/devices/carrier-variants.json, the device records for
VoLTE, Wi-Fi calling, video calling and VoNR (docs/data-model.md, "Device
records").

A device record says what one device's own carrier file configures for one
carrier profile. The checks keep it to that: four capabilities and a closed
field list; every profile published; every device in the device catalog; one
value per profile, capability, device and stack; a source the evidence index
lists for that capability and state; no off from Samsung or Apple; entries
inside five years; the digest of the data it was built with; and
canonical bytes. And every VoLTE, Wi-Fi calling or video calling label
published supported against a single family's off (round 17, step 2) has an
off record here from each off source and at least one on record (round 22);
without the file such a label fails even without --require. A label whose
gate carries the reason off_older_than_five_years (round 32's old-off clause)
has at least one on record and no off record here, because rule 7 withholds
every off behind it.

Usage: validate_carrier_variants.py [REPO_ROOT] [--freshness warn|fail] [--require]
Without the file the check passes unless --require is given.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import re
import sys
from typing import Any

import validate_public_carrier_data
from validate_public_carrier_data import (
    FRESHNESS_MODES,
    ValidationError,
    check_freshness,
    parse_entry_month,
    parse_freshness_window,
)

VARIANTS_PATH = Path("generated/devices/carrier-variants.json")
SCHEMA_VERSION = 1
CAPABILITIES = ["video_calling", "volte", "vonr", "vowifi"]
TOP_LEVEL_FIELDS = {
    "schema_version",
    "description",
    "based_on_data_digest",
    "checks_through",
    "stale_after",
    "capabilities",
    "profiles",
}
RECORD_FIELDS = {"state", "source", "stack", "newest_entry", "devices", "basis"}
REQUIRED_RECORD_FIELDS = {"state", "source", "stack", "devices"}
STATES = {"on", "off", "conditional"}
# The device-scoped sources and the software their values hold for. No other
# source gives a device record: the Samsung IMS table and Samsung
# CarrierConfig are read from one model and serve every model of the build,
# Apple has no per-board split, and the APN lists are carrier-wide.
SOURCE_STACKS = {
    "samsung_omc": "stock",
    "google_carriersettings": "stock",
    "google_pixel_vendor_carriersettings": "stock",
    "fairphone_official_source": "stock",
    "lineageos_device_overlays": "lineageos",
    "sony_open_devices_aosp": "aosp",
}
# Sources whose off never publishes (rule 9): only their on is a record.
ON_ONLY_SOURCES = {"samsung_omc"}
SAMSUNG_DEVICE_SOURCES = {"samsung_omc"}
BASIS = "samsung_vonr_switch"
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
ANDROID_DEVICE_RE = re.compile(r"android:[a-z0-9-]{3,80}")
SAMSUNG_DEVICE_RE = re.compile(r"samsung:[A-Z0-9][A-Z0-9._/+-]{1,63}")
STALE_ENTRY_MAX_AGE_YEARS = 5
MAX_BYTES = 15_000_000


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError(f"{path}: cannot read JSON: {exc}") from exc


def canonical_bytes(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def record_order(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (record["state"], record["source"], record["stack"], record.get("newest_entry", ""))


def catalog_devices(root: Path) -> tuple[set[str], set[str]]:
    """Android catalog device IDs, and the upper-cased models Samsung devices list."""
    devices = load_json(root / "generated/devices/android.json")["devices"]
    ids = {device["device_id"] for device in devices}
    samsung = {
        model.upper()
        for device in devices
        if any(brand.casefold() == "samsung" for brand in device.get("brands", []))
        for model in device.get("models", [])
    }
    return ids, samsung


def rule7_floor(checks_through: date) -> tuple[int, int]:
    """The oldest newest_entry month rule 7 leaves published."""
    return (checks_through.year - STALE_ENTRY_MAX_AGE_YEARS, checks_through.month)


def validate_record(
    where: str,
    record: Any,
    capability: str,
    android_ids: set[str],
    samsung_models: set[str],
    floor: tuple[int, int],
    sources: dict[str, list[str]],
    basis: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValidationError(f"{where}: a record must be an object")
    extra = set(record) - RECORD_FIELDS
    missing = REQUIRED_RECORD_FIELDS - set(record)
    if extra or missing:
        raise ValidationError(f"{where}: record fields are invalid (extra {sorted(extra)}, missing {sorted(missing)})")
    state, source, stack = record["state"], record["source"], record["stack"]
    if state not in STATES:
        raise ValidationError(f"{where}: state {state!r} is not on, off or conditional")
    if source not in SOURCE_STACKS:
        raise ValidationError(f"{where}: {source!r} gives no device record")
    if stack != SOURCE_STACKS[source]:
        raise ValidationError(f"{where}: {source} values hold for stack {SOURCE_STACKS[source]}, not {stack!r}")
    if source in ON_ONLY_SOURCES and state != "on":
        raise ValidationError(f"{where}: a {source} record is on only, never {state}")
    if "newest_entry" in record:
        month = parse_entry_month(Path(where), record["newest_entry"], "newest_entry")
        if month < floor:
            raise ValidationError(f"{where}: newest_entry {record['newest_entry']} is outside rule 7's five years")
    devices = record["devices"]
    if not isinstance(devices, list) or not devices or devices != sorted(set(devices)):
        raise ValidationError(f"{where}: devices must be a non-empty sorted list without repeats")
    for device in devices:
        if not isinstance(device, str):
            raise ValidationError(f"{where}: a device must be a string")
        if source in SAMSUNG_DEVICE_SOURCES:
            if not SAMSUNG_DEVICE_RE.fullmatch(device) or device[len("samsung:"):] not in samsung_models:
                raise ValidationError(f"{where}: {device} is not a Samsung model the device catalog lists")
        elif not ANDROID_DEVICE_RE.fullmatch(device) or device not in android_ids:
            raise ValidationError(f"{where}: {device} is not in generated/devices/android.json")
    listed = [label for label, names in sources.items() if source in names]
    if state == "conditional":
        known = "conditional" in listed or len(listed) >= 2
    else:
        known = state in listed
    if not known:
        raise ValidationError(f"{where}: the evidence index does not list {source} as {state} for {capability}")
    has_basis = capability == "vonr" and source == "samsung_omc" and (basis or {}).get("basis") == BASIS
    if "basis" in record and record["basis"] != BASIS:
        raise ValidationError(f"{where}: basis must be {BASIS}")
    if ("basis" in record) != has_basis:
        raise ValidationError(f"{where}: basis must be present exactly where capability_basis names {BASIS}")
    return record


def device_backed_labels(
    evidence: dict[str, dict[str, Any]], reason: str | None = None
) -> dict[tuple[str, str], list[str]]:
    """(profile, capability) to the off sources of every VoLTE, Wi-Fi calling
    or video calling label published supported against a single family's
    off (round 17, step 2): the profile carries the gate
    single_family_off:<capability> and capability_sources lists both on and
    off, which validate_public_carrier_data accepts only for such a label.
    reason selects the labels whose gate carries that reason (round 32's
    off_older_than_five_years); None selects those whose gate carries none."""
    labels: dict[tuple[str, str], list[str]] = {}
    for profile_id, item in evidence.items():
        gated = {
            gate["key"].partition(":")[2]
            for gate in item.get("quality_gates", [])
            if gate["section"] == "capabilities"
            and gate["key"].partition(":")[0] == validate_public_carrier_data.SINGLE_FAMILY_OFF_GATE
            and gate.get("reason") == reason
        }
        for capability in sorted(gated & validate_public_carrier_data.DEVICE_BACKED_LABEL_CAPABILITIES):
            kinds = item.get("capability_sources", {}).get(capability, {})
            if "on" in kinds and "off" in kinds:
                labels[(profile_id, capability)] = kinds["off"]
    return labels


def check_device_backed_labels(
    path: Path,
    labels: dict[tuple[str, str], list[str]],
    profiles: dict[str, Any],
) -> None:
    """Each off behind a supported label of round 17's step 2 is visible
    here: the profile and capability hold an off record from every off
    source capability_sources names, and at least one on record (round 22:
    the device file shows both sides)."""
    for (profile_id, capability), sources in sorted(labels.items()):
        records = profiles.get(profile_id, {}).get(capability, [])
        if not any(record["state"] == "on" for record in records):
            raise ValidationError(
                f"{path}: {profile_id} {capability} is supported against an off, but the file has no on record"
            )
        for source in sources:
            if not any(record["state"] == "off" and record["source"] == source for record in records):
                raise ValidationError(
                    f"{path}: {profile_id} {capability} is supported against an off from "
                    f"{source}, but the file has no off record from it"
                )


def check_old_off_labels(
    path: Path,
    labels: dict[tuple[str, str], list[str]],
    profiles: dict[str, Any],
) -> None:
    """Each supported label of round 32's old-off clause (the gate's reason
    off_older_than_five_years) has at least one on record here, and no off
    record: rule 7 withholds every off behind it, so an off record would be
    a current off that the label hides."""
    for (profile_id, capability), _sources in sorted(labels.items()):
        records = profiles.get(profile_id, {}).get(capability, [])
        if not any(record["state"] == "on" for record in records):
            raise ValidationError(
                f"{path}: {profile_id} {capability} is supported against an off older than "
                "five years, but the file has no on record"
            )
        offs = sorted({record["source"] for record in records if record["state"] == "off"})
        if offs:
            raise ValidationError(
                f"{path}: {profile_id} {capability} is supported against an off older than "
                f"five years, but the file has an off record from {', '.join(offs)}"
            )


def validate(root: Path, freshness: str, require: bool) -> str:
    path = root / VARIANTS_PATH
    if not path.exists():
        if require:
            raise ValidationError(f"{path}: missing")
        evidence_path = root / "generated/evidence-index.json"
        if evidence_path.exists():
            published = {item["profile_id"]: item for item in load_json(evidence_path)["profiles"]}
            labels = device_backed_labels(published)
            old_off = device_backed_labels(published, validate_public_carrier_data.OFF_OLDER_THAN_FIVE_YEARS)
            if labels or old_off:
                raise ValidationError(
                    f"{path}: missing, but {len(labels)} supported labels keep their off as device "
                    f"records and {len(old_off)} rest on on records against an off older than five years"
                )
        return f"no {VARIANTS_PATH}; nothing to check"
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValidationError(f"{path}: {len(raw)} bytes is over the {MAX_BYTES} byte guard")
    data = load_json(path)
    if raw != canonical_bytes(data):
        raise ValidationError(f"{path}: not canonical JSON (sorted keys, compact, one trailing newline)")
    if not isinstance(data, dict) or set(data) != TOP_LEVEL_FIELDS:
        raise ValidationError(f"{path}: top-level fields must be exactly {sorted(TOP_LEVEL_FIELDS)}")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValidationError(f"{path}: schema_version must be {SCHEMA_VERSION}")
    if not isinstance(data["description"], str) or not data["description"]:
        raise ValidationError(f"{path}: description must be a non-empty string")
    if data["capabilities"] != CAPABILITIES:
        raise ValidationError(f"{path}: capabilities must be exactly {CAPABILITIES}")
    metadata = load_json(root / "generated/android/metadata.json")
    if not isinstance(data["based_on_data_digest"], str) or not DIGEST_RE.fullmatch(data["based_on_data_digest"]):
        raise ValidationError(f"{path}: based_on_data_digest must be sha256:<64 hex>")
    if data["based_on_data_digest"] != metadata.get("data_digest"):
        raise ValidationError(f"{path}: based_on_data_digest is not generated/android/metadata.json's data_digest")
    index = load_json(root / "generated/index.json")
    window = parse_freshness_window(path, data)
    if window is None or (data["checks_through"], data["stale_after"]) != (index["checks_through"], index["stale_after"]):
        raise ValidationError(f"{path}: checks_through and stale_after must equal generated/index.json's")
    paths = {item["profile_id"]: item["path"] for item in index["profiles"]}
    evidence = {
        item["profile_id"]: item
        for item in load_json(root / "generated/evidence-index.json")["profiles"]
    }
    android_ids, samsung_models = catalog_devices(root)
    floor = rule7_floor(window.checks_through)
    profiles = data["profiles"]
    if not isinstance(profiles, dict):
        raise ValidationError(f"{path}: profiles must be an object")
    records = cells = 0
    devices_seen: set[str] = set()
    for profile_id, capabilities in profiles.items():
        where = f"{path}: {profile_id}"
        if profile_id not in paths:
            raise ValidationError(f"{where}: not a published profile in generated/index.json")
        if not isinstance(capabilities, dict) or not capabilities:
            raise ValidationError(f"{where}: must map capabilities to records")
        profile_evidence = evidence.get(profile_id, {})
        for capability, items in capabilities.items():
            here = f"{where} {capability}"
            if capability not in CAPABILITIES:
                raise ValidationError(f"{here}: not one of {CAPABILITIES}")
            if not isinstance(items, list) or not items:
                raise ValidationError(f"{here}: must be a non-empty list of records")
            seen: dict[tuple[str, str], str] = {}
            for item in items:
                record = validate_record(
                    here,
                    item,
                    capability,
                    android_ids,
                    samsung_models,
                    floor,
                    profile_evidence.get("capability_sources", {}).get(capability, {}),
                    profile_evidence.get("capability_basis", {}).get(capability),
                )
                for device in record["devices"]:
                    key = (device, record["stack"])
                    if key in seen:
                        raise ValidationError(f"{here}: {device} ({record['stack']}) has two records")
                    seen[key] = record["state"]
                    devices_seen.add(device)
                records += 1
                cells += len(record["devices"])
            if items != sorted(items, key=record_order):
                raise ValidationError(f"{here}: records are not in (state, source, stack, newest_entry) order")
    labels = device_backed_labels(evidence)
    check_device_backed_labels(path, labels, profiles)
    old_off = device_backed_labels(evidence, validate_public_carrier_data.OFF_OLDER_THAN_FIVE_YEARS)
    check_old_off_labels(path, old_off, profiles)
    check_freshness(window, freshness)
    return (
        f"validated {records} device records ({cells} device values) for "
        f"{len(devices_seen)} devices on {len(profiles)} profiles; "
        f"{len(labels)} supported labels keep their off as device records; "
        f"{len(old_off)} supported labels have only offs older than five years"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--freshness", choices=FRESHNESS_MODES, default="warn")
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    parser.add_argument("--require", action="store_true", help="fail when the file is missing")
    args = parser.parse_args(argv[1:])
    validate_public_carrier_data.TODAY_OVERRIDE = args.today
    print(validate(args.root, args.freshness, args.require))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
