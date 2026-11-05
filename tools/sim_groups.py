#!/usr/bin/env python3
"""Which brands a SIM group holds, and whether OCD can tell them apart.

Migration step 6 (rule round 47, item 4). generated/operators/sim-groups.json
links each OCD profile that the carrier-identity table reaches to its brand or
brands, with a tellable value:

  yes        the profile is one entry's alone: the same test tools/two_answers.py
             uses before a brand's statement may speak for it.
  ambiguous  two or more entries share the profile, a crossing rule of another
             entry shares some of its SIMs, or another entry's rule sits inside
             it, so a SIM without the narrower field could be either: GID1 44
             with no SPN could be congstar or fraenk.
  no         a plain profile on a network with host-only brands: no source gives
             a selector, so OCD does not tell them apart; the SIM may still show
             a name (LIDL Connect on 262-02).

The file is a view of the identity table, entities.json and the profiles, so it
is derived, never edited, and validate rebuilds and compares it. It changes no
profile: the table's rule stands that it never changes OCD's matcher (rule round
32). core and same_subscribers stay recorded links on entities.json's brands;
nothing reads them to carry a value or an answer across, and no observed_only
group exists, because no ruling allows one yet.

  write [--root DIR]    write the file
  check [--root DIR]    fail unless the file equals what this tool derives

Only the standard library is used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import profile_ids  # noqa: E402
import two_answers  # noqa: E402
import validate_public_carrier_data as carrier_validator  # noqa: E402

FILE = "generated/operators/sim-groups.json"
SCHEMA = "operator-sim-groups.schema.json"
DESCRIPTION = (
    "Migration step 6 of the device > carrier > plan model (rule round 47, item 4): which brands each OCD profile holds, "
    "from the carrier-identity table. tellable says whether OCD can tell them apart: yes, the profile is one entry's alone; "
    "ambiguous, entries may share its SIMs; no, a plain profile on a network with host-only brands: no source gives a selector, "
    "so OCD does not tell them apart; the SIM may still show a name. A profile the table does not "
    "reach has no row, which says nothing about its brand. Nothing here changes a match, a value or a phone. OCD Android reads "
    "this file for the plan picker only, and no carrier settings component reads it. The dated host links, core and same_subscribers are on the brands in entities.json."
)


def sharing_keys(identity: two_answers.Identity, listing: list[str], match: dict[str, Any]) -> set[str]:
    """The other entries that may hold some of this rule's SIMs: a crossing rule,
    as Identity.brand_alone finds it, or a rule inside this one."""
    found: set[str] = set()
    for other, rule in identity.selectors:
        if other["key"] in listing or not profile_ids.rules_overlap(rule, match):
            continue
        if profile_ids.rule_implies(rule, match):
            found.add(other["key"])
        elif not profile_ids.rule_implies(match, rule) and profile_ids.dimensions(rule) == profile_ids.dimensions(match):
            found.add(other["key"])
    return found


def row_of(profile_id: str, match: dict[str, Any], identity: two_answers.Identity) -> dict[str, Any] | None:
    listing = sorted({entry["key"] for entry in identity.listing.get(profile_id, [])})
    if identity.plain(match):
        riding = {entry["key"] for entry in identity.host_only_on([str(code) for code in match["mccmnc"]])}
        brands = sorted(set(listing) | riding)
        tellable = "no" if riding else "yes"
    elif not listing:
        return None
    else:
        sharing = sharing_keys(identity, listing, match)
        brands = sorted(set(listing) | sharing)
        tellable = "yes" if len(brands) == 1 else "ambiguous"
    if not brands:
        return None
    return {"profile_id": profile_id, "brands": brands, "tellable": tellable}


def build(root: Path) -> dict[str, Any]:
    profiles = two_answers.load_profiles(root)
    matches = {pid: profile["match"] for pid, (_, profile) in profiles.items()}
    identity = two_answers.load_identity(root, matches)
    rows = [row for row in (row_of(pid, matches[pid], identity) for pid in sorted(matches)) if row]
    tally = {name: sum(1 for row in rows if row["tellable"] == name) for name in ("yes", "ambiguous", "no")}
    return {
        "schema_version": 1,
        "description": DESCRIPTION,
        "license": "CC0-1.0",
        "counts": {"profiles": len(rows), **tally},
        "profiles": rows,
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
        return [f"{FILE}: differs from what tools/sim_groups.py derives; run tools/sim_groups.py write"]
    return []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("write", "check"))
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    if args.command == "write":
        document = build(args.root)
        (args.root / FILE).write_text(dump(document), encoding="utf-8")
        print(f"sim groups: {document['counts']}")
        return 0
    found = problems(args.root)
    for line in found[:50]:
        print(line, file=sys.stderr)
    if found:
        return 1
    print("sim groups: valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
