#!/usr/bin/env python3
"""OCD Check reports: check an issue, rebuild observed/, validate observed/.

A report points, phones prove (the anti-fake design of 2026-10-20). An OCD
Check report names entries of one OCD data release's closed list, never a
value: `volte:on`, `volte:off`, the same for `vowifi`, `sms_over_ims`,
`video_calling` and `vonr`, or `apn:<row key>` for a row that release's
apns-conf.xml has for the SIM's network. Each entry carries the result class
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
      express, and the release: its tag exists, its data digest matches, the
      profile and every APN row key are in it. Plausibility checks against
      the release flag a report as suspect. Writes {"valid", "suspect",
      "errors", "flags", "report_sha256"} and the bot's comment. Exit 0
      whether the report is valid or not.

  rebuild --issues ISSUES.json --root DIR [--pr-body BODY.md]
      Rebuilds DIR/observed/ from every report issue (a JSON list as the REST
      API returns them): one file per valid report, observed/reports/issue-N.json,
      with its status after the noise filters, and observed/summary.json. An
      issue closed as not planned is left out, which is how a maintainer
      withdraws a report.

  validate --root DIR
      Checks every file under DIR/observed/reports/ and that
      observed/summary.json is what the reports give. Exit 1 on a problem.

  check-file REPORT.json [--root DIR]
      Checks one bare report, as the app wrote it, with DIR's release tags.
      Exit 1 when invalid.

The noise filters (they order what people read; they are not a defence):
closed schema, privacy scan, a hash of the report text, plausibility against
the release, one counted report per account and cell, a monthly cap per
account, a hold on an account's reports until 14 days after its first
accepted report (counted from that report, not from the account's sign-up),
and expiry 90 days after the test. Observed reports are unverified
observations, kept apart from carriers/, generated/ and the releases; they
never change an OCD value. Only the standard library is used, as in the
other validators.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, NamedTuple

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from validate_public_carrier_data import SCHEMA_TYPES, load_schema, schema_json_text  # noqa: E402

REPORT_SCHEMA = "ocd-check-report.schema.json"
SUMMARY_SCHEMA = "observed-summary.schema.json"
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
REPORT_FILE_RE = re.compile(r"issue-([1-9][0-9]{0,8})\.json")
RELEASE_TAG_RE = re.compile(r"data-20[0-9]{2}\.(0[1-9]|1[0-2])(\.[1-9][0-9]{0,2})?")

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
    "retested_by_ocd": "Set only from OCD's own phones after a passed T2 call test, from the owner's private ledger. Empty until that status is published.",
}

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
HEX_FIELDS = {"$.ocd_profile", "$.sim.gid1_prefix", "$.release.data_digest", "$.tested_on"}
SAFE_KEY = re.compile(r"[a-z][a-z0-9_]{0,40}")


class Check(NamedTuple):
    valid: bool
    errors: list[str]
    flags: list[str]
    report: dict[str, Any] | None
    sha256: str | None
    tag: str | None


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
        if result["result"] == "works" and kind == "on" and not t2:
            out.append(f"{where}.result: works needs a passed T2 call test in call_types")
        if result["result"] == "works" and kind == "off" and not off_calls:
            out.append(f"{where}.result: works for an off entry needs a call measured with the feature off")
        if result["result"] == "signed_in" and t2:
            out.append(f"{where}.result: with a passed T2 call test the result is works")
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


# ---------------------------------------------------------------- releases


class Releases:
    """OCD's data releases, read from this repository's `data-*` tags with
    `git show`. The release a report was tested against must exist; its
    profiles and its apns-conf.xml rows are the closed list a report points
    into."""

    APN = re.compile(r"<apn\s+([^>]*?)/?>")
    ATTRIBUTE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cache: dict[tuple[str, str], Any] = {}

    def git(self, *args: str) -> str | None:
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        return done.stdout if done.returncode == 0 else None

    def tags(self) -> list[str]:
        if ("tags", "") not in self.cache:
            out = self.git("tag", "-l", "data-*") or ""
            self.cache[("tags", "")] = sorted(t for t in out.split() if RELEASE_TAG_RE.fullmatch(t))
        return self.cache[("tags", "")]

    def file(self, tag: str, path: str) -> str | None:
        if (tag, path) not in self.cache:
            self.cache[(tag, path)] = self.git("show", f"refs/tags/{tag}:{path}")
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


def release_problems(report: dict[str, Any], releases: Releases) -> tuple[list[str], list[str], str | None]:
    """(errors, flags, tag): the release the report points into, and whether
    every pointer exists there. Flags are plausibility checks against the
    release: they hold a report, they do not reject it."""
    errors: list[str] = []
    flags: list[str] = []
    tag = report["release"]["tag"]
    digest = report["release"]["data_digest"]
    if tag is not None:
        if tag not in releases.tags():
            return [f"$.release.tag: {tag} is not an OCD data release"], flags, None
        if releases.digest(tag) != digest:
            return [f"$.release.data_digest: is not the data digest of {tag}"], flags, None
    else:
        tag = next((t for t in releases.tags() if releases.digest(t) == digest), None)
        if tag is None:
            return ["$.release.data_digest: is the digest of no OCD data release; pull a release and test again"], flags, None
    profile = report["ocd_profile"]
    capabilities = releases.profiles(tag).get(profile) if profile else None
    if profile is not None and capabilities is None:
        errors.append(f"$.ocd_profile: is not a profile of {tag}")
    mccmnc = report["sim"]["mccmnc"]
    keys = None
    for index, result in enumerate(report["results"]):
        kind, feature = entry_kind(result["entry"])
        if kind == "apn":
            keys = releases.apn_keys(tag, mccmnc) if keys is None else keys
            if result["entry"].removeprefix("apn:") not in keys:
                errors.append(f"$.results[{index}].entry: is not an APN row {tag} has for {mccmnc}")
            continue
        if result["result"] in PASSED and kind == "on" and feature == "video_calling" and report["device"]["ims_stack"] == "phh_ims":
            flags.append(f"$.results[{index}]: video calling passed on PHH IMS, which has no video")
        if capabilities is not None and (profile, feature) not in releases.recorded(tag):
            value = {"supported": "on", "unsupported": "off"}.get(capabilities.get(feature, "unknown"))
            if result["ocd"] and value != kind:
                flags.append(f"$.results[{index}].ocd: {tag} gives {feature} {value or 'no value'} for this profile, with no device record")
    return errors, flags, tag


def report_problems(report: Any, today: date, releases: Releases | None) -> tuple[list[str], list[str], str | None]:
    """(errors, flags, release tag) of one parsed report. Without RELEASES
    the release is not checked (validate on a checkout without tags)."""
    schema = load_schema(REPORT_SCHEMA, TOOLS.parent / "schemas")
    problems: list[str] = []
    if isinstance(report, dict) and report.get("schema") == "ocd-check-report.v1":
        return ["$.schema: this is the read-only check's report (ocd-check-report.v1); the form takes the owner build's test report (ocd-check-test-report)"], [], None
    schema_problems(report, schema, schema, "$", problems)
    problems += privacy_problems(report)
    if problems:
        return list(dict.fromkeys(problems)), [], None
    problems += consistency_problems(report, today)
    if problems or releases is None:
        return list(dict.fromkeys(problems)), [], report["release"]["tag"]
    errors, flags, tag = release_problems(report, releases)
    return errors, flags, tag


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
    problems, flags, tag = report_problems(report, today, releases)
    errors = list(dict.fromkeys(errors + problems))
    return Check(not errors, errors, flags if not errors else [], report if not errors else None, digest, tag)


ENTRY_NAMES = {
    "volte": "VoLTE",
    "vowifi": "Wi-Fi calling",
    "video_calling": "Video calling",
    "vonr": "VoNR",
    "sms_over_ims": "SMS over IMS",
}


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


def comment(check: Check, number: int, repository: str) -> str:
    """The bot's one comment on the issue, edited in place on every check."""
    docs = f"https://github.com/{repository}/blob/main/community/README.md"
    lines = [BOT_MARKER]
    if check.valid:
        report = check.report or {}
        device = report["device"]
        label = SUSPECT_LABEL if check.flags else VALID_LABEL
        lines += [
            f"**Valid OCD Check report** (`{label}`). Report hash: `{check.sha256}`.",
            "",
            "A report points at entries of an OCD data release; it never changes an OCD value, a file under `generated/` "
            "or a release, and it never makes a phone skip its own test. At most it makes a phone test an entry earlier. "
            f"It is recorded as `observed/reports/issue-{number}.json` through the bot's pull request "
            "\"Observed reports (unverified)\", which a maintainer merges, and `observed/summary.json` counts it as "
            "\"reported, not checked by OCD\" once the noise filters let it through "
            f"([community/README.md]({docs})).",
            "",
            f"Phone: {device['model']} ({device['codename']}), {device['rom_family']}, Android {device['android_major']}, "
            f"IMS stack {device['ims_stack']}. SIM: {report['sim']['mccmnc']}. Release: {check.tag}.",
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


def report_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The issues that count: report issues, not pull requests, not closed as not planned."""
    out = []
    for issue in issues:
        if "pull_request" in issue or LABEL not in labels_of(issue):
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
        author = (issue.get("user") or {}).get("login", "")
        newest[(author, schema_json_text(cell_of(check.report)))] = issue["number"]
    for issue, check in accepted:
        number = issue["number"]
        author = (issue.get("user") or {}).get("login", "")
        released = HOLD_RELEASED_LABEL in labels_of(issue)
        tested = date.fromisoformat(check.report["tested_on"])
        if check.sha256 in hashes:
            out[number] = ("duplicate", [f"the same report as #{hashes[check.sha256]}"])
            continue
        hashes[check.sha256] = number
        if today - tested > timedelta(days=EXPIRE_DAYS):
            out[number] = ("expired", [f"tested more than {EXPIRE_DAYS} days ago"])
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
    its hash and release, the status after the noise filters, and the mark
    every observed entry carries."""
    return {
        "issue": issue["number"],
        "reported_on": created_on(issue).isoformat(),
        "report_sha256": check.sha256,
        "release": check.tag,
        "status": status[0],
        "status_reasons": status[1],
        "verification": UNVERIFIED,
        "report": check.report,
    }


RECORD_KEYS = {"issue", "reported_on", "report_sha256", "release", "status", "status_reasons", "verification", "report"}
RECORD_STATUSES = {"counted", "held", "superseded", "duplicate", "expired"}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per device × carrier profile × stack × entry: the counted reports by
    result ("reported, not checked by OCD"), "contested" when a counted
    report measured a clean failure, the held reports, and the
    "re-tested by OCD" status, which only OCD's own phones set and which is
    empty here. Deterministic: no time, sorted keys and cells."""
    cells: dict[str, dict[str, Any]] = {}
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
            "Unverified observations from OCD Check reports (observed/reports/), per device, carrier profile, software "
            "stack and release entry. A report only points at an entry of an OCD data release; it never changes an OCD "
            "value, a file under generated/ or a release, and it never makes a phone skip its own test. Nothing here is "
            "a support claim."
        ),
        "verification": UNVERIFIED,
        "statuses": STATUS_DESCRIPTIONS,
        "reports": {status: sum(1 for r in records if r["status"] == status) for status in sorted(RECORD_STATUSES)},
        "cells": [cells[key] for key in sorted(cells)],
    }


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
    return {"written": [item["issue"] for item in records], "left_out": left_out,
            "counted": [item["issue"] for item in records if item["status"] == "counted"]}


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
        if item["status"] not in RECORD_STATUSES or not isinstance(item["status_reasons"], list):
            problems.append(f"status must be one of {', '.join(sorted(RECORD_STATUSES))}, with a list of reasons")
        if not isinstance(item["report_sha256"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["report_sha256"]):
            problems.append("report_sha256 must be sha256:<64 hex>")
        if not isinstance(item["release"], str) or not RELEASE_TAG_RE.fullmatch(item["release"]):
            problems.append("release must be a data release tag")
        try:
            date.fromisoformat(item["reported_on"])
        except (TypeError, ValueError):
            problems.append("reported_on must be a date")
        report_errors, _, _ = report_problems(item["report"], date.max - timedelta(days=2), None)
        problems += report_errors
        if path.read_text(encoding="utf-8") != dump(item):
            problems.append("is not written as the tool writes it (indent 2, a final newline)")
        errors += [f"{name}: {problem}" for problem in problems]
        if not problems:
            records.append(item)
    return records, errors


def validate_tree(root: Path) -> list[str]:
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
    return errors


def pr_body(result: dict[str, list[int]], before: set[int]) -> str:
    added = [n for n in result["written"] if n not in before]
    removed = sorted(before - set(result["written"]))
    lines = [
        "Observed reports from OCD Check report issues, recorded as **unverified**.",
        "",
        "- `observed/reports/issue-N.json`: one file per valid report, as submitted, with its hash, its release and its status after the noise filters.",
        "- `observed/summary.json`: per device × carrier profile × stack × release entry, \"reported, not checked by OCD\" by result, \"contested\" for a clean measured failure, the held reports, and an empty \"re-tested by OCD\".",
        "",
        "A report only points at an entry of an OCD data release. Nothing here changes `carriers/`, `generated/` or a release, "
        "and a report never changes an OCD value or makes a phone skip its own test. Merging accepts the files; it does not verify the results.",
        "",
        f"Reports in this pull request: {', '.join(f'#{n}' for n in result['written']) or 'none'}; counted: {', '.join(f'#{n}' for n in result['counted']) or 'none'}.",
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
    one.add_argument("--root", type=Path, default=Path("."), help="the checkout whose data-* tags are the releases")
    one.add_argument("--repository", default="open-carrier-data/open-carrier-data")
    one.add_argument("--today")
    build = sub.add_parser("rebuild")
    build.add_argument("--issues", type=Path, required=True)
    build.add_argument("--root", type=Path, default=Path("."))
    build.add_argument("--pr-body", type=Path)
    build.add_argument("--today")
    check = sub.add_parser("validate")
    check.add_argument("--root", type=Path, default=Path("."))
    single = sub.add_parser("check-file")
    single.add_argument("report", type=Path)
    single.add_argument("--root", type=Path, default=Path("."))
    single.add_argument("--today")
    args = parser.parse_args(argv)

    if args.command == "check-issue":
        event = json.loads(args.event.read_text(encoding="utf-8"))
        issue = event["issue"]
        result = check_issue(issue, today_utc(args.today), Releases(args.root))
        args.result.write_text(dump({
            "issue": issue["number"], "valid": result.valid, "suspect": bool(result.flags), "errors": result.errors,
            "flags": result.flags, "report_sha256": result.sha256, "release": result.tag,
        }), encoding="utf-8")
        args.comment.write_text(comment(result, issue["number"], args.repository), encoding="utf-8")
        print(f"issue #{issue['number']}: {'valid' if result.valid else 'not valid'}{' (suspect)' if result.flags else ''}, {result.sha256}")
        for line in result.errors + result.flags:
            print(f"  {line}")
        return 0
    if args.command == "rebuild":
        issues = json.loads(args.issues.read_text(encoding="utf-8"))
        before = {int(m.group(1)) for p in (args.root / OBSERVED / "reports").glob("issue-*.json") if (m := REPORT_FILE_RE.fullmatch(p.name))}
        result = rebuild(issues, args.root, today_utc(args.today), Releases(args.root))
        if args.pr_body:
            args.pr_body.write_text(pr_body(result, before), encoding="utf-8")
        print(f"written: {result['written']}; counted: {result['counted']}; left out as not valid: {result['left_out']}")
        return 0
    if args.command == "validate":
        errors = validate_tree(args.root)
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
        problems, flags, tag = report_problems(report, today_utc(args.today), Releases(args.root))
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        for flag in flags:
            print(f"suspect: {flag}", file=sys.stderr)
        if not problems:
            print(f"valid against {tag}{' (suspect)' if flags else ''}; {report_hash(text)}")
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
