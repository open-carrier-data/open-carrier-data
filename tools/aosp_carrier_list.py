#!/usr/bin/env python3
"""Android's carrier ID table, pinned for OCD's resolution order (rule round 45, item 3).

OCD ranks a profile that names Android carrier IDs by the weight of Android's
own rule behind that ID (CarrierResolver.CarrierMatchingRule). The phone's
OcdCarrierSettings reads those rules from the phone's table
(content://carrier_id/all); the public resolver, lookup.json's `weight` and
the golden vectors read the same rules from tools/aosp/carrier-id-table.json,
which this tool writes from the AOSP carrier list of the ROM's Android
version (TelephonyProvider assets/latest_carrier_id/carrier_list.textpb).

  import TEXTPB --commit SHA --tree TEXT [--out tools/aosp/carrier-id-table.json]
      Expands every carrier_attribute into the rows CarrierIdProvider stores
      (one row per combination of its repeated fields, GID1, GID2 and SPN in
      lower case, duplicates once) and writes them, one row per line.

The rows carry the AOSP carrier list's own values (Apache-2.0, the Android
Open Source Project). Only the standard library is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

TABLE = Path(__file__).resolve().parent / "aosp" / "carrier-id-table.json"
SCHEMA = "ocd-aosp-carrier-id-table/1"

# CarrierIdProvider's column for each repeated field of a carrier_attribute,
# in the order convertCarrierAttrToContentValues walks them.
FIELDS = (
    ("mccmnc_tuple", "mccmnc"),
    ("imsi_prefix_xpattern", "imsi_prefix_xpattern"),
    ("gid1", "gid1"),
    ("gid2", "gid2"),
    ("plmn", "plmn"),
    ("spn", "spn"),
    ("preferred_apn", "apn"),
    ("iccid_prefix", "iccid_prefix"),
    ("privilege_access_rule", "privilege_access_rule"),
)
LOWER_CASE = frozenset({"gid1", "gid2", "spn"})
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}]|[A-Za-z_][A-Za-z0-9_]*\s*:?|-?[0-9]+')


def parse_textpb(text: str) -> dict[str, list[Any]]:
    """The protobuf text format of carrier_list.textpb, as nested dicts of lists."""
    tokens = TOKEN.findall(text)
    position = 0

    def block() -> dict[str, list[Any]]:
        nonlocal position
        out: dict[str, list[Any]] = {}
        while position < len(tokens):
            token = tokens[position]
            if token == "}":
                position += 1
                return out
            name = token.rstrip(":").strip()
            position += 1
            if tokens[position] == "{":
                position += 1
                value: Any = block()
            else:
                raw = tokens[position]
                value = json.loads(raw) if raw.startswith('"') else int(raw)
                position += 1
            out.setdefault(name, []).append(value)
        return out

    return block()


def provider_rows(carrier_list: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """The rows CarrierIdProvider.updateDatabaseFromPb inserts."""
    rows: list[dict[str, Any]] = []
    for carrier in carrier_list.get("carrier_id", []):
        carrier_id = carrier["canonical_id"][0]
        parent = carrier.get("parent_canonical_id", [0])[0]
        for attribute in carrier.get("carrier_attribute", []):
            combinations: list[dict[str, str]] = [{}]
            for field, column in FIELDS:
                values = attribute.get(field, [])
                if values:
                    combinations = [
                        {**row, column: value.lower() if column in LOWER_CASE else value}
                        for row in combinations
                        for value in values
                    ]
            unique: list[dict[str, str]] = []
            for row in combinations:
                if row not in unique:
                    unique.append(row)
            for row in unique:
                item: dict[str, Any] = {"carrier_id": carrier_id}
                if parent > 0:
                    item["parent_carrier_id"] = parent
                item.update(row)
                rows.append(item)
    return rows


def dump(document: dict[str, Any]) -> str:
    head = {k: v for k, v in document.items() if k != "rows"}
    lines = ",\n".join(json.dumps(row, ensure_ascii=False, separators=(", ", ": ")) for row in document["rows"])
    text = json.dumps(head, ensure_ascii=False, indent=2)
    return text[:-2] + ',\n  "rows": [\n' + lines + "\n  ]\n}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("textpb", type=Path)
    imp.add_argument("--commit", required=True, help="the TelephonyProvider commit the file comes from")
    imp.add_argument("--tree", required=True, help="the Android tree, for example 'LineageOS 24.0'")
    imp.add_argument("--out", type=Path, default=TABLE)
    args = parser.parse_args(argv)
    data = args.textpb.read_bytes()
    carrier_list = parse_textpb(data.decode("utf-8"))
    rows = provider_rows(carrier_list)
    document = {
        "schema": SCHEMA,
        "about": "Android's carrier ID table as CarrierIdProvider stores it, expanded from the AOSP carrier list "
                 "(Apache-2.0, the Android Open Source Project). OCD ranks a carrier-ID selector by the weight of "
                 "the rules behind that ID on the SIM's network (rule round 45, item 3); tools/aosp_carrier_list.py writes this file.",
        "source": {
            "project": "platform/packages/providers/TelephonyProvider",
            "path": "assets/latest_carrier_id/carrier_list.textpb",
            "tree": args.tree,
            "commit": args.commit,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "version": carrier_list["version"][0],
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dump(document), encoding="utf-8")
    print(f"{args.out}: version {document['version']}, {len(carrier_list.get('carrier_id', []))} carrier IDs, {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
