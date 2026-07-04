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
        expired_claim["expires"] = (date.today() - timedelta(days=1)).isoformat()
        write_json(claims_dir / "expired.json", expired_claim)
        expect_error(
            lambda: validate_community_claims.main(
                [
                    "validate_community_claims.py",
                    str(claims_dir),
                    str(root / "generated" / "community"),
                    "--write-index",
                ]
            ),
            "claim is expired",
        )

    print("community claim validation tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
