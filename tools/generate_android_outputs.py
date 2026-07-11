#!/usr/bin/env python3
"""Generate Android-facing output from public carrier profiles."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def profile_paths(carriers_dir: Path) -> list[Path]:
    return sorted(path for path in carriers_dir.rglob("*.json") if path.is_file())


def attr(name: str, value: Any) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    return f' {name}="{escape(text, {"\"": "&quot;"})}"'


def label_text(profile: dict[str, Any], apn: dict[str, Any]) -> str:
    display_name = str(profile["display_name"]).strip()
    apn_name = str(apn["name"]).strip()
    if display_name.lower() == apn_name.lower():
        return display_name[:120]
    return f"{display_name} {apn_name}"[:120]


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


def apn_records(profile: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    match = profile.get("match", {})
    mccmncs = match.get("mccmnc", [])
    profile_mvnos = profile_apn_mvnos(match)
    if not profile_mvnos:
        return records
    for mccmnc in mccmncs:
        if not isinstance(mccmnc, str) or len(mccmnc) not in {5, 6}:
            continue
        mcc = mccmnc[:3]
        mnc = mccmnc[3:]
        for apn in profile.get("android_apns", []) or []:
            if not isinstance(apn, dict):
                continue
            base = {
                "carrier": label_text(profile, apn),
                "mcc": mcc,
                "mnc": mnc,
                "apn": apn["apn"],
                "type": ",".join(apn["types"]),
            }
            if apn.get("mvno_type") and apn.get("mvno_match_data"):
                mvnos: list[tuple[str, str] | None] = [
                    (str(apn["mvno_type"]), str(apn["mvno_match_data"]))
                ]
            else:
                mvnos = profile_mvnos
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
                "carrier_id",
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
            for mvno in mvnos:
                record = dict(base)
                if mvno:
                    record["mvno_type"] = mvno[0]
                    record["mvno_match_data"] = mvno[1]
                records.append(record)
    return records


def write_apns(path: Path, profiles: list[dict[str, Any]], version: int) -> int:
    records: list[dict[str, str]] = []
    for profile in profiles:
        records.extend(apn_records(profile))
    unique_records = {
        json.dumps(record, sort_keys=True, separators=(",", ":")): record
        for record in records
    }
    records = sorted(
        unique_records.values(),
        key=lambda item: (
            item.get("mcc", ""),
            item.get("mnc", ""),
            item.get("mvno_type", ""),
            item.get("mvno_match_data", ""),
            item.get("apn", ""),
            item.get("type", ""),
        )
    )
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<apns version="{version}">',
    ]
    for record in records:
        attrs = "".join(attr(key, record[key]) for key in sorted(record))
        lines.append(f"  <apn{attrs} />")
    lines.append("</apns>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(records)


def write_lookup(path: Path, carriers_dir: Path, profile_items: list[tuple[Path, dict[str, Any]]]) -> None:
    profiles = []
    for profile_path, profile in profile_items:
        profiles.append(lookup_record(carriers_dir, profile_path, profile))
    value = {"schema_version": 1, "profiles": profiles}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def lookup_record(carriers_dir: Path, profile_path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": profile["profile_id"],
        "display_name": profile["display_name"],
        "path": profile_path.relative_to(carriers_dir.parent).as_posix(),
        "match": profile["match"],
        "capabilities": profile["capabilities"],
        "android_apn_count": len(profile.get("android_apns", []) or []),
        "has_android_carrier_config": bool(profile.get("android_carrier_config")),
    }


def mccmnc_index_record(carriers_dir: Path, profile_path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": profile["profile_id"],
        "display_name": profile["display_name"],
        "path": profile_path.relative_to(carriers_dir.parent).as_posix(),
        "match": profile["match"],
    }


def write_mccmnc_index(
    path: Path,
    carriers_dir: Path,
    profile_items: list[tuple[Path, dict[str, Any]]],
) -> int:
    index: dict[str, list[dict[str, Any]]] = {}
    for profile_path, profile in profile_items:
        match = profile.get("match", {})
        mccmncs = match.get("mccmnc", []) if isinstance(match, dict) else []
        if not isinstance(mccmncs, list):
            continue
        record = mccmnc_index_record(carriers_dir, profile_path, profile)
        valid_mccmncs = sorted(
            mccmnc
            for mccmnc in set(mccmncs)
            if isinstance(mccmnc, str) and len(mccmnc) in {5, 6}
        )
        for mccmnc in valid_mccmncs:
            index.setdefault(mccmnc, []).append(record)
    for records in index.values():
        records.sort(key=lambda item: (item["profile_id"], item["display_name"]))
    value = {"schema_version": 1, "mccmnc": dict(sorted(index.items()))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(index)


def write_carrier_id_index(
    path: Path,
    carriers_dir: Path,
    profile_items: list[tuple[Path, dict[str, Any]]],
) -> int:
    index: dict[str, list[dict[str, Any]]] = {}
    for profile_path, profile in profile_items:
        match = profile.get("match", {})
        carrier_ids = match.get("android_carrier_ids", []) if isinstance(match, dict) else []
        if not isinstance(carrier_ids, list):
            continue
        record = mccmnc_index_record(carriers_dir, profile_path, profile)
        valid_carrier_ids = sorted(
            carrier_id
            for carrier_id in set(carrier_ids)
            if isinstance(carrier_id, int) and not isinstance(carrier_id, bool)
        )
        for carrier_id in valid_carrier_ids:
            index.setdefault(str(carrier_id), []).append(record)
    for records in index.values():
        records.sort(key=lambda item: (item["profile_id"], item["display_name"]))
    value = {"schema_version": 1, "android_carrier_ids": dict(sorted(index.items()))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(index)


def write_carrier_config(path: Path, profiles: list[dict[str, Any]]) -> int:
    records = []
    for profile in profiles:
        config = profile.get("android_carrier_config")
        if not config:
            continue
        records.append(
            {
                "profile_id": profile["profile_id"],
                "display_name": profile["display_name"],
                "match": profile["match"],
                "android_carrier_config": config,
            }
        )
    value = {"schema_version": 1, "profiles": records}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(records)


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
        if isinstance(value, bool):
            lines.append(f"    <boolean{attr('name', key)}{attr('value', value)} />")
        elif isinstance(value, int) and not isinstance(value, bool):
            lines.append(f"    <int{attr('name', key)}{attr('value', value)} />")
        elif isinstance(value, str):
            lines.append(f"    <string{attr('name', key)}>{escape(value)}</string>")
        elif isinstance(value, list):
            if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
                lines.append(f"    <int-array{attr('name', key)}{attr('num', len(value))}>")
                for item in value:
                    lines.append(f"      <item{attr('value', item)} />")
                lines.append("    </int-array>")
            elif all(isinstance(item, str) for item in value):
                lines.append(f"    <string-array{attr('name', key)}{attr('num', len(value))}>")
                for item in value:
                    lines.append(f"      <item{attr('value', item)} />")
                lines.append("    </string-array>")
    return lines


def write_carrier_config_xml(path: Path, profiles: list[dict[str, Any]]) -> int:
    blocks: list[tuple[str, dict[str, str], list[str]]] = []
    for profile in profiles:
        config = profile.get("android_carrier_config")
        if not isinstance(config, dict) or not config:
            continue
        config_lines = config_xml_lines(config)
        if not config_lines:
            continue
        for filters in config_filter_records(profile):
            blocks.append((str(profile["profile_id"]), filters, config_lines))

    blocks.sort(
        key=lambda item: (
            item[1].get("cid", ""),
            item[1].get("mcc", ""),
            item[1].get("mnc", ""),
            item[1].get("spn", ""),
            item[1].get("gid1", ""),
            item[0],
        )
    )
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<carrier_config_list>",
    ]
    for profile_id, filters, config_lines in blocks:
        lines.append(f"  <!-- {escape(profile_id)} -->")
        attrs = "".join(attr(key, filters[key]) for key in sorted(filters))
        lines.append(f"  <carrier_config{attrs}>")
        lines.extend(config_lines)
        lines.append("  </carrier_config>")
    lines.append("</carrier_config_list>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(blocks)


def write_metadata(
    path: Path,
    profiles: list[dict[str, Any]],
    apn_version: int,
    apn_count: int,
    config_xml_count: int,
) -> None:
    apn_unrepresentable = sum(
        1
        for profile in profiles
        if profile.get("android_apns") and not profile_apn_mvnos(profile.get("match", {}))
    )
    config_unrepresentable = sum(
        1
        for profile in profiles
        if profile.get("android_carrier_config") and not config_filter_records(profile)
    )
    value = {
        "schema_version": 1,
        "target": {
            "apn_database_version": apn_version,
            "carrier_config_gid_matching": "exact_only",
        },
        "output": {
            "apn_row_count": apn_count,
            "carrier_config_xml_block_count": config_xml_count,
        },
        "omissions": {
            "apn_profiles_with_unrepresentable_match": apn_unrepresentable,
            "carrier_config_profiles_with_unrepresentable_match": config_unrepresentable,
        },
    }
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
    args = parser.parse_args(argv[1:])
    if args.apn_version < 1:
        parser.error("--apn-version must be a positive integer")
    carriers_dir = args.carriers_dir
    generated_dir = args.generated_dir
    profile_items = [(path, load_json(path)) for path in profile_paths(carriers_dir)]
    profiles = [profile for _, profile in profile_items]
    apn_count = write_apns(
        generated_dir / "android" / "apns-conf.xml",
        profiles,
        args.apn_version,
    )
    write_lookup(generated_dir / "android" / "lookup.json", carriers_dir, profile_items)
    mccmnc_count = write_mccmnc_index(
        generated_dir / "android" / "mccmnc-index.json",
        carriers_dir,
        profile_items,
    )
    carrier_id_count = write_carrier_id_index(
        generated_dir / "android" / "carrier-id-index.json",
        carriers_dir,
        profile_items,
    )
    config_count = write_carrier_config(
        generated_dir / "android" / "carrier-config-overrides.json",
        profiles,
    )
    config_xml_count = write_carrier_config_xml(
        generated_dir / "android" / "carrier-config-list.xml",
        profiles,
    )
    write_metadata(
        generated_dir / "android" / "metadata.json",
        profiles,
        args.apn_version,
        apn_count,
        config_xml_count,
    )
    print(
        f"generated Android output for {len(profiles)} profile(s): "
        f"{apn_count} APN row(s), {config_count} CarrierConfig profile(s), "
        f"{mccmnc_count} MCC/MNC key(s), {carrier_id_count} Android carrier ID key(s), "
        f"{config_xml_count} CarrierConfig XML block(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
