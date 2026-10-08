#!/usr/bin/env python3
"""Phone-level publish guard: hold an `apns-conf.xml` change that takes a
phone's internet, attach or working MMS away, or moves MMS off a current
vendor's tuple (rule decisions of 2026-10-06, publish guard of 2026-10-08,
change 22).

usage: check_phone_guard.py BASE_XML HEAD_XML --generator CHECKOUT
       [--accept DIGEST] [--report-json PATH]

Both files are read with `android_phone_model`. Only scopes in both files are
compared, on the 3GPP data network types of HOLD_TYPES. A trip is one of:

- internet_lost: the scope loses its internet lead on a network type;
- attach_lost: the scope loses its attach lead;
- mms_lost: the scope loses working MMS (a route with an MMSC);
- mms_away: MMS moves from a current vendor's tuple (APN, MMSC, MMS proxy,
  MMS port) to one no current vendor gives. APN and MMSC are case-folded and
  a trailing `/` on the MMSC is ignored. The vendor tuples come from the
  generator's records of CHECKOUT, the head's checkout.

Everything else is reported, never held: credentials and HTTP proxies on the
leads, leads that move to an APN no current vendor gives, scopes that leave
the file, losses only on IWLAN or CDMA, other MMS moves, stored rows and
`persist_apns_for_plmn` events.

The digest is the first 16 hex characters of sha256 over the sorted trip
lines `condition|scope|network types|old value|new value`, joined by and
ending with a newline. The trips pass only with `--accept` equal to it; a
pull request body accepts them with the line `phone-guard-accept: DIGEST`.

Exit 0 with no trips or accepted trips, 1 with unaccepted trips, 2 on any
error. Byte-identical files exit 0 at once.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import functools
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET

import android_phone_model as phone

HOLD_TYPES = {"GPRS": 1, "EDGE": 2, "UMTS": 3, "HSPA": 10, "LTE": 13, "HSPA+": 15, "NR": 20}
OTHER_TYPES = {"IWLAN": 18, "eHRPD": 14, "EVDO-A": 6, "1xRTT": 7}
LIST_LIMIT = 15


def fmt(scope: phone.Scope) -> str:
    mcc, mnc, mvno_type, match = scope
    return f"{mcc}/{mnc}" + (f" {mvno_type.upper()} {match}" if mvno_type else "")


def load_generator(checkout: Path):
    tools = checkout / "tools"
    sys.path.insert(0, str(tools))
    spec = importlib.util.spec_from_file_location("measured_generator", tools / "generate_android_outputs.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["measured_generator"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@functools.lru_cache(maxsize=None)
def generator_records(checkout: Path):
    """The generator of CHECKOUT and its APN records of CHECKOUT's data."""
    generator = load_generator(checkout)
    profiles = [generator.load_json(path) for path in generator.profile_paths(checkout / "carriers")]
    evidence = generator.load_apn_evidence(checkout / "generated" / "evidence-index.json")
    return generator, generator.apn_xml_rows(profiles, evidence).records


def vendor_mms_tuples(checkout: Path) -> dict[phone.Scope, set[tuple]]:
    """Per scope, the MMS tuples of the rows a current vendor backs for `mms`,
    from the generator's own records of CHECKOUT."""
    generator, records = generator_records(checkout)
    out: dict[phone.Scope, set[tuple]] = defaultdict(set)
    for record in records:
        if not record.get("_current", {}).get("mms") or generator.placeholder_apn(record["apn"]):
            continue
        if not str(record.get("mmsc") or "").strip():
            continue
        row = phone.parse_lines([generator.apn_row_line(record)])[0]
        out[phone.scope_of(row)].add((row.get("apn", ""), row.get("mmsc") or None,
                                      row.get("mmsproxy") or "", phone.port_from_string(row.get("mmsport"))))
    return out


def vendor_rows(checkout: Path) -> dict[phone.Scope, dict[str, dict[str, set]]]:
    """Per scope and case-folded APN, the credentials and proxies of the rows
    any current vendor backs (for the report only)."""
    generator, records = generator_records(checkout)
    out: dict[phone.Scope, dict[str, dict[str, set]]] = defaultdict(dict)
    for record in records:
        if not any((record.get("_current") or {}).values()):
            continue
        row = phone.parse_lines([generator.apn_row_line(record)])[0]
        entry = out[phone.scope_of(row)].setdefault(str(row.get("apn", "")).casefold(),
                                                    {"credentials": set(), "proxies": set()})
        entry["credentials"].add((row.get("user") or "", row.get("password") or ""))
        entry["proxies"].add(row.get("proxy") or "")
    return out


def norm(mms: tuple | None) -> tuple | None:
    if mms is None:
        return None
    return (str(mms[0]).casefold(), (mms[1] or "").rstrip("/").casefold(), mms[2] or "", mms[3])


def works(mms: tuple | None) -> bool:
    return bool(mms and mms[1])


def mms_text(mms: tuple | None) -> str:
    if mms is None:
        return "none"
    port = mms[3] if mms[3] is not None and mms[3] >= 0 else "-"
    return f"{mms[0]} mmsc={mms[1] or 'none'} mmsproxy={mms[2] or '-'} mmsport={port}"


def lead_text(lead: tuple | None) -> str:
    return "none" if lead is None else str(lead[0])


def read_rows(path: Path) -> list[dict[str, Any]]:
    """The rows of an apns-conf.xml. The file must be well-formed XML with
    one `<apn>` element per line, as the generator writes it."""
    root = ET.parse(path).getroot()
    if root.tag != "apns":
        raise ValueError(f"{path}: root element is <{root.tag}>, not <apns>")
    rows = phone.parse_xml(path)
    if len(rows) != len(root.findall("apn")):
        raise ValueError(f"{path}: {len(root.findall('apn'))} <apn> elements, {len(rows)} read line by line")
    return rows


def trips(before: dict, after: dict, vendor: dict) -> list[dict[str, Any]]:
    found: dict[tuple, list[str]] = defaultdict(list)
    for scope in set(before) & set(after):
        tuples = {norm(t) for t in vendor.get(scope, ())}
        for name in HOLD_TYPES:
            b_inet, b_mms, b_attach = before[scope][name][:3]
            a_inet, a_mms, a_attach = after[scope][name][:3]
            if b_inet and not a_inet:
                found[("internet_lost", fmt(scope), lead_text(b_inet), "none")].append(name)
            if b_attach and not a_attach:
                found[("attach_lost", fmt(scope), lead_text(b_attach), "none")].append(name)
            if works(b_mms) and not works(a_mms):
                found[("mms_lost", fmt(scope), mms_text(b_mms), mms_text(a_mms))].append(name)
            elif (works(b_mms) and norm(b_mms) != norm(a_mms) and norm(b_mms) in tuples
                    and norm(a_mms) not in tuples):
                found[("mms_away", fmt(scope), mms_text(b_mms), mms_text(a_mms))].append(name)
    return [{"condition": c, "scope": s, "types": types, "old": o, "new": n}
            for (c, s, o, n), types in sorted(found.items())]


def trip_line(trip: dict[str, Any]) -> str:
    return "|".join((trip["condition"], trip["scope"], ",".join(trip["types"]), trip["old"], trip["new"]))


def digest(found: list[dict[str, Any]]) -> str:
    text = "".join(line + "\n" for line in sorted(trip_line(trip) for trip in found))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def report(before: dict, after: dict, tables: tuple, vendor: dict, rows: dict) -> list[str]:
    items: dict[str, set[str]] = defaultdict(set)
    warnings: list[str] = []
    for scope in sorted(set(before) - set(after)):
        items["scopes gone, MVNO" if scope[2] else "scopes gone, network"].add(fmt(scope))
    for scope in sorted(set(before) & set(after)):
        b, a, s = before[scope], after[scope], fmt(scope)
        known = rows.get(scope, {})
        tuples = {norm(t) for t in vendor.get(scope, ())}
        lost: dict[str, set[str]] = defaultdict(set)
        for name in {**HOLD_TYPES, **OTHER_TYPES}:
            (b_inet, b_mms, b_attach, _, b_mlead), (a_inet, a_mms, a_attach, _, a_mlead) = b[name], a[name]
            group = "hold" if name in HOLD_TYPES else "other"
            for kind, old, new in (("internet", b_inet, a_inet), ("attach", b_attach, a_attach)):
                if old and not new:
                    lost[kind].add(group)
            if works(b_mms) and not works(a_mms):
                lost["mms"].add(group)
            for role, old, new in (("internet", b_inet, a_inet), ("attach", b_attach, a_attach),
                                   ("MMS", b_mlead, a_mlead)):
                if not new or old == new:
                    continue
                vendor_apn = known.get(str(new[0]).casefold())
                if (new[3] or new[4]) and (not old or (old[3], old[4]) != (new[3], new[4])):
                    items[f"credentials gained or changed on the {role} lead"].add(s)
                    nonempty = {c for c in (vendor_apn or {}).get("credentials", ()) if any(c)}
                    if nonempty and (new[3], new[4]) not in vendor_apn["credentials"]:
                        warnings.append(f"WARNING: {s} {role} lead {new[0]}: credentials a current vendor's "
                                        f"credentials for this APN contradict")
                if new[1] and (not old or old[1] != new[1]):
                    items[f"HTTP proxy gained or changed on the {role} lead"].add(s)
                    if new[1] not in (vendor_apn or {}).get("proxies", ()):
                        warnings.append(f"WARNING: {s} {role} lead {new[0]}: proxy {new[1]} no current "
                                        f"vendor row of this APN gives")
                if (role != "MMS" and old and str(old[0]).casefold() != str(new[0]).casefold()
                        and vendor_apn is None):
                    items[f"{role} lead moves to an APN no current vendor gives"].add(s)
            if b_mms != a_mms and works(b_mms) and works(a_mms) and norm(b_mms) != norm(a_mms):
                if norm(a_mms) in tuples and norm(b_mms) not in tuples:
                    items["MMS moves to a vendor tuple"].add(s)
                elif norm(a_mms) not in tuples and norm(b_mms) not in tuples:
                    items["MMS moves between tuples no vendor gives"].add(s)
        for kind, groups in lost.items():
            if groups == {"other"}:
                items[f"{kind} lost only on IWLAN or CDMA"].add(s)
    lines = [f"stored rows: {phone.stored_count(tables[0])} -> {phone.stored_count(tables[1])}"]
    for label, table in zip(("before", "after"), tables):
        events = phone.persist_events(table)
        if events:
            lines.append(f"persist_apns_for_plmn fires {label}: {sorted({numeric for numeric, _ in events})}")
    for key in sorted(items):
        scopes = sorted(items[key])
        more = f" and {len(scopes) - LIST_LIMIT} more" if len(scopes) > LIST_LIMIT else ""
        lines.append(f"{key}: {len(scopes)}: {', '.join(scopes[:LIST_LIMIT])}{more}")
    unique = list(dict.fromkeys(warnings))
    return unique[:LIST_LIMIT * 2] + ([f"... {len(unique) - LIST_LIMIT * 2} more warnings"]
                                      if len(unique) > LIST_LIMIT * 2 else []) + lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("base", type=Path)
    parser.add_argument("head", type=Path)
    parser.add_argument("--generator", type=Path, required=True, help="the head's checkout")
    parser.add_argument("--accept", action="append", default=[], help="a digest that accepts the trips")
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv[1:])
    if args.base.read_bytes() == args.head.read_bytes():
        print("phone-level guard: PASS, apns-conf.xml is unchanged")
        result: dict[str, Any] = {"verdict": "pass", "trips": [], "digest": None, "report": []}
    else:
        before_rows, after_rows = read_rows(args.base), read_rows(args.head)
        types = {**HOLD_TYPES, **OTHER_TYPES}
        before, before_tables = phone.phone_state(before_rows, types)
        after, after_tables = phone.phone_state(after_rows, types)
        vendor = vendor_mms_tuples(args.generator.resolve())
        found = trips(before, after, vendor)
        code = digest(found) if found else None
        verdict = "pass" if not found else "accepted" if code in args.accept else "hold"
        lines = report(before, after, (before_tables, after_tables), vendor,
                       vendor_rows(args.generator.resolve()))
        print(f"phone-level guard: {verdict.upper()}, {len(found)} trip(s) on {', '.join(HOLD_TYPES)}")
        for trip in found:
            print(f"  {trip_line(trip)}")
        if code:
            print(f"phone-guard-accept: {code}")
        print("report, never held:")
        for line in lines:
            print(f"  {line}")
        result = {"verdict": verdict, "trips": found, "digest": code, "report": lines}
    if args.report_json:
        args.report_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 1 if result["verdict"] == "hold" else 0


def run(argv: list[str]) -> int:
    """main, failing closed: any error, including a SystemExit other than
    --help, exits 2."""
    try:
        return main(argv)
    except SystemExit as exc:
        if exc.code == 0 and ("-h" in argv or "--help" in argv):
            return 0
        print(f"phone-level guard: ERROR exit {exc.code}", file=sys.stderr)
        return 2
    except BaseException as exc:
        print(f"phone-level guard: ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv))
