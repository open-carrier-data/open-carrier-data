#!/usr/bin/env python3
"""Regression tests for neutral carrier profile matching and --explain."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import generate_android_outputs
import resolve_carrier_profiles as resolver
import validate_public_carrier_data


def profile(profile_id: str, match: dict) -> dict:
    return {"profile_id": profile_id, "match": match}


def check_resolution() -> None:
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


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def carrier(match: dict, capabilities: dict, **facts: object) -> dict:
    value = {
        "schema_version": 1,
        "display_name": "Example",
        "match": match,
        "capabilities": capabilities,
        **facts,
    }
    value["profile_id"] = validate_public_carrier_data.canonical_profile_id(match)
    return value


def check_explain() -> None:
    """--explain gives the profile stack, each profile's value and sources for
    every capability, CarrierConfig key and add-on, and the SIM's APN rows in
    file order with the reasons for their order."""
    plain = carrier(
        {"mccmnc": ["26201"]},
        {"volte": "supported", "mms": "supported"},
        android_carrier_config={"carrier_volte_available_bool": True, "maxMessageSize": 300000},
        android_apns=[
            {"name": "Old", "apn": "internet.old.example", "types": ["default", "ia"]},
            {"name": "Web", "apn": "internet.example", "types": ["default", "mms"], "mmsc": "http://mms.example"},
        ],
    )
    brand = carrier(
        {"mccmnc": ["26201"], "spn": ["Brand"]},
        {"volte": "unknown"},
        android_carrier_config={"maxMessageSize": 600000},
        android_apns=[{"name": "Brand", "apn": "brand.example", "types": ["default"]}],
    )
    other = carrier(
        {"mccmnc": ["26202"]},
        {"volte": "supported"},
        android_apns=[{"name": "Other", "apn": "other.example", "types": ["default"]}],
    )
    old_row = generate_android_outputs.apn_fact_key(plain["android_apns"][0], "default")
    old_attach = generate_android_outputs.apn_fact_key(plain["android_apns"][0], "ia")
    evidence = {
        "schema_version": 1,
        "description": "Test evidence.",
        "source_snapshots": [],
        "profiles": sorted(
            [
                {
                    "profile_id": plain["profile_id"],
                    "observation_count": 3,
                    "verified_observation_count": 0,
                    "sources": ["apple_carrier_bundles", "lineageos", "samsung_omc"],
                    "fact_sources": [
                        {
                            "section": "android_apns",
                            "key": old_row,
                            "sources": ["lineageos"],
                        },
                        {
                            "section": "android_apns",
                            "key": old_attach,
                            "sources": ["lineageos"],
                        },
                        {
                            "section": "android_carrier_config",
                            "key": "maxMessageSize",
                            "sources": ["samsung_omc"],
                        },
                    ],
                    "capability_sources": {
                        "mms": {"on": ["lineageos"]},
                        "volte": {"on": ["apple_carrier_bundles", "samsung_omc"]},
                    },
                    "newest_entry": "2026-08",
                },
                {
                    "profile_id": brand["profile_id"],
                    "observation_count": 1,
                    "verified_observation_count": 0,
                    "sources": ["aosp"],
                    "fact_sources": [],
                    "capability_sources": {"volte": {"off": ["aosp"]}},
                    "quality_gates": [
                        {
                            "kind": "quality_gate",
                            "section": "capabilities",
                            "key": "single_family_off:volte",
                            "observed_value_count": 1,
                            "resolution": "omitted_from_stable",
                        }
                    ],
                },
                {
                    "profile_id": other["profile_id"],
                    "observation_count": 1,
                    "verified_observation_count": 0,
                    "sources": ["lineageos"],
                    "fact_sources": [],
                    "capability_sources": {"volte": {"on": ["lineageos"]}},
                },
            ],
            key=lambda item: item["profile_id"],
        ),
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for value in (plain, brand, other):
            write_json(root / "carriers" / validate_public_carrier_data.public_path_for(value["profile_id"]), value)
        write_json(root / "generated" / "evidence-index.json", evidence)
        with contextlib.redirect_stdout(io.StringIO()):
            generate_android_outputs.main(
                ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
            )
        lookup_path = root / "generated" / "android" / "lookup.json"
        lookup = json.loads(lookup_path.read_text(encoding="utf-8"))
        evidence_path = root / "generated" / "evidence-index.json"

        result = resolver.explain(lookup, {"mccmnc": "26201", "spn": "brand"}, root, evidence_path)
        assert [item["profile_id"] for item in result["profiles"]] == [
            plain["profile_id"],
            brand["profile_id"],
        ], result["profiles"]
        assert result["profiles"][0]["newest_entry"] == "2026-08"
        volte = result["capabilities"]["volte"]
        assert volte["answer"] == "unknown" and volte["answer_from"] == brand["profile_id"], volte
        assert volte["by_profile"] == [
            {"profile_id": plain["profile_id"], "value": "supported", "on": ["apple_carrier_bundles", "samsung_omc"]},
            {"profile_id": brand["profile_id"], "value": "unknown", "off": ["aosp"], "gates": ["single_family_off:volte"]},
        ], volte
        assert result["capabilities"]["mms"]["answer"] == "unknown", "only the most specific profile answers"
        size = result["android_carrier_config"]["maxMessageSize"]
        assert size["applied"] == 600000, "the most specific profile's value is applied"
        assert size["by_profile"] == [
            {"profile_id": plain["profile_id"], "value": 300000, "sources": ["samsung_omc"]},
            {"profile_id": brand["profile_id"], "value": 600000, "sources": ["aosp"]},
        ], size
        assert result["android_carrier_config"]["carrier_volte_available_bool"]["by_profile"][0]["sources"] == [
            "apple_carrier_bundles",
            "lineageos",
            "samsung_omc",
        ], "a fact without a fact_sources entry rests on every profile source"
        assert result["apns"]["scope"] == "mvno"
        assert [row["row"]["apn"] for row in result["apns"]["rows"]] == ["brand.example"], (
            "an SPN that has rows gets only its own rows"
        )

        plain_result = resolver.explain(lookup, {"mccmnc": "26201"}, root, evidence_path)
        rows = plain_result["apns"]["rows"]
        assert plain_result["apns"]["scope"] == "network"
        assert [row["row"]["apn"] for row in rows] == ["internet.example", "internet.old.example"], rows
        assert [row["position"] for row in rows] == [1, 2]
        assert rows[0]["lead_type"] == "default"
        assert rows[0]["reasons"]["value_families"] == ["aosp_apn_lists", "apple_carrier_bundles", "samsung_omc"], rows[0]
        assert rows[1]["reasons"]["value_families"] == ["aosp_apn_lists"], rows[1]
        assert rows[1]["reasons"]["row_sources"] == ["lineageos"]
        assert rows[0]["reasons"]["value_from_current_vendor"] is True, rows[0]
        assert rows[0]["reasons"]["row_from_current_vendor"] is True, rows[0]
        assert rows[1]["reasons"]["row_from_current_vendor"] is False, rows[1]
        assert rows[0]["reasons"]["ia_left_out"] is False, rows[0]
        assert rows[1]["reasons"]["value_from_current_vendor"] is False, rows[1]
        assert rows[1]["reasons"]["ia_left_out"] is True, (
            "Samsung gives this network's internet APN, so the LineageOS-only row loses ia"
        )
        assert rows[1]["row"]["type"] == "default", rows[1]
        conf = (root / "generated" / "android" / "apns-conf.xml").read_text(encoding="utf-8")
        assert conf.index('apn="internet.example"') < conf.index('apn="internet.old.example"'), (
            "explain shows the order apns-conf.xml has"
        )

        output = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "resolve_carrier_profiles.py"),
                "--lookup",
                str(lookup_path),
                "--mccmnc",
                "26201",
                "--spn",
                "Brand",
                "--explain",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert json.loads(output)["capabilities"]["volte"]["answer"] == "unknown"


def main() -> int:
    check_resolution()
    check_explain()
    print("carrier profile resolver tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
