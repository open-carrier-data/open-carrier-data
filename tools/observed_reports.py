#!/usr/bin/env python3
"""OCD Check reports: check an issue, rebuild observed/, validate observed/.

A report points, phones prove (the anti-fake design of 2026-10-20). An OCD
Check report names entries of the closed list of one OCD data commit or
release, never a value: `volte:on`, `volte:off`, the same for `vowifi`,
`sms_over_ims`, `video_calling` and `vonr`, or `apn:<row key>` for a row that
data's apns-conf.xml has for the SIM's network. Since rule round 29 (S13) the
app names the commit of OCD's main it read its data at, with its data digest;
apps before round 29 name a `data-*` release tag, which is still taken. Each entry carries the result class
the phone measured. No report can bring a new value onto a phone; a report
can only make a phone test an entry earlier, and the phone keeps nothing that
fails its own test.

The "OCD Check report" issue form carries one fenced JSON block that the OCD
Check owner build prefills (schemas/ocd-check-report.schema.json). This tool
is the whole logic of .github/workflows/ocd-check-report.yml, so it runs the
same way on a laptop:

  check-issue --event EVENT.json --result RESULT.json --comment COMMENT.md
      Checks the issue in a GitHub `issues` event: the form's shape, the
      report against the schema, the privacy scan on every value, the title
      and the rest of the issue text, the consistency checks a schema cannot
      express, and the data it names: a commit on main (or a release tag)
      that exists, whose data digest matches, and that holds the profile and
      every APN row key. Plausibility checks against that data flag a report
      as suspect. Writes {"valid", "suspect",
      "errors", "flags", "report_sha256"} and the bot's comment. Exit 0
      whether the report is valid or not.

  rebuild --issues ISSUES.json --root DIR [--pr-body BODY.md]
      Rebuilds DIR/observed/ from every report issue (a JSON list as the REST
      API returns them): one file per valid report, observed/reports/issue-N.json,
      with its status after the noise filters, and observed/summary.json from
      the reports of other accounts; and DIR/devices/records/measured.json
      from the measured records the owner's account submitted (rule round 30,
      item 4). An issue closed as not planned is left out, which is how a
      maintainer withdraws a report. Run tools/ocd_dataset.py generate after
      it, so generated/devices/device-records.json and the dataset manifest
      follow.

  validate --root DIR
      Checks every file under DIR/observed/reports/ and that
      observed/summary.json and devices/records/measured.json are what the
      reports give. Exit 1 on a problem.

  source-reviews --root DIR --issues ISSUES.json --out DIR2
      Plans one source-review issue per carrier profile (or SIM key) and
      target whose measured record corrects OCD's published value, names a
      winner after a failure, falls back to Android's default or found no
      value that passes (rule 10, rule round 30): DIR2/plan.json lists the
      issues to open or update, with their bodies beside it. ISSUES.json is
      the repository's issues labelled source-review.

  check-file REPORT.json [--root DIR]
      Checks one bare report, as the app wrote it, against DIR's main history
      and release tags. Exit 1 when invalid.

DIR is a checkout of main with its history and tags (a blobless clone is
enough: git fetches a file's content when it is read). --main names the ref
whose history counts as main (default HEAD).

The noise filters (they order what people read; they are not a defence):
closed schema, privacy scan, a hash of the report text, plausibility against
the release, one counted report per account and cell, a monthly cap per
account, a hold on an account's reports until 14 days after its first
accepted report (counted from that report, not from the account's sign-up),
and expiry 90 days after the test. Observed reports are unverified
observations, kept apart from carriers/, generated/ and the releases; they
never change an OCD value.

The owner's results (rule round 30, item 4; round 29 fired O1 of round 18).
Reports of the owner's account (OWNER_ACCOUNTS, by GitHub user ID, which a
renamed or reclaimed login cannot take) skip the account filters. The OCD
Check owner build (ocd-android #29) sends each settled result as one issue
labelled `ocd-device-record` ("[OCD device record] ..."), whose body's only
JSON block is one per-device record of kind `measured`
(schemas/device-records.schema.json, $defs.record) for this device, ROM line,
IMS stack and carrier profile or SIM key. The bot takes it into
devices/records/measured.json, and from there into
generated/devices/device-records.json, only when all of these hold: the
issue's author is the owner's account; the record passes the closed schema
and its key recomputes; its value is a candidate (OCD's resolved
value or an alternative of the profile's stack, the Google lane's value of
the profile's fill or default, the other value of a switch, Android's
default, or for the emergency data test only accepted, refused or Android's
default won); its key is not group A (those enter only with a second-agent
read) and not group B; the privacy scan passes; and its data commit is on
main with its data digest and holds the dataset. `validate` and the phone
guard then run on the bot's pull request. observed/retested.json of round 29
is folded into these records. The owner's pointer reports stay pointers in
observed/reports/; other accounts' reports stay "reported, not checked by
OCD" in summary.json, also when they carry a settled field, and an outside
account can never submit records. Only the standard library is used, as in
the other validators.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, NamedTuple

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from validate_public_carrier_data import SCHEMA_TYPES, load_schema, schema_json_text  # noqa: E402
import ocd_dataset  # noqa: E402

REPORT_SCHEMA = "ocd-check-report.schema.json"
SUMMARY_SCHEMA = "observed-summary.schema.json"
RECORD_SCHEMA = "device-records.schema.json"
# The owner build's settled results as per-device records (rule round 30):
# one issue per record, labelled RECORD_LABEL, the record its only JSON block.
RECORD_LABEL = "ocd-device-record"
RECORD_TITLE_PREFIX = "[OCD device record]"
MEASURED_FILE = "devices/records/measured.json"
REPORT_KIND = "ocd-check-test-report"
LABEL = "ocd-check-report"
VALID_LABEL = "report:valid"
SUSPECT_LABEL = "report:suspect"
INVALID_LABEL = "report:invalid"
HOLD_RELEASED_LABEL = "report:hold-released"
TITLE_PREFIX = "[OCD Check report]"
TEMPLATE = "ocd-check-report.yml"
BOT_MARKER = "<!-- ocd-check-report-bot -->"
REPORT_HEADING = "Report"
PRIVACY_HEADING = "Privacy check"
UNVERIFIED = "unverified"
OBSERVED = "observed"
# Round 29's separate file, folded into the measured records (round 30).
RETESTED_FILE = "retested.json"
SOURCE_REVIEW_LABEL = "source-review"
REVIEW_MARKER = "<!-- ocd-source-review"
BOT_LOGIN = "github-actions[bot]"
# The owner's GitHub account, by its user ID (logins can be renamed and taken
# again; the ID cannot). Its reports are the owner's own phones' (rule round
# 29), and only it submits measured records (rule round 30). Every other
# account is "outside" and stays "reported, not checked by OCD".
OWNER_ACCOUNTS = {122638570: "belagrf"}
OWNER = "owner"
OUTSIDE = "outside"
TESTERS = (OWNER, OUTSIDE)
REPORT_FILE_RE = re.compile(r"issue-([1-9][0-9]{0,8})\.json")
RELEASE_TAG_RE = re.compile(r"data-20[0-9]{2}\.(0[1-9]|1[0-2])(\.[1-9][0-9]{0,2})?")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")

FEATURES = ("volte", "vowifi", "video_calling", "vonr", "sms_over_ims")
VOICE = {"volte", "vowifi", "vonr"}
T2_BEARERS = {"volte": {"lte", "lte_ca"}, "vowifi": {"iwlan"}}
RESULTS = ("works", "signed_in", "service_off", "not_possible", "failed", "not_tested")
PASSED = {"works", "signed_in", "service_off"}
RESULTS_BY_KIND = {
    "on": {"works", "signed_in", "not_possible", "failed", "not_tested"},
    "off": {"works", "service_off", "failed", "not_tested"},
    "apn": {"works", "failed", "not_tested"},
}
# The entries a settled result can name (rule round 29), with the bearer a
# call level is proven on; SMS over IMS settles only as SMS both ways.
SETTLED_BEARERS = {"volte:on": "lte", "vowifi:on": "iwlan", "sms_over_ims:on": None}
SMS_ENTRY = "sms_over_ims:on"
# A failure that does not say the entry fails: the test itself broke.
UNCLEAN_FAILURES = {"revert_not_proven", "insert_no_row", "read_back_differs"}
APN_ON_PHONE = {"present", "same_as_phone_row"}

# The noise filters.
EARLIEST_TEST = date(2026, 10, 1)  # the owner build exists since 2026-10-19
HOLD_DAYS = 14
EXPIRE_DAYS = 90
MONTHLY_CAP = 10
MAX_REPORT_CHARS = 30_000
MAX_ERRORS = 40

STATUS_TEXT = {
    "reported": "reported, not checked by OCD",
    "contested": "contested: a clean measured failure was reported",
    "retested_by_ocd": "re-tested by OCD",
}
STATUS_DESCRIPTIONS = {
    "reported": "Counted reports of people's phones, by result. Not checked by OCD: anyone can open an issue, and nothing checks who sent a report or whether the phone exists.",
    "contested": "At least one counted report measured a clean failure of the entry (the test ran and the phone's state came back). It asks the next phone to test the entry and a maintainer to look; it switches nothing off.",
    "retested_by_ocd": "Always null here. The owner's phones' settled results are measured records in generated/devices/device-records.json (rule round 30), where observed/retested.json of round 29 was folded in.",
}
# The level a measured record's result is reached at (rule round 30, item 4).
RECORD_LEVELS = {
    "works": {"L3"}, "calls_out": {"L2", "L3"}, "sms_both_ways": {"sms_both_ways"}, "no_regression_passed": {"no_regression"},
    "winner_after_failure": {"L2", "L3", "sms_both_ways", "no_regression"},
    "no_value_passed": {"L2", "L3", "sms_both_ways", "no_regression"},
    "emergency_data_accepted": {"emergency_data"}, "emergency_data_refused": {"emergency_data"}, "emergency_default_won": {"emergency_data"},
}
# Fixed-shape fields of a submitted record that skip the two phone heuristics.
RECORD_HEX_PATH = re.compile(
    r"\$\.(record_key|data\.commit|data\.data_digest|target\.row_key|carrier\.profile_id|carrier\.gid1|"
    r"first_measured|last_measured|valid_until|second_agent_read\.read_at|differs_between_sims\[\d+\]\.last_measured)"
)

# The privacy scan: the same patterns as the app's PrivacyScan
# (app-ocd-check, core/PrivacyScan.kt), which ports BLOCK_PATTERNS of the
# private sanitize_profiles.py, EXTRA_VALUE_PATTERNS and the key scan of
# field_observations.py, and phone_check.py's SIP/tel URI and IP shapes.
# A hit names the field and the rule, never the matched text.
BLOCK_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "long_decimal_identity": re.compile(r"\b\d{14,20}\b"),
    "international_phone": re.compile(r"\+\d{8,15}\b"),
    "secret_word": re.compile(r"(?i)\b(pswd|secret|token|authorization)\b"),
    "raw_vendor_file": re.compile(
        r"(?i)\b(customer\.xml|cscfeature\.xml|imsupdate\.json|omc\.info|"
        r"customer_carrier_feature\.json|carrier_canonical_id_list\.json|"
        r"carrier\.plist|\.ipcc|carrier_settings\.pb|mbn)\b"
    ),
    "raw_vendor_key": re.compile(r"\b(CarrierFeature_|GRASSE-AUTH|SemCarrierFeature|CarrierBundle|CSettingsDir)\b"),
    "gras_payload": re.compile(r"(?i)\b(updateURL|pkgHash|pkgSize|fileDownloadUrl|deviceId|imei)\b"),
    "ims_patch": re.compile(
        r"\b(imsswitch_update|imsprofile_update|globalsettings_update|mnomap_update|"
        r"add_mnomap|remove_mnomap|remove_profile|epdgsettings|iwlansettings|"
        r"vowifisettings|enableIms|enableService[A-Za-z]+|mnoname)\b"
    ),
    "sip_or_tel_uri": re.compile(r"\b(?:sip|sips|tel|urn):[^\s,;>\"\]]+"),
    "ipv4_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "ipv6_address": re.compile(r"\b[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){3,7}\b"),
}
EXTRA_VALUE_PATTERNS = {
    "spaced_international_phone": re.compile(r"\+\d{1,3}[ ./-]?(?:\(\d{1,5}\)[ ./-]?)?\d{2,5}[ ./-]\d{3,}"),
    "national_phone": re.compile(r"\b0\d{2,5}[ /-]?\d{6,}\b"),
}
BLOCKED_KEY = re.compile(r"(?i)(imsi|iccid|imei|meid|msisdn|phone_number|subscriber|line1|device_id|android_id|serial)")
KEY_SCAN_PATTERNS = ("secret_word", "raw_vendor_key", "gras_payload")
# Fixed-shape fields skip only the two phone heuristics: an all-digit hash
# tail or GID1 prefix can look like a national number, and a date is none.
HEX_FIELDS = {"$.ocd_profile", "$.sim.gid1_prefix", "$.release.commit", "$.release.data_digest", "$.tested_on", "$.device.build"}
SAFE_KEY = re.compile(r"[a-z][a-z0-9_]{0,40}")


class Check(NamedTuple):
    valid: bool
    errors: list[str]
    flags: list[str]
    report: dict[str, Any] | None
    sha256: str | None
    # The data the report points into: a main commit (40 hex) or a release tag.
    ref: str | None


# ---------------------------------------------------------------- schema


def schema_problems(value: Any, schema: dict[str, Any], root: dict[str, Any], where: str, out: list[str]) -> None:
    """Every way VALUE breaks SCHEMA, as schema_problem in
    validate_public_carrier_data.py judges it, collected instead of the
    first. Messages name the path and what the schema wants, never the value;
    an unknown key is named only when it is a plain identifier."""
    if "$ref" in schema:
        schema_problems(value, root["$defs"][schema["$ref"].removeprefix("#/$defs/")], root, where, out)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(SCHEMA_TYPES[name](value) for name in names):
            out.append(f"{where}: must be of type {'/'.join(names)}")
            return
    if "const" in schema and schema_json_text(value) != schema_json_text(schema["const"]):
        out.append(f"{where}: must be {schema_json_text(schema['const'])}")
        return
    if "enum" in schema and schema_json_text(value) not in {schema_json_text(v) for v in schema["enum"]}:
        out.append(f"{where}: must be one of {', '.join(schema_json_text(v) for v in schema['enum'])}")
        return
    if "anyOf" in schema:
        options = []
        for option in schema["anyOf"]:
            found: list[str] = []
            schema_problems(value, option, root, where, found)
            if not found:
                break
            options.append(found)
        else:
            out.append(f"{where}: matches none of the allowed forms ({'; or '.join(o[0].split(': ', 1)[-1] for o in options)})")
            return
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{where}: is shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{where}: is longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{where}: does not have the allowed form")
        if schema.get("format") == "date":
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    raise ValueError(value)
                date.fromisoformat(value)
            except ValueError:
                out.append(f"{where}: is not a date (YYYY-MM-DD)")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where}: is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where}: is above {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{where}: has fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where}: has more than {schema['maxItems']} items")
        if schema.get("uniqueItems") and len({schema_json_text(v) for v in value}) != len(value):
            out.append(f"{where}: has repeated items")
        if "items" in schema:
            for index, item in enumerate(value[:100]):
                schema_problems(item, schema["items"], root, f"{where}[{index}]", out)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{where}: lacks {key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                schema_problems(item, properties[key], root, f"{where}.{key}", out)
            elif schema.get("additionalProperties") is False:
                out.append(f"{where}: has the unknown key {safe_key(key)}")
            elif isinstance(schema.get("additionalProperties"), dict):
                schema_problems(item, schema["additionalProperties"], root, f"{where}.{safe_key(key)}", out)


def safe_key(key: str) -> str:
    """A key as the comment may show it: only a plain identifier that passes the privacy scan."""
    if SAFE_KEY.fullmatch(key) and not scan_key("$", key) and not scan_text("$", key):
        return key
    return "(a key not shown here)"


# ---------------------------------------------------------------- privacy


def scan_text(path: str, text: str, phone_heuristics: bool = True) -> list[str]:
    """The privacy rules TEXT breaks, as messages naming PATH and the rule."""
    hits = []
    candidates = [text]
    if any(char.isdigit() and not "0" <= char <= "9" for char in text):
        candidates.append("".join(str(int(char)) if char.isdigit() else char for char in text))
    for candidate in candidates:
        for name, pattern in BLOCK_PATTERNS.items():
            if pattern.search(candidate):
                hits.append(f"{path}: looks like private data ({name})")
        if phone_heuristics:
            for name, pattern in EXTRA_VALUE_PATTERNS.items():
                if pattern.search(candidate):
                    hits.append(f"{path}: looks like a phone number ({name})")
    return list(dict.fromkeys(hits))


def scan_key(path: str, key: str) -> list[str]:
    hits = []
    if BLOCKED_KEY.search(key):
        hits.append(f"{path}: a key names a private identifier (blocked_key)")
    for name in KEY_SCAN_PATTERNS:
        if BLOCK_PATTERNS[name].search(key):
            hits.append(f"{path}: a key names private data ({name})")
    return hits


def privacy_problems(value: Any, where: str = "$") -> list[str]:
    """The fail-closed privacy scan over every key and string of a report."""
    out: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{where}.{safe_key(key)}"
            out += scan_key(path, key)
            out += privacy_problems(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out += privacy_problems(child, f"{where}[{index}]")
    elif isinstance(value, str):
        out += scan_text(where, value, phone_heuristics=where not in HEX_FIELDS)
    return out


# ---------------------------------------------------------------- entries


def entry_kind(entry: str) -> tuple[str, str | None]:
    """("on" | "off", feature) for a feature entry, ("apn", None) for an APN row."""
    if entry.startswith("apn:"):
        return "apn", None
    feature, value = entry.split(":")
    return value, feature


def apn_key(apn: str, types: str | None, protocol: str | None) -> str:
    """The row key the app writes after `apn:`: the APN in lower case, its
    types in lower case and sorted, its protocol in upper case (the app's
    `apnKey` in owner/core/Apn.kt)."""
    kinds = sorted(t.strip().lower() for t in (types or "").split(",") if t.strip())
    return apn.lower() + "|" + ",".join(kinds) + "|" + (protocol or "").upper()


def clean_failure(result: dict[str, Any]) -> bool:
    """A failure that says the entry fails here: the test ran and the phone's state came back."""
    return result["result"] == "failed" and result.get("reason") not in UNCLEAN_FAILURES and result.get("restored") is not False


# ---------------------------------------------------------------- consistency


def consistency_problems(report: dict[str, Any], today: date) -> list[str]:
    """What a schema cannot say: the report agrees with itself. Runs only on a
    report that passed the schema."""
    out: list[str] = []
    tested_on = date.fromisoformat(report["tested_on"])
    if tested_on > today + timedelta(days=1):
        out.append("$.tested_on: is in the future")
    if tested_on < EARLIEST_TEST:
        out.append(f"$.tested_on: is before {EARLIEST_TEST.isoformat()}, older than the OCD Check owner build")
    if report["ocd_profile"] is None and "gid1_prefix" in report["sim"]:
        out.append("$.sim.gid1_prefix: is sent only with the OCD profile that matches by it")
    seen: set[str] = set()
    pointers: dict[str, dict[str, list[str]]] = {}
    for index, result in enumerate(report["results"]):
        where = f"$.results[{index}]"
        entry = result["entry"]
        kind, feature = entry_kind(entry)
        if entry in seen:
            out.append(f"{where}.entry: {entry.split('|')[0]} is listed twice")
        seen.add(entry)
        if result["result"] not in RESULTS_BY_KIND[kind]:
            allowed = ", ".join(r for r in RESULTS if r in RESULTS_BY_KIND[kind])
            out.append(f"{where}.result: for {'an APN row' if kind == 'apn' else 'an ' + kind + ' entry'} it must be one of {allowed}")
        if result["result"] in ("not_possible", "failed", "not_tested") and "reason" not in result:
            out.append(f"{where}.reason: {result['result']} needs a reason")
        if (result["how"] == "observed") != result["phone"]:
            out.append(f"{where}.how: the phone's own value is observed, every other entry is tested")
        if result.get("kept") and (result["how"] != "tested" or result["result"] not in PASSED):
            out.append(f"{where}.kept: only a tested entry that passed is kept")
        calls = result.get("call_types", [])
        t2 = [call for call in calls if call["test"] == "t2"]
        off_calls = [call for call in calls if call["test"] == "with_feature_off"]
        if t2 and not (kind == "on" and feature in T2_BEARERS):
            out.append(f"{where}.call_types: the T2 call test covers only volte:on and vowifi:on")
        elif any(call["network"] not in T2_BEARERS.get(feature or "", set()) for call in t2):
            out.append(f"{where}.call_types: a T2 call must be on the feature's bearer")
        if off_calls and not (kind == "off" and feature in VOICE):
            out.append(f"{where}.call_types: a call with the feature off belongs only to the off entry of a voice feature")
        if result["result"] == "works" and kind == "on" and entry == SMS_ENTRY:
            if (result.get("settled") or {}).get("level") != "l3":
                out.append(f"{where}.result: works for sms_over_ims:on needs SMS both ways settled")
        elif result["result"] == "works" and kind == "on" and not t2:
            out.append(f"{where}.result: works needs a passed T2 call test in call_types")
        if result["result"] == "works" and kind == "off" and not off_calls:
            out.append(f"{where}.result: works for an off entry needs a call measured with the feature off")
        if result["result"] == "signed_in" and t2:
            out.append(f"{where}.result: with a passed T2 call test the result is works")
        if "settled" in result:
            out += settled_problems(report, result, where, tested_on, today)
        if kind == "apn":
            types = entry.split("|")[1].split(",")
            if "emergency" in types:
                out.append(f"{where}.entry: the app never tests an emergency APN row")
            if not result["ocd"]:
                out.append(f"{where}.ocd: an APN row entry always points at OCD's row")
            if result["phone"] != (result["result"] == "not_tested" and result.get("reason") in APN_ON_PHONE):
                out.append(f"{where}.phone: an APN row is the phone's own exactly when it is not tested because it is present")
            continue
        if result["ocd"] and report["ocd_profile"] is None:
            out.append(f"{where}.ocd: OCD has no value without a profile")
        flags = pointers.setdefault(feature, {"ocd": [], "phone": []})
        for name in ("ocd", "phone"):
            if result[name]:
                flags[name].append(entry)
    for feature, flags in pointers.items():
        for name in ("ocd", "phone"):
            if len(flags[name]) > 1:
                out.append(f"$.results: {name} points at both {feature}:on and {feature}:off")
    return out


def settled_problems(report: dict[str, Any], result: dict[str, Any], where: str, tested_on: date, today: date) -> list[str]:
    """What a settled result must agree with (rule round 29): the entries
    and levels rounds 26 to 28 settle, the data commit and the ROM build it
    was measured against, and dates within the 90 days a level holds. The
    level comes from the phone's call ledger on the same build, so it can be
    newer than the test run the report names; it is never in the future."""
    out: list[str] = []
    settled = result["settled"]
    where = f"{where}.settled"
    entry = result["entry"]
    if entry not in SETTLED_BEARERS:
        return [f"{where}: only volte:on, vowifi:on and sms_over_ims:on carry a settled result"]
    if "commit" not in report["release"]:
        out.append(f"{where}: a settled result needs the data commit and its digest in $.release (round 29 S13)")
    if "build" not in report["device"]:
        out.append(f"{where}: a settled result needs the ROM build in $.device.build (levels are per build)")
    measured = date.fromisoformat(settled["measured_on"])
    if measured > today + timedelta(days=1):
        out.append(f"{where}.measured_on: is in the future")
    elif tested_on - measured > timedelta(days=EXPIRE_DAYS):
        out.append(f"{where}.measured_on: is more than {EXPIRE_DAYS} days before tested_on, so the level no longer holds")
    passed = result["result"] in PASSED
    failed = clean_failure(result)
    if not passed and not failed:
        out.append(f"{where}: only a pass or a clean measured failure is settled")
        return out
    level, method, bearer = settled["level"], settled["method"], SETTLED_BEARERS[entry]
    legs = method.split("+")
    if bearer is None:
        if level != "l3" or method != "self_sms" or result["result"] != "works":
            out.append(f"{where}: SMS over IMS settles only as SMS both ways: level l3, method self_sms, result works")
        return out
    if settled.get("bearer") != bearer:
        out.append(f"{where}.bearer: {entry} is measured on {bearer}")
    if "self_sms" in legs:
        out.append(f"{where}.method: a call level is measured by calls")
    elif passed and level == "l3":
        if result["result"] != "works" or len(legs) != 2:
            out.append(f"{where}: l3 (works) is the result works with both legs, outgoing+incoming")
    elif passed:
        if result["result"] != "signed_in" or len(legs) != 1:
            out.append(f"{where}: l2 (calls out) is the result signed_in with one leg, the outgoing call")
    elif len(legs) != 1:
        out.append(f"{where}.method: a measured failure names the one call that failed")
    elif level == "l3" and method != "real_call":
        out.append(f"{where}.method: an incoming call is one of the owner's own calls (real_call)")
    return out


# ---------------------------------------------------------------- the data a report names


class Releases:
    """The OCD data a report can point into, read from this checkout with
    `git show`: a commit of main (round 29 S13: the app names the commit it
    read its data at) or a `data-*` release tag (apps before round 29). The
    data must exist; its profiles and its apns-conf.xml rows are the closed
    list a report points into. A commit counts only when it is in the
    history of MAIN: GitHub serves a fork's or an unmerged branch's commit by
    its SHA too."""

    APN = re.compile(r"<apn\s+([^>]*?)/?>")
    ATTRIBUTE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')

    def __init__(self, root: Path, main: str = "HEAD") -> None:
        self.root = root
        self.main = main
        self.cache: dict[tuple[str, str], Any] = {}

    def git(self, *args: str, lazy: bool = True) -> str | None:
        # A blobless clone fetches a file's content when it is read; the
        # history check needs no network (GIT_NO_LAZY_FETCH, git 2.44+).
        env = None if lazy else {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, env=env)
        return done.stdout if done.returncode == 0 else None

    def on_main(self, commit: str) -> bool:
        """Whether COMMIT is a commit in the history of main here."""
        key = ("#main", commit)
        if key not in self.cache:
            self.cache[key] = bool(COMMIT_RE.fullmatch(commit)) and self.git(
                "merge-base", "--is-ancestor", commit, self.main, lazy=False) is not None
        return self.cache[key]

    @staticmethod
    def spec(ref: str) -> str:
        """What `git show` reads for REF: the tag's ref, or the commit itself."""
        return f"refs/tags/{ref}" if RELEASE_TAG_RE.fullmatch(ref) else ref

    def tags(self) -> list[str]:
        if ("tags", "") not in self.cache:
            out = self.git("tag", "-l", "data-*") or ""
            self.cache[("tags", "")] = sorted(t for t in out.split() if RELEASE_TAG_RE.fullmatch(t))
        return self.cache[("tags", "")]

    def file(self, tag: str, path: str) -> str | None:
        if (tag, path) not in self.cache:
            self.cache[(tag, path)] = self.git("show", f"{self.spec(tag)}:{path}")
        return self.cache[(tag, path)]

    def digest(self, tag: str) -> str | None:
        text = self.file(tag, "generated/android/metadata.json")
        return json.loads(text).get("data_digest") if text else None

    def profiles(self, tag: str) -> dict[str, dict[str, str]]:
        key = (tag, "#profiles")
        if key not in self.cache:
            text = self.file(tag, "generated/android/lookup.json")
            profiles = json.loads(text)["profiles"] if text else []
            self.cache[key] = {p["profile_id"]: p.get("capabilities", {}) for p in profiles}
        return self.cache[key]

    def recorded(self, tag: str) -> set[tuple[str, str]]:
        """(profile, capability) pairs with any device record: there OCD's value can depend on the phone model."""
        key = (tag, "#records")
        if key not in self.cache:
            text = self.file(tag, "generated/devices/carrier-variants.json")
            profiles = json.loads(text)["profiles"] if text else {}
            self.cache[key] = {(p, c) for p, caps in profiles.items() for c in caps}
        return self.cache[key]

    def dataset(self, commit: str) -> dict[str, Any] | None:
        """The OCD dataset at COMMIT: profiles.json, google-lane.json and apn-index.json, or None."""
        key = (commit, "#dataset")
        if key not in self.cache:
            texts = [self.file(commit, ocd_dataset.FILES[role][1]) for role in ("profiles", "google_lane", "apn_index")]
            self.cache[key] = None if any(t is None for t in texts) else {
                "profiles": json.loads(texts[0]), "lane": json.loads(texts[1]), "index": json.loads(texts[2])}
        return self.cache[key]

    def apn_keys(self, tag: str, mccmnc: str) -> set[str]:
        key = (tag, "#apns")
        if key not in self.cache:
            rows: dict[str, set[str]] = {}
            for match in self.APN.finditer(self.file(tag, "generated/android/apns-conf.xml") or ""):
                attributes = dict(self.ATTRIBUTE.findall(match.group(1)))
                if "apn" not in attributes:
                    continue
                numeric = attributes.get("mcc", "") + attributes.get("mnc", "")
                rows.setdefault(numeric, set()).add(apn_key(xml_text(attributes["apn"]), xml_text(attributes.get("type", "")), attributes.get("protocol")))
            self.cache[key] = rows
        return self.cache[key].get(mccmnc, set())


def xml_text(value: str) -> str:
    return value.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def data_label(ref: str) -> str:
    """A commit as "commit 1a2b3c4d5e6f", a release by its tag."""
    return f"commit {ref[:12]}" if COMMIT_RE.fullmatch(ref) else ref


def report_ref(report: dict[str, Any]) -> str | None:
    """The commit or the release tag a schema-valid report names."""
    return report["release"].get("commit") or report["release"].get("tag")


def release_problems(report: dict[str, Any], releases: Releases) -> tuple[list[str], list[str], str | None]:
    """(errors, flags, ref): the data the report points into (a main commit
    or a release tag), and whether every pointer exists there. Flags are
    plausibility checks against that data: they hold a report, they do not
    reject it."""
    errors: list[str] = []
    flags: list[str] = []
    digest = report["release"]["data_digest"]
    if "commit" in report["release"]:
        tag = report["release"]["commit"]
        if not releases.on_main(tag):
            return ["$.release.commit: is not a commit of OCD's main"], flags, None
        if releases.digest(tag) != digest:
            return [f"$.release.data_digest: is not the data digest of {data_label(tag)}"], flags, None
    elif (tag := report["release"]["tag"]) is not None:
        if tag not in releases.tags():
            return [f"$.release.tag: {tag} is not an OCD data release"], flags, None
        if releases.digest(tag) != digest:
            return [f"$.release.data_digest: is not the data digest of {tag}"], flags, None
    else:
        tag = next((t for t in releases.tags() if releases.digest(t) == digest), None)
        if tag is None:
            return ["$.release.data_digest: is the digest of no OCD data release; pull a release and test again"], flags, None
    name = data_label(tag)
    profile = report["ocd_profile"]
    capabilities = releases.profiles(tag).get(profile) if profile else None
    if profile is not None and capabilities is None:
        errors.append(f"$.ocd_profile: is not a profile of {name}")
    mccmnc = report["sim"]["mccmnc"]
    keys = None
    for index, result in enumerate(report["results"]):
        kind, feature = entry_kind(result["entry"])
        if kind == "apn":
            keys = releases.apn_keys(tag, mccmnc) if keys is None else keys
            if result["entry"].removeprefix("apn:") not in keys:
                errors.append(f"$.results[{index}].entry: is not an APN row {name} has for {mccmnc}")
            continue
        if result["result"] in PASSED and kind == "on" and feature == "video_calling" and report["device"]["ims_stack"] == "phh_ims":
            flags.append(f"$.results[{index}]: video calling passed on PHH IMS, which has no video")
        if capabilities is not None and (profile, feature) not in releases.recorded(tag):
            value = {"supported": "on", "unsupported": "off"}.get(capabilities.get(feature, "unknown"))
            if result["ocd"] and value != kind:
                flags.append(f"$.results[{index}].ocd: {name} gives {feature} {value or 'no value'} for this profile, with no device record")
    return errors, flags, tag


def report_problems(report: Any, today: date, releases: Releases | None, owner: bool = False) -> tuple[list[str], list[str], str | None]:
    """(errors, flags, ref) of one parsed report: ref is the main commit or
    the release tag it points into. Without RELEASES the data is not checked
    (validate on a checkout without history or tags). OWNER: the report
    comes from the owner's account, the only one that submits measured
    records."""
    schema = load_schema(REPORT_SCHEMA, TOOLS.parent / "schemas")
    problems: list[str] = []
    if is_record(report):
        return record_issue_problems(report, owner, today, releases)
    if isinstance(report, dict) and report.get("schema") == "ocd-check-report.v1":
        return ["$.schema: this is the read-only check's report (ocd-check-report.v1); the form takes the owner build's test report (ocd-check-test-report)"], [], None
    schema_problems(report, schema, schema, "$", problems)
    problems += privacy_problems(report)
    if problems:
        return list(dict.fromkeys(problems)), [], None
    problems += consistency_problems(report, today)
    if problems or releases is None:
        return list(dict.fromkeys(problems)), [], report_ref(report)
    errors, flags, tag = release_problems(report, releases)
    return errors, flags, tag


# ---------------------------------------------------------------- measured records (rule round 30)


def record_privacy_problems(value: Any, where: str) -> list[str]:
    """The privacy scan over a submission, with the phone heuristics off only
    for the fixed-shape fields (hashes, row keys, profile ids, GID1, dates)."""
    out: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{where}.{safe_key(key)}"
            out += scan_key(path, key)
            out += record_privacy_problems(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out += record_privacy_problems(child, f"{where}[{index}]")
    elif isinstance(value, str):
        out += scan_text(where, value, phone_heuristics=not RECORD_HEX_PATH.fullmatch(where))
    return out


def current_registry(root: Path) -> dict[str, dict[str, Any]]:
    """Main's closed key registry: a measured record is served with main's dataset."""
    path = root / ocd_dataset.REGISTRY_PATH
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("keys", {})


def record_candidate_problems(record: dict[str, Any], dataset: dict[str, Any], where: str) -> list[str]:
    """The value is a candidate at the data commit (rule round 30, item 4): a
    resolved value or an alternative of the profile's stack, the Google
    lane's value of its fill or of default, the other value of a switch, or
    Android's default; an APN record names a row of the profile."""
    profiles, lane, index = dataset["profiles"], dataset["lane"], dataset["index"]
    carrier, target = record["carrier"], record["target"]
    if carrier["scope"] == "all":
        return [f"{where}.carrier: a measured record names a carrier profile or a SIM key"]
    stacks: list[list[dict[str, Any]]] = []
    fills: set[str] = {"default"}
    if carrier["scope"] == "profile":
        for network in profiles["networks"].values():
            for profile in network["profiles"]:
                if profile["id"] == carrier["profile_id"]:
                    stacks.append(ocd_dataset.profile_stack(network["profiles"], profile, network["mcc"] + network["mnc"]))
                    fills |= {item["entry"] for item in profile["fill"]}
        if not stacks:
            return [f"{where}.carrier.profile_id: is not a profile of the data commit (record_unknown_profile)"]
    else:
        network = profiles["networks"].get(f"{carrier['mcc']}-{carrier['mnc']}")
        sim = {"mcc": carrier["mcc"], "mnc": carrier["mnc"], "gid1": carrier.get("gid1"), "spn": carrier.get("spn")}
        stack = ocd_dataset.resolve_stack(network["profiles"], sim) if network else []
        if stack and stack[-1]["kind"] == "ocd":
            return [f"{where}.carrier: a SIM key record is for a SIM that default or a fill-only profile serves; this SIM has {stack[-1]['id']}"]
        if stack:
            stacks.append(stack)
            fills |= {item["entry"] for item in stack[-1]["fill"]}
    if target["type"] == "config":
        key = target["key"]
        meta = profiles["keys"].get(key)
        if meta is None:
            return [f"{where}.target.key: is not in the data commit's key registry (unknown_key)"]
        if record["value_kind"] != "value" or meta["type"] == "bool":
            return []
        values = [p["values"][key] for stack in stacks for p in stack if key in p["values"]]
        values += [alt["value"] for stack in stacks for p in stack for alt in p["alternatives"].get(key, [])]
        values += [lane["entries"][name]["values"][key] for name in sorted(fills) if name in lane["entries"] and key in lane["entries"][name]["values"]]
        if schema_json_text(record["value"]) not in {schema_json_text(v) for v in values}:
            return [f"{where}.value: is no candidate for this key and profile at the data commit (record_not_candidate)"]
        return []
    rows = {row["row_key"]: row for row in index["rows"]}
    row_key = target["row_key"]
    if row_key is None:
        return []
    row = rows.get(row_key)
    if row is None:
        return [f"{where}.target.row_key: is not a row of the data commit's apns-conf.xml (record_apn_row_unknown)"]
    if stacks and not any(p["id"] in row["profiles"] for stack in stacks for p in stack):
        return [f"{where}.target.row_key: is not a row of this SIM's profile stack (record_apn_row_unknown)"]
    return []


def record_issue_problems(record: Any, owner: bool, today: date, releases: Releases | None) -> tuple[list[str], list[str], str | None]:
    """(errors, flags, ref) of one measured record from an `ocd-device-record` issue."""
    if not owner:
        return ["$: measured records are taken only from the owner's account (rule round 30); other accounts send pointer reports"], [], None
    where = "$"
    errors: list[str] = []
    schema = load_schema(RECORD_SCHEMA, TOOLS.parent / "schemas")
    schema_problems(record, schema["$defs"]["record"], schema, where, errors)
    errors += record_privacy_problems(record, where)
    if errors:
        return list(dict.fromkeys(errors)), [], None
    if record["kind"] != "measured" or record["claim"] != "measured":
        return [f"{where}: the owner build sends records of kind measured only"], [], None
    registry = current_registry(releases.root if releases is not None else TOOLS.parent)
    errors += ocd_dataset.record_problems(record, registry, {}, where) if registry else [f"{where}: main has no key registry ({ocd_dataset.REGISTRY_PATH})"]
    if record["result"] not in RECORD_LEVELS or record["level"] not in RECORD_LEVELS.get(record["result"], set()):
        errors.append(f"{where}: result and level do not fit (works L3, calls_out L2 or L3, sms_both_ways, no_regression_passed at no_regression, emergency results at emergency_data)")
    if record["method"] is None or record["first_measured"] is None:
        errors.append(f"{where}: a measured record names its method and the days measured")
    last = record["last_measured"]
    if last is not None:
        if date.fromisoformat(last) > today + timedelta(days=1):
            errors.append(f"{where}.last_measured: is in the future")
        elif releases is not None and today - date.fromisoformat(last) > timedelta(days=EXPIRE_DAYS):
            errors.append(f"{where}.last_measured: is more than {EXPIRE_DAYS} days ago, so the record has expired")
    commit = record["data"]["commit"]
    if releases is not None and not errors:
        if not releases.on_main(commit):
            errors.append(f"{where}.data.commit: is not a commit of OCD's main")
        elif releases.digest(commit) != record["data"]["data_digest"]:
            errors.append(f"{where}.data.data_digest: is not the data digest of {data_label(commit)}")
        else:
            dataset = releases.dataset(commit)
            if dataset is None:
                errors.append(f"{where}.data.commit: {data_label(commit)} holds no OCD dataset (generated/ocd-dataset/)")
            else:
                errors += record_candidate_problems(record, dataset, where)
    return list(dict.fromkeys(errors)), [], commit


def report_date(report: dict[str, Any]) -> date:
    """The test date of a pointer report, or a record's last measurement."""
    if is_record(report):
        return date.fromisoformat(report["last_measured"])
    return date.fromisoformat(report["tested_on"])


def is_record(report: Any) -> bool:
    """A per-device record (an `ocd-device-record` issue's JSON), not a pointer report."""
    return isinstance(report, dict) and "record_key" in report and "schema" not in report


def is_record_issue(issue: dict[str, Any]) -> bool:
    return RECORD_LABEL in labels_of(issue) or (issue.get("title") or "").startswith(RECORD_TITLE_PREFIX)


FENCED_JSON_RE = re.compile(r"```[A-Za-z]*[ \t]*\r?\n(.*?)\r?\n?```", re.DOTALL)


def check_record_issue(issue: dict[str, Any], today: date, releases: Releases | None) -> Check:
    """An `ocd-device-record` issue: the body's only JSON block is one measured record."""
    errors: list[str] = []
    title = issue.get("title") or ""
    body = (issue.get("body") or "").replace("\r\n", "\n")
    # A record title names its key, profile id and model; hex ids are no phone numbers.
    errors += [e.replace("$", "the title", 1) for e in scan_text("$", title, phone_heuristics=False)]
    blocks = FENCED_JSON_RE.findall(body)
    if len(blocks) != 1:
        errors.append(f"the issue body must hold exactly one JSON block (it holds {len(blocks)}): the OCD Check owner build sends one record per issue")
        return Check(False, errors, [], None, None, None)
    raw = blocks[0].strip()
    # The app's privacy box names the identifiers it left out ("IMEI"), so
    # its ticked line is not scanned; every other line of the text is.
    rest = re.sub(r"(?m)^\s*- \[[xX ]\] .*$", "", FENCED_JSON_RE.sub("", body))
    errors += [e.replace("$", "the issue text outside the record", 1) for e in scan_text("$", rest)]
    privacy = form_sections(body).get(PRIVACY_HEADING)
    if privacy is not None and not CHECKED_RE.search(privacy):
        errors.append(f"the \"{PRIVACY_HEADING}\" box is not ticked")
    if len(raw) > MAX_REPORT_CHARS:
        errors.append(f"the record is longer than {MAX_REPORT_CHARS} characters")
        return Check(False, errors, [], None, None, None)
    digest = report_hash(raw)
    try:
        record = strict_json(raw)
    except json.JSONDecodeError as error:
        errors.append(f"the record is not valid JSON (line {error.lineno}, column {error.colno}: {error.msg})")
        return Check(False, errors, [], None, digest, None)
    except ValueError as error:
        errors.append(f"the record is not valid JSON ({error})")
        return Check(False, errors, [], None, digest, None)
    if not is_record(record):
        errors.append("the JSON block is not one per-device record (schemas/device-records.schema.json, $defs.record)")
        return Check(False, errors, [], None, digest, None)
    problems, flags, ref = record_issue_problems(record, is_owner(issue), today, releases)
    errors = list(dict.fromkeys(errors + problems))
    return Check(not errors, errors, flags if not errors else [], record if not errors else None, digest, ref)


# ---------------------------------------------------------------- the issue


class DuplicateKey(ValueError):
    pass


def strict_json(text: str) -> Any:
    """JSON with no repeated key and no NaN or Infinity."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise DuplicateKey(f"the key {safe_key(key)} appears twice in one object")
            out[key] = value
        return out

    def constant(name: str) -> Any:
        raise ValueError(f"{name} is not allowed")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


HEADING_RE = re.compile(r"^### (.+?)[ \t]*\r?\n(.*?)(?=^### |\Z)", re.MULTILINE | re.DOTALL)
FENCE_RE = re.compile(r"\A\s*```[A-Za-z]*[ \t]*\r?\n(.*?)\r?\n?```\s*\Z", re.DOTALL)
CHECKED_RE = re.compile(r"^\s*- \[[xX]\] ", re.MULTILINE)


def unfence(text: str) -> str:
    """The text inside one or two code fences: GitHub fences a `render: json`
    field, and a pasted block may bring its own."""
    for _ in range(2):
        match = FENCE_RE.match(text)
        if not match:
            break
        text = match.group(1)
    return text.strip()


def report_hash(text: str) -> str:
    """SHA-256 of the report text with Unix line ends and no outer blank
    space: the hash the app shows for the text it prefilled."""
    return "sha256:" + hashlib.sha256(text.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()


def form_sections(body: str) -> dict[str, str]:
    return {heading.strip(): value for heading, value in HEADING_RE.findall(body)}


def check_issue(issue: dict[str, Any], today: date, releases: Releases | None) -> Check:
    """Every problem of one report issue, or none, and its plausibility flags."""
    if is_record_issue(issue):
        return check_record_issue(issue, today, releases)
    errors: list[str] = []
    title = issue.get("title") or ""
    body = (issue.get("body") or "").replace("\r\n", "\n")
    errors += [e.replace("$", "the title", 1) for e in scan_text("$", title)]
    sections = form_sections(body)
    if REPORT_HEADING not in sections:
        errors.append(f"the issue has no \"{REPORT_HEADING}\" field: open it with the OCD Check report form, as the app does")
        return Check(False, errors, [], None, None, None)
    raw = unfence(sections[REPORT_HEADING])
    rest = HEADING_RE.sub(lambda m: "" if m.group(1).strip() == REPORT_HEADING else m.group(0), body)
    errors += [e.replace("$", "the issue text outside the report", 1) for e in scan_text("$", rest)]
    privacy = sections.get(PRIVACY_HEADING)
    if privacy is None or not CHECKED_RE.search(privacy):
        errors.append(f"the \"{PRIVACY_HEADING}\" box is not ticked")
    if raw in ("", "_No response_"):
        errors.append("the report field is empty")
        return Check(False, errors, [], None, None, None)
    if len(raw) > MAX_REPORT_CHARS:
        errors.append(f"the report is longer than {MAX_REPORT_CHARS} characters")
        return Check(False, errors, [], None, None, None)
    digest = report_hash(raw)
    try:
        report = strict_json(raw)
    except json.JSONDecodeError as error:
        errors.append(f"the report is not valid JSON (line {error.lineno}, column {error.colno}: {error.msg})")
        return Check(False, errors, [], None, digest, None)
    except ValueError as error:
        errors.append(f"the report is not valid JSON ({error})")
        return Check(False, errors, [], None, digest, None)
    problems, flags, ref = report_problems(report, today, releases, owner=is_owner(issue))
    errors = list(dict.fromkeys(errors + problems))
    return Check(not errors, errors, flags if not errors else [], report if not errors else None, digest, ref)


ENTRY_NAMES = {
    "volte": "VoLTE",
    "vowifi": "Wi-Fi calling",
    "video_calling": "Video calling",
    "vonr": "VoNR",
    "sms_over_ims": "SMS over IMS",
}
BEARER_NAMES = {"lte": "LTE", "iwlan": "Wi-Fi"}


def settled_class(result: dict[str, Any]) -> str:
    """The record's result class of a settled result: works, calls_out, sms_both_ways or failed."""
    if result["result"] == "failed":
        return "failed"
    if result["entry"] == SMS_ENTRY:
        return "sms_both_ways"
    return "works" if result["settled"]["level"] == "l3" else "calls_out"


def settled_text(result: dict[str, Any]) -> str:
    """A settled result in plain words, as the record and the comment say it. Calls out never claims incoming."""
    settled = result["settled"]
    over = f" over {BEARER_NAMES[settled['bearer']]}" if settled.get("bearer") else ""
    level = settled["level"].upper()
    text = {
        "works": f"works ({level}): calls both ways{over} (audio from packet counts)",
        "calls_out": f"calls out ({level}){over}, incoming not tested (audio from packet counts)",
        "sms_both_ways": f"SMS both ways over IMS ({level}){over}",
        "failed": (f"failed ({level}) at the incoming call{over}" if settled["level"] == "l3" else f"failed ({level}) at the outgoing call{over}, incoming not tested")
        + (f": {result['reason']}" if result.get("reason") else ""),
    }[settled_class(result)]
    return f"{text}; {settled['method']}, measured {settled['measured_on']}"


def entry_name(entry: str) -> str:
    kind, feature = entry_kind(entry)
    if kind == "apn":
        apn, types, protocol = entry.removeprefix("apn:").split("|")
        return f"APN {apn} ({types}{', ' + protocol if protocol else ''})"
    return f"{ENTRY_NAMES[feature]} {kind}"


def comment_line(error: str) -> str:
    """One problem as a list item: the path as code, the message with no
    backtick that could break the Markdown."""
    if error.startswith("$") and ": " in error:
        path, message = error.split(": ", 1)
        return f"- `{path}`: {message.replace('`', chr(39))}"
    return f"- {error.replace('`', chr(39))}"


def comment(check: Check, number: int, repository: str, owner: bool = False) -> str:
    """The bot's one comment on the issue, edited in place on every check.
    OWNER: the issue is from the owner's account (OWNER_ACCOUNTS)."""
    docs = f"https://github.com/{repository}/blob/main/community/README.md"
    lines = [BOT_MARKER]
    if check.valid and is_record(check.report):
        lines += [
            f"**Valid measured record** (`{VALID_LABEL}`) from the owner's account (rule round 30). Record hash: `{check.sha256}`.",
            "",
            f"Through the bot's pull request \"Observed reports (unverified)\", which a maintainer merges after `validate` and the phone "
            f"guard pass, it enters `{MEASURED_FILE}` and so `generated/devices/device-records.json`: a measured record for this "
            "device, ROM line and IMS stack, served only there, for 90 days after its last measurement; the newest issue of a "
            "record key counts. A correction opens a "
            f"source review; no configured carrier value changes ([community/README.md]({docs})).",
            "",
            "| Record | Target | Value | Result | Level | Carrier | Measured |",
            "|---|---|---|---|---|---|---|",
        ]
        for record in [check.report]:
            target = ocd_dataset.record_target_text(record["target"])
            value = {"value": "`" + schema_json_text(record["value"]).replace("|", "\\|")[:60] + "`", "android_default": "Android's default", "none": "none"}[record["value_kind"]]
            carrier = ocd_dataset.record_carrier_text(record["carrier"])
            when = record["first_measured"] + ("" if record["first_measured"] == record["last_measured"] else " to " + record["last_measured"])
            lines.append(f"| `{record['record_key']}` | `{target}` | {value} | {record['result']} | {record['level']} | `{carrier}` | {when} |")
        return "\n".join(lines) + "\n"
    if check.valid:
        report = check.report or {}
        device = report["device"]
        label = SUSPECT_LABEL if check.flags else VALID_LABEL
        lines += [
            f"**Valid OCD Check report** (`{label}`). Report hash: `{check.sha256}`.",
            "",
            "A report points at entries of OCD's data (a commit of main or a release); it never changes an OCD value, a file under `generated/` "
            "or a release, and it never makes a phone skip its own test. At most it makes a phone test an entry earlier. "
            f"It is recorded as `observed/reports/issue-{number}.json` through the bot's pull request "
            "\"Observed reports (unverified)\", which a maintainer merges, and "
            + ("as the owner's report it is not counted in `observed/summary.json` " if owner else
               "`observed/summary.json` counts it as \"reported, not checked by OCD\" once the noise filters let it through ")
            + f"([community/README.md]({docs})).",
            "",
            f"Phone: {device['model']} ({device['codename']}), {device['rom_family']}, Android {device['android_major']}, "
            f"IMS stack {device['ims_stack']}" + (f", build {device['build']}" if device.get("build") else "")
            + f". SIM: {report['sim']['mccmnc']}. Data: {data_label(check.ref or '')}.",
            "",
            "| Entry | OCD's | Phone's | How | Result |",
            "|---|---|---|---|---|",
        ]
        for result in report["results"]:
            reason = f" ({result['reason']})" if result.get("reason") and result["result"] not in PASSED else ""
            lines.append(
                f"| {entry_name(result['entry'])} | {'yes' if result['ocd'] else ''} | {'yes' if result['phone'] else ''} "
                f"| {result['how']} | {result['result']}{reason} |"
            )
        settled = [result for result in report["results"] if "settled" in result]
        if settled:
            lines += ["", "Settled results (rule round 29):"]
            lines += [f"- {entry_name(result['entry'])}: {settled_text(result)}" for result in settled]
            if owner:
                lines += ["", "From the owner's account: since rule round 30 the owner build sends settled results as "
                          f"measured records (`{RECORD_LABEL}` issues), which enter `{MEASURED_FILE}`. This pointer report "
                          "stays in observed/ and changes nothing."]
            else:
                lines += ["", "Not from the owner's account: these stay \"reported, not checked by OCD\"; only the owner's "
                          "phones submit measured records."]
        if check.flags:
            lines += ["", f"**Held as suspect** (`{SUSPECT_LABEL}`) until a maintainer looks; it does not count yet:"]
            lines += [comment_line(flag) for flag in check.flags]
    else:
        shown = check.errors[:MAX_ERRORS]
        lines += [
            f"**This report is not valid** (`{INVALID_LABEL}`). Nothing was recorded.",
            "",
            "What is wrong:",
            *[comment_line(error) for error in shown],
        ]
        if len(check.errors) > len(shown):
            lines.append(f"- and {len(check.errors) - len(shown)} more")
        lines += [
            "",
            "Edit the issue to fix it, and the check runs again. A report passes as the OCD Check app writes it; "
            "if it was changed by hand, open a new one from the app instead.",
        ]
        if any("private data" in error or "phone number" in error or "private identifier" in error for error in check.errors):
            lines += [
                "",
                "**Something here looks like private data.** Edit it out now. GitHub keeps an issue's edit history, "
                f"so ask a maintainer to delete the issue ([SECURITY.md](https://github.com/{repository}/blob/main/SECURITY.md)).",
            ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- observed/


def dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def created_on(issue: dict[str, Any]) -> date:
    return datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00")).astimezone(timezone.utc).date()


def labels_of(issue: dict[str, Any]) -> set[str]:
    return {label["name"] if isinstance(label, dict) else label for label in issue.get("labels", [])}


def is_owner(issue: dict[str, Any]) -> bool:
    """The issue is from the owner's account, by its GitHub user ID."""
    return (issue.get("user") or {}).get("id") in OWNER_ACCOUNTS


def tester_of(issue: dict[str, Any]) -> str:
    return OWNER if is_owner(issue) else OUTSIDE


def report_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The issues that count: report issues, not pull requests, not closed as not planned."""
    out = []
    for issue in issues:
        if "pull_request" in issue or not (LABEL in labels_of(issue) or RECORD_LABEL in labels_of(issue)):
            continue
        if issue.get("state") == "closed" and issue.get("state_reason") == "not_planned":
            continue
        out.append(issue)
    return sorted(out, key=lambda issue: issue["number"])


def cell_of(report: dict[str, Any]) -> dict[str, Any]:
    """Round 19's key: device × carrier profile × stack (with the IMS stack and Android major)."""
    device = report["device"]
    return {
        "device": {"model": device["model"], "codename": device["codename"]},
        "carrier_profile": report["ocd_profile"],
        "mccmnc": report["sim"]["mccmnc"],
        "stack": {"rom_family": device["rom_family"], "ims_stack": device["ims_stack"], "android_major": device["android_major"]},
    }


def statuses(accepted: list[tuple[dict[str, Any], Check]], today: date) -> dict[int, tuple[str, list[str]]]:
    """The noise filters over every valid report: counted, held, superseded,
    duplicate or expired, with the reasons. Account signals are computed here
    from the issues and never written out."""
    out: dict[int, tuple[str, list[str]]] = {}
    first: dict[str, date] = {}
    for issue, _ in accepted:
        author = (issue.get("user") or {}).get("login", "")
        first[author] = min(first.get(author, created_on(issue)), created_on(issue))
    newest: dict[tuple[str, str], int] = {}
    hashes: dict[str, int] = {}
    monthly: dict[tuple[str, str], int] = {}
    for issue, check in accepted:
        if is_record(check.report):
            continue
        author = (issue.get("user") or {}).get("login", "")
        newest[(author, schema_json_text(cell_of(check.report)))] = issue["number"]
    for issue, check in accepted:
        number = issue["number"]
        author = (issue.get("user") or {}).get("login", "")
        released = HOLD_RELEASED_LABEL in labels_of(issue)
        tested = report_date(check.report)
        if check.sha256 in hashes:
            out[number] = ("duplicate", [f"the same report as #{hashes[check.sha256]}"])
            continue
        hashes[check.sha256] = number
        if today - tested > timedelta(days=EXPIRE_DAYS):
            out[number] = ("expired", [f"tested more than {EXPIRE_DAYS} days ago"])
            continue
        if is_owner(issue):
            # Rule round 29: the owner's phones; no account hold, no cap, every report counts toward n.
            # A plausibility flag still holds the report until a maintainer looks.
            flagged = check.flags and not released
            out[number] = ("held", ["suspect: " + "; ".join(flag.split(": ", 1)[-1] for flag in check.flags)]) if flagged else ("counted", [])
            continue
        if newest[(author, schema_json_text(cell_of(check.report)))] != number:
            out[number] = ("superseded", ["a newer report of the same account for the same phone, SIM and software counts instead"])
            continue
        reasons = []
        if not released:
            if today - first[author] < timedelta(days=HOLD_DAYS):
                reasons.append(f"new_account: the account's first accepted report is less than {HOLD_DAYS} days old")
            if check.flags:
                reasons.append("suspect: " + "; ".join(flag.split(": ", 1)[-1] for flag in check.flags))
        month = (author, created_on(issue).strftime("%Y-%m"))
        monthly[month] = monthly.get(month, 0) + 1
        if monthly[month] > MONTHLY_CAP and not released:
            reasons.append(f"monthly_cap: more than {MONTHLY_CAP} reports of one account in one month")
        out[number] = ("held", reasons) if reasons else ("counted", [])
    return out


def record(issue: dict[str, Any], check: Check, status: tuple[str, list[str]]) -> dict[str, Any]:
    """One file under observed/reports/: the report as submitted, its issue,
    its hash and the data it points into (`release`: the main commit or the
    release tag), the status after the noise filters, the tester (`owner`
    for the owner's account, else `outside`), and the mark every report file
    carries: the raw report stays unverified. A measured record of the
    owner's account (an `ocd-device-record` issue) is kept here too, and
    devices/records/measured.json is built from these files."""
    return {
        "issue": issue["number"],
        "reported_on": created_on(issue).isoformat(),
        "report_sha256": check.sha256,
        "release": check.ref,
        "status": status[0],
        "status_reasons": status[1],
        "tester": tester_of(issue),
        "verification": UNVERIFIED,
        "report": check.report,
    }


RECORD_KEYS = {"issue", "reported_on", "report_sha256", "release", "status", "status_reasons", "tester", "verification", "report"}
RECORD_STATUSES = {"counted", "held", "superseded", "duplicate", "expired"}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per device × carrier profile × stack × entry, from the reports of
    accounts other than the owner's: the counted reports by result
    ("reported, not checked by OCD"), "contested" when a counted report
    measured a clean failure, and the held reports. "re-tested by OCD" stays
    null here: the owner's results are measured records (rule round 30).
    Deterministic: no time, sorted keys and cells."""
    cells: dict[str, dict[str, Any]] = {}
    records = [r for r in records if r["tester"] == OUTSIDE]
    for item in sorted(records, key=lambda r: r["issue"]):
        if item["status"] not in ("counted", "held"):
            continue
        report = item["report"]
        base = cell_of(report)
        for result in report["results"]:
            cell = {**base, "entry": result["entry"]}
            key = schema_json_text(cell)
            entry = cells.setdefault(key, {**cell, "reported": None, "contested": None, "retested_by_ocd": None, "held": 0, "verification": UNVERIFIED})
            if item["status"] == "held":
                entry["held"] += 1
                continue
            when = item["reported_on"]
            reported = entry["reported"] or {"status": STATUS_TEXT["reported"], "count": 0, "results": dict.fromkeys(RESULTS, 0), "first_report": when, "last_report": when, "issues": []}
            reported["count"] += 1
            reported["results"][result["result"]] += 1
            reported["first_report"] = min(reported["first_report"], when)
            reported["last_report"] = max(reported["last_report"], when)
            reported["issues"].append(item["issue"])
            entry["reported"] = reported
            if clean_failure(result):
                contested = entry["contested"] or {"status": STATUS_TEXT["contested"], "count": 0, "first_report": when, "last_report": when, "issues": []}
                contested["count"] += 1
                contested["first_report"] = min(contested["first_report"], when)
                contested["last_report"] = max(contested["last_report"], when)
                contested["issues"].append(item["issue"])
                entry["contested"] = contested
    return {
        "schema_version": 1,
        "description": (
            "Unverified observations from OCD Check reports of people's phones (observed/reports/, every account but the "
            "owner's), per device, carrier profile, software stack and entry. A report only points at an entry of OCD's "
            "data at one commit or release; it never changes an OCD value, a file under generated/ or a release, and it "
            "never makes a phone skip its own test. Nothing here is a support claim. The owner's results are measured "
            "records in generated/devices/device-records.json."
        ),
        "verification": UNVERIFIED,
        "statuses": STATUS_DESCRIPTIONS,
        "reports": {status: sum(1 for r in records if r["status"] == status) for status in sorted(RECORD_STATUSES)},
        "cells": [cells[key] for key in sorted(cells)],
    }


MEASURED_DESCRIPTION = (
    "The owner's measured records (rule round 30, item 4): settled results the OCD Check owner build submitted from the "
    "owner's GitHub account, one per record_key, the newest kept and each dropped after its valid_until. Written only by "
    "tools/observed_reports.py rebuild from the report issues; outside reports stay pointers in observed/."
)


def measured_document(records: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    """devices/records/measured.json as of AS_OF: the records of the owner's
    counted submissions, one per record_key (the newest last_measured, then
    the newest issue), without those past valid_until on AS_OF."""
    best: dict[str, tuple[tuple[str, int], dict[str, Any]]] = {}
    for item in sorted(records, key=lambda r: r["issue"]):
        if item["tester"] != OWNER or item["status"] != "counted" or not is_record(item["report"]):
            continue
        for record in [item["report"]]:
            if record["valid_until"] is None or record["valid_until"] < as_of.isoformat():
                continue
            rank = (record["last_measured"], item["issue"])
            if record["record_key"] not in best or best[record["record_key"]][0] <= rank:
                best[record["record_key"]] = (rank, {"issue": item["issue"], "record": record})
    return {"schema_version": 1, "description": MEASURED_DESCRIPTION, "as_of": as_of.isoformat(),
            "records": [best[key][1] for key in sorted(best)]}


def dump_sorted(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def without_as_of(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "as_of"}


def write_measured(root: Path, records: list[dict[str, Any]], today: date) -> None:
    """Writes devices/records/measured.json as of TODAY, but keeps the file
    (and its as_of) when TODAY changes nothing in it, so a quiet day makes no
    bot pull request. validate rebuilds it as of its own as_of."""
    path = root / MEASURED_FILE
    current = measured_document(records, today)
    if path.is_file():
        try:
            old = strict_json(path.read_text(encoding="utf-8"))
            old_day = date.fromisoformat(old["as_of"])
        except (ValueError, TypeError, KeyError):
            old = None
        if old is not None and old_day <= today:
            again = measured_document(records, old_day)
            if path.read_text(encoding="utf-8") == dump_sorted(again) and without_as_of(again) == without_as_of(current):
                return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_sorted(current), encoding="utf-8")


def rebuild(issues: list[dict[str, Any]], root: Path, today: date, releases: Releases | None) -> dict[str, list[int]]:
    """Writes ROOT/observed/ from the issues. Returns the issue numbers written and left out."""
    reports_dir = root / OBSERVED / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    accepted = []
    left_out = []
    for issue in report_issues(issues):
        check = check_issue(issue, today, releases)
        if check.valid:
            accepted.append((issue, check))
        else:
            left_out.append(issue["number"])
    status = statuses(accepted, today)
    records = [record(issue, check, status[issue["number"]]) for issue, check in accepted]
    wanted = {f"issue-{item['issue']}.json": dump(item) for item in records}
    for path in reports_dir.glob("issue-*.json"):
        if path.name not in wanted:
            path.unlink()
    for name, text in wanted.items():
        path = reports_dir / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    (root / OBSERVED / "summary.json").write_text(dump(summarize(records)), encoding="utf-8")
    write_measured(root, records, today)
    # Round 29's observed/retested.json is folded into the measured records.
    (root / OBSERVED / RETESTED_FILE).unlink(missing_ok=True)
    return {"written": [item["issue"] for item in records], "left_out": left_out,
            "counted": [item["issue"] for item in records if item["status"] == "counted"],
            "owner": [item["issue"] for item in records if item["tester"] == OWNER and item["status"] == "counted"],
            "records": [item["issue"] for item in records if is_record(item["report"]) and item["status"] == "counted"]}


def read_records(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records = []
    errors = []
    reports_dir = root / OBSERVED / "reports"
    for path in sorted(reports_dir.glob("*")) if reports_dir.is_dir() else []:
        name = f"{OBSERVED}/reports/{path.name}"
        if path.name == ".gitkeep":
            continue
        match = REPORT_FILE_RE.fullmatch(path.name)
        if not match:
            errors.append(f"{name}: the name must be issue-N.json")
            continue
        try:
            item = strict_json(path.read_text(encoding="utf-8"))
        except ValueError as error:
            errors.append(f"{name}: not valid JSON ({error})")
            continue
        if not isinstance(item, dict) or set(item) != RECORD_KEYS:
            errors.append(f"{name}: must hold exactly {', '.join(sorted(RECORD_KEYS))}")
            continue
        problems = []
        if item["issue"] != int(match.group(1)):
            problems.append(f"issue must be {match.group(1)}")
        if item["verification"] != UNVERIFIED:
            problems.append(f"verification must be {UNVERIFIED}")
        if item["tester"] not in TESTERS:
            problems.append(f"tester must be one of {', '.join(TESTERS)}")
        if item["status"] not in RECORD_STATUSES or not isinstance(item["status_reasons"], list):
            problems.append(f"status must be one of {', '.join(sorted(RECORD_STATUSES))}, with a list of reasons")
        if not isinstance(item["report_sha256"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["report_sha256"]):
            problems.append("report_sha256 must be sha256:<64 hex>")
        if not isinstance(item["release"], str) or not (RELEASE_TAG_RE.fullmatch(item["release"]) or COMMIT_RE.fullmatch(item["release"])):
            problems.append("release must be a data release tag or a commit of main")
        elif isinstance(item["report"], dict) and isinstance(item["report"].get("release"), dict) \
                and "commit" in item["report"]["release"] and item["release"] != item["report"]["release"]["commit"]:
            problems.append("release must be the commit the report names")
        elif is_record(item["report"]) and isinstance(item["report"].get("data"), dict) and item["release"] != item["report"]["data"].get("commit"):
            problems.append("release must be the record's data commit")
        try:
            date.fromisoformat(item["reported_on"])
        except (TypeError, ValueError):
            problems.append("reported_on must be a date")
        report_errors, _, _ = report_problems(item["report"], date.max - timedelta(days=2), None, owner=item["tester"] == OWNER)
        problems += report_errors
        if path.read_text(encoding="utf-8") != dump(item):
            problems.append("is not written as the tool writes it (indent 2, a final newline)")
        errors += [f"{name}: {problem}" for problem in problems]
        if not problems:
            records.append(item)
    return records, errors


def validate_measured(root: Path, records: list[dict[str, Any]], today: date) -> list[str]:
    """devices/records/measured.json: an as_of not after TODAY, and what the reports give as of that day."""
    name = MEASURED_FILE
    path = root / MEASURED_FILE
    if not path.is_file():
        return [f"{name}: is missing"]
    try:
        document = strict_json(path.read_text(encoding="utf-8"))
        as_of = date.fromisoformat(document["as_of"])
    except (ValueError, TypeError, KeyError) as error:
        return [f"{name}: not valid JSON with an as_of date ({error})"]
    if as_of > today + timedelta(days=1):
        return [f"{name}: as_of is in the future"]
    if path.read_text(encoding="utf-8") != dump_sorted(measured_document(records, as_of)):
        return [f"{name}: is not what the reports give as of {as_of.isoformat()}; run tools/observed_reports.py rebuild"]
    return []


def validate_tree(root: Path, today: date | None = None) -> list[str]:
    records, errors = read_records(root)
    summary_path = root / OBSERVED / "summary.json"
    if not summary_path.is_file():
        return errors + [f"{OBSERVED}/summary.json: is missing"]
    try:
        summary = strict_json(summary_path.read_text(encoding="utf-8"))
    except ValueError as error:
        return errors + [f"{OBSERVED}/summary.json: not valid JSON ({error})"]
    schema = load_schema(SUMMARY_SCHEMA, TOOLS.parent / "schemas")
    problems: list[str] = []
    schema_problems(summary, schema, schema, "$", problems)
    errors += [f"{OBSERVED}/summary.json: {problem}" for problem in problems]
    if not errors and summary_path.read_text(encoding="utf-8") != dump(summarize(records)):
        errors.append(f"{OBSERVED}/summary.json: is not what the reports give; run tools/observed_reports.py rebuild")
    if not errors:
        errors += validate_measured(root, records, today or datetime.now(timezone.utc).date())
    if (root / OBSERVED / RETESTED_FILE).exists():
        errors.append(f"{OBSERVED}/{RETESTED_FILE}: round 29's file is folded into {MEASURED_FILE} (rule round 30); remove it")
    return errors


def pr_body(result: dict[str, list[int]], before: set[int]) -> str:
    added = [n for n in result["written"] if n not in before]
    removed = sorted(before - set(result["written"]))
    lines = [
        "Observed reports from OCD Check report issues: people's reports recorded as **unverified**, the owner's measured records as per-device records (rule round 30).",
        "",
        "- `observed/reports/issue-N.json`: one file per valid report, as submitted, with its hash, its release, its tester (`owner` or `outside`) and its status after the noise filters.",
        "- `observed/summary.json`: other accounts' reports per device × carrier profile × stack × entry, \"reported, not checked by OCD\" by result, \"contested\" for a clean measured failure, and the held reports.",
        f"- `{MEASURED_FILE}`: the measured records of the owner's `{RECORD_LABEL}` issues, one per record key, with a 90-day expiry, and from it `generated/devices/device-records.json` and the dataset manifest (tools/ocd_dataset.py generate).",
        "",
        "A pointer report only points at an entry of OCD's data and never changes an OCD value or makes a phone skip its own test. "
        "A measured record is served only on the owner's phones of its device, ROM line and IMS stack; it changes no configured "
        "carrier value in `carriers/`, and a correction opens a source review after the merge. Merging accepts the files; it does not verify the results.",
        "",
        f"Reports in this pull request: {', '.join(f'#{n}' for n in result['written']) or 'none'}; counted: {', '.join(f'#{n}' for n in result['counted']) or 'none'}; "
        f"the owner's: {', '.join(f'#{n}' for n in result.get('owner', [])) or 'none'}; with measured records: {', '.join(f'#{n}' for n in result.get('records', [])) or 'none'}.",
    ]
    if added:
        lines.append(f"New: {', '.join(f'#{n}' for n in added)}.")
    if removed:
        lines.append(f"Removed (withdrawn, closed as not planned, or no longer valid): {', '.join(f'#{n}' for n in removed)}.")
    if result["left_out"]:
        lines.append(f"Left out as not valid: {', '.join(f'#{n}' for n in result['left_out'])}.")
    if added:
        lines += [""] + [f"Closes #{n}" for n in added]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- source reviews


def review_key(record: dict[str, Any]) -> str:
    """One source review per carrier profile (or SIM key) and target."""
    return f"{ocd_dataset.record_carrier_text(record['carrier'])}|{ocd_dataset.record_target_text(record['target'])}"


def published_value(profiles: dict[str, Any] | None, record: dict[str, Any]) -> tuple[bool, Any]:
    """(found, value): OCD's resolved value of the record's key for its profile in main's dataset."""
    if profiles is None or record["carrier"]["scope"] != "profile" or record["target"]["type"] != "config":
        return False, None
    key = record["target"]["key"]
    for network in profiles["networks"].values():
        for profile in network["profiles"]:
            if profile["id"] == record["carrier"]["profile_id"]:
                values = {}
                for item in ocd_dataset.profile_stack(network["profiles"], profile, network["mcc"] + network["mnc"]):
                    values.update(item["values"])
                return (key in values), values.get(key)
    return False, None


def review_records(document: dict[str, Any], profiles: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """The measured records that open a source review (rule 10, rule round
    30): a winner after a measured failure, no value that passed, Android's
    default winning, or a measured value other than OCD's published one."""
    out: dict[str, list[dict[str, Any]]] = {}
    for item in document["records"]:
        record = item["record"]
        found, value = published_value(profiles, record)
        correction = record["value_kind"] == "value" and found and schema_json_text(value) != schema_json_text(record["value"])
        if record["result"] in ("winner_after_failure", "no_value_passed", "emergency_default_won") \
                or record["value_kind"] == "android_default" or correction:
            out.setdefault(review_key(record), []).append({**item, "published": value if found else None, "published_found": found})
    return out


def review_signature(items: list[dict[str, Any]]) -> str:
    """What the review is about, without dates, counts or issue numbers: a renewal does not reopen a closed review."""
    parts = sorted(schema_json_text({k: item["record"][k] for k in ("device", "rom", "ims_stack", "target", "value_kind", "value", "result", "level")}) for item in items)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def review_marker(key: str, signature: str) -> str:
    return f"{REVIEW_MARKER} key={key} signature={signature} -->"


REVIEW_MARKER_RE = re.compile(re.escape(REVIEW_MARKER) + r" key=(\S+) signature=([0-9a-f]{12}) -->")


def review_title(key: str) -> str:
    carrier, target = key.split("|")
    return f"[Source review] {target} for {carrier}"


def review_body(key: str, items: list[dict[str, Any]], as_of: str, repository: str) -> str:
    carrier, target = key.split("|")
    base = f"https://github.com/{repository}/blob/main"
    lines = [
        review_marker(key, review_signature(items)),
        f"**Source review** (rule 10, rule round 30): the owner's phone measured `{target}` for `{carrier}` differently from OCD's "
        "configured value, or found no value that passes.",
        "",
        "| Phone | Software | Measured value | Result | OCD's published value | Method | n | Measured | Valid until | Data |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in sorted(items, key=lambda i: i["record"]["record_key"]):
        record = item["record"]
        value = {"value": "`" + schema_json_text(record["value"])[:80] + "`", "android_default": "Android's default", "none": "none passed"}[record["value_kind"]]
        published = "`" + schema_json_text(item["published"])[:80] + "`" if item["published_found"] else "none published"
        stack = f"{record['rom']['family']} {record['rom']['line']}, {record['ims_stack']['id']}" + (f" ({record['ims_stack']['fork']})" if record["ims_stack"]["fork"] else "")
        when = record["first_measured"] + ("" if record["first_measured"] == record["last_measured"] else " to " + record["last_measured"])
        lines.append(
            f"| {record['device']['model']} ({record['device']['codename']}) | {stack} | {value} | {record['result']} ({record['level']}) | "
            f"{published} | {record['method']} | {record['n']} | {when} | {record['valid_until']} | commit {record['data']['commit'][:12]} |"
        )
    lines += [
        "",
        f"Records: [`{MEASURED_FILE}`]({base}/{MEASURED_FILE}) as of {as_of}, from the report issues "
        + ", ".join(f"#{n}" for n in sorted({item["issue"] for item in items})) + ".",
        "",
        "**What to do.** Review the source or importer behind OCD's value for this profile "
        f"([`generated/evidence-index.json`]({base}/generated/evidence-index.json) names the source family). If the source "
        "or the importer is wrong, fix it there, with this evidence in the pull request; the configured value then changes "
        "through the normal data path. If the cause is the phone, its IMS stack or the SIM's plan, say so here. A maintainer "
        "closes the issue after the review.",
        "",
        "This issue changes nothing by itself. The measured record is served only on the owner's phones of its device, ROM line "
        "and IMS stack (rule round 30); configured carrier values in `carriers/` change only through a source review. The bot "
        "opens one issue per profile and target, keeps this text current while records are current, never closes it, and opens "
        "a new one after a close only when the measured results change.",
    ]
    return "\n".join(lines) + "\n"


def review_plan(document: dict[str, Any], issues: list[dict[str, Any]], repository: str, profiles: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The source-review issues to open or update: one per key with current
    records. An open bot issue of the key is updated when its text differs;
    without one, a new issue is opened unless a closed one already covers the
    same measured results. Issues the bot did not open are never touched."""
    bot: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        if "pull_request" in issue or (issue.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        match = REVIEW_MARKER_RE.match((issue.get("body") or "").replace("\r\n", "\n"))
        if match:
            bot.setdefault(match.group(1), []).append({**issue, "signature": match.group(2)})
    plan = []
    for key, items in sorted(review_records(document, profiles).items()):
        body = review_body(key, items, document["as_of"], repository)
        existing = sorted(bot.get(key, []), key=lambda i: i["number"])
        open_ = [i for i in existing if i.get("state") == "open"]
        if open_:
            target = open_[-1]
            if (target.get("body") or "").replace("\r\n", "\n") != body:
                plan.append({"action": "update", "number": target["number"], "key": key, "body": body})
        elif not any(i["signature"] == review_signature(items) for i in existing):
            plan.append({"action": "create", "title": review_title(key), "key": key, "body": body})
    return plan


# ---------------------------------------------------------------- CLI


def today_utc(value: str | None) -> date:
    return date.fromisoformat(value) if value else datetime.now(timezone.utc).date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("check-issue")
    one.add_argument("--event", type=Path, required=True)
    one.add_argument("--result", type=Path, required=True)
    one.add_argument("--comment", type=Path, required=True)
    one.add_argument("--root", type=Path, default=Path("."), help="the checkout of main with its history and data-* tags")
    one.add_argument("--main", default="HEAD", help="the ref whose history is main's (default HEAD)")
    one.add_argument("--repository", default="open-carrier-data/open-carrier-data")
    one.add_argument("--today")
    build = sub.add_parser("rebuild")
    build.add_argument("--issues", type=Path, required=True)
    build.add_argument("--root", type=Path, default=Path("."))
    build.add_argument("--main", default="HEAD")
    build.add_argument("--pr-body", type=Path)
    build.add_argument("--today")
    check = sub.add_parser("validate")
    check.add_argument("--root", type=Path, default=Path("."))
    check.add_argument("--today")
    review = sub.add_parser("source-reviews")
    review.add_argument("--root", type=Path, default=Path("."))
    review.add_argument("--issues", type=Path, required=True, help="the repository's issues labelled source-review (a JSON list)")
    review.add_argument("--out", type=Path, required=True, help="a folder for plan.json and the issue bodies")
    review.add_argument("--repository", default="open-carrier-data/open-carrier-data")
    single = sub.add_parser("check-file")
    single.add_argument("report", type=Path)
    single.add_argument("--root", type=Path, default=Path("."))
    single.add_argument("--main", default="HEAD")
    single.add_argument("--today")
    args = parser.parse_args(argv)

    if args.command == "check-issue":
        event = json.loads(args.event.read_text(encoding="utf-8"))
        issue = event["issue"]
        result = check_issue(issue, today_utc(args.today), Releases(args.root, args.main))
        args.result.write_text(dump({
            "issue": issue["number"], "valid": result.valid, "suspect": bool(result.flags), "errors": result.errors,
            "flags": result.flags, "report_sha256": result.sha256, "release": result.ref,
            "intake_label": RECORD_LABEL if is_record_issue(issue) else LABEL,
        }), encoding="utf-8")
        args.comment.write_text(comment(result, issue["number"], args.repository, owner=is_owner(issue)), encoding="utf-8")
        print(f"issue #{issue['number']}: {'valid' if result.valid else 'not valid'}{' (suspect)' if result.flags else ''}, {result.sha256}")
        for line in result.errors + result.flags:
            print(f"  {line}")
        return 0
    if args.command == "rebuild":
        issues = json.loads(args.issues.read_text(encoding="utf-8"))
        before = {int(m.group(1)) for p in (args.root / OBSERVED / "reports").glob("issue-*.json") if (m := REPORT_FILE_RE.fullmatch(p.name))}
        result = rebuild(issues, args.root, today_utc(args.today), Releases(args.root, args.main))
        if args.pr_body:
            args.pr_body.write_text(pr_body(result, before), encoding="utf-8")
        print(f"written: {result['written']}; counted: {result['counted']}; the owner's: {result['owner']}; with measured records: {result['records']}; left out as not valid: {result['left_out']}")
        return 0
    if args.command == "source-reviews":
        errors = validate_tree(args.root)
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            return 1
        document = json.loads((args.root / MEASURED_FILE).read_text(encoding="utf-8"))
        profiles_path = args.root / ocd_dataset.FILES["profiles"][1]
        profiles = json.loads(profiles_path.read_text(encoding="utf-8")) if profiles_path.is_file() else None
        plan = review_plan(document, json.loads(args.issues.read_text(encoding="utf-8")), args.repository, profiles)
        args.out.mkdir(parents=True, exist_ok=True)
        steps = []
        for index, step in enumerate(plan):
            name = f"review-{index + 1}.md"
            (args.out / name).write_text(step.pop("body"), encoding="utf-8")
            steps.append({**step, "body_file": name})
        (args.out / "plan.json").write_text(dump(steps), encoding="utf-8")
        for step in steps:
            print(f"{step['action']}: {step['key']}" + (f" (#{step['number']})" if "number" in step else ""))
        if not steps:
            print("source reviews: nothing to open or update")
        return 0
    if args.command == "validate":
        errors = validate_tree(args.root, today_utc(args.today))
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        if not errors:
            records, _ = read_records(args.root)
            print(f"observed/: {len(records)} report(s), summary up to date")
        return 1 if errors else 0
    if args.command == "check-file":
        text = args.report.read_text(encoding="utf-8")
        try:
            report = strict_json(text)
        except ValueError as error:
            print(f"error: not valid JSON ({error})", file=sys.stderr)
            return 1
        problems, flags, ref = report_problems(report, today_utc(args.today), Releases(args.root, args.main))
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        for flag in flags:
            print(f"suspect: {flag}", file=sys.stderr)
        if not problems:
            print(f"valid against {data_label(ref or '')}{' (suspect)' if flags else ''}; {report_hash(text)}")
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
