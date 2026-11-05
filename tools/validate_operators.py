#!/usr/bin/env python3
"""Validate generated/operators/ and rule 3's prefix limits on every published file (rule round 32).

  python3 tools/validate_operators.py [ROOT] [--freshness warn|fail] [--require] [--today YYYY-MM-DD]

generated/operators/statements.json (schemas/operator-statements.schema.json)
holds what operators, brands and MVNOs state on their own pages, with the
page, the day it was read and a passage hash, never quoted text.
generated/operators/carrier-identity.json (schemas/carrier-identity.schema.json)
is the carrier-identity table. generated/operators/entities.json
(schemas/operator-entities.schema.json, migration step 5, rule round 47,
item 4) holds its entries as networks, operators and brands.
generated/operators/offers.json (schemas/operator-offers.schema.json, step 8)
holds dated offers with feature states. The checks:

- both files match their schemas, are sorted and unique, and name only keys
  the identity table has;
- a statement that sets a value is a live, second-checked, network-wide MMS
  end with MMSC hosts, an end day that has passed and an admitting source;
- an unlapsed statement is younger than 180 days since its confirmation and
  365 since its sweep (a warning, or an error with --freshness fail);
- free text carries no quotation marks, phone numbers, long digit runs or
  e-mail addresses;
- every identity selector maps to a published profile with exactly that
  match;
- every profile that publishes mms unsupported from operator_statement lies
  inside a value-setting statement's network codes and MMSC hosts, and every
  operator_statement_lapsed:mms gate inside a lapsed one;
- entities.json is sorted and unique, lists every identity entry, names only
  operators it has, keeps MCC and MNC apart, keeps a link's dates in order, and
  stays out of what phones pull;
- every offer is sorted, belongs to a known brand, rests on an admitted statement
  of that brand and service, and has a state that statement allows: a lapsed
  statement or offer reads unknown, and a state stronger than depends_on_plan
  needs a passage of the carrier's own page;
- every IMSI and ICCID selector in every published file (carriers/,
  generated/, devices/, observed/: JSON selectors, the Google lane's rules
  and fill conditions, apns-conf.xml's mvno_match_data and
  carrier-config-list.xml's imsi attributes) passes rule 3's
  subscriber_prefix_ok: an ICCID prefix of 5 to 13 digits, an IMSI pattern
  of 5 to 10 digits or x.

Exit 1 on a problem. Only the standard library is used.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import validate_public_carrier_data as carrier_validator  # noqa: E402

OPERATORS_DIR = "generated/operators"
STATEMENTS = f"{OPERATORS_DIR}/statements.json"
IDENTITY = f"{OPERATORS_DIR}/carrier-identity.json"
ENTITIES = f"{OPERATORS_DIR}/entities.json"
OFFERS = f"{OPERATORS_DIR}/offers.json"
# What carrier settings read: the dataset's manifest. The files below are for
# people and are never a value, so they stay out of it (rule round 47, item 4).
# OCD Android reads offers.json and sim-groups.json for the plan picker only, by
# the pull's own path, never through the manifest (rule round 51, item 4).
MANIFEST = "generated/ocd-dataset/manifest.json"
SIM_GROUPS = f"{OPERATORS_DIR}/sim-groups.json"
PLAN_FAMILIES = f"{OPERATORS_DIR}/plan-families.json"
NEVER_PULLED = (ENTITIES, OFFERS, SIM_GROUPS, PLAN_FAMILIES,)
OPERATOR_STATEMENT = "operator_statement"
LAPSED_GATE = "operator_statement_lapsed"
LAPSE_UNCONFIRMED_DAYS = 180
LAPSE_UNSWEPT_DAYS = 365
PUBLISHED_DIRS = ("carriers", "generated", "devices", "observed")
SELECTOR_KEYS = {"iccid_prefixes": "iccid", "imsi_prefix_patterns": "imsi", "iccid": "iccid", "imsi": "imsi"}
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")
DIGIT_RUN_RE = re.compile(r"\d[\d /-]{5,}\d")
PHONE_RE = re.compile(r"\+\d[\d /-]{6,}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TEXT_FIELDS = ("operator", "paraphrase")


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_problems(path: Path, value: Any, name: str) -> list[str]:
    try:
        carrier_validator.check_against_schema(path, value, name)
    except carrier_validator.ValidationError as exc:
        return [str(exc)]
    return []


def text_problem(text: str, where: str) -> str | None:
    undated = DATE_RE.sub(" ", text)
    if DIGIT_RUN_RE.search(undated) or PHONE_RE.search(undated):
        return f"{where}: a long digit run looks like a phone number or an identity"
    if EMAIL_RE.search(text):
        return f"{where}: an e-mail address is not allowed"
    return None


# ---------------------------------------------------------------- rule 3 everywhere


def imsi_attribute_stem(value: str) -> str:
    """carrier-config-list.xml writes an IMSI rule as a pattern such as
    26207[0-9]*: a trailing any-digits run is dropped and a single-digit
    wildcard reads as x."""
    value = re.sub(r"(\[0-9\]|\\d|\.)\*$", "", value)
    return re.sub(r"\[0-9\]|\\d|\.|\?", "x", value)


def json_selector_problems(value: Any, where: str) -> Iterable[str]:
    if isinstance(value, dict):
        kind = value.get("kind")
        if kind in ("imsi", "iccid") and isinstance(value.get("value"), str):
            if not carrier_validator.subscriber_prefix_ok(kind, value["value"]):
                yield f"{where}: an {kind} selector of {len(value['value'])} characters is outside rule 3's prefix limits"
        for key, item in value.items():
            if key in SELECTOR_KEYS:
                for selector in item if isinstance(item, list) else [item]:
                    if isinstance(selector, (str, int)) and not carrier_validator.subscriber_prefix_ok(SELECTOR_KEYS[key], str(selector)):
                        yield f"{where}.{key}: a selector of {len(str(selector))} characters is outside rule 3's prefix limits"
            elif isinstance(item, (dict, list)):
                yield from json_selector_problems(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from json_selector_problems(item, f"{where}[{index}]")


def xml_selector_problems(path: Path, label: str) -> Iterable[str]:
    for element in ET.parse(path).getroot().iter():
        kind = element.get("mvno_type")
        if kind in ("imsi", "iccid") and not carrier_validator.subscriber_prefix_ok(kind, element.get("mvno_match_data") or ""):
            yield f"{label}: a <{element.tag}> {kind} mvno_match_data is outside rule 3's prefix limits"
        for attribute in ("imsi", "iccid"):
            raw = element.get(attribute)
            if raw is not None:
                stem = imsi_attribute_stem(raw) if attribute == "imsi" else raw
                if not carrier_validator.subscriber_prefix_ok(attribute, stem):
                    yield f"{label}: a <{element.tag}> {attribute} attribute is outside rule 3's prefix limits"


def prefix_problems(root: Path) -> list[str]:
    """Rule 3's limits on every published file. The problem lines name the
    file, the place and the length, never the selector itself."""
    out: list[str] = []
    for directory in PUBLISHED_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            label = path.relative_to(root).as_posix()
            if path.suffix == ".json":
                try:
                    value = load(path)
                except (OSError, json.JSONDecodeError) as exc:
                    out.append(f"{label}: unreadable JSON: {exc}")
                    continue
                out.extend(f"{label}: {problem}" for problem in json_selector_problems(value, "$"))
            elif path.suffix == ".xml":
                try:
                    out.extend(xml_selector_problems(path, label))
                except ET.ParseError as exc:
                    out.append(f"{label}: unreadable XML: {exc}")
    return out


# ---------------------------------------------------------------- statements


def lapse_since(statement: dict[str, Any]) -> date:
    checked = date.fromisoformat(statement["checked_at"])
    swept = date.fromisoformat(statement["swept_at"])
    return min(checked + timedelta(days=LAPSE_UNCONFIRMED_DAYS), swept + timedelta(days=LAPSE_UNSWEPT_DAYS))


def statement_problems(data: dict[str, Any], today: date, identity_keys: set[str] | None) -> tuple[list[str], list[str]]:
    """(errors, freshness warnings) for statements.json."""
    errors: list[str] = []
    stale: list[str] = []
    statements = data["statements"]
    ids = [item["id"] for item in statements]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        errors.append(f"{STATEMENTS}: statements must be sorted by id and unique")
    pairs = [(item["identity_key"], item["service"]) for item in statements if item["status"] != "unknown"]
    if len(pairs) != len(set(pairs)):
        errors.append(f"{STATEMENTS}: one status per brand and service")
    if data["countries"] != sorted({item["country"] for item in statements}):
        errors.append(f"{STATEMENTS}: countries must list the statements' countries, sorted")
    counts = {
        "statements": len(statements),
        "lapsed": sum(1 for item in statements if "lapsed" in item),
        "sets_value": sum(1 for item in statements if item["sets_value"]),
    }
    if data["counts"] != counts:
        errors.append(f"{STATEMENTS}: counts must be {counts}")
    by_id = {item["id"]: item for item in statements}
    for item in statements:
        where = f"{STATEMENTS}: {item['id']}"
        if identity_keys is not None and item["identity_key"] not in identity_keys:
            errors.append(f"{where}: identity_key {item['identity_key']} is not in {IDENTITY}")
        for name in TEXT_FIELDS:
            problem = text_problem(item[name], f"{where}.{name}")
            if problem:
                errors.append(problem)
        for index, source in enumerate(item["sources"]):
            problem = text_problem(source["publisher"], f"{where}.sources[{index}].publisher")
            if problem:
                errors.append(problem)
        if not any(source["role"] == "admits" for source in item["sources"]):
            errors.append(f"{where}: a statement rests on an admitting source")
        urls = [source["url"] for source in item["sources"]]
        if len(urls) != len(set(urls)):
            errors.append(f"{where}: a source is listed twice")
        if item["mccmnc"] != sorted(item["mccmnc"]) or item.get("mmsc_hosts", []) != sorted(item.get("mmsc_hosts", [])):
            errors.append(f"{where}: mccmnc and mmsc_hosts are sorted")
        own_status = item.get("previous_status", item["status"])
        if "last_day" in item and "first_day_without" in item and date.fromisoformat(item["first_day_without"]) != date.fromisoformat(item["last_day"]) + timedelta(days=1):
            errors.append(f"{where}: first_day_without is the day after last_day")
        if own_status == "ended" and "first_day_without" not in item:
            errors.append(f"{where}: an end needs first_day_without")
        if own_status != "ended" and ("first_day_without" in item or "last_day" in item):
            errors.append(f"{where}: only an end carries last_day or first_day_without")
        if "mmsc_hosts" in item and (item["service"] != "mms" or item["scope"] != "network" or own_status != "ended"):
            errors.append(f"{where}: only a network-wide MMS end carries mmsc_hosts")
        if ("lapsed" in item) != ("previous_status" in item) or ("lapsed" in item and item["status"] != "unknown"):
            errors.append(f"{where}: a lapsed statement is unknown with its previous_status")
        if item["status"] == "unknown" and "lapsed" not in item:
            errors.append(f"{where}: only a lapsed statement publishes unknown")
        since = lapse_since(item)
        if "lapsed" in item:
            if item["lapsed"]["since"] != since.isoformat():
                errors.append(f"{where}: lapsed.since must be {since.isoformat()}")
        elif today >= since:
            stale.append(f"{where}: not confirmed or swept in time; it lapsed on {since.isoformat()} and the next publish turns it unknown")
        if item["checked_at"] > today.isoformat() or item["swept_at"] > today.isoformat():
            errors.append(f"{where}: checked_at and swept_at are not in the future")
        if item["sets_value"]:
            check = item["second_check"] or {}
            if not (
                item["service"] == "mms"
                and item["status"] == "ended"
                and item["scope"] == "network"
                and not item["host_only"]
                and item.get("mmsc_hosts")
                and check.get("verdict") == "confirmed"
                and "lapsed" not in item
                and date.fromisoformat(item["first_day_without"]) <= today
            ):
                errors.append(f"{where}: only a live, second-checked network-wide MMS end with MMSC hosts and a passed end day sets a value")
        if item["host_only"] and item["scope"] != "brand":
            errors.append(f"{where}: a host-only brand's statement has brand scope")
    for network in data["mms_ended_networks"]:
        target = by_id.get(network["statement"])
        if (
            target is None
            or target["service"] != "mms"
            or target["scope"] != "network"
            or target.get("previous_status", target["status"]) != "ended"
            or network["mccmnc"] not in target["mccmnc"]
            or network["first_day_without"] != target.get("first_day_without")
        ):
            errors.append(f"{STATEMENTS}: mms_ended_networks {network['mccmnc']} does not match a network-wide MMS end")
    codes = [network["mccmnc"] for network in data["mms_ended_networks"]]
    if codes != sorted(set(codes)):
        errors.append(f"{STATEMENTS}: mms_ended_networks are sorted and unique")
    return errors, stale


# ---------------------------------------------------------------- identity table


def identity_problems(data: dict[str, Any], root: Path) -> list[str]:
    out: list[str] = []
    entries = data["entries"]
    keys = [entry["key"] for entry in entries]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        out.append(f"{IDENTITY}: entries must be sorted by key and unique")
    if data["countries"] != sorted({entry["country"] for entry in entries}):
        out.append(f"{IDENTITY}: countries must list the entries' countries, sorted")
    known = set(keys)
    for entry in entries:
        where = f"{IDENTITY}: {entry['key']}"
        if not entry["key"].startswith(entry["country"].lower() + "."):
            out.append(f"{where}: the key starts with its country")
        if entry["operator_key"] is not None and entry["operator_key"] not in known:
            out.append(f"{where}: operator_key {entry['operator_key']} is not an entry")
        if entry["kind"] == "operator" and entry["operator_key"] != entry["key"]:
            out.append(f"{where}: an operator is its own operator_key")
        if entry["host_only"] != (entry["kind"] != "operator" and not entry["selectors"]):
            out.append(f"{where}: host_only means a brand or MVNO without any selector a source states")
        if entry["host_networks"] != sorted(entry["host_networks"]):
            out.append(f"{where}: host_networks are sorted")
        ids = [selector["profile_id"] for selector in entry["selectors"]]
        if ids != sorted(set(ids)):
            out.append(f"{where}: selectors are sorted by profile_id and unique")
        for selector in entry["selectors"]:
            path = root / "carriers" / "open" / (selector["profile_id"].removeprefix("open.") + ".json")
            if not path.is_file():
                out.append(f"{where}: selector profile {selector['profile_id']} is not published")
                continue
            profile = load(path)
            if profile.get("match") != selector["match"]:
                out.append(f"{where}: selector {selector['profile_id']} differs from the profile's match")
            if not set(selector["match"]["mccmnc"]) <= set(entry["host_networks"]):
                out.append(f"{where}: selector {selector['profile_id']} lies outside host_networks")
        for label in entry["labels"]:
            if not set(label["networks"]) <= set(entry["host_networks"]) | set(label["networks"]):
                out.append(f"{where}: label networks are not host networks")
    return out


# ---------------------------------------------------------------- the MMS override in the profiles


def mmsc_host(mmsc: str) -> str:
    text = mmsc.strip()
    if "://" not in text:
        text = "http://" + text
    return (urlsplit(text).hostname or "").lower()


def profile_mms_hosts(profile: dict[str, Any]) -> set[str]:
    return {
        mmsc_host(str(apn["mmsc"]))
        for apn in profile.get("android_apns") or []
        if ("mms" in (apn.get("types") or []) or "*" in (apn.get("types") or [])) and apn.get("mmsc")
    }


def override_problems(root: Path, statements: dict[str, Any] | None) -> list[str]:
    """Every profile the evidence index marks with operator_statement agrees
    with a statement in statements.json."""
    out: list[str] = []
    evidence_path = root / "generated" / "evidence-index.json"
    if not evidence_path.is_file():
        return out
    evidence = load(evidence_path)
    live = [item for item in (statements or {}).get("statements", []) if item["sets_value"]]
    lapsed = [
        item
        for item in (statements or {}).get("statements", [])
        if "lapsed" in item and item["service"] == "mms" and item.get("mmsc_hosts")
    ]
    for record in evidence.get("profiles", []):
        profile_id = record["profile_id"]
        off = ((record.get("capability_sources") or {}).get("mms") or {}).get("off", [])
        gates = {gate["key"] for gate in record.get("quality_gates", [])}
        uses = OPERATOR_STATEMENT in off
        lapsed_gate = f"{LAPSED_GATE}:mms" in gates
        if not uses and not lapsed_gate:
            continue
        path = root / "carriers" / "open" / (profile_id.removeprefix("open.") + ".json")
        if not path.is_file():
            out.append(f"{profile_id}: the evidence index names a profile that is not published")
            continue
        profile = load(path)
        codes = set(profile["match"]["mccmnc"])
        hosts = profile_mms_hosts(profile)
        pool = live if uses else lapsed
        if statements is None:
            out.append(f"{profile_id}: uses operator statements, but {STATEMENTS} is missing")
            continue
        if not any(codes <= set(item["mccmnc"]) and hosts <= set(item["mmsc_hosts"]) for item in pool):
            kind = "a value-setting" if uses else "a lapsed"
            out.append(f"{profile_id}: no {kind} MMS statement covers its network codes and MMSC hosts")
        if uses:
            config = profile.get("android_carrier_config") or {}
            fact = next(
                (f for f in record.get("fact_sources", []) if f["section"] == "android_carrier_config" and f["key"] == "enabledMMS"),
                None,
            )
            if profile["capabilities"].get("mms") != "unsupported" or config.get("enabledMMS") is not False:
                out.append(f"{profile_id}: an operator statement publishes mms unsupported and enabledMMS false")
            if fact is None or OPERATOR_STATEMENT not in fact["sources"]:
                out.append(f"{profile_id}: enabledMMS false names operator_statement as its source")
    return out


# ---------------------------------------------------------------- entities


def day_of(bound: str | None) -> str | None:
    return bound.removeprefix("≤") if bound else None


def sorted_unique(values: list[Any], where: str) -> list[str]:
    if values != sorted(set(values)):
        return [f"{where}: must be sorted and unique"]
    return []


def entity_problems(document: dict[str, Any], identity: dict[str, Any] | None) -> list[str]:
    """What the schema cannot say about entities.json."""
    out: list[str] = []
    networks = document["networks"]
    operators = {item["key"] for item in document["operators"]}
    brands = {item["key"] for item in document["brands"]}
    regulated = {item["country"] for item in document["regulators"]}
    out += sorted_unique([item["country"] for item in document["regulators"]], f"{ENTITIES}: regulators")
    out += sorted_unique([(item["mcc"], item["mnc"]) for item in networks], f"{ENTITIES}: networks")
    out += sorted_unique([item["key"] for item in document["operators"]], f"{ENTITIES}: operators")
    out += sorted_unique([item["key"] for item in document["brands"]], f"{ENTITIES}: brands")
    for item in networks:
        where = f"{ENTITIES}: network {item['mcc']}-{item['mnc']}"
        listed = item["on_regulator_list"]
        if (listed is None) != (item["country"] not in regulated):
            out.append(f"{where}: on_regulator_list is null exactly where no regulator's list was read")
        if listed is True and not item["holder"]:
            out.append(f"{where}: a code on the regulator's list names its holder")
        if listed is not True and item["holder"]:
            out.append(f"{where}: only the regulator's list gives a holder")
        if item["operator_key"] is not None and item["operator_key"] not in operators:
            out.append(f"{where}: names operator {item['operator_key']}, which the file does not list")
        out += sorted_unique([name["name"] for name in item["vendor_names"]], f"{where}: vendor_names")
    for item in document["brands"]:
        where = f"{ENTITIES}: brand {item['key']}"
        if item["operator_key"] is not None and item["operator_key"] not in operators:
            out.append(f"{where}: names operator {item['operator_key']}, which the file does not list")
        if item["part_of"] is not None and item["part_of"] not in brands:
            out.append(f"{where}: part_of {item['part_of']} is not a brand")
        for link in item["runs_on"]:
            if link["host"] not in operators:
                out.append(f"{where}: runs on {link['host']}, which the file does not list")
            start, end = day_of(link["valid_from"]), day_of(link["valid_to"])
            if start and end and start > end:
                out.append(f"{where}: a link ends before it starts")
            if link["note"]:
                problem = text_problem(link["note"], where)
                if problem:
                    out.append(problem)
    if identity is not None:
        for entry in identity["entries"]:
            if entry["key"] not in brands:
                out.append(f"{ENTITIES}: identity entry {entry['key']} is not a brand here")
            if entry["kind"] == "operator" and entry["key"] not in operators:
                out.append(f"{ENTITIES}: identity operator {entry['key']} is not an operator here")
        known = {entry["key"] for entry in identity["entries"]}
        for key in sorted(brands - known):
            out.append(f"{ENTITIES}: brand {key} is not in the identity table")
    return out


STATE_OF_STATUS = {"ended": "ended", "not_offered": "not_offered", "offered": "depends_on_plan", "unknown": "unknown"}


def offer_problems(document: dict[str, Any], statements: dict[str, Any] | None, identity: dict[str, Any] | None) -> list[str]:
    """What the schema cannot say about offers.json."""
    out: list[str] = []
    by_id = {item["id"]: item for item in (statements or {}).get("statements", [])}
    brands = {entry["key"] for entry in identity["entries"]} if identity else None
    offers = document["offers"]
    out += sorted_unique([item["id"] for item in offers], f"{OFFERS}: offers")
    features = [(item["brand"], item["service"]) for item in document["brand_features"]]
    out += sorted_unique(features, f"{OFFERS}: brand_features")
    counts = {"offers": len(offers), "lapsed": sum(1 for item in offers if "lapsed" in item), "brand_features": len(features)}
    if document["counts"] != counts:
        out.append(f"{OFFERS}: counts must be {counts}")
    for item in offers:
        where = f"{OFFERS}: {item['id']}"
        if not item["id"].startswith(item["brand"] + "."):
            out.append(f"{where}: an offer ID starts with its brand's key")
        if brands is not None and item["brand"] not in brands:
            out.append(f"{where}: unknown brand {item['brand']}")
        start, end = day_of(item["valid_from"]), day_of(item["valid_to"])
        if start and end and start > end:
            out.append(f"{where}: ends before it starts")
        for name in ("name", "paraphrase", "condition"):
            problem = text_problem(item[name], f"{where}.{name}") if item[name] else None
            if problem:
                out.append(problem)
        for feature in item["features"]:
            statement = by_id.get(feature["statement"])
            if statement is None:
                out.append(f"{where}: rests on {feature['statement']}, which statements.json does not list")
                continue
            if statement["identity_key"] != item["brand"] or statement["service"] != feature["service"]:
                out.append(f"{where}: {feature['service']} rests on another brand's or service's statement")
            status = statement["status"]
            state = feature["state"]
            if "lapsed" in item and state != "unknown":
                out.append(f"{where}: a lapsed offer reads unknown")
            elif status != "offered" and state not in (STATE_OF_STATUS[status], "unknown"):
                out.append(f"{where}: {state} does not fit the statement's status {status}")
    for item in document["brand_features"]:
        where = f"{OFFERS}: {item['brand']} {item['service']}"
        statement = by_id.get(item["statement"])
        if statement is None:
            out.append(f"{where}: rests on {item['statement']}, which statements.json does not list")
        elif statement["identity_key"] != item["brand"] or statement["service"] != item["service"]:
            out.append(f"{where}: rests on another brand's or service's statement")
        elif item["state"] != STATE_OF_STATUS[statement["status"]]:
            out.append(f"{where}: must read {STATE_OF_STATUS[statement['status']]}, as its statement does")
    return out


def pulled_problems(root: Path) -> list[str]:
    """Files for people stay out of what carrier settings read."""
    path = root / MANIFEST
    if not path.is_file():
        return []
    listed = {str(item.get("path")) for item in load(path).get("files", []) if isinstance(item, dict)}
    return [f"{MANIFEST}: lists {name}, which no carrier settings component reads" for name in NEVER_PULLED if name in listed]


# ---------------------------------------------------------------- main


def validate(root: Path, today: date, freshness: str, require: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    statements_path = root / STATEMENTS
    identity_path = root / IDENTITY
    statements = identity = None
    if require and not statements_path.is_file():
        errors.append(f"{STATEMENTS}: missing")
    if require and not identity_path.is_file():
        errors.append(f"{IDENTITY}: missing")
    if identity_path.is_file():
        identity = load(identity_path)
        problems = schema_problems(identity_path, identity, "carrier-identity.schema.json")
        errors.extend(problems)
        if not problems:
            errors.extend(identity_problems(identity, root))
    if statements_path.is_file():
        statements = load(statements_path)
        problems = schema_problems(statements_path, statements, "operator-statements.schema.json")
        errors.extend(problems)
        if not problems:
            keys = {entry["key"] for entry in identity["entries"]} if identity else None
            if identity is None:
                errors.append(f"{IDENTITY}: missing next to {STATEMENTS}")
            found, stale = statement_problems(statements, today, keys)
            errors.extend(found)
            (errors if freshness == "fail" else warnings).extend(stale)
        else:
            statements = None
    entities_path = root / ENTITIES
    if entities_path.is_file():
        entities = load(entities_path)
        problems = schema_problems(entities_path, entities, "operator-entities.schema.json")
        errors.extend(problems)
        if not problems:
            errors.extend(entity_problems(entities, identity))
    offers_path = root / OFFERS
    if offers_path.is_file():
        offers = load(offers_path)
        problems = schema_problems(offers_path, offers, "operator-offers.schema.json")
        errors.extend(problems)
        if not problems:
            errors.extend(offer_problems(offers, statements, identity))
    errors.extend(pulled_problems(root))
    errors.extend(override_problems(root, statements))
    errors.extend(prefix_problems(root))
    return errors, warnings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--freshness", choices=("warn", "fail"), default="warn")
    parser.add_argument("--require", action="store_true", help="fail when generated/operators/ is missing")
    parser.add_argument("--today", type=date.fromisoformat)
    args = parser.parse_args(argv)
    errors, warnings = validate(args.root, args.today or utc_today(), args.freshness, args.require)
    for line in warnings:
        print(f"warning: {line}", file=sys.stderr)
    for line in errors[:200]:
        print(f"error: {line}", file=sys.stderr)
    if errors:
        print(f"operators: {len(errors)} problem(s)", file=sys.stderr)
        return 1
    print("validated generated/operators/ and rule 3's prefix limits on every published file")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
