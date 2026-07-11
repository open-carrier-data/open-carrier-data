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


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def base_claim() -> dict:
    today = date.today()
    return {
        "schema_version": 1,
        "claim_id": "claim.example.mobile.mms",
        "summary": "Example Mobile MMS works with this APN.",
        "status": "verified",
        "carrier_match": {
            "mccmnc": ["00101"],
            "spn": ["Example"],
        },
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
                "date": today.isoformat(),
                "result": "works",
                "summary": "MMS send and receive were tested.",
            }
        ],
        "last_verified": today.isoformat(),
        "expires": (today + timedelta(days=365)).isoformat(),
    }


def expect_error(fn, expected_text: str) -> None:
    try:
        fn()
    except validate_community_claims.ClaimError as exc:
        assert_true(expected_text in str(exc), f"wrong error: {exc}")
        return
    raise AssertionError("expected ClaimError")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claims_dir = root / "community" / "claims"
        index_root = root / "generated" / "community"

        low_claim = base_claim()
        write_json(claims_dir / "low.json", low_claim)
        validate_community_claims.main(
            [
                "validate_community_claims.py",
                str(claims_dir),
                str(index_root),
                "--stable-dir",
                str(root / "carriers"),
                "--write-index",
            ]
        )
        community = json.loads((index_root / "index.json").read_text(encoding="utf-8"))
        candidate = json.loads(
            (index_root.parent / "candidate" / "index.json").read_text(
                encoding="utf-8"
            )
        )
        assert_true(
            community["claims"][0]["computed_risk"] == "low",
            "specific MMS claim should compute as low risk",
        )
        assert_true(
            community["claims"][0]["recommended_channel"] == "stable_eligible",
            "verified low-risk claim should be stable-eligible",
        )
        assert_true(
            len(candidate["claims"]) == 1,
            "stable-eligible claim should also appear in candidate index",
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claims_dir = root / "community" / "claims"
        high_claim = base_claim()
        high_claim["claim_id"] = "claim.example.mobile.vowifi.override"
        high_claim["carrier_match"] = {"mccmnc": ["00101"]}
        high_claim["change_type"] = "override"
        high_claim["changes"] = {
            "android_carrier_config": {
                "carrier_volte_provisioning_required_bool": False
            }
        }
        high_claim["risk"] = "low"
        high_claim["expires"] = (date.today() + timedelta(days=90)).isoformat()
        write_json(claims_dir / "understated.json", high_claim)
        expect_error(
            lambda: validate_community_claims.main(
                [
                    "validate_community_claims.py",
                    str(claims_dir),
                    str(root / "generated" / "community"),
                    "--stable-dir",
                    str(root / "carriers"),
                    "--write-index",
                ]
            ),
            "declared risk low is lower than computed risk high",
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claims_dir = root / "community" / "claims"
        expired_claim = base_claim()
        expired_claim["claim_id"] = "claim.example.mobile.expired"
        expired_claim["last_verified"] = (date.today() - timedelta(days=10)).isoformat()
        expired_claim["evidence"][0]["date"] = expired_claim["last_verified"]
        expired_claim["expires"] = (date.today() - timedelta(days=1)).isoformat()
        write_json(claims_dir / "expired.json", expired_claim)
        result = validate_community_claims.main(
            [
                "validate_community_claims.py",
                str(claims_dir),
                str(root / "generated" / "community"),
                "--stable-dir",
                str(root / "carriers"),
                "--write-index",
            ]
        )
        assert_true(result == 0, "expired claims should not fail validation")
        index = json.loads(
            (root / "generated" / "community" / "index.json").read_text(encoding="utf-8")
        )
        assert_true(index["claims"] == [], "expired claims should be excluded from indexes")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claims_dir = root / "community" / "claims"
        stable_dir = root / "carriers"
        match = {"mccmnc": ["00101"], "spn": ["Example"]}
        profile_id = validate_community_claims.public_data.canonical_profile_id(match)
        write_json(
            stable_dir / validate_community_claims.public_data.public_path_for(profile_id),
            {
                "schema_version": 1,
                "profile_id": profile_id,
                "display_name": "Example",
                "match": match,
                "capabilities": {"mms": "unsupported"},
            },
        )
        conflict = base_claim()
        conflict["claim_id"] = "claim.example.mobile.mms.conflict"
        conflict["changes"] = {"capabilities": {"mms": "supported"}}
        conflict["expires"] = (date.today() + timedelta(days=180)).isoformat()
        write_json(claims_dir / "conflict.json", conflict)
        validate_community_claims.main(
            [
                "validate_community_claims.py",
                str(claims_dir),
                str(root / "generated" / "community"),
                "--stable-dir",
                str(stable_dir),
                "--write-index",
            ]
        )
        indexed = json.loads(
            (root / "generated" / "community" / "index.json").read_text(encoding="utf-8")
        )["claims"][0]
        assert_true(indexed["conflicts_with_stable"], "stable conflict should be computed")
        assert_true(
            indexed["stable_conflict_profile_ids"] == [profile_id],
            "computed conflict should identify the stable profile",
        )
        assert_true(
            indexed["recommended_channel"] == "community",
            "a conflicting claim must not be promoted automatically",
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        claims_dir = root / "community" / "claims"
        claim = base_claim()
        claim["evidence"] = [
            {
                "type": "maintainer_review",
                "date": date.today().isoformat(),
                "result": "observed",
                "summary": "The submitter cannot grant their own maintainer review.",
            }
        ]
        write_json(claims_dir / "self-review.json", claim)
        expect_error(
            lambda: validate_community_claims.main(
                [
                    "validate_community_claims.py",
                    str(claims_dir),
                    str(root / "generated" / "community"),
                    "--stable-dir",
                    str(root / "carriers"),
                    "--write-index",
                ]
            ),
            "evidence[0].type is invalid",
        )

    print("community claim validation tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
