#!/usr/bin/env python3
"""Regression tests for neutral carrier profile matching."""

from __future__ import annotations

import resolve_carrier_profiles as resolver


def profile(profile_id: str, match: dict) -> dict:
    return {"profile_id": profile_id, "match": match}


def main() -> int:
    lookup = {
        "profiles": [
            profile("generic", {"mccmnc": ["26202"]}),
            profile("spn", {"mccmnc": ["26202"], "spn": ["Example"]}),
            profile(
                "spn-and-id",
                {
                    "mccmnc": ["26202"],
                    "spn": ["Example"],
                    "android_carrier_ids": [42],
                },
            ),
            profile("other", {"mccmnc": ["26203"]}),
        ]
    }
    matched = resolver.resolve(
        lookup,
        {"mccmnc": "26202", "spn": "example", "android_carrier_id": 42},
    )
    assert [item["profile_id"] for item in matched] == [
        "generic",
        "spn",
        "spn-and-id",
    ]
    assert [
        item["profile_id"]
        for item in resolver.resolve(lookup, {"mccmnc": "26202"})
    ] == ["generic"]
    assert resolver.imsi_pattern_matches("26202x1", "262029123456789")
    assert not resolver.imsi_pattern_matches("26202x1", "262029223456789")
    assert resolver.any_prefix_matches(["aB"], "AB12")
    print("carrier profile resolver tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
