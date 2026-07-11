#!/usr/bin/env python3
"""Convert the tested-claim GitHub issue form into community claim JSON."""

from __future__ import annotations

import argparse
from datetime import date
import json
import re
import sys
from pathlib import Path
from typing import Any


HEADING_RE = re.compile(r"^### (.+?)\n\n(.*?)(?=\n### |\Z)", re.MULTILINE | re.DOTALL)
NO_RESPONSE = {"", "_No response_", "No response"}
CAPABILITIES = {
    "mms",
    "volte",
    "vowifi",
    "vonr",
    "video_calling",
    "sms_over_ims",
    "rcs",
    "esim",
    "ims_conference",
    "wifi_calling_roaming",
}


class ConversionError(Exception):
    pass


def clean_field(value: str) -> str:
    value = value.strip()
    if value in NO_RESPONSE:
        return ""
    fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", value, re.DOTALL)
    return fence.group(1).strip() if fence else value


def form_fields(body: str) -> dict[str, str]:
    fields = {
        heading.strip(): clean_field(value)
        for heading, value in HEADING_RE.findall(body)
    }
    return fields


def split_values(value: str) -> list[str]:
    return sorted(
        {
            item.strip()
            for item in re.split(r"[,\s]+", value)
            if item.strip()
        }
    )


def split_csv_values(value: str) -> list[str]:
    return sorted({item.strip() for item in value.split(",") if item.strip()})


def key_value_lines(value: str, label: str) -> dict[str, str]:
    if not value:
        return {}
    out: dict[str, str] = {}
    for line_number, line in enumerate(value.splitlines(), 1):
        if not line.strip():
            continue
        key, separator, child = line.partition(":")
        if not separator or not key.strip() or not child.strip():
            raise ConversionError(
                f"{label} line {line_number} must use 'Name: value'"
            )
        normalized = key.strip().casefold()
        if normalized in out:
            raise ConversionError(f"{label} repeats {key.strip()}")
        out[normalized] = child.strip()
    return out


def carrier_match(fields: dict[str, str]) -> dict[str, Any]:
    match: dict[str, Any] = {"mccmnc": split_values(required(fields, "MCC/MNC"))}
    details = key_value_lines(
        fields.get("Optional carrier match details", ""),
        "Optional carrier match details",
    )
    supported = {
        "spn",
        "android carrier id",
        "gid1 prefix",
        "gid2 prefix",
        "iccid prefix",
        "imsi prefix pattern",
    }
    unknown = set(details) - supported
    if unknown:
        raise ConversionError(f"unknown optional match field(s): {sorted(unknown)}")
    string_fields = {
        "spn": "spn",
        "gid1 prefix": "gid1_prefixes",
        "gid2 prefix": "gid2_prefixes",
        "iccid prefix": "iccid_prefixes",
        "imsi prefix pattern": "imsi_prefix_patterns",
    }
    for input_name, output_name in string_fields.items():
        if input_name not in details:
            continue
        values = split_csv_values(details[input_name])
        if output_name in {"gid1_prefixes", "gid2_prefixes"}:
            values = [value.upper() for value in values]
        if output_name == "imsi_prefix_patterns":
            values = [value.lower() for value in values]
        match[output_name] = values
    if "android carrier id" in details:
        try:
            match["android_carrier_ids"] = [
                int(value) for value in split_values(details["android carrier id"])
            ]
        except ValueError as exc:
            raise ConversionError("Android carrier ID must be an integer") from exc
    return match


def apn_changes(raw: str) -> dict[str, Any]:
    values = key_value_lines(raw, "APN settings")
    supported = {
        "name",
        "apn",
        "types",
        "mmsc",
        "mms proxy",
        "mms port",
        "proxy",
        "port",
        "user",
        "password",
        "protocol",
        "roaming protocol",
    }
    unknown = set(values) - supported
    if unknown:
        raise ConversionError(f"unknown APN field(s): {sorted(unknown)}")
    if "apn" not in values or "types" not in values:
        raise ConversionError("APN settings require APN and Types")
    apn: dict[str, Any] = {
        "name": values.get("name", values["apn"]),
        "apn": values["apn"],
        "types": sorted({value.casefold() for value in split_values(values["types"])}),
    }
    names = {
        "mmsc": "mmsc",
        "mms proxy": "mmsproxy",
        "proxy": "proxy",
        "user": "user",
        "password": "password",
    }
    for input_name, output_name in names.items():
        if input_name in values:
            apn[output_name] = values[input_name]
    for input_name, output_name in {"mms port": "mmsport", "port": "port"}.items():
        if input_name in values:
            try:
                apn[output_name] = int(values[input_name])
            except ValueError as exc:
                raise ConversionError(f"{input_name} must be an integer") from exc
    for input_name, output_name in {
        "protocol": "protocol",
        "roaming protocol": "roaming_protocol",
    }.items():
        if input_name in values:
            apn[output_name] = values[input_name].upper()
    return {"android_apns": [apn]}


def proposed_changes(fields: dict[str, str]) -> dict[str, Any]:
    feature = required(fields, "Affected feature or setting")
    advanced = fields.get("Advanced changes JSON", "")
    if feature == "Advanced changes JSON":
        return json_object(fields, "Advanced changes JSON")
    if advanced:
        raise ConversionError(
            "Advanced changes JSON must be empty unless it is the selected setting"
        )
    if feature == "APN settings":
        return apn_changes(required(fields, "APN settings"))
    if feature not in CAPABILITIES:
        raise ConversionError(f"unsupported affected feature: {feature}")
    state = required(fields, "Desired capability state")
    if state == "not_applicable":
        raise ConversionError("choose a capability state for the selected feature")
    return {"capabilities": {feature: state}}


def required(fields: dict[str, str], label: str) -> str:
    value = fields.get(label, "")
    if not value:
        raise ConversionError(f"missing form field: {label}")
    return value


def json_object(fields: dict[str, str], label: str) -> dict[str, Any]:
    raw = required(fields, label)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConversionError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ConversionError(f"{label} must be a JSON object")
    return value


def issue_claim(event: dict[str, Any]) -> dict[str, Any]:
    issue = event.get("issue")
    if not isinstance(issue, dict):
        raise ConversionError("event has no issue")
    number = issue.get("number")
    body = issue.get("body")
    if not isinstance(number, int) or number < 1 or not isinstance(body, str):
        raise ConversionError("issue event has invalid number or body")

    fields = form_fields(body)
    privacy = required(fields, "Privacy check")
    if not re.search(r"- \[[xX]\]", privacy):
        raise ConversionError("privacy confirmation is not checked")
    summary = required(fields, "Short summary")
    carrier = required(fields, "Carrier and country")
    evidence_date = required(fields, "Evidence date")
    try:
        parsed_date = date.fromisoformat(evidence_date)
    except ValueError as exc:
        raise ConversionError("Evidence date must be YYYY-MM-DD") from exc

    evidence_summary = required(fields, "Evidence summary")
    device_os = fields.get("Device and OS", "")
    if device_os:
        evidence_summary = f"{evidence_summary} Device/OS: {device_os}"
    evidence: dict[str, Any] = {
        "type": required(fields, "Evidence type"),
        "date": parsed_date.isoformat(),
        "result": required(fields, "Test result"),
        "summary": evidence_summary[:280],
    }
    evidence_url = fields.get("Public evidence URL", "")
    if evidence_url:
        evidence["url"] = evidence_url

    notes = fields.get("Extra notes", "")
    context = f"Submitted through GitHub issue #{number} for {carrier}."
    if notes:
        context = f"{context} {notes}"

    return {
        "schema_version": 1,
        "claim_id": f"claim.issue.{number}",
        "summary": summary,
        "status": "proposed",
        "carrier_match": carrier_match(fields),
        "change_type": required(fields, "Change type"),
        "changes": proposed_changes(fields),
        "evidence": [evidence],
        "last_verified": parsed_date.isoformat(),
        "notes": context[:500],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--output-root", default="community/claims", type=Path)
    args = parser.parse_args(argv[1:])
    try:
        event = json.loads(args.event.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConversionError(f"cannot read issue event: {exc}") from exc
    claim = issue_claim(event)
    target = args.output_root / f"issue-{event['issue']['number']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(claim, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(target.as_posix())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
