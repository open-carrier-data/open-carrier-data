#!/usr/bin/env python3
"""Compare another apns-conf.xml, or a directory of them, with the generated one."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

Scope = tuple[str, str, str, str]
Key = tuple[str, str, str, str, str]


def xml_paths(source: Path) -> list[Path]:
    if source.is_dir():
        return sorted(path for path in source.glob("*.xml") if path.is_file())
    return [source]


def load_rows(source: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in xml_paths(source):
        root = ET.parse(path).getroot()
        rows.extend(dict(element.attrib) for element in root.iter("apn"))
    return rows


def row_scope(row: dict[str, str]) -> Scope:
    return (
        row.get("mcc", "") + row.get("mnc", ""),
        row.get("mvno_type", "").casefold(),
        row.get("mvno_match_data", "").casefold(),
        row.get("apn", "").strip().casefold(),
    )


def row_types(row: dict[str, str]) -> str:
    return ",".join(sorted(part.strip() for part in row.get("type", "").split(",") if part.strip()))


def row_key(row: dict[str, str]) -> Key:
    return (*row_scope(row), row_types(row))


def compare(theirs: list[dict[str, str]], ours: list[dict[str, str]], mccmnc: set[str]) -> dict[str, Any]:
    if mccmnc:
        theirs = [row for row in theirs if row_scope(row)[0] in mccmnc]
        ours = [row for row in ours if row_scope(row)[0] in mccmnc]
    their_keys = {row_key(row) for row in theirs}
    our_keys = {row_key(row) for row in ours}
    their_scopes = {row_scope(row) for row in theirs}
    our_scopes = {row_scope(row) for row in ours}
    their_networks = {row_scope(row)[0] for row in theirs}
    our_networks = {row_scope(row)[0] for row in ours}

    def describe(row: dict[str, str]) -> dict[str, str]:
        scope = row_scope(row)
        return {
            "mccmnc": scope[0],
            "mvno_type": row.get("mvno_type", ""),
            "mvno_match_data": row.get("mvno_match_data", ""),
            "apn": row.get("apn", ""),
            "type": row_types(row),
            "carrier": row.get("carrier", ""),
        }

    seen: set[Key] = set()
    only_ours = []
    for row in ours:
        key = row_key(row)
        if key in their_keys or key in seen:
            continue
        seen.add(key)
        only_ours.append(describe(row))
    seen = set()
    only_theirs = []
    for row in theirs:
        key = row_key(row)
        if key in our_keys or key in seen:
            continue
        seen.add(key)
        item = describe(row)
        if scope_of(item) in our_scopes:
            item["difference"] = "types"
        elif item["mccmnc"] in our_networks:
            item["difference"] = "apn"
        else:
            item["difference"] = "network"
        only_theirs.append(item)
    return {
        "their_rows": len(theirs),
        "our_rows": len(ours),
        "shared_rows": len(their_keys & our_keys),
        "networks_only_ours": sorted(our_networks - their_networks),
        "networks_only_theirs": sorted(their_networks - our_networks),
        "rows_only_ours": only_ours,
        "rows_only_theirs": only_theirs,
    }


def scope_of(item: dict[str, str]) -> Scope:
    return (
        item["mccmnc"],
        item["mvno_type"].casefold(),
        item["mvno_match_data"].casefold(),
        item["apn"].strip().casefold(),
    )


def print_summary(report: dict[str, Any]) -> None:
    by_difference: dict[str, int] = defaultdict(int)
    for item in report["rows_only_theirs"]:
        by_difference[item["difference"]] += 1
    print(f"their rows: {report['their_rows']}")
    print(f"our rows: {report['our_rows']}")
    print(f"rows in both, by network, MVNO selector, APN, and types: {report['shared_rows']}")
    print(f"rows only in ours: {len(report['rows_only_ours'])}")
    print(
        f"rows only in theirs: {len(report['rows_only_theirs'])} "
        f"(same APN with other types: {by_difference['types']}, "
        f"APN we lack: {by_difference['apn']}, network we lack: {by_difference['network']})"
    )
    print(f"networks only in ours: {len(report['networks_only_ours'])}")
    print(f"networks only in theirs: {len(report['networks_only_theirs'])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theirs", type=Path, help="an apns-conf.xml or a directory of per-country XML files")
    parser.add_argument("--ours", type=Path, default=Path("generated/android/apns-conf.xml"))
    parser.add_argument("--mccmnc", action="append", default=[], help="limit the comparison to these networks")
    parser.add_argument("--json", type=Path, help="write the full report here")
    args = parser.parse_args(argv[1:])
    report = compare(load_rows(args.theirs), load_rows(args.ours), set(args.mccmnc))
    print_summary(report)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
