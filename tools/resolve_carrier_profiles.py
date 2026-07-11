#!/usr/bin/env python3
"""Resolve all public carrier profiles matching a SIM/network identity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


MATCH_DIMENSIONS = (
    "gid1_prefixes",
    "gid2_prefixes",
    "iccid_prefixes",
    "imsi_prefix_patterns",
    "spn",
    "android_carrier_ids",
)


def imsi_pattern_matches(pattern: str, imsi: str) -> bool:
    if len(imsi) < len(pattern):
        return False
    return all(
        expected.lower() == "x" or expected == actual
        for expected, actual in zip(pattern, imsi)
    )


def any_prefix_matches(prefixes: list[Any], value: str) -> bool:
    normalized = value.casefold()
    return any(
        isinstance(prefix, str) and normalized.startswith(prefix.casefold())
        for prefix in prefixes
    )


def profile_matches(match: dict[str, Any], identity: dict[str, Any]) -> bool:
    if identity.get("mccmnc") not in match.get("mccmnc", []):
        return False

    for key, identity_key in (
        ("gid1_prefixes", "gid1"),
        ("gid2_prefixes", "gid2"),
        ("iccid_prefixes", "iccid"),
    ):
        expected = match.get(key, [])
        if expected and (
            not isinstance(identity.get(identity_key), str)
            or not any_prefix_matches(expected, identity[identity_key])
        ):
            return False

    expected_spns = match.get("spn", [])
    if expected_spns and (
        not isinstance(identity.get("spn"), str)
        or identity["spn"].casefold()
        not in {str(value).casefold() for value in expected_spns}
    ):
        return False

    expected_imsis = match.get("imsi_prefix_patterns", [])
    if expected_imsis and (
        not isinstance(identity.get("imsi"), str)
        or not any(
            isinstance(pattern, str)
            and imsi_pattern_matches(pattern, identity["imsi"])
            for pattern in expected_imsis
        )
    ):
        return False

    expected_carrier_ids = match.get("android_carrier_ids", [])
    if expected_carrier_ids and identity.get("android_carrier_id") not in expected_carrier_ids:
        return False
    return True


def specificity(match: dict[str, Any]) -> int:
    return sum(bool(match.get(key)) for key in MATCH_DIMENSIONS)


def resolve(lookup: dict[str, Any], identity: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = lookup.get("profiles", [])
    if not isinstance(profiles, list):
        raise ValueError("lookup.profiles must be a list")
    matches = [
        profile
        for profile in profiles
        if isinstance(profile, dict)
        and isinstance(profile.get("match"), dict)
        and profile_matches(profile["match"], identity)
    ]
    return sorted(
        matches,
        key=lambda profile: (
            specificity(profile["match"]),
            str(profile.get("profile_id", "")),
        ),
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookup", type=Path, default=Path("generated/android/lookup.json"))
    parser.add_argument("--mccmnc", required=True)
    parser.add_argument("--spn")
    parser.add_argument("--gid1")
    parser.add_argument("--gid2")
    parser.add_argument("--iccid")
    parser.add_argument("--imsi")
    parser.add_argument("--android-carrier-id", type=int)
    args = parser.parse_args(argv[1:])
    lookup = json.loads(args.lookup.read_text(encoding="utf-8"))
    identity = {
        key: value
        for key, value in {
            "mccmnc": args.mccmnc,
            "spn": args.spn,
            "gid1": args.gid1,
            "gid2": args.gid2,
            "iccid": args.iccid,
            "imsi": args.imsi,
            "android_carrier_id": args.android_carrier_id,
        }.items()
        if value is not None
    }
    print(
        json.dumps(
            {
                "schema_version": 1,
                "resolution_order": "generic_to_specific",
                "profiles": resolve(lookup, identity),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
