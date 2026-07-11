#!/usr/bin/env python3
"""Regression tests for community claim validation."""

from __future__ import annotations

from datetime import date, timedelta
import json
import tempfile
from pathlib import Path

import validate_community_claims


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def base_claim() -> dict:
    today = date.today().isoformat()
    return {
        "schema_version": 1,
        "claim_id": "claim.example.mobile.mms",
        "summary": "Example Mobile MMS works with this APN.",
        "status": "proposed",
        "carrier_match": {"mccmnc": ["00101"], "spn": ["Example"]},
        "change_type": "add",
        "changes": {
            "android_apns": [
                {
                    "name": "Example MMS",
                    "apn": "mms.example",
                    "types": ["mms"],
                    "mmsc": "https://mms.example/mmsc",
                }
            ]
        },
        "evidence": [
            {
                "type": "device_test",
                "date": today,
                "result": "works",
                "summary": "MMS send and receive were tested.",
            }
        ],
        "last_verified": today,
    }


def expect_error(fn, expected_text: str) -> None:
    try:
        fn()
    except validate_community_claims.ClaimError as exc:
        assert expected_text in str(exc), f"wrong error: {exc}"
        return
    raise AssertionError("expected ClaimError")


def run(root: Path, *, write: bool = True) -> int:
    argv = [
        "validate_community_claims.py",
        str(root / "community" / "claims"),
        str(root / "generated" / "community"),
        "--stable-dir",
        str(root / "carriers"),
        "--evidence-index",
        str(root / "generated" / "evidence-index.json"),
    ]
    if write:
        argv.append("--write-index")
    return validate_community_claims.main(argv)


def indexed_claim(root: Path) -> dict:
    return json.loads(
        (root / "generated/community/index.json").read_text(encoding="utf-8")
    )["claims"][0]


def main() -> int:
    assert validate_community_claims.match_risk(
        {"mccmnc": ["00101", "00102"], "spn": ["Example"]}
    ) == "medium"
    assert validate_community_claims.match_risk(
        {
            "mccmnc": ["00101", "00102"],
            "android_carrier_ids": [42],
        }
    ) == "low"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "community/claims/low.json", base_claim())
        assert run(root) == 0
        claim = indexed_claim(root)
        candidate = json.loads(
            (root / "generated/candidate/index.json").read_text(encoding="utf-8")
        )
        assert claim["computed_risk"] == "low"
        assert claim["recommended_channel"] == "candidate"
        assert claim["path"] == "community/claims/low.json"
        assert claim["changes"] == base_claim()["changes"]
        assert claim["evidence"] == base_claim()["evidence"]
        assert len(candidate["claims"]) == 1
        assert date.fromisoformat(claim["expires"]) == date.today() + timedelta(days=365)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claim = base_claim()
        claim["claim_id"] = "claim.example.mobile.vowifi.override"
        claim["carrier_match"] = {"mccmnc": ["00101"]}
        claim["change_type"] = "override"
        claim["changes"] = {
            "android_carrier_config": {
                "carrier_volte_provisioning_required_bool": False
            }
        }
        write_json(root / "community/claims/high.json", claim)
        run(root)
        result = indexed_claim(root)
        assert result["computed_risk"] == "high"
        assert result["recommended_channel"] == "community"
        assert date.fromisoformat(result["expires"]) == date.today() + timedelta(days=90)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claim = base_claim()
        claim["claim_id"] = "claim.example.mobile.expired"
        claim["last_verified"] = (date.today() - timedelta(days=10)).isoformat()
        claim["evidence"][0]["date"] = claim["last_verified"]
        claim["expires"] = (date.today() - timedelta(days=1)).isoformat()
        write_json(root / "community/claims/expired.json", claim)
        run(root)
        assert json.loads(
            (root / "generated/community/index.json").read_text(encoding="utf-8")
        )["claims"] == []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        match = {"mccmnc": ["00101"], "spn": ["Example"]}
        profile_id = validate_community_claims.public_data.canonical_profile_id(match)
        write_json(
            root / "carriers" / validate_community_claims.public_data.public_path_for(profile_id),
            {
                "schema_version": 1,
                "profile_id": profile_id,
                "display_name": "Example",
                "match": match,
                "capabilities": {"mms": "unsupported"},
            },
        )
        claim = base_claim()
        claim["claim_id"] = "claim.example.mobile.mms.conflict"
        claim["changes"] = {"capabilities": {"mms": "supported"}}
        write_json(root / "community/claims/conflict.json", claim)
        run(root)
        result = indexed_claim(root)
        assert result["conflicts_with_stable"]
        assert result["computed_risk"] == "high"
        assert result["stable_conflict_profile_ids"] == [profile_id]
        assert result["recommended_channel"] == "community"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claim = base_claim()
        claim["status"] = "verified"
        write_json(root / "community/claims/self-verified.json", claim)
        expect_error(lambda: run(root), "status must be proposed")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claim = base_claim()
        claim["changes"]["android_apns"][0]["types"] = ["default"]
        claim["evidence"] = [
            {
                "type": "maintained_source_reference",
                "date": date.today().isoformat(),
                "result": "observed",
                "summary": "An unrelated repository contains this value.",
                "url": "https://example.com/untrusted/settings",
            }
        ] * 2
        write_json(root / "community/claims/untrusted.json", claim)
        run(root)
        result = indexed_claim(root)
        assert result["confidence"] == "medium"
        assert result["evidence_count"] == 1
        assert result["computed_risk"] == "medium"
        assert result["recommended_channel"] == "community"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(
            root / "generated/evidence-index.json",
            {
                "source_snapshots": [
                    {"upstream_url": "https://example.com/maintained/carrier-data"}
                ]
            },
        )
        claim = base_claim()
        claim["changes"]["android_apns"][0]["types"] = ["default"]
        claim["evidence"] = [
            {
                "type": "maintained_source_reference",
                "date": date.today().isoformat(),
                "result": "observed",
                "summary": "The maintained source contains this value.",
                "url": "https://example.com/maintained/carrier-data/path",
            }
        ]
        write_json(root / "community/claims/trusted.json", claim)
        run(root)
        result = indexed_claim(root)
        assert result["confidence"] == "high"
        assert result["recommended_channel"] == "candidate"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claim = base_claim()
        claim["changes"]["android_apns"][0]["user"] = "shared-user"
        claim["changes"]["android_apns"][0]["password"] = "shared-pass"
        write_json(root / "community/claims/credentials.json", claim)
        expect_error(lambda: run(root), "require a public carrier")
        claim["evidence"].append(
            {
                "type": "carrier_documentation",
                "date": date.today().isoformat(),
                "result": "observed",
                "summary": "The carrier publishes the shared APN login.",
                "url": "https://example.com/public-apn",
            }
        )
        write_json(root / "community/claims/credentials.json", claim)
        run(root)

    print("community claim validation tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
