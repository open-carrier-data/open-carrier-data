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


def check_explain_shared_file() -> None:
    """--explain names a value Google gives only from its unconfirmed shared
    file (shared_file_unconfirmed); such a value is not a current vendor's."""
    plain = carrier(
        {"mccmnc": ["64004"]},
        {},
        android_apns=[
            {"name": "Wap", "apn": "Wap", "types": ["default"], "proxy": "10.154.0.8", "port": 9401},
            {"name": "Internet", "apn": "internet", "types": ["default"]},
        ],
    )
    wap = generate_android_outputs.apn_fact_key(plain["android_apns"][0], "default")
    internet = generate_android_outputs.apn_fact_key(plain["android_apns"][1], "default")
    evidence = {
        "schema_version": 1,
        "description": "Test evidence.",
        "source_snapshots": [],
        "profiles": [
            {
                "profile_id": plain["profile_id"],
                "observation_count": 3,
                "verified_observation_count": 0,
                "sources": ["google_carriersettings", "lineageos", "mobile_broadband_provider_info"],
                "fact_sources": sorted(
                    [
                        {
                            "section": "android_apns",
                            "key": wap,
                            "sources": ["google_carriersettings"],
                            "shared_file_sources": ["google_carriersettings"],
                        },
                        {
                            "section": "android_apns",
                            "key": internet,
                            "sources": ["lineageos", "mobile_broadband_provider_info"],
                        },
                    ],
                    key=lambda fact: fact["key"],
                ),
                "capability_sources": {},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "carriers" / validate_public_carrier_data.public_path_for(plain["profile_id"]), plain)
        write_json(root / "generated" / "evidence-index.json", evidence)
        with contextlib.redirect_stdout(io.StringIO()):
            generate_android_outputs.main(
                ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
            )
        lookup = json.loads((root / "generated" / "android" / "lookup.json").read_text(encoding="utf-8"))
        result = resolver.explain(lookup, {"mccmnc": "64004"}, root, root / "generated" / "evidence-index.json")
        rows = result["apns"]["rows"]
        assert [row["row"]["apn"] for row in rows] == ["internet", "Wap"], rows
        assert rows[0]["reasons"]["shared_file_unconfirmed"] is False, rows[0]
        assert rows[1]["reasons"]["shared_file_unconfirmed"] is True, rows[1]
        assert rows[1]["reasons"]["value_from_current_vendor"] is False, rows[1]
        assert rows[1]["reasons"]["row_sources"] == ["google_carriersettings"], rows[1]


def check_explain_proxy_free_first() -> None:
    """--explain says an internet row without an HTTP proxy comes before a
    proxied one (proxy_free_first), here although more families give the
    proxied value and no current vendor gives either; an MMS row never
    counts."""
    plain = carrier(
        {"mccmnc": ["62006"]},
        {},
        android_apns=[
            {"name": "WAP", "apn": "wap", "types": ["default", "supl"], "proxy": "10.93.85.88", "port": 9201},
            {"name": "Internet", "apn": "internet", "types": ["default", "supl"]},
            {"name": "MMS", "apn": "mms", "types": ["mms"], "mmsc": "http://mms.example", "mmsproxy": "10.93.85.88", "mmsport": 9201},
        ],
    )
    keys = [generate_android_outputs.apn_fact_key(row, row["types"][0]) for row in plain["android_apns"]]
    evidence = {
        "schema_version": 1,
        "description": "Test evidence.",
        "source_snapshots": [],
        "profiles": [
            {
                "profile_id": plain["profile_id"],
                "observation_count": 4,
                "verified_observation_count": 0,
                "sources": ["apple_carrier_bundles", "lineageos", "mobile_broadband_provider_info"],
                "fact_sources": sorted(
                    [
                        {"section": "android_apns", "key": keys[0], "sources": ["lineageos", "mobile_broadband_provider_info"]},
                        {"section": "android_apns", "key": keys[1], "sources": ["apple_carrier_bundles"]},
                        {"section": "android_apns", "key": keys[2], "sources": ["lineageos"]},
                    ],
                    key=lambda fact: fact["key"],
                ),
                "capability_sources": {},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "carriers" / validate_public_carrier_data.public_path_for(plain["profile_id"]), plain)
        write_json(root / "generated" / "evidence-index.json", evidence)
        with contextlib.redirect_stdout(io.StringIO()):
            generate_android_outputs.main(
                ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
            )
        lookup = json.loads((root / "generated" / "android" / "lookup.json").read_text(encoding="utf-8"))
        result = resolver.explain(lookup, {"mccmnc": "62006"}, root, root / "generated" / "evidence-index.json")
        rows = result["apns"]["rows"]
        assert [row["row"]["apn"] for row in rows] == ["internet", "wap", "mms"], rows
        assert rows[0]["reasons"]["proxy_free_first"] is True, rows[0]
        assert rows[1]["reasons"]["proxy_free_first"] is False, rows[1]
        assert rows[2]["reasons"]["proxy_free_first"] is False, rows[2]


def check_explain_stored_with_best_row() -> None:
    """--explain notes a row written before a better-ranked row Android stores
    as one with it (stored_with_best_row): the phone keeps the later, best
    row's values."""
    plain = carrier(
        {"mccmnc": ["21406"]},
        {},
        android_apns=[
            {"name": "RACC", "apn": "internet.racc.es", "types": ["default", "supl"]},
            {"name": "RACC old", "apn": "internet.racc.es", "types": ["default"], "user": "CLIENTERACC", "password": "RACC", "authtype": 1},
            {"name": "Other", "apn": "other.example", "types": ["default"]},
        ],
    )
    rows_in = plain["android_apns"]
    sources = [["samsung_omc"], ["lineageos"], ["mobile_broadband_provider_info"]]
    facts = [
        {"section": "android_apns", "key": generate_android_outputs.apn_fact_key(row, apn_type), "sources": group}
        for row, group in zip(rows_in, sources)
        for apn_type in row["types"]
    ]
    evidence = {
        "schema_version": 1,
        "description": "Test evidence.",
        "source_snapshots": [],
        "profiles": [
            {
                "profile_id": plain["profile_id"],
                "observation_count": 3,
                "verified_observation_count": 0,
                "sources": sorted({source for group in sources for source in group}),
                "fact_sources": sorted(facts, key=lambda fact: fact["key"]),
                "capability_sources": {},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "carriers" / validate_public_carrier_data.public_path_for(plain["profile_id"]), plain)
        write_json(root / "generated" / "evidence-index.json", evidence)
        with contextlib.redirect_stdout(io.StringIO()):
            generate_android_outputs.main(
                ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
            )
        lookup = json.loads((root / "generated" / "android" / "lookup.json").read_text(encoding="utf-8"))
        result = resolver.explain(lookup, {"mccmnc": "21406"}, root, root / "generated" / "evidence-index.json")
        rows = result["apns"]["rows"]
        assert [(row["row"]["apn"], row["row"].get("user")) for row in rows] == [
            ("internet.racc.es", "CLIENTERACC"),
            ("internet.racc.es", None),
            ("other.example", None),
        ], rows
        assert [row["reasons"]["stored_with_best_row"] for row in rows] == [True, False, False], rows
        assert rows[1]["reasons"]["row_from_current_vendor"] is True, rows[1]
        # Round 32, D8: the lead sends RACC old's username, password and auth
        # type, which only LineageOS gives, under Samsung's bare best row.
        leads = {entry["role"]: entry for entry in result["apns"]["credential_sources"]}
        assert set(leads) == {"internet", "attach"}, leads
        internet = leads["internet"]
        assert (internet["apn"], internet["class_a"], internet["sent"], internet["sends_credentials"]) == (
            "internet.racc.es", True, True, True), internet
        assert set(internet["fields"]) == {"user", "password", "authtype"}, internet
        for field in ("user", "password", "authtype"):
            value = internet["fields"][field]
            assert (value["position"], value["filled_in"], value["sources"], value["current_sources"]) == (
                1, True, ["lineageos"], []), (field, value)
        assert internet["fields"]["user"]["value"] == "CLIENTERACC", internet
        assert len(internet["network_types"]) == 7, internet


def check_explain_superseded_google_credentials() -> None:
    """--explain lists a row rule 1 of round 32 (D8) left out: its only
    effect on the lead's stored row was credentials only Google's frozen
    Pixel copies give, under Google's current bare row of the APN; and the
    lead's credential sources then name no filled-in value."""
    plain = carrier(
        {"mccmnc": ["26220"]},
        {},
        android_apns=[
            {"name": "Enreach DE", "apn": "internet.mvno.mobi", "types": ["default", "dun", "supl"], "authtype": 1},
            {"name": "MVNO DE", "apn": "internet.mvno.mobi", "types": ["default", "supl"], "user": "mvno",
             "password": "mvno", "authtype": 1},
        ],
    )
    rows_in = plain["android_apns"]
    sources = [["google_carriersettings", "google_pixel_vendor_carriersettings"], ["google_pixel_vendor_carriersettings"]]
    facts = [
        {"section": "android_apns", "key": generate_android_outputs.apn_fact_key(row, apn_type), "sources": group}
        for row, group in zip(rows_in, sources)
        for apn_type in row["types"]
    ]
    evidence = {
        "schema_version": 1,
        "description": "Test evidence.",
        "source_snapshots": [],
        "profiles": [
            {
                "profile_id": plain["profile_id"],
                "observation_count": 2,
                "verified_observation_count": 0,
                "sources": sorted({source for group in sources for source in group}),
                "fact_sources": sorted(facts, key=lambda fact: fact["key"]),
                "capability_sources": {},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "carriers" / validate_public_carrier_data.public_path_for(plain["profile_id"]), plain)
        write_json(root / "generated" / "evidence-index.json", evidence)
        with contextlib.redirect_stdout(io.StringIO()):
            generate_android_outputs.main(
                ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
            )
        lookup = json.loads((root / "generated" / "android" / "lookup.json").read_text(encoding="utf-8"))
        metadata = json.loads((root / "generated" / "android" / "metadata.json").read_text(encoding="utf-8"))
        result = resolver.explain(lookup, {"mccmnc": "26220"}, root, root / "generated" / "evidence-index.json")
    assert [row["row"]["carrier"] for row in result["apns"]["rows"]] == ["Enreach DE"], result["apns"]["rows"]
    left = [(item["row"]["carrier"], item["reasons"]) for item in result["apns"]["left_out"]]
    assert left == [("MVNO DE", {"superseded_google_credentials_left_out": ["user", "password"]})], left
    assert metadata["omissions"]["credential_rows_left_out_superseded_google_copy"] == 1, metadata["omissions"]
    internet = next(e for e in result["apns"]["credential_sources"] if e["role"] == "internet")
    assert (internet["sends_credentials"], set(internet["fields"])) == (False, {"authtype"}), internet
    assert internet["fields"]["authtype"]["filled_in"] is False, internet


def check_explain_vendor_mms() -> None:
    """--explain says when the first internet row lost "mms" (mms_left_out),
    when a current vendor's MMS row moved ahead (vendor_mms_ahead), and when
    an internet row kept "mms" because no vendor MMS row serves all its
    mobile network types (mms_kept_no_vendor_coverage)."""
    cases = {
        # 234/30 shape: EE's internet row carries a stale MMS setting; Google
        # gives eezone.
        "23430": (
            [
                {"name": "EE", "apn": "everywhere", "types": ["default", "mms"], "mmsc": "http://mms.ee.example"},
                {"name": "T-Mobile", "apn": "general.t-mobile.uk", "types": ["default", "mms"], "mmsc": "http://mmsc.t-mobile.example"},
                {"name": "EE MMS", "apn": "eezone", "types": ["mms"], "mmsc": "http://mms/", "mmsproxy": "149.254.201.135", "mmsport": 8080},
            ],
            [{"default": ["google_carriersettings"], "mms": ["lineageos"]}, {"default": ["lineageos"], "mms": ["lineageos"]}, {"mms": ["google_carriersettings"]}],
        ),
        # The only vendor MMS row serves LTE and NR; the internet row serves
        # every network type and keeps "mms".
        "26210": (
            [
                {"name": "Web", "apn": "web.example", "types": ["default", "mms"], "mmsc": "http://mms.old.example"},
                {"name": "MMS", "apn": "mms.example", "types": ["mms"], "mmsc": "http://mms.example", "bearer_bitmask": "14|20"},
            ],
            [{"default": ["lineageos"], "mms": ["lineageos"]}, {"mms": ["google_carriersettings"]}],
        ),
    }
    results = {}
    for mccmnc, (apns, sources) in cases.items():
        plain = carrier({"mccmnc": [mccmnc]}, {}, android_apns=apns)
        facts = [
            {"section": "android_apns", "key": generate_android_outputs.apn_fact_key(row, apn_type), "sources": group[apn_type]}
            for row, group in zip(apns, sources)
            for apn_type in row["types"]
        ]
        evidence = {
            "schema_version": 1,
            "description": "Test evidence.",
            "source_snapshots": [],
            "profiles": [
                {
                    "profile_id": plain["profile_id"],
                    "observation_count": len(apns),
                    "verified_observation_count": 0,
                    "sources": sorted({source for fact in facts for source in fact["sources"]}),
                    "fact_sources": sorted(facts, key=lambda fact: fact["key"]),
                    "capability_sources": {},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "carriers" / validate_public_carrier_data.public_path_for(plain["profile_id"]), plain)
            write_json(root / "generated" / "evidence-index.json", evidence)
            with contextlib.redirect_stdout(io.StringIO()):
                generate_android_outputs.main(
                    ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
                )
            lookup = json.loads((root / "generated" / "android" / "lookup.json").read_text(encoding="utf-8"))
            result = resolver.explain(lookup, {"mccmnc": mccmnc}, root, root / "generated" / "evidence-index.json")
        results[mccmnc] = [
            (
                row["row"]["apn"],
                row["row"]["type"],
                row["reasons"]["mms_left_out"],
                row["reasons"]["vendor_mms_ahead"],
                row["reasons"]["mms_kept_no_vendor_coverage"],
            )
            for row in result["apns"]["rows"]
        ]
    assert results["23430"] == [
        ("everywhere", "default", True, False, False),
        ("eezone", "mms", False, True, False),
        ("general.t-mobile.uk", "default,mms", False, False, False),
    ], results["23430"]
    assert results["26210"] == [
        ("web.example", "default,mms", False, False, True),
        ("mms.example", "mms", False, False, False),
    ], results["26210"]


def check_explain_absorbed_mms() -> None:
    """--explain lists a stale MMS-only row apns-conf.xml leaves out because
    Android merges it into an earlier row (absorbed_mms_left_out)."""
    apns = [
        {"name": "Spark", "apn": "internet", "types": ["default", "supl"]},
        {"name": "Spark MMS", "apn": "internet", "types": ["mms"], "mmsc": "http://mms.spark.example"},
        {"name": "Old MMS", "apn": "internet", "types": ["mms"], "mmsc": "http://mms.old.example"},
    ]
    sources = [["google_carriersettings"], ["google_carriersettings"], ["lineageos"]]
    plain = carrier({"mccmnc": ["53005"]}, {}, android_apns=apns)
    facts = [
        {"section": "android_apns", "key": generate_android_outputs.apn_fact_key(row, apn_type), "sources": group}
        for row, group in zip(apns, sources)
        for apn_type in row["types"]
    ]
    evidence = {
        "schema_version": 1,
        "description": "Test evidence.",
        "source_snapshots": [],
        "profiles": [
            {
                "profile_id": plain["profile_id"],
                "observation_count": 3,
                "verified_observation_count": 0,
                "sources": ["google_carriersettings", "lineageos"],
                "fact_sources": sorted(facts, key=lambda fact: fact["key"]),
                "capability_sources": {},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "carriers" / validate_public_carrier_data.public_path_for(plain["profile_id"]), plain)
        write_json(root / "generated" / "evidence-index.json", evidence)
        with contextlib.redirect_stdout(io.StringIO()):
            generate_android_outputs.main(
                ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
            )
        lookup = json.loads((root / "generated" / "android" / "lookup.json").read_text(encoding="utf-8"))
        result = resolver.explain(lookup, {"mccmnc": "53005"}, root, root / "generated" / "evidence-index.json")
        metadata = json.loads((root / "generated" / "android" / "metadata.json").read_text(encoding="utf-8"))
    rows = result["apns"]["rows"]
    left_out = result["apns"]["left_out"]
    assert sorted(row["row"].get("mmsc", "") for row in rows) == ["", "http://mms.spark.example"], rows
    assert [(row["row"]["mmsc"], row["reasons"]["absorbed_mms_left_out"]) for row in left_out] == [
        ("http://mms.old.example", True)
    ], left_out
    assert metadata["omissions"]["mms_rows_left_out_absorbed_by_android"] == 1, metadata["omissions"]


def check_explain_internet_stored_row_mms() -> None:
    """--explain marks step 2b's rows (rule round 33): a row stored with the
    first internet row that lost "mms" (mms_left_out_stored_with_internet)
    and an MMS-only one left out of apns-conf.xml
    (left_out_stored_with_internet), which metadata.json counts with step
    9's rows."""
    cases = {
        # 274/12 shape: a stale MMS-only twin of Samsung's internet row.
        "27412": (
            [
                {"name": "internet.tal.is", "apn": "internet.tal.is", "types": ["default", "supl"], "authtype": 1,
                 "mmsc": "http://mms.tal.is/servlets/mms", "mmsproxy": "213.167.138.210", "mmsport": 8080},
                {"name": "Tal", "apn": "internet.tal.is", "types": ["mms"],
                 "mmsc": "http://mms.tal.is/servlets/mms", "mmsproxy": "213.167.138.210", "mmsport": 8080},
                {"name": "Tal MMS", "apn": "mms.tal.is", "types": ["mms"], "authtype": 1,
                 "mmsc": "http://mms.tal.is/servlets/mms", "mmsproxy": "213.167.138.210", "mmsport": 8080},
            ],
            [{"default": ["samsung_omc"], "supl": ["samsung_omc"]}, {"mms": ["lineageos"]}, {"mms": ["samsung_omc"]}],
        ),
        # 452/01 shape: Apple's dun,mms row with the internet row's key.
        "45201": (
            [
                {"name": "m-wap", "apn": "m-wap", "types": ["default"], "authtype": 1, "user": "mms", "password": "mms",
                 "mmsc": "http://203.162.21.114/mmsc", "mmsproxy": "203.162.21.114", "mmsport": 8080},
                {"name": "Mobifone", "apn": "m-wap", "types": ["dun", "mms"], "user": "mms", "password": "mms",
                 "mmsc": "http://203.162.21.114/mmsc", "mmsproxy": "203.162.21.114", "mmsport": 8080},
                {"name": "Mobi-gprs-mms", "apn": "m-i090", "types": ["mms"], "authtype": 1, "user": "mms", "password": "mms",
                 "mmsc": "http://203.162.21.114/mmsc", "mmsproxy": "203.162.21.114", "mmsport": 8080},
            ],
            [{"default": ["google_carriersettings"]}, {"dun": ["apple_carrier_bundles"], "mms": ["apple_carrier_bundles"]},
             {"mms": ["google_carriersettings"]}],
        ),
    }
    results = {}
    for mccmnc, (apns, sources) in cases.items():
        plain = carrier({"mccmnc": [mccmnc]}, {}, android_apns=apns)
        facts = [
            {"section": "android_apns", "key": generate_android_outputs.apn_fact_key(row, apn_type), "sources": group[apn_type]}
            for row, group in zip(apns, sources)
            for apn_type in row["types"]
        ]
        evidence = {
            "schema_version": 1,
            "description": "Test evidence.",
            "source_snapshots": [],
            "profiles": [
                {
                    "profile_id": plain["profile_id"],
                    "observation_count": len(apns),
                    "verified_observation_count": 0,
                    "sources": sorted({source for fact in facts for source in fact["sources"]}),
                    "fact_sources": sorted(facts, key=lambda fact: fact["key"]),
                    "capability_sources": {},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "carriers" / validate_public_carrier_data.public_path_for(plain["profile_id"]), plain)
            write_json(root / "generated" / "evidence-index.json", evidence)
            with contextlib.redirect_stdout(io.StringIO()):
                generate_android_outputs.main(
                    ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
                )
            lookup = json.loads((root / "generated" / "android" / "lookup.json").read_text(encoding="utf-8"))
            result = resolver.explain(lookup, {"mccmnc": mccmnc}, root, root / "generated" / "evidence-index.json")
            metadata = json.loads((root / "generated" / "android" / "metadata.json").read_text(encoding="utf-8"))
        results[mccmnc] = (
            [(row["row"]["apn"], row["row"]["type"], row["reasons"]["mms_left_out_stored_with_internet"])
             for row in result["apns"]["rows"]],
            [(row["row"]["apn"], row["row"]["type"], row["reasons"]["absorbed_mms_left_out"],
              row["reasons"]["left_out_stored_with_internet"]) for row in result["apns"]["left_out"]],
            metadata["omissions"],
        )
    rows, left_out, omissions = results["27412"]
    assert left_out == [("internet.tal.is", "mms", True, True)], left_out
    assert not any(marked for _, _, marked in rows), rows
    assert omissions["mms_rows_left_out_absorbed_by_android"] == 1, omissions
    rows, left_out, omissions = results["45201"]
    assert ("m-wap", "dun", True) in rows and left_out == [], (rows, left_out)
    assert omissions["mms_types_left_out_not_vendor_backed"] == 1, omissions


def check_explain_emergency() -> None:
    """--explain says why a row keeps "emergency" (emergency_basis), lists a
    row whose only type was "emergency" under left_out with its reason, and
    marks an emergency-named internet row ranked after the other internet
    row (round 21)."""
    plain = carrier(
        {"mccmnc": ["20608"]},
        {},
        android_apns=[
            {"name": "SOS", "apn": "SOS", "types": ["default"], "protocol": "IPV6", "roaming_protocol": "IPV4V6"},
            {"name": "VOO", "apn": "internet.voo.be", "types": ["default", "supl"]},
            {"name": "Emergency", "apn": "sos", "types": ["emergency"], "protocol": "IPV6", "roaming_protocol": "IPV6"},
            {"name": "Emergency", "apn": "sos", "types": ["emergency"], "protocol": "IPV4V6", "roaming_protocol": "IPV4V6"},
        ],
    )
    keys = [generate_android_outputs.apn_fact_key(row, row["types"][0]) for row in plain["android_apns"]]
    evidence = {
        "schema_version": 1,
        "description": "Test evidence.",
        "source_snapshots": [],
        "profiles": [
            {
                "profile_id": plain["profile_id"],
                "observation_count": 4,
                "verified_observation_count": 0,
                "sources": ["apple_carrier_bundles", "samsung_omc"],
                "fact_sources": sorted(
                    [
                        {"section": "android_apns", "key": keys[0], "sources": ["samsung_omc"]},
                        {"section": "android_apns", "key": keys[1], "sources": ["samsung_omc"]},
                        {"section": "android_apns", "key": keys[2], "sources": ["apple_carrier_bundles"]},
                        {"section": "android_apns", "key": keys[3], "sources": ["apple_carrier_bundles"]},
                    ],
                    key=lambda fact: fact["key"],
                ),
                "capability_sources": {},
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "carriers" / validate_public_carrier_data.public_path_for(plain["profile_id"]), plain)
        write_json(root / "generated" / "evidence-index.json", evidence)
        with contextlib.redirect_stdout(io.StringIO()):
            generate_android_outputs.main(
                ["generate_android_outputs.py", str(root / "carriers"), str(root / "generated")]
            )
        lookup = json.loads((root / "generated" / "android" / "lookup.json").read_text(encoding="utf-8"))
        result = resolver.explain(lookup, {"mccmnc": "20608"}, root, root / "generated" / "evidence-index.json")
        metadata = json.loads((root / "generated" / "android" / "metadata.json").read_text(encoding="utf-8"))
    rows = result["apns"]["rows"]
    assert [row["row"]["apn"] for row in rows] == ["internet.voo.be", "SOS", "sos"], rows
    assert [row["reasons"]["emergency_named_ranks_last"] for row in rows] == [False, True, False], rows
    assert [row["reasons"]["emergency_basis"] for row in rows] == [None, None, "android_default"], rows
    left_out = result["apns"]["left_out"]
    assert [(row["row"]["protocol"], row["reasons"]) for row in left_out] == [
        ("IPV6", {"emergency_left_out": "not_vendor_stated"})
    ], left_out
    assert metadata["omissions"]["emergency_types_left_out_not_vendor_stated"] == 1, metadata["omissions"]


def main() -> int:
    check_resolution()
    check_explain()
    check_explain_shared_file()
    check_explain_proxy_free_first()
    check_explain_stored_with_best_row()
    check_explain_vendor_mms()
    check_explain_superseded_google_credentials()
    check_explain_absorbed_mms()
    check_explain_internet_stored_row_mms()
    check_explain_emergency()
    print("carrier profile resolver tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
