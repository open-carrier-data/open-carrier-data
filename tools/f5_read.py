#!/usr/bin/env python3
"""F5 reads of emergency-line changes, published with each commit of main
(rule round 31, SM6).

Rule round 31 (2026-10-28), SM6: "OCD's publisher runs F5's independent read
for each main commit that changes emergency lines, and publishes the read
with that commit. Build pins and runtime installs take an emergency-line
change only with that read." Releases keep their draft read.

The read is this tool: a deterministic, documented check that anyone can
rerun, not an agent. OCD's checks run on free GitHub runners only, where no
agent runs; an agent's read (round 29's desk read) can still stand in for a
held line set, see `publish --agent-read`. The tool is public main's, it is
not the data's builder (the private sanitizer and the generator), and
`validate` reruns it on every pull request and push, so a read on main is
the one this tool gives for that change.

Emergency lines are round 29's F5 lines: the phone-level guard's emergency
items (check_phone_guard.py: an emergency lead gained, lost or changed, a
network type left without an emergency profile, an emergency profile missing
under an APN set, an emergency-named APN becoming the internet or attach
lead), and, which the guard leaves out, the emergency lead of a scope that
only one side has (a new or a gone scope, against what its SIMs get on the
other side: the network's rows, or Android's default EIMS profile). Each line
is `condition|scope|network types|old|new`, as the S20 pin step writes them.

Rules, the first that decides wins (RULES_VERSION):

  android_default   the new lead is Android's default EIMS request (APN `sos`,
                    IPV4V6 both ways, no request attribute), or a row of the
                    file that asks exactly that: what every ROM without
                    carrier data sends. proceed.
  unreachable_scope the scope's network code has a length no SIM of that
                    country reports (Google's carrier list names at least 3
                    networks of the MCC and all with the other MNC length),
                    so no phone matches it: TelephonyProvider and OCD's
                    matcher compare MCC+MNC as written. proceed.
  gap               a network type left without an emergency profile, an
                    emergency profile missing under an APN set, or an
                    emergency-named APN leading data: the phone loses its
                    emergency PDN there, or uses an emergency APN for data. hold.
  foreign_name      the new lead's APN name ends in a country label that
                    Google's carrier list uses for other MCCs and never for
                    this one (the 302/37 class: CNT Ecuador's
                    `emergency.volte.ims.cnt.net.ec` under a Canadian code). hold.
  stated            a current vendor or LineageOS's own list states that row
                    for emergency on this scope (the generator's S1-A
                    evidence: APN, protocol and roaming protocol). proceed.
  not_stated        anything else. hold.

The verdict is proceed when every line proceeds, no_lines when the change has
no emergency line, hold otherwise. The lines digest is the first 16 hex
digits of SHA-256 over the sorted lines, each ending with a newline, as the
pin step computes it.

generated/ocd-dataset/f5-reads.json holds the chain of reads: one entry for
each change of the APN rows on main since `since`, oldest first, each naming
its base and head by the SHA-256 of the APN file's `<apn>` lines (the header,
which names the data digest, is left out) and the data digest. A consumer
that has rows R0 and takes rows Rn walks the chain back from Rn to R0; it
takes the change only when every entry on the way proceeds or has no lines.
It is a companion file of the dataset, not a manifest role (round 31).

usage:
  f5_read.py lines BASE_XML HEAD_XML
  f5_read.py read BASE_XML HEAD_XML [--root CHECKOUT] [--base-commit SHA]
  f5_read.py publish [--root PUBLIC] --base-xml BASE_XML [--base-commit SHA] [--base-data-digest D]
                     [--agent-read FILE] [--builder NAME]
  f5_read.py check [--root DIR] [--base-xml BASE_XML --base-file BASE_F5_READS] [--base-commit SHA]
  f5_read.py chain [--root DIR] --from APN_ROWS_SHA256 [--gate full|narrow --networks 262-02,262-03]
  f5_read.py backfill --repo CLONE --since SHA [--until REF] [--root DIR]

Exit codes: 0 proceed, no lines or valid; 1 a check refused; 2 an error;
3 publish wrote a hold (the publisher holds the publish).

Only the standard library is used, as in the other public tools.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import android_phone_model as phone  # noqa: E402
import check_phone_guard as guard  # noqa: E402

RULES_VERSION = 1
READ_SCHEMA = "ocd-f5-read/1"
FILE_SCHEMA_VERSION = 1
FILE = "generated/ocd-dataset/f5-reads.json"
APN_FILE = "generated/android/apns-conf.xml"
LANE_FILE = "generated/ocd-dataset/google-lane.json"
READER = f"ocd-f5-check: open-carrier-data tools/f5_read.py, rules {RULES_VERSION} (deterministic; docs/ocd-dataset.md#f5-reads)"
BUILDER = "carrier-data-bot: the private publisher (sanitizer and Android generator)"
VERDICTS = ("proceed", "hold", "no_lines")
RULES = {
    "android_default": "proceed",
    "unreachable_scope": "proceed",
    "gap": "hold",
    "foreign_name": "hold",
    "stated": "proceed",
    "not_stated": "hold",
}
METHODS = ("deterministic", "agent")
SHA_RE = re.compile(r"[0-9a-f]{40}")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
LINES_DIGEST_RE = re.compile(r"[0-9a-f]{16}")
TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
# The two-letter labels Google's canonical names use that are not the ISO
# code a country's domain ends with.
DOMAIN_FOR_SUFFIX = {"gb": "uk"}
NEW_SCOPE = "emergency lead of a new scope"
GONE_SCOPE = "emergency lead of a gone scope"
DEFAULT_KEY = guard.emergency_key(guard.ANDROID_DEFAULT_EIMS)


class F5Error(Exception):
    """An input is malformed; the message names it."""


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def apn_rows_sha256(xml: bytes) -> str:
    """SHA-256 over the `<apn .../>` lines of an apns-conf.xml in order, each
    with its newline: the rows a phone stores, without the header comment."""
    rows = [line for line in xml.splitlines(keepends=True) if line.lstrip().startswith(b"<apn ")]
    return hashlib.sha256(b"".join(rows)).hexdigest()


def header_digest(xml: bytes) -> str | None:
    match = re.search(rb"(?m)^    data_digest: (sha256:[0-9a-f]{64})$", xml[:4096])
    return match.group(1).decode("ascii") if match else None


def line_of(item: dict[str, Any]) -> str:
    return "|".join((item["condition"], item["scope"], ",".join(item["types"]), item["old"], item["new"]))


def lines_digest(lines: list[str]) -> str | None:
    if not lines:
        return None
    return hashlib.sha256("".join(line + "\n" for line in sorted(lines)).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the lines


def fallback_scope(scope: phone.Scope, typed: dict) -> phone.Scope | None:
    """The scope a SIM of SCOPE uses when SCOPE has no rows on that side:
    an MVNO SIM falls back to its network's rows without an MVNO selector;
    with none, Android adds its default EIMS profile (None)."""
    mcc, mnc, mvno_type, _ = scope
    if mvno_type and (mcc, mnc, "", "") in typed:
        return (mcc, mnc, "", "")
    return None


def emergency_items(before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The F5 emergency lines between two APN files, each with the structured
    keys (`old_key`, `new_key`) the rules read."""
    types = {**guard.HOLD_TYPES, **guard.OTHER_TYPES}
    before, before_tables = phone.phone_state(before_rows, types)
    after, after_tables = phone.phone_state(after_rows, types)
    b_typed = guard.typed_leads(before_rows, before_tables)
    a_typed = guard.typed_leads(after_rows, after_tables)
    found: dict[tuple, dict[str, Any]] = {}

    def add(condition: str, scope: phone.Scope, old: Any, new: Any, old_text: str, new_text: str, name: str) -> None:
        slot = found.setdefault((condition, guard.fmt(scope), old_text, new_text),
                                {"scope_key": scope, "old_key": old, "new_key": new, "types": []})
        slot["types"].append(name)

    for scope in set(before) & set(after):
        for name in guard.WATCH_TYPES:
            old, new = b_typed[scope][name]["emergency"], a_typed[scope][name]["emergency"]
            if old != new:
                if old and new and old[0] and not new[0]:
                    condition = "emergency lead gained"
                elif old and new and not old[0] and new[0]:
                    condition = "emergency lead lost"
                else:
                    condition = "emergency lead changed"
                add(condition, scope, old, new, guard.emergency_text(old), guard.emergency_text(new), name)
            b_inet, _, b_attach = before[scope][name][:3]
            a_inet, _, a_attach = after[scope][name][:3]
            for role, o, n in (("internet", b_inet, a_inet), ("attach", b_attach, a_attach)):
                if n and guard.emergency_named(n[0]) and not (o and guard.emergency_named(o[0])):
                    add(f"emergency-named APN becomes the {role} lead", scope, o, n, guard.lead_text(o), guard.lead_text(n), name)
        for preferred in sorted(a_typed[scope]["_sets"] - b_typed[scope]["_sets"]):
            for name in guard.WATCH_TYPES:
                add(f"emergency profile missing under APN set {preferred}", scope, None, None, "an emergency profile", "none", name)
    for scope, condition, here, there in (
        *((s, NEW_SCOPE, a_typed, b_typed) for s in set(after) - set(before)),
        *((s, GONE_SCOPE, b_typed, a_typed) for s in set(before) - set(after)),
    ):
        other = fallback_scope(scope, there)
        for name in guard.WATCH_TYPES:
            mine = here[scope][name]["emergency"]
            theirs = there[other][name]["emergency"] if other else DEFAULT_KEY
            old, new = (theirs, mine) if condition == NEW_SCOPE else (mine, theirs)
            if old != new:
                add(condition, scope, old, new, guard.emergency_text(old), guard.emergency_text(new), name)
    out = []
    for (condition, scope, old_text, new_text), slot in sorted(found.items()):
        item = {"condition": condition, "scope": scope, "types": slot["types"], "old": old_text, "new": new_text,
                "scope_key": slot["scope_key"], "old_key": slot["old_key"], "new_key": slot["new_key"]}
        item["line"] = line_of(item)
        out.append(item)
    return out


# ---------------------------------------------------------------- the rules


class Context:
    """What the rules read from the head's checkout: the rows a current
    vendor or LineageOS states for emergency, per scope, and per MCC the
    MNC lengths and country labels of Google's carrier list."""

    def __init__(self, root: Path | None) -> None:
        self.stated: dict[phone.Scope, set[tuple[str, str, str]]] = defaultdict(set)
        self.mnc_lengths: dict[str, set[int]] = defaultdict(set)
        self.networks: dict[str, int] = defaultdict(int)
        self.countries: dict[str, set[str]] = defaultdict(set)
        if root is None:
            return
        lane_path = root / LANE_FILE
        if lane_path.is_file():
            lane = json.loads(lane_path.read_text(encoding="utf-8"))
            seen = set()
            for rule in lane.get("rules", []):
                network = (rule["mcc"], rule["mnc"])
                if network not in seen:
                    seen.add(network)
                    self.mnc_lengths[rule["mcc"]].add(len(rule["mnc"]))
                    self.networks[rule["mcc"]] += 1
                match = re.search(r"_([a-z]{2})$", rule["canonical_name"])
                if match:
                    self.countries[rule["mcc"]].add(DOMAIN_FOR_SUFFIX.get(match.group(1), match.group(1)))
        generator = root / "tools/generate_android_outputs.py"
        if generator.is_file():
            module, records = guard.generator_records(root.resolve())
            if not hasattr(module, "serves_emergency") or not hasattr(module, "emergency_stated"):
                records = []  # a generator from before S1-A states no emergency row
            for record in records:
                if not module.serves_emergency(record) or not module.emergency_stated(record):
                    continue
                row = phone.parse_lines([module.apn_row_line(record)])[0]
                self.stated[phone.scope_of(row)].add((str(row.get("apn", "")).casefold(),
                                                      str(row.get("protocol") or "IP"), str(row.get("roaming_protocol") or "IP")))
        self.all_labels = {label for labels in self.countries.values() for label in labels}

    def unreachable(self, scope: phone.Scope) -> bool:
        mcc, mnc = scope[0], scope[1]
        lengths = self.mnc_lengths.get(mcc, set())
        return self.networks.get(mcc, 0) >= 3 and len(lengths) == 1 and len(mnc) not in lengths

    def foreign(self, scope: phone.Scope, apn: str) -> str | None:
        match = re.search(r"\.([a-z]{2})$", apn.casefold())
        if not match:
            return None
        label = match.group(1)
        mine = self.countries.get(scope[0], set())
        if mine and label not in mine and label in self.all_labels:
            return label
        return None


def judge(item: dict[str, Any], context: Context) -> dict[str, str]:
    condition, scope, new = item["condition"], item["scope_key"], item["new_key"]
    if condition.startswith("emergency lead"):
        if new is not None and (new[0] or guard.emergency_labels(new) == ["equal"]):
            return {"rule": "android_default", "why": "the new lead asks Android's default emergency request (sos, IPV4V6 both ways)"}
    if context.unreachable(scope):
        return {"rule": "unreachable_scope",
                "why": f"no SIM of MCC {scope[0]} reports a {len(scope[1])}-digit MNC (Google's carrier list: {sorted(context.mnc_lengths[scope[0]])})"}
    if new is None or condition.startswith("emergency profile missing") or condition.startswith("emergency-named APN"):
        return {"rule": "gap", "why": "a network type or APN set loses its emergency profile, or an emergency APN leads data"}
    label = context.foreign(scope, str(new[1]))
    if label:
        return {"rule": "foreign_name",
                "why": f"APN {new[1]} ends in .{label}, a country label Google's carrier list never uses for MCC {scope[0]} ({sorted(context.countries[scope[0]])})"}
    request = (str(new[1]).casefold(), str(new[2]), str(new[3]))
    if request in context.stated.get(scope, set()):
        return {"rule": "stated", "why": "a current vendor or LineageOS's own list states this row for emergency on this scope"}
    return {"rule": "not_stated", "why": "no current vendor or LineageOS row states this emergency request for this scope"}


def read_files(base_xml: bytes, head_xml: bytes, root: Path | None, base_commit: str | None = None,
               context: Context | None = None, read_at: str | None = None) -> dict[str, Any]:
    """The F5 read of the change BASE_XML -> HEAD_XML, with the head's checkout
    ROOT for the rules' context."""
    with tempfile.TemporaryDirectory(prefix="f5-read-") as folder:
        base_path, head_path = Path(folder) / "base.xml", Path(folder) / "head.xml"
        base_path.write_bytes(base_xml)
        head_path.write_bytes(head_xml)
        items = emergency_items(guard.read_rows(base_path), guard.read_rows(head_path)) if base_xml != head_xml else []
    context = context if context is not None else Context(root) if items else Context(None)
    findings = []
    for item in items:
        decided = judge(item, context)
        findings.append({"line": item["line"], "rule": decided["rule"], "verdict": RULES[decided["rule"]], "why": decided["why"]})
    lines = sorted(item["line"] for item in items)
    findings.sort(key=lambda f: f["line"])
    verdict = "no_lines" if not lines else "proceed" if all(f["verdict"] == "proceed" for f in findings) else "hold"
    held = [f for f in findings if f["verdict"] == "hold"]
    notes = ("No emergency line: the change leaves every scope's emergency lead as it was." if not lines else
             f"{len(lines)} emergency line(s); {len(held)} held ({', '.join(sorted({f['rule'] for f in held}))})." if held else
             f"{len(lines)} emergency line(s), each passed by a rule ({', '.join(sorted({f['rule'] for f in findings}))}).")
    return {
        "schema": READ_SCHEMA,
        "base": {"commit": base_commit, "apn_rows_sha256": apn_rows_sha256(base_xml), "data_digest": header_digest(base_xml)},
        "head": {"apn_rows_sha256": apn_rows_sha256(head_xml), "data_digest": header_digest(head_xml)},
        "lines_digest": lines_digest(lines),
        "lines": lines,
        "findings": findings,
        "verdict": verdict,
        "method": "deterministic",
        "rules_version": RULES_VERSION,
        "reader": READER,
        "builder": BUILDER,
        "read_at": read_at or now_utc(),
        "notes": notes,
    }


# ---------------------------------------------------------------- the file


def empty_file(since_commit: str | None, rows: str) -> dict[str, Any]:
    return {"schema_version": FILE_SCHEMA_VERSION, "apn_rows_sha256": rows,
            "since": {"commit": since_commit, "apn_rows_sha256": rows}, "reads": []}


def dump(document: dict[str, Any]) -> bytes:
    parts = []
    for key in sorted(document):
        value = document[key]
        head = json.dumps(key) + ":"
        if key == "reads" and value:
            body = "[\n" + ",\n".join(json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for item in value) + "\n]"
        else:
            body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        parts.append(head + body)
    return ("{" + ",".join(parts) + "}\n").encode("utf-8")


def load_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise F5Error(f"{path}: repeated member {key}")
            out[key] = value
        return out
    def constant(value):
        raise F5Error(f"{path}: {value} is not JSON")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def read_problems(read: Any, where: str) -> list[str]:
    keys = {"schema", "base", "head", "lines_digest", "lines", "findings", "verdict", "method", "rules_version", "reader", "builder", "read_at", "notes"}
    if not isinstance(read, dict) or set(read) != keys:
        return [f"{where}: a read holds exactly {', '.join(sorted(keys))}"]
    out = []
    if read["schema"] != READ_SCHEMA:
        out.append(f"{where}: schema must be {READ_SCHEMA}")
    base, head = read["base"], read["head"]
    if not isinstance(base, dict) or set(base) != {"commit", "apn_rows_sha256", "data_digest"} \
            or not (base["commit"] is None or (isinstance(base["commit"], str) and SHA_RE.fullmatch(base["commit"]))):
        out.append(f"{where}: base holds commit (40 hex or null), apn_rows_sha256 and data_digest")
    if not isinstance(head, dict) or set(head) != {"apn_rows_sha256", "data_digest"}:
        out.append(f"{where}: head holds apn_rows_sha256 and data_digest")
    for part in (base, head):
        if isinstance(part, dict):
            if not isinstance(part.get("apn_rows_sha256"), str) or not HEX64_RE.fullmatch(part["apn_rows_sha256"]):
                out.append(f"{where}: apn_rows_sha256 must be 64 hex")
            if not (part.get("data_digest") is None or (isinstance(part.get("data_digest"), str) and DIGEST_RE.fullmatch(part["data_digest"]))):
                out.append(f"{where}: data_digest must be sha256:<64 hex>")
    if out:
        return out
    lines = read["lines"]
    if not isinstance(lines, list) or lines != sorted(set(lines)) or not all(isinstance(line, str) and line.count("|") >= 4 for line in lines):
        out.append(f"{where}: lines is a sorted list of distinct condition|scope|types|old|new lines")
    elif read["lines_digest"] != lines_digest(lines):
        out.append(f"{where}: lines_digest is not the digest of its lines")
    if read["verdict"] not in VERDICTS:
        out.append(f"{where}: verdict is one of {', '.join(VERDICTS)}")
    elif (read["verdict"] == "no_lines") != (not lines):
        out.append(f"{where}: verdict no_lines goes with no lines, and only with none")
    if read["method"] not in METHODS:
        out.append(f"{where}: method is deterministic or agent")
    for name in ("reader", "builder", "notes"):
        if not isinstance(read[name], str) or not read[name].strip():
            out.append(f"{where}: {name} must be a sentence")
    if isinstance(read["reader"], str) and isinstance(read["builder"], str) and read["reader"].strip().casefold() == read["builder"].strip().casefold():
        out.append(f"{where}: the reader must not be the builder")
    if not isinstance(read["read_at"], str) or not TIME_RE.fullmatch(read["read_at"]):
        out.append(f"{where}: read_at must be ISO 8601 UTC with seconds")
    findings = read["findings"]
    if not isinstance(findings, list) or not all(isinstance(f, dict) and set(f) == {"line", "rule", "verdict", "why"} for f in findings):
        out.append(f"{where}: findings are line, rule, verdict, why")
    elif read["method"] == "deterministic":
        if [f["line"] for f in findings] != lines or any(RULES.get(f["rule"]) != f["verdict"] for f in findings):
            out.append(f"{where}: a deterministic read has one finding per line with its rule's verdict")
        elif read["verdict"] != ("no_lines" if not lines else "proceed" if all(f["verdict"] == "proceed" for f in findings) else "hold"):
            out.append(f"{where}: the verdict does not follow from the findings")
    if read["rules_version"] != RULES_VERSION and read["method"] == "deterministic":
        out.append(f"{where}: rules_version {read['rules_version']} is not this tool's {RULES_VERSION}")
    return out


def file_problems(document: Any, xml: bytes | None, where: str = FILE) -> list[str]:
    """The chain's own rules: shape, each read well-formed, each read's base
    the previous head, the last head this commit's APN rows."""
    keys = {"schema_version", "apn_rows_sha256", "since", "reads"}
    if not isinstance(document, dict) or set(document) != keys or document["schema_version"] != FILE_SCHEMA_VERSION:
        return [f"{where}: holds exactly {', '.join(sorted(keys))} with schema_version {FILE_SCHEMA_VERSION}"]
    out = []
    since = document["since"]
    if not isinstance(since, dict) or set(since) != {"commit", "apn_rows_sha256"} or not isinstance(since["apn_rows_sha256"], str) \
            or not HEX64_RE.fullmatch(since["apn_rows_sha256"]) or not (since["commit"] is None or SHA_RE.fullmatch(str(since["commit"]))):
        return [f"{where}: since holds commit and apn_rows_sha256"]
    if not isinstance(document["reads"], list):
        return [f"{where}: reads is a list"]
    rows = since["apn_rows_sha256"]
    for index, read in enumerate(document["reads"]):
        problems = read_problems(read, f"{where}: read {index}")
        out += problems
        if problems:
            continue
        if read["base"]["apn_rows_sha256"] != rows:
            out.append(f"{where}: read {index} does not start where the chain stands ({rows[:12]})")
        if read["base"]["apn_rows_sha256"] == read["head"]["apn_rows_sha256"]:
            out.append(f"{where}: read {index} reads no change of the APN rows")
        rows = read["head"]["apn_rows_sha256"]
    if document["apn_rows_sha256"] != rows:
        out.append(f"{where}: apn_rows_sha256 is not the chain's last head")
    if xml is not None:
        if apn_rows_sha256(xml) != document["apn_rows_sha256"]:
            out.append(f"{where}: the chain ends at {document['apn_rows_sha256'][:12]}, but {APN_FILE} has rows {apn_rows_sha256(xml)[:12]}; "
                       "run tools/f5_read.py publish for this change")
    return out


def chain_path(document: dict[str, Any], start: str, end: str | None = None) -> list[dict[str, Any]] | None:
    """The reads from rows START to END (default: the chain's end), oldest
    first; [] when START is END; None when the chain does not pass START."""
    end = end or document["apn_rows_sha256"]
    if start == end:
        return []
    reads = document["reads"]
    for index in range(len(reads) - 1, -1, -1):
        if reads[index]["head"]["apn_rows_sha256"] == end:
            path = []
            for back in range(index, -1, -1):
                path.append(reads[back])
                if reads[back]["base"]["apn_rows_sha256"] == start:
                    return list(reversed(path))
            return None
    return None


def path_verdict(path: list[dict[str, Any]] | None, gate: str = "full", networks: set[str] | None = None) -> tuple[str, list[str]]:
    """Whether a consumer may take the change along PATH (SM6): `full` needs
    every read to proceed or have no lines; `narrow` (a device family whose
    emergency data test first use passed, SM10) needs a proceeding read only
    for lines on NETWORKS that change an emergency lead's APN name or roaming
    protocol. Returns (take or refuse, the lines that refuse)."""
    if path is None:
        return "refuse", ["no published F5 read chain leads from the installed APN rows to these"]
    blocking = []
    for read in path:
        if read["verdict"] in ("proceed", "no_lines"):
            continue
        held = {f["line"] for f in read["findings"] if f["verdict"] == "hold"} if read["method"] == "deterministic" else set(read["lines"])
        for line in sorted(held):
            if gate == "narrow" and not narrow_relevant(line, networks or set()):
                continue
            blocking.append(line)
    return ("refuse" if blocking else "take"), blocking


def narrow_relevant(line: str, networks: set[str]) -> bool:
    """A line the narrow gate still reads: on one of NETWORKS (mcc-mnc), and
    changing the emergency lead's APN name or roaming protocol."""
    parts = line.split("|")
    if len(parts) < 5:
        return True
    network = parts[1].split()[0].replace("/", "-")
    if network not in networks:
        return False
    old, new = parts[3].split(" [")[0].split(), parts[4].split(" [")[0].split()
    old = [w for w in old if w not in ("Android", "default")]
    new = [w for w in new if w not in ("Android", "default")]
    if len(old) < 2 or len(new) < 2:
        return True
    # Letter case counts: Wi-Fi calling sends the APN name as written.
    return old[0] != new[0] or old[1].split("/")[-1] != new[1].split("/")[-1]


def append_read(document: dict[str, Any] | None, read: dict[str, Any], since_commit: str | None, head_xml: bytes) -> dict[str, Any]:
    if document is None:
        document = empty_file(since_commit, read["base"]["apn_rows_sha256"])
    if document["apn_rows_sha256"] != read["base"]["apn_rows_sha256"]:
        raise F5Error(f"{FILE}: the chain stands at {document['apn_rows_sha256'][:12]}, the read starts at {read['base']['apn_rows_sha256'][:12]}")
    return {**document, "reads": document["reads"] + [read], "apn_rows_sha256": read["head"]["apn_rows_sha256"]}


def agent_read_stands_in(read: dict[str, Any], agent: dict[str, Any], builder: str) -> list[str]:
    """An agent's read (round 29's x1s-ocd-f5-read.v1 or this tool's shape
    with method agent) may stand in for a held deterministic read of exactly
    the same lines."""
    problems = []
    if agent.get("lines_digest") != read["lines_digest"]:
        problems.append(f"lines_digest {agent.get('lines_digest')!r} is not this change's {read['lines_digest']!r}")
    if agent.get("verdict") != "proceed":
        problems.append("the agent's verdict is not proceed")
    reader = str(agent.get("reader", "")).strip()
    if not reader or reader.casefold() in (builder.casefold(), READER.casefold()):
        problems.append("the agent read names no reader, or names the builder")
    if not TIME_RE.fullmatch(str(agent.get("read_at", ""))) or not str(agent.get("notes", "")).strip():
        problems.append("the agent read needs read_at and notes")
    return problems


# ---------------------------------------------------------------- git helpers


def git_show(repo: Path, ref: str, path: str) -> bytes | None:
    done = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True)
    return done.stdout if done.returncode == 0 else None


def first_parent_commits(repo: Path, since: str, until: str) -> list[str]:
    done = subprocess.run(["git", "-C", str(repo), "rev-list", "--first-parent", "--reverse", f"{since}..{until}", "--", APN_FILE],
                          capture_output=True, text=True, check=True)
    return [line for line in done.stdout.split() if line]


def checkout_tree(repo: Path, ref: str, target: Path) -> None:
    """The files of REF the rules read: carriers, generated, schemas, tools."""
    archive = subprocess.run(["git", "-C", str(repo), "archive", ref, "carriers", "generated", "tools", "schemas"],
                             capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ln = sub.add_parser("lines")
    ln.add_argument("base", type=Path)
    ln.add_argument("head", type=Path)
    rd = sub.add_parser("read")
    rd.add_argument("base", type=Path)
    rd.add_argument("head", type=Path)
    rd.add_argument("--root", type=Path, default=TOOLS.parent, help="the head's checkout (rules' context)")
    rd.add_argument("--base-commit")
    pb = sub.add_parser("publish")
    pb.add_argument("--root", type=Path, default=TOOLS.parent)
    pb.add_argument("--base-xml", type=Path, required=True, help="public main's apns-conf.xml before this change")
    pb.add_argument("--base-commit", help="public main's commit before this change")
    pb.add_argument("--base-file", type=Path, help="public main's f5-reads.json (default: the one in ROOT, as checked out)")
    pb.add_argument("--agent-read", type=Path, help="an independent agent's proceed read of exactly these lines, for a held change")
    pb.add_argument("--builder", default=BUILDER)
    pb.add_argument("--read-at")
    pb.add_argument("--report", type=Path)
    ck = sub.add_parser("check")
    ck.add_argument("--root", type=Path, default=TOOLS.parent)
    ck.add_argument("--base-xml", type=Path, help="the base commit's apns-conf.xml (a pull request's base, or HEAD~1)")
    ck.add_argument("--base-file", type=Path, help="the base commit's f5-reads.json (absent before the chain began)")
    ck.add_argument("--base-commit")
    ch = sub.add_parser("chain")
    ch.add_argument("--root", type=Path, default=TOOLS.parent)
    ch.add_argument("--from", dest="start", required=True, help="the installed APN rows' SHA-256 (apn_rows_sha256)")
    ch.add_argument("--to", dest="end")
    ch.add_argument("--gate", choices=("full", "narrow"), default="full")
    ch.add_argument("--networks", default="", help="for --gate narrow: the matched networks, mcc-mnc, comma-separated")
    bf = sub.add_parser("backfill")
    bf.add_argument("--repo", type=Path, required=True, help="a clone of open-carrier-data with main")
    bf.add_argument("--since", required=True, help="the commit the chain starts at")
    bf.add_argument("--until", default="origin/main")
    bf.add_argument("--root", type=Path, default=TOOLS.parent, help="where to write generated/ocd-dataset/f5-reads.json")
    bf.add_argument("--read-at")
    args = parser.parse_args(argv)
    try:
        if args.command == "lines":
            items = emergency_items(guard.read_rows(args.base), guard.read_rows(args.head))
            for item in items:
                print(item["line"])
            print(f"{len(items)} emergency line(s), digest {lines_digest([i['line'] for i in items])}")
            return 0
        if args.command == "read":
            read = read_files(args.base.read_bytes(), args.head.read_bytes(), args.root, args.base_commit)
            print(json.dumps(read, indent=2, sort_keys=True, ensure_ascii=False))
            return 0 if read["verdict"] != "hold" else 3
        if args.command == "publish":
            head_xml = (args.root / APN_FILE).read_bytes()
            base_xml = args.base_xml.read_bytes()
            base_file = load_file(args.base_file) if args.base_file else load_file(args.root / FILE)
            if apn_rows_sha256(base_xml) == apn_rows_sha256(head_xml):
                document = base_file or empty_file(args.base_commit, apn_rows_sha256(head_xml))
                (args.root / FILE).parent.mkdir(parents=True, exist_ok=True)
                (args.root / FILE).write_bytes(dump(document))
                print("f5 read: the APN rows did not change; no read")
                result = {"verdict": "unchanged", "read": None}
            else:
                read = read_files(base_xml, head_xml, args.root, args.base_commit, read_at=args.read_at)
                if read["verdict"] == "hold" and args.agent_read:
                    agent = json.loads(args.agent_read.read_text(encoding="utf-8"))
                    problems = agent_read_stands_in(read, agent, args.builder)
                    if problems:
                        print("f5 read: the agent read does not stand in: " + "; ".join(problems), file=sys.stderr)
                    else:
                        read = {**read, "method": "agent", "verdict": "proceed", "reader": agent["reader"], "read_at": agent["read_at"],
                                "notes": f"An independent agent read the {len(read['lines'])} held line(s): {agent['notes']}"}
                document = append_read(base_file, read, args.base_commit, head_xml)
                (args.root / FILE).parent.mkdir(parents=True, exist_ok=True)
                (args.root / FILE).write_bytes(dump(document))
                result = {"verdict": read["verdict"], "read": read}
                print(f"f5 read: {read['verdict']}, {len(read['lines'])} emergency line(s), digest {read['lines_digest']}")
                for finding in read["findings"]:
                    print(f"  {finding['verdict']:7} {finding['rule']:17} {finding['line'][:300]}")
            if args.report:
                args.report.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            return 3 if result["verdict"] == "hold" else 0
        if args.command == "check":
            xml = (args.root / APN_FILE).read_bytes()
            document = load_file(args.root / FILE)
            if document is None:
                print(f"error: {FILE} is missing; run tools/f5_read.py publish", file=sys.stderr)
                return 1
            problems = file_problems(document, xml)
            if not problems and args.base_xml is not None:
                base_xml = args.base_xml.read_bytes()
                base_document = load_file(args.base_file) if args.base_file and args.base_file.is_file() and args.base_file.stat().st_size else None
                if base_document is not None:
                    prefix = base_document["reads"]
                    if document["since"] != base_document["since"] or document["reads"][:len(prefix)] != prefix:
                        problems.append(f"{FILE}: does not extend the base's chain; reads on main are never rewritten")
                if apn_rows_sha256(base_xml) != apn_rows_sha256(xml):
                    path = chain_path(document, apn_rows_sha256(base_xml))
                    if path is None or len(path) != 1:
                        problems.append(f"{FILE}: the change of the APN rows from the base needs exactly one new read from the base's rows")
                    else:
                        read = path[0]
                        again = read_files(base_xml, xml, args.root, args.base_commit, read_at=read["read_at"])
                        if read["lines"] != again["lines"]:
                            problems.append(f"{FILE}: the read's lines are not this change's (recomputed digest {again['lines_digest']})")
                        elif read["method"] == "deterministic" and read["findings"] != again["findings"]:
                            problems.append(f"{FILE}: the read's findings are not what the rules give")
                        if read["verdict"] == "hold":
                            problems.append(f"{FILE}: the change's F5 read is hold; an emergency-line change enters main only with a read that proceeds")
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            if not problems:
                last = document["reads"][-1] if document["reads"] else None
                print(f"f5 reads: valid, {len(document['reads'])} read(s) since {(document['since']['commit'] or 'the start')[:12]}"
                      + (f", the last {last['verdict']} ({len(last['lines'])} line(s))" if last else ""))
            return 1 if problems else 0
        if args.command == "chain":
            document = load_file(args.root / FILE)
            if document is None:
                print(f"refuse: {FILE} is missing", file=sys.stderr)
                return 1
            path = chain_path(document, args.start, args.end)
            networks = {n.strip() for n in args.networks.split(",") if n.strip()}
            decision, blocking = path_verdict(path, args.gate, networks)
            print(json.dumps({"decision": decision, "reads": None if path is None else len(path), "blocking": blocking,
                              "verdicts": None if path is None else [r["verdict"] for r in path]}, indent=2))
            return 0 if decision == "take" else 1
        if args.command == "backfill":
            commits = first_parent_commits(args.repo, args.since, args.until)
            document = None
            previous = args.since
            base_xml = git_show(args.repo, previous, APN_FILE)
            if base_xml is None:
                raise F5Error(f"{args.since} has no {APN_FILE}")
            document = empty_file(subprocess.run(["git", "-C", str(args.repo), "rev-parse", args.since], capture_output=True, text=True, check=True).stdout.strip(),
                                  apn_rows_sha256(base_xml))
            for commit in commits:
                head_xml = git_show(args.repo, commit, APN_FILE)
                if head_xml is None or apn_rows_sha256(head_xml) == apn_rows_sha256(base_xml):
                    base_xml, previous = head_xml or base_xml, commit
                    continue
                with tempfile.TemporaryDirectory(prefix="f5-backfill-") as folder:
                    checkout_tree(args.repo, commit, Path(folder))
                    read = read_files(base_xml, head_xml, Path(folder), previous, read_at=args.read_at)
                document = append_read(document, read, None, head_xml)
                print(f"{previous[:12]} -> {commit[:12]}: {read['verdict']}, {len(read['lines'])} line(s)")
                for finding in read["findings"]:
                    print(f"  {finding['verdict']:7} {finding['rule']:17} {finding['line'][:200]}")
                base_xml, previous = head_xml, commit
            (args.root / FILE).parent.mkdir(parents=True, exist_ok=True)
            (args.root / FILE).write_bytes(dump(document))
            print(f"wrote {FILE}: {len(document['reads'])} read(s) since {args.since[:12]}")
            return 0
    except (F5Error, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
