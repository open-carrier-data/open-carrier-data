#!/usr/bin/env python3
"""Regression tests for GitHub issue-form claim conversion."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import issue_to_claim
import validate_community_claims


BODY = """### Short summary

Example MMS works.

### Carrier and country

Example Mobile, Germany

### MCC/MNC

26299

### Optional carrier match details

SPN: Example

### Change type

add

### Affected feature or setting

mms

### Desired capability state

supported

### APN settings

_No response_

### Advanced changes JSON

_No response_

### Evidence type

device_test

### Test result

works

### Evidence date

2026-07-11

### Evidence summary

Sent and received an MMS.

### Public evidence URL

_No response_

### Device and OS

Galaxy S20, LineageOS

### Extra notes

Roaming was disabled.

### Privacy check

- [X] I checked this report.
"""


def replace_field(body: str, label: str, value: str) -> str:
    fields = issue_to_claim.form_fields(body)
    old = f"### {label}\n\n{fields[label] or '_No response_'}"
    return body.replace(old, f"### {label}\n\n{value}", 1)


def expect_error(body: str, expected: str) -> None:
    try:
        issue_to_claim.issue_claim({"issue": {"number": 42, "body": body}})
    except issue_to_claim.ConversionError as exc:
        assert expected in str(exc), str(exc)
        return
    raise AssertionError("expected ConversionError")


def main() -> int:
    claim = issue_to_claim.issue_claim({"issue": {"number": 42, "body": BODY}})
    assert claim["claim_id"] == "claim.issue.42"
    assert claim["status"] == "proposed"
    assert claim["carrier_match"] == {
        "mccmnc": ["26299"],
        "spn": ["Example"],
    }
    assert claim["changes"] == {"capabilities": {"mms": "supported"}}
    assert claim["evidence"][0]["result"] == "works"
    assert "url" not in claim["evidence"][0]
    assert "Device/OS: Galaxy S20, LineageOS" in claim["evidence"][0]["summary"]
    json.dumps(claim)
    with tempfile.TemporaryDirectory() as tmp:
        claims_dir = Path(tmp) / "community/claims"
        claim_path = claims_dir / "issue-42.json"
        claim_path.parent.mkdir(parents=True)
        claim_path.write_text(json.dumps(claim), encoding="utf-8")
        validated = validate_community_claims.validate_claim(
            claim_path,
            claims_dir,
            [],
            set(),
        )
        assert validated["claim_id"] == "claim.issue.42"

    apn_body = replace_field(BODY, "Affected feature or setting", "APN settings")
    apn_body = replace_field(apn_body, "Desired capability state", "not_applicable")
    apn_body = replace_field(
        apn_body,
        "APN settings",
        "Name: Example MMS\nAPN: mms.example\nTypes: mms\nMMS port: 8080",
    )
    apn_claim = issue_to_claim.issue_claim(
        {"issue": {"number": 43, "body": apn_body}}
    )
    assert apn_claim["changes"]["android_apns"] == [
        {
            "name": "Example MMS",
            "apn": "mms.example",
            "types": ["mms"],
            "mmsport": 8080,
        }
    ]

    advanced_body = replace_field(
        BODY,
        "Affected feature or setting",
        "Advanced changes JSON",
    )
    advanced_body = replace_field(
        advanced_body,
        "Desired capability state",
        "not_applicable",
    )
    advanced_body = replace_field(advanced_body, "Advanced changes JSON", "not json")
    expect_error(advanced_body, "Advanced changes JSON is not valid JSON")
    expect_error(BODY.replace("- [X]", "- [ ]"), "privacy confirmation")
    expect_error(
        BODY.replace("SPN: Example", "Unknown thing: value"),
        "unknown optional match field",
    )
    print("issue claim conversion tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
