#!/usr/bin/env python3
"""Plan families the SIM itself shows: migration step 7 (rule round 47, item 4).

A plan family is a tariff group a carrier marks on the SIM, the idea behind
Android's specific carrier ID: a child ID with a parent. Round 47 keeps them in
carrier data as today's selectors, so this file makes no new SIM group and
changes no match. It is a label over the profiles that already exist:
generated/operators/plan-families.json lists each child ID of Android's pinned
carrier ID table, its parent, a segment read from its name, and the OCD
profiles whose SIM rule lies inside the child's rules. A plan is never a
matching key, and phones never read this file.

The parent is what Android calls the carrier; a child's rules that no profile
states are counted, not filled in, because a new profile would change what
phones load. The rule's values stay in tools/aosp/carrier-id-table.json and the
profiles, so this file carries no selector.

  write [--root DIR]    write the file
  check [--root DIR]    fail unless the file equals what this tool derives

Only the standard library is used.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import re
import sys
from typing import Any

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import two_answers  # noqa: E402
import validate_public_carrier_data as carrier_validator  # noqa: E402

FILE = "generated/operators/plan-families.json"
SCHEMA = "operator-plan-families.schema.json"
TABLE = TOOLS / "aosp" / "carrier-id-table.json"
NAMES = TOOLS / "aosp" / "carrier-id-names.json"
# Android's row column for each field of a profile's match, in lower case as
# CarrierIdProvider stores GID1, GID2 and the SPN.
COLUMNS = (
    ("gid1_prefixes", "gid1", str.lower),
    ("gid2_prefixes", "gid2", str.lower),
    ("spn", "spn", str.lower),
    ("imsi_prefix_patterns", "imsi_prefix_xpattern", str),
    ("iccid_prefixes", "iccid_prefix", str),
)
ROW_KEYS = ("mccmnc",) + tuple(column for _, column, _ in COLUMNS)
SEGMENTS = (
    (re.compile(r"post-?paid", re.I), "postpaid"),
    (re.compile(r"pre-?paid", re.I), "prepaid"),
    (re.compile(r"\b5G SA\b", re.I), "5g_sa"),
    (re.compile(r"\b5G\b", re.I), "5g"),
    (re.compile(r"\bB2B\b|business", re.I), "business"),
)
DESCRIPTION = (
    "Migration step 7 of the device > carrier > plan model (rule round 47, item 4): the plan families a SIM itself shows, "
    "from the child IDs of Android's pinned carrier ID table, as labels over the OCD profiles that already state their rules. "
    "segment is read from Android's name: prepaid, postpaid, 5g, 5g_sa or business; other marks a child that names something "
    "else, such as a host network. profiles lists the OCD profiles inside the child's rules, parent_profiles the ones that "
    "name the parent's ID, and rules_without_profile counts the child's rules no profile states. A plan family stays a "
    "selector in carrier data: it is never a new SIM group or a matching key, nothing here changes a value, and phones never "
    "read this file."
)


def rule_key(row: dict[str, Any]) -> tuple[str | None, ...]:
    return tuple(row.get(name) for name in ROW_KEYS)


def profile_rule_keys(match: dict[str, Any]) -> set[tuple[str | None, ...]]:
    """The Android rows that would state exactly this profile's rule."""
    axes: list[list[str | None]] = [[str(code) for code in match["mccmnc"]]]
    for field, _column, fold in COLUMNS:
        values = match.get(field)
        axes.append([fold(str(value)) for value in values] if values else [None])
    return set(itertools.product(*axes))


def segment_of(name: str) -> str:
    return next((segment for pattern, segment in SEGMENTS if pattern.search(name)), "other")


def build(root: Path, table: dict[str, Any] | None = None, names: dict[str, Any] | None = None) -> dict[str, Any]:
    table = table if table is not None else two_answers.read_json(TABLE)
    names = names if names is not None else two_answers.read_json(NAMES)
    if names["source_sha256"] != table["source"]["sha256"]:
        raise two_answers.TwoAnswersError("tools/aosp: the names and the table read different lists")
    profiles = {pid: profile["match"] for pid, (_, profile) in two_answers.load_profiles(root).items()}
    rules: dict[int, set[tuple[str | None, ...]]] = {}
    for row in table["rows"]:
        if "parent_carrier_id" in row:
            rules.setdefault(row["carrier_id"], set()).add(rule_key(row))
    families = []
    for child, child_rules in sorted(rules.items()):
        parent = names["parents"][str(child)]
        name = names["names"][str(child)]
        inside = sorted(
            pid for pid, match in profiles.items()
            if child in (match.get("android_carrier_ids") or []) or profile_rule_keys(match) <= child_rules
        )
        stated = set().union(*(profile_rule_keys(profiles[pid]) for pid in inside)) if inside else set()
        families.append({
            "id": f"android.{child}",
            "android_carrier_id": child,
            "name": name,
            "segment": segment_of(name),
            "parent_android_carrier_id": parent,
            "parent_name": names["names"].get(str(parent), ""),
            "profiles": inside,
            "parent_profiles": sorted(pid for pid, match in profiles.items() if parent in (match.get("android_carrier_ids") or [])),
            "rules_without_profile": len(child_rules - stated),
        })
    return {
        "schema_version": 1,
        "description": DESCRIPTION,
        "license": "CC0-1.0",
        "android_carrier_list_version": table["version"],
        "counts": {
            "families": len(families),
            "with_profile": sum(1 for item in families if item["profiles"]),
            "profiles": sum(len(item["profiles"]) for item in families),
        },
        "families": families,
    }


def dump(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def problems(root: Path) -> list[str]:
    path = root / FILE
    if not path.is_file():
        return [f"{FILE}: missing"]
    document = two_answers.read_json(path)
    try:
        carrier_validator.check_against_schema(path, document, SCHEMA)
    except carrier_validator.ValidationError as exc:
        return [str(exc)]
    if path.read_text(encoding="utf-8") != dump(build(root)):
        return [f"{FILE}: differs from what tools/plan_families.py derives; run tools/plan_families.py write"]
    return []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("write", "check"))
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    if args.command == "write":
        document = build(args.root)
        (args.root / FILE).write_text(dump(document), encoding="utf-8")
        print(f"plan families: {document['counts']}")
        return 0
    found = problems(args.root)
    for line in found[:50]:
        print(line, file=sys.stderr)
    if found:
        return 1
    print("plan families: valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
