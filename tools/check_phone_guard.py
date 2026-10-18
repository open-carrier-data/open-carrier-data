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

Everything else is reported, never held: credentials and HTTP proxies gained
or changed on the leads, credentials lost on the leads, leads that move to an
APN no current vendor gives, scopes that leave the file, losses only on IWLAN
or CDMA, other MMS moves, stored rows and `persist_apns_for_plmn` events.
A lead sends credentials when it has a username or password and its resolved
auth type is not 0; credentials are lost when the old lead sent them and the
new lead sends none, with a WARNING when every row a current vendor backs for
the new lead's APN in the scope carries credentials (rule decisions of
2026-10-13, round 14).

Also reported, never held, on WATCH_TYPES (HOLD_TYPES plus IWLAN; rule
decisions of 2026-10-18, round 20): the `ims` lead of each scope in both
files lost, its APN changed (case-folded), or only its protocol or roaming
protocol changed, and an APN with an emergency name
(`carrier_config_types.emergency_named`, shared with the generator) becoming
the internet or attach lead. The `ims` lead is the first data profile that
serves the type on the network type, as for the internet lead.

The `emergency` lead is what the phone uses (rule decisions of 2026-10-18,
round 21, S1-A): the first profile that can handle `emergency` (enabled, with
the type; an empty type is Android's TYPE_ALL, which has no emergency bit),
serves the network type, has cellular infrastructure and passes the APN set
filter for preferred set 0 (set -1 or 0). When no profile of the scope can
handle `emergency` on any network type, Android adds its own DEFAULT EIMS
profile, `sos` IPV4V6/IPV4V6 with APN set -1 (ANDROID_DEFAULT_EIMS,
`DataProfileManager.java:339-350, 630-641`). The report prints an emergency
lead "gained" (Android's default to a row of the file), "lost" (a row of the
file to Android's default) or "changed" (any other change of the request:
APN, either protocol, auth type, credentials, MTU, network types,
`skip_464xlat`, `always_on`, profile ID or modem-cognitive), each value
labelled against Android's default: `equal`, `carrier name`, `IPv4 only`,
`IPv6 only`, `request attribute`, or `network-type gap` for a network type
left without an emergency profile. It also prints "emergency profile
missing under APN set N" for a scope where a preferred APN set N (0, or the
set of a row that serves `default`) leaves no emergency profile in the head
but did not in the base (`DataProfileManager.java:799-808`). Lines that touch
LTE, NR or IWLAN are listed first.

None of these lines enters the trips or the digest. Each condition prints a
count line, then one line per scope and value change up to
WATCH_LIST_LIMIT; `--report-json` keeps them all under `watch`.

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
from carrier_config_types import emergency_named

HOLD_TYPES = {"GPRS": 1, "EDGE": 2, "UMTS": 3, "HSPA": 10, "LTE": 13, "HSPA+": 15, "NR": 20}
OTHER_TYPES = {"IWLAN": 18, "eHRPD": 14, "EVDO-A": 6, "1xRTT": 7}
LIST_LIMIT = 15
# The IMS and emergency report (round 20): the hold types plus Wi-Fi calling.
WATCH_TYPES = {**HOLD_TYPES, "IWLAN": 18}
WATCH_APN_TYPES = ("ims",)
WATCH_LIST_LIMIT = 30
# Report lines that touch these network types are listed first (round 21).
WATCH_FIRST = ("LTE", "NR", "IWLAN")
# Android's DEFAULT EIMS profile, added when no profile of the SIM can handle
# `emergency` (DataProfileManager.java:339-350, buildDefaultApnSetting
# :630-641): APN `sos`, IPV4V6 at home and when roaming, APN set "match all".
# The keys are those of android_phone_model.apn_setting (rule decisions of
# 2026-10-18, round 21, S1-A).
ANDROID_DEFAULT_EIMS: dict[str, Any] = {
    "srcs": [], "base_srcs": [], "name": "DEFAULT EIMS", "apn": "sos", "proxy": "", "port": -1,
    "mmsc": None, "mmsproxy": "", "mmsport": -1, "user": "", "password": "", "authtype": 0,
    "types": frozenset({"emergency"}), "protocol": "IPV4V6", "roaming_protocol": "IPV4V6",
    "carrier_enabled": 1, "nt": 0, "lingering": 0, "profile_id": 0, "persistent": 0, "apn_set_id": -1,
    "carrier_id": -1, "skip464": -1, "always_on": 0, "infra": 3, "esim": 0, "mtu4": 0, "mtu6": 0,
    "merged_from": [], "android_default": True,
}


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


def sends_credentials(lead: tuple | None) -> bool:
    """A lead (`android_phone_model.lead_key`) sends credentials when it has a
    username or password and its resolved auth type is not 0."""
    return bool(lead and (lead[3] or lead[4]) and lead[5] != 0)


def protocol_text(lead: tuple | None) -> str:
    return "none" if lead is None else f"{lead[0]} {lead[6]}/{lead[7]}"


def handles_emergency(profile: dict[str, Any]) -> bool:
    """ApnSetting.canHandleType for `emergency` (ApnSetting.java:1271-1287):
    enabled and carrying the type. An empty type is TYPE_ALL, which has no
    emergency bit (`android_phone_model.type_set` gives KNOWN_TYPES for it)."""
    return (bool(profile["carrier_enabled"]) and "emergency" in profile["types"]
            and profile["types"] != phone.KNOWN_TYPES)


def emergency_profiles(settings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The scope's profiles, plus ANDROID_DEFAULT_EIMS when none of them can
    handle `emergency` on any network type."""
    if any(handles_emergency(p) for p in settings):
        return settings
    return settings + [ANDROID_DEFAULT_EIMS]


def emergency_lead(settings: list[dict[str, Any]], network_type: int,
                   preferred_set: int = 0) -> dict[str, Any] | None:
    """The first profile of `emergency_profiles` that handles `emergency` on
    the network type with cellular infrastructure and passes the APN set
    filter (`DataProfileManager.java:778-808`): set -1 or the preferred set."""
    return next((p for p in settings if handles_emergency(p) and phone.serves(p, network_type)
                 and p["infra"] & 1 and p["apn_set_id"] in (-1, preferred_set)), None)


def emergency_key(profile: dict[str, Any] | None) -> tuple | None:
    """What an emergency lead puts into the request, and whether it is
    Android's default."""
    if profile is None:
        return None
    return (bool(profile.get("android_default")), profile["apn"], profile["protocol"],
            profile["roaming_protocol"], profile["user"], profile["password"], profile["authtype"],
            profile["mtu4"], profile["mtu6"], profile["nt"], profile["skip464"], profile["always_on"],
            profile["profile_id"], profile["persistent"])


def emergency_labels(key: tuple | None) -> list[str]:
    """An emergency lead against Android's default request (round 21)."""
    if key is None:
        return ["network-type gap"]
    _, apn, protocol, roaming, user, password, authtype, mtu4, mtu6, nt, skip464, always_on, profile_id, \
        persistent = key
    labels = []
    if apn != "sos":
        labels.append("carrier name")
    if "IP" in (protocol, roaming):
        labels.append("IPv4 only")
    if "IPV6" in (protocol, roaming):
        labels.append("IPv6 only")
    if user or password or authtype or mtu4 > 0 or mtu6 > 0 or nt or skip464 != -1 or always_on \
            or profile_id or persistent:
        labels.append("request attribute")
    return labels or ["equal"]


def emergency_text(key: tuple | None) -> str:
    if key is None:
        return "none [network-type gap]"
    text = f"{key[1]} {key[2]}/{key[3]}"
    return f"Android default {text}" if key[0] else f"{text} [{', '.join(emergency_labels(key))}]"


def stranded_sets(settings: list[dict[str, Any]]) -> set[int]:
    """The preferred APN sets (0, or the set of a profile that serves
    `default`) under which no profile can carry an emergency request on any
    network type of WATCH_TYPES."""
    candidates = {0} | {p["apn_set_id"] for p in settings
                        if "default" in p["types"] and p["apn_set_id"] not in (0, -1)}
    emergency = emergency_profiles(settings)
    return {preferred for preferred in candidates
            if not any(emergency_lead(emergency, network_type, preferred)
                       for network_type in WATCH_TYPES.values())}


def typed_leads(rows: list[dict[str, Any]], tables: dict) -> dict:
    """Per scope, network type of WATCH_TYPES and APN type of
    WATCH_APN_TYPES: the lead (`android_phone_model.lead_key`) of the first
    data profile that serves the type, from the stored rows in TABLES; under
    "emergency", the `emergency_key` of the phone's emergency lead with
    Android's fallback; and under "_sets", the scope's `stranded_sets`."""
    out: dict[phone.Scope, dict[str, Any]] = {}
    for scope in {phone.scope_of(row) for row in rows}:
        settings = phone.profiles(phone.scope_rows(tables, scope))
        emergency = emergency_profiles(settings)
        out[scope] = {
            name: {**{kind: phone.lead_key(next((p for p in settings if kind in p["types"]
                                                 and phone.serves(p, network_type) and phone.cellular(p)),
                                                None))
                      for kind in WATCH_APN_TYPES},
                   "emergency": emergency_key(emergency_lead(emergency, network_type))}
            for name, network_type in WATCH_TYPES.items()}
        out[scope]["_sets"] = stranded_sets(settings)
    return out


def watch(before: dict, after: dict, before_typed: dict, after_typed: dict) -> list[dict[str, Any]]:
    """The IMS and emergency report items, never trips: per condition, scope
    and old and new value, the network types of WATCH_TYPES it holds on."""
    found: dict[tuple, list[str]] = defaultdict(list)
    for scope in set(before) & set(after):
        for name in WATCH_TYPES:
            for kind in WATCH_APN_TYPES:
                old, new = before_typed[scope][name][kind], after_typed[scope][name][kind]
                if old and not new:
                    found[(f"{kind} lead lost", fmt(scope), protocol_text(old), "none")].append(name)
                elif old and str(old[0]).casefold() != str(new[0]).casefold():
                    found[(f"{kind} lead APN changed", fmt(scope), protocol_text(old),
                           protocol_text(new))].append(name)
                elif old and (old[6], old[7]) != (new[6], new[7]):
                    found[(f"{kind} lead protocol changed", fmt(scope), protocol_text(old),
                           protocol_text(new))].append(name)
            old, new = before_typed[scope][name]["emergency"], after_typed[scope][name]["emergency"]
            if old != new:
                if old and new and old[0] and not new[0]:
                    condition = "emergency lead gained"
                elif old and new and not old[0] and new[0]:
                    condition = "emergency lead lost"
                else:
                    condition = "emergency lead changed"
                found[(condition, fmt(scope), emergency_text(old), emergency_text(new))].append(name)
            b_inet, _, b_attach = before[scope][name][:3]
            a_inet, _, a_attach = after[scope][name][:3]
            for role, old, new in (("internet", b_inet, a_inet), ("attach", b_attach, a_attach)):
                if new and emergency_named(new[0]) and not (old and emergency_named(old[0])):
                    found[(f"emergency-named APN becomes the {role} lead", fmt(scope), lead_text(old),
                           lead_text(new))].append(name)
        for preferred in sorted(after_typed[scope]["_sets"] - before_typed[scope]["_sets"]):
            found[(f"emergency profile missing under APN set {preferred}", fmt(scope),
                   "an emergency profile", "none")].extend(WATCH_TYPES)
    return [{"condition": c, "scope": s, "types": types, "old": o, "new": n}
            for (c, s, o, n), types in sorted(found.items())]


def watch_lines(items: list[dict[str, Any]]) -> list[str]:
    """A count line per condition (scopes), then its value lines up to
    WATCH_LIST_LIMIT."""
    lines: list[str] = []
    for condition in sorted({item["condition"] for item in items}):
        mine = sorted((item for item in items if item["condition"] == condition),
                      key=lambda item: not set(item["types"]) & set(WATCH_FIRST))
        lines.append(f"{condition}: {len({item['scope'] for item in mine})} scope(s)")
        for item in mine[:WATCH_LIST_LIMIT]:
            lines.append(f"  {item['scope']}: {item['old']} -> {item['new']} ({','.join(item['types'])})")
        if len(mine) > WATCH_LIST_LIMIT:
            lines.append(f"  ... {len(mine) - WATCH_LIST_LIMIT} more (--report-json lists them all)")
    return lines


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
                if sends_credentials(old) and not sends_credentials(new):
                    items[f"credentials lost on the {role} lead"].add(s)
                    given = (vendor_apn or {}).get("credentials", ())
                    if given and all(any(c) for c in given):
                        warnings.append(f"WARNING: {s} {role} lead {new[0]}: sends no credentials, every current "
                                        f"vendor row of this APN carries credentials")
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
        result: dict[str, Any] = {"verdict": "pass", "trips": [], "digest": None, "report": [], "watch": []}
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
        watched = watch(before, after, typed_leads(before_rows, before_tables),
                        typed_leads(after_rows, after_tables))
        print(f"phone-level guard: {verdict.upper()}, {len(found)} trip(s) on {', '.join(HOLD_TYPES)}")
        for trip in found:
            print(f"  {trip_line(trip)}")
        if code:
            print(f"phone-guard-accept: {code}")
        print("report, never held:")
        for line in lines:
            print(f"  {line}")
        print("IMS and emergency report, never held:" if watched else
              "IMS and emergency report, never held: no change")
        for line in watch_lines(watched):
            print(f"  {line}")
        result = {"verdict": verdict, "trips": found, "digest": code, "report": lines, "watch": watched}
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
