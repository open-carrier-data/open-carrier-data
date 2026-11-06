#!/usr/bin/env python3
"""Keep generated/devices/carrier-variants.json on the generator's data_digest.

A reader takes metadata.json, the dataset manifest and carrier-variants.json as
one state only when all three name one data_digest. The generator writes the
first and tools/ocd_dataset.py the second, but the private publisher writes the
third, so a refresh of a branch whose tools move the digest left it behind. Its
records are not part of the digest, and such a change moves none of them, so
stamping the new digest is all it needs. This is the edit that pull requests
such as #317 and #408 made by hand.

  digest_chain.py stamp --root .   write metadata.json's digest into the records
  digest_chain.py check --root .   exit 1 unless all three name one digest

A repository without the records file stamps nothing and checks the other two,
as tools/validate_carrier_variants.py passes it without --require. This tool is
not an input of data_digest, and the refresh bot runs it with no packages
installed: it needs the standard library and the tools beside it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

from validate_carrier_variants import VARIANTS_PATH, canonical_bytes

METADATA_PATH = Path("generated/android/metadata.json")
MANIFEST_PATH = Path("generated/ocd-dataset/manifest.json")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class DigestChainError(Exception):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DigestChainError(f"{path}: cannot be read: {exc}") from exc
    if not isinstance(data, dict):
        raise DigestChainError(f"{path}: is not a JSON object")
    return data


def generator_digest(root: Path) -> str:
    digest = read_json(root / METADATA_PATH).get("data_digest")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise DigestChainError(f"{METADATA_PATH}: data_digest is missing or malformed")
    return digest


def stamp(root: Path) -> bool:
    """Write the generator's digest into the records; True when the file changed.
    Nothing else in the file moves, and a file already in step is left alone."""
    digest = generator_digest(root)
    path = root / VARIANTS_PATH
    if not path.is_file():
        return False
    data = read_json(path)
    if "based_on_data_digest" not in data:
        raise DigestChainError(f"{VARIANTS_PATH}: has no based_on_data_digest")
    if data["based_on_data_digest"] == digest:
        return False
    data["based_on_data_digest"] = digest
    path.write_bytes(canonical_bytes(data))
    return True


def problems(root: Path) -> list[str]:
    digest = generator_digest(root)
    named = {str(MANIFEST_PATH): read_json(root / MANIFEST_PATH).get("data_digest")}
    if (root / VARIANTS_PATH).is_file():
        named[str(VARIANTS_PATH)] = read_json(root / VARIANTS_PATH).get("based_on_data_digest")
    return [f"{path}: names {value}, {METADATA_PATH} names {digest}" for path, value in named.items() if value != digest]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("stamp", "check"))
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv[1:])
    try:
        if args.command == "stamp":
            print(f"{VARIANTS_PATH}: {'stamped' if stamp(args.root) else 'in step, not written'}")
            return 0
        found = problems(args.root)
    except DigestChainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for line in found:
        print(f"error: {line}", file=sys.stderr)
    if not found:
        print("one data_digest across metadata.json, the manifest and carrier-variants.json")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
