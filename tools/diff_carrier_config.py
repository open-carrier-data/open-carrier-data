#!/usr/bin/env python3
"""Compare two `carrier-config-list.xml` files key by key (rule decisions of
2026-10-18, round 20). Report only: it never fails on a difference.

usage: diff_carrier_config.py OLD_XML NEW_XML [--json PATH]

A block is keyed by its filter attributes: every attribute of
`<carrier_config>` except `name`, which Android does not match on. A key line
is added, removed or changed within a block; the lines of a block that only
one file has count as added or removed.

The safety class (SAFETY_CLASS_PATTERN: key names with `emergency`, `e911` or
`ecbm`, the WPS, TTY and RTT keys, and `iwlan.*`; rounds 10 and 18) is listed
in full, line by line. Every other key gets one count line: lines added,
removed and changed. `--json` writes every change of every key.

Exit 0 after a comparison, 2 on any error (a missing or malformed file).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any
import xml.etree.ElementTree as ET

SAFETY_CLASS_PATTERN = re.compile(r"emergency|e911|ecbm|wps|tty|rtt|^iwlan\.", re.IGNORECASE)
# Attributes of <carrier_config> that are not filters.
NOT_FILTERS = frozenset({"name"})

Block = tuple[tuple[str, str], ...]


def safety_class(key: str) -> bool:
    return bool(SAFETY_CLASS_PATTERN.search(key))


def value_of(element: ET.Element) -> str:
    """One key line's value as text: a scalar's `value`, a string's text, an
    array's items in order."""
    if element.tag.endswith("-array"):
        return "[" + ", ".join(str(item.get("value", "")) for item in element) + "]"
    if element.tag == "string":
        return element.text or ""
    return str(element.get("value", ""))


def read_blocks(path: Path) -> dict[Block, dict[str, str]]:
    """Per block filter, its keys and values. A key or a block written twice
    keeps the later value, as Android's putAll does."""
    root = ET.parse(path).getroot()
    if root.tag != "carrier_config_list":
        raise ValueError(f"{path}: root element is <{root.tag}>, not <carrier_config_list>")
    blocks: dict[Block, dict[str, str]] = {}
    for block in root:
        if block.tag != "carrier_config":
            continue
        key = tuple(sorted((name, value) for name, value in block.attrib.items() if name not in NOT_FILTERS))
        values = blocks.setdefault(key, {})
        for element in block:
            name = element.get("name")
            if name is None:
                raise ValueError(f"{path}: a <{element.tag}> without a name")
            values[name] = value_of(element)
    return blocks


def block_text(block: Block) -> str:
    attrs = dict(block)
    head = f"{attrs.pop('mcc', '?')}/{attrs.pop('mnc', '?')}"
    return " ".join([head, *(f"{name}={value}" for name, value in sorted(attrs.items()))])


def compare(old: dict[Block, dict[str, str]], new: dict[Block, dict[str, str]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for block in sorted(set(old) | set(new)):
        before, after = old.get(block, {}), new.get(block, {})
        for key in sorted(set(before) | set(after)):
            if key not in after:
                change = "removed"
            elif key not in before:
                change = "added"
            elif before[key] != after[key]:
                change = "changed"
            else:
                continue
            changes.append({"block": block_text(block), "key": key, "change": change,
                            "old": before.get(key), "new": after.get(key), "safety_class": safety_class(key)})
    return changes


def summary(old: dict[Block, dict[str, str]], new: dict[Block, dict[str, str]],
            changes: list[dict[str, Any]]) -> list[str]:
    def lines(blocks: dict[Block, dict[str, str]]) -> int:
        return sum(len(values) for values in blocks.values())

    def counts(items: list[dict[str, Any]]) -> str:
        n = {kind: sum(1 for item in items if item["change"] == kind) for kind in ("added", "removed", "changed")}
        return f"+{n['added']} -{n['removed']} ~{n['changed']}"

    changed_blocks = {block_text(b) for b in set(old) & set(new) if old[b] != new[b]}
    out = [
        f"blocks: {len(old)} -> {len(new)} ({len(set(new) - set(old))} added, {len(set(old) - set(new))} removed, "
        f"{len(changed_blocks)} changed)",
        f"key lines: {lines(old)} -> {lines(new)} ({counts(changes)})",
    ]
    safety = [item for item in changes if item["safety_class"]]
    out.append(f"safety class (emergency, e911, ecbm, WPS, TTY, RTT, iwlan.*), in full: {counts(safety)}")
    for item in sorted(safety, key=lambda item: (item["key"], item["block"], item["change"])):
        if item["change"] == "added":
            out.append(f"  + {item['block']} {item['key']}={item['new']}")
        elif item["change"] == "removed":
            out.append(f"  - {item['block']} {item['key']}={item['old']}")
        else:
            out.append(f"  ~ {item['block']} {item['key']}: {item['old']} -> {item['new']}")
    per_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in changes:
        if not item["safety_class"]:
            per_key[item["key"]].append(item)
    out.append(f"other keys, lines per key: {len(per_key)} key(s)")
    for key in sorted(per_key):
        out.append(f"  {key}: {counts(per_key[key])}")
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--json", type=Path, help="write every change of every key here")
    args = parser.parse_args(argv[1:])
    old, new = read_blocks(args.old), read_blocks(args.new)
    changes = compare(old, new)
    lines = summary(old, new, changes)
    print("CarrierConfig diff, report only:")
    for line in lines:
        print(f"  {line}")
    if args.json:
        args.json.write_text(json.dumps({"summary": lines, "changes": changes}, indent=2) + "\n", encoding="utf-8")
    return 0


def run(argv: list[str]) -> int:
    """main, with any error, including a SystemExit other than --help, as exit 2."""
    try:
        return main(argv)
    except SystemExit as exc:
        if exc.code == 0 and ("-h" in argv or "--help" in argv):
            return 0
        print(f"CarrierConfig diff: ERROR exit {exc.code}", file=sys.stderr)
        return 2
    except BaseException as exc:
        print(f"CarrierConfig diff: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv))
