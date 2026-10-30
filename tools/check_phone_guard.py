#!/usr/bin/env python3
"""Phone-level publish guard: hold an `apns-conf.xml` change that takes a
phone's internet, attach or working MMS away, or moves MMS off a current
vendor's tuple (rule decisions of 2026-10-06, publish guard of 2026-10-08,
change 22).

usage: check_phone_guard.py BASE_XML HEAD_XML --generator CHECKOUT
       [--base-generator CHECKOUT | --base-ref REV]
       [--accept DIGEST] [--report-json PATH]

Both files are read with `android_phone_model`. Only scopes in both files are
compared, on the 3GPP data network types of HOLD_TYPES. A trip is one of:

- internet_lost: the scope loses its internet lead on a network type;
- attach_lost: the scope loses its attach lead;
- mms_lost: the scope loses working MMS (a route with an MMSC);
- mms_away: MMS moves from a current vendor's tuple (APN, MMSC, MMS proxy,
  MMS port) to one no current vendor gives. APN and MMSC are case-folded and
  a trailing `/` on the MMSC is ignored. The vendor tuples come from the
  generator's records of CHECKOUT, the head's checkout. With
  `--base-generator` (the base's checkout) or `--base-ref` (a revision of
  CHECKOUT's repository, whose tools, carriers and evidence index the guard
  extracts), MMS also trips when it moves off a tuple a current vendor gave
  in the base to one no current vendor gives in the head (rule decisions
  round 35, item E; round 15's base vendor tuples): a change that also takes
  the vendor's row away cannot hide the move.

Everything else is reported, never held: credentials and HTTP proxies gained
or changed on the leads, credentials lost on the leads, internet and attach
leads that move to an APN no current vendor gives for their role (internet:
`default`; attach: `default` or `ia`; rule decisions round 35, item E: an APN
a vendor gives only for MMS does not back an attach), scopes that leave the
file, network scopes that leave while a current Google, Samsung or Apple
observation lists their code, MVNO scopes that leave with what their SIMs'
fallback to the network's plain rows changes in the internet, attach, MMS or
IMS APN, losses only on IWLAN or CDMA, other MMS moves, stored rows and
`persist_apns_for_plmn` events.
A lead sends credentials when it has a username or password and its resolved
auth type is not 0; credentials are lost when the old lead sent them and the
new lead sends none, with a WARNING when every row a current vendor backs for
the new lead's APN in the scope carries credentials (rule decisions of
2026-10-13, round 14).

Also reported, never held (rule decisions round 32, D8): "credentials filled
in from a non-current source on the {role} lead", for every lead of the head
on HOLD_TYPES whose stored row takes a username, password, auth type or MTU
from a lower-ranked row of its group (`android_phone_model.fill_ins`) that no
current vendor backs, under a best row a current vendor backs (class (a)),
where the base's lead on that network type had another APN or other
filled-in values. Each scope names the sources of the filling rows, read from
the generator's records of CHECKOUT when they are exactly the head file's
rows (`aligned_records`); otherwise the report says the sources are unknown.
`class_a_list` gives the whole class (a) list of a checkout, which
`credential_fill_ins.py` prints for each publish and the release notes carry.

Also reported, never held, on WATCH_TYPES (HOLD_TYPES plus IWLAN; rule
decisions of 2026-10-18, round 20): the `ims` lead of each scope in both
files lost, its APN changed (case-folded), or only its protocol or roaming
protocol changed, and an APN with an emergency name (`emergency_named`)
becoming the internet or attach lead. The `ims` lead is the first data
profile that serves the type on the network type, as for the internet lead.
When no profile of the scope can handle `ims` on any network type, Android
adds its own DEFAULT IMS profile, `ims` IPV4V6/IPV4V6 with APN set -1
(ANDROID_DEFAULT_IMS, `DataProfileManager.java:343-355`; rule decisions round
35, item C). So a scope that loses its last `ims` row lands on Android's
default ("ims lead lost to Android's default"), and a row that takes `ims`
where only the default served it is reported as gained; when that row also
serves `default`, the internet APN now carries IMS registration ("IMS
profile gained on an internet APN, displacing Android's DEFAULT IMS"). The
head's IMS leads on a row that a `*` type gave `ims`, that no current vendor
backs for `ims`, in a scope where a current vendor gives an `ims` row, are
listed too ("ims lead on a *-typed row no current vendor backs for ims"),
from the generator's records of CHECKOUT when they are the head file's rows.
Rule round 34 adds two lines, report only and never held: "xcap lead APN
changed", the first data profile that serves `xcap` (REPORT_APN_CHANGE_TYPES)
taking another APN (case-folded), and "attach lead APN changed", the attach
lead (`android_phone_model.leads`) taking another APN, so a later import that
moves either lead under change 18 step 2c or step 4b is seen in the publish.
Rule round 38 (item 5) adds "dun lead APN changed" and "supl lead APN
changed" the same way, report only and never held: #228's dry run moved
204/04's tethering lead to another operator's APN and 244/04's and 244/13's
SUPL leads to APNs no current vendor gives, and no line showed it.

The `emergency` lead is what the phone uses (rule decisions of 2026-10-18,
round 21, S1-A): the first profile that can handle `emergency` (enabled, with
the type; an empty type is Android's TYPE_ALL, which has no emergency bit,
as `android_phone_model.type_set` reads it),
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
import subprocess
import sys
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

import android_phone_model as phone

HOLD_TYPES = {"GPRS": 1, "EDGE": 2, "UMTS": 3, "HSPA": 10, "LTE": 13, "HSPA+": 15, "NR": 20}
OTHER_TYPES = {"IWLAN": 18, "eHRPD": 14, "EVDO-A": 6, "1xRTT": 7}
LIST_LIMIT = 15
# The IMS and emergency report (round 20): the hold types plus Wi-Fi calling.
WATCH_TYPES = {**HOLD_TYPES, "IWLAN": 18}
WATCH_APN_TYPES = ("ims",)
# Leads whose APN change alone is reported, never held (rule round 34: xcap;
# rule round 38, item 5: dun and supl).
REPORT_APN_CHANGE_TYPES = ("xcap", "dun", "supl")
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
# Android's DEFAULT IMS profile, added when no profile of the SIM can handle
# `ims` (DataProfileManager.java:343-355, buildDefaultApnSetting): APN `ims`,
# IPV4V6 at home and when roaming, every network type, APN set "match all"
# (rule decisions round 35, item C).
ANDROID_DEFAULT_IMS: dict[str, Any] = {
    **ANDROID_DEFAULT_EIMS, "name": "DEFAULT IMS", "apn": "ims", "types": frozenset({"ims"}),
}
# The types that back a lead's role (rule decisions round 35, item E).
ROLE_TYPES = {"internet": frozenset({"default"}), "attach": frozenset({"default", "ia"})}
# Sources whose observation of a network code means the network is live:
# the current vendors and Apple's bundles (round 35, item B's stop).
LISTING_SOURCES = frozenset({"google_carriersettings", "samsung_omc", "samsung_ims", "apple_carrier_bundles"})


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


BASE_CHECKOUT_PATHS = ("tools", "carriers", "schemas", "generated/evidence-index.json")


def extract_checkout(checkout: Path, revision: str, into: Path) -> Path:
    """The tools, carriers, schemas and evidence index of REVISION of
    CHECKOUT's git repository (those of BASE_CHECKOUT_PATHS the revision has),
    extracted into INTO (`git archive`), as a checkout the generator
    functions read."""
    present = subprocess.run(["git", "-C", str(checkout), "ls-tree", "--name-only", revision, "--",
                              *BASE_CHECKOUT_PATHS], check=True, capture_output=True, text=True).stdout.split()
    if "tools" not in present:
        raise ValueError(f"{revision} of {checkout} has no tools/")
    listed = subprocess.run(["git", "-C", str(checkout), "archive", "--format=tar", revision, "--", *present],
                            check=True, capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(into)], input=listed.stdout, check=True)
    return into


@functools.lru_cache(maxsize=None)
def generator_rows(checkout: Path):
    """The generator of CHECKOUT and its `apn_xml_rows` of CHECKOUT's data."""
    generator = load_generator(checkout)
    profiles = [generator.load_json(path) for path in generator.profile_paths(checkout / "carriers")]
    evidence = generator.load_apn_evidence(checkout / "generated" / "evidence-index.json")
    return generator, generator.apn_xml_rows(profiles, evidence)


def generator_records(checkout: Path):
    """The generator of CHECKOUT and its APN records of CHECKOUT's data."""
    generator, rows = generator_rows(checkout)
    return generator, rows.records


generator_records.cache_clear = generator_rows.cache_clear  # type: ignore[attr-defined]


def aligned_records(checkout: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The generator's records of CHECKOUT, one per row of ROWS in file
    order, when they are exactly the rows of that file (the head's file,
    generated from CHECKOUT); None otherwise, and then no source is named."""
    generator, records = generator_records(checkout)
    if len(records) != len(rows):
        return None
    for record, row in zip(records, rows):
        line = generator.apn_row_line(record).strip()
        if line == row["_line"]:
            continue
        parsed = phone.parse_lines([line])
        if not parsed or ({k: v for k, v in parsed[0].items() if not k.startswith("_")}
                          != {k: v for k, v in row.items() if not k.startswith("_")}):
            return None
    return records


def record_sources(record: dict[str, Any] | None, key: str) -> frozenset[str]:
    """Every source of a generator record's `_support` or `_current`, over
    all its types."""
    out: set[str] = set()
    for sources in ((record or {}).get(key) or {}).values():
        out.update(sources)
    return frozenset(out)


# Credentials from non-current sources (rule decisions round 32, D8). A lead's
# stored row takes a username, password, auth type or MTU from a lower-ranked
# row of its group where the best row sets none (android_phone_model.fill_ins).
# The fill-in is class (a) when no current vendor backs any filling row
# (`_current`) and one backs the best row. Report only: no trip, no digest.
CREDENTIAL_ROLES = ("internet", "attach", "MMS")
CREDENTIAL_SENT_FIELDS = ("user", "password", "authtype")
CREDENTIAL_MTU_FIELDS = ("mtu", "mtu_v4", "mtu_v6")


def lead_credentials(rows: list[dict[str, Any]], tables: dict, records: list[dict[str, Any]] | None,
                     network_types: dict[str, int] = HOLD_TYPES,
                     scopes: Any = None) -> list[dict[str, Any]]:
    """Per scope, role (internet, attach, MMS) and lead, on NETWORK_TYPES:
    every field of CREDENTIAL_FIELDS the lead's stored row carries, with the
    file row that wrote it, whether that is the group's best (last) row, and
    with RECORDS (aligned_records) the row's sources and current vendors.
    `fill_ins` holds the fields a lower-ranked row filled in, `class_a`
    whether that fill-in is class (a) (None without records), and `sent`
    whether the lead sends a filled-in value: credentials with an auth type
    other than 0, or an MTU."""
    out: dict[tuple, dict[str, Any]] = {}
    for scope in sorted(scopes if scopes is not None else {phone.scope_of(row) for row in rows}):
        stored = phone.scope_rows(tables, scope)
        by_srcs = {tuple(row["_srcs"]): row for row in stored}
        settings = phone.profiles(stored)
        for name, network_type in network_types.items():
            internet, mms, attach = phone.leads(settings, network_type)
            for role, profile in zip(CREDENTIAL_ROLES, (internet, attach, mms)):
                row = by_srcs.get(tuple(profile["base_srcs"])) if profile else None
                if row is None:
                    continue
                best = row["_srcs"][-1]
                writers = dict(row.get("_writers") or {})
                fills = phone.fill_ins(row)
                fields = {}
                for field, index in sorted(writers.items()):
                    fields[field] = {
                        "value": rows[index].get(field),
                        "row": index,
                        "best_row": index == best,
                        **({"sources": sorted(record_sources(records[index], "_support")),
                            "current_sources": sorted(record_sources(records[index], "_current"))}
                           if records is not None else {}),
                    }
                class_a = None
                if records is not None and fills:
                    class_a = (bool(record_sources(records[best], "_current"))
                               and not any(record_sources(records[index], "_current") for index in fills.values()))
                sent = bool((set(fills) & set(CREDENTIAL_SENT_FIELDS) and sends_credentials(phone.lead_key(profile)))
                            or set(fills) & set(CREDENTIAL_MTU_FIELDS))
                signature = (str(profile["apn"]), tuple(sorted((field, str(rows[index].get(field)))
                                                               for field, index in fills.items())))
                key = (scope, role, signature)
                entry = out.get(key)
                if entry is None:
                    out[key] = entry = {
                        "scope": fmt(scope), "role": role, "apn": profile["apn"], "network_types": [],
                        "sends_credentials": sends_credentials(phone.lead_key(profile)),
                        "fields": fields, "fill_ins": sorted(fills), "class_a": class_a, "sent": sent,
                        "fill_in_sources": sorted(set().union(*(record_sources(records[index], "_support")
                                                                for index in fills.values())))
                        if records is not None and fills else [],
                        "_signature": signature, "_scope": scope,
                    }
                entry["network_types"].append(name)
    return list(out.values())


def class_a_entries(rows: list[dict[str, Any]], tables: dict, records: list[dict[str, Any]] | None,
                    ) -> list[dict[str, Any]]:
    """The class (a) leads of `lead_credentials` on HOLD_TYPES."""
    return [entry for entry in lead_credentials(rows, tables, records) if entry["class_a"]]


def class_a_summary(entries: list[dict[str, Any]]) -> str:
    on_lte = [entry for entry in entries if "LTE" in entry["network_types"]]
    sent = [entry for entry in on_lte if entry["sent"]]
    return (f"{len(on_lte)} LTE lead role(s) in {len({e['scope'] for e in on_lte})} scope(s), "
            f"{len(sent)} of them sent, in {len({e['scope'] for e in sent})} scope(s)")


def class_a_lines(entries: list[dict[str, Any]], left_out: list[dict[str, Any]] | None = None,
                  kept: list[dict[str, Any]] | None = None) -> list[str]:
    """The class (a) list (round 32, D8, rule 6): per scope and role the APN,
    the filled-in fields, the sources of the filling rows, sent or only
    stored, and the network types; then the rows rule 1 left out of
    apns-conf.xml, when the generator names them."""
    lines = [f"class (a) fill-ins: {class_a_summary(entries)}"]
    for entry in entries:
        types = "all hold types" if len(entry["network_types"]) == len(HOLD_TYPES) else ",".join(
            entry["network_types"])
        lines.append(f"  {entry['scope']} {entry['role']} {entry['apn']}: {', '.join(entry['fill_ins'])} from "
                     f"{'+'.join(entry['fill_in_sources']) or 'unknown sources'}; "
                     f"{'sent' if entry['sent'] else 'stored only'} ({types})")
    if left_out is not None:
        lines.append(f"rows rule 1 left out of apns-conf.xml (superseded Google copies): {len(left_out)}")
        for row in left_out:
            lines.append(f"  {row['scope']} {row['apn']} ({row['type']}): {', '.join(row['fields'])} from "
                         f"{'+'.join(row['sources'])}")
    if kept:
        lines.append(f"rows rule 1 keeps because the operator's own page names credentials: {len(kept)}")
        for row in kept:
            lines.append(f"  {row['scope']} {row['apn']} ({row['type']}): {row['page']} (read {row['read']})")
    return lines


def credentials_left_out(checkout: Path) -> list[dict[str, Any]] | None:
    """The rows the generator of CHECKOUT left out of apns-conf.xml under
    rule 1 (`credentials_left_out` of its apn_xml_rows, each with the fields
    it filled in and its sources); None when the generator has no rule 1."""
    return rule1_rows(checkout, "credentials_left_out")


def rule1_rows(checkout: Path, name: str) -> list[dict[str, Any]] | None:
    """The rows of apn_xml_rows' field NAME (credentials_left_out, or
    credentials_kept_operator_page: the rows only the operator's own page
    kept), with their scope, APN, type, filled-in fields or page, and
    sources; None when the generator has no such field."""
    generator, apn_rows = generator_rows(checkout)
    rows = getattr(apn_rows, name, None)
    if rows is None:
        return None
    out = []
    for record in rows:
        attributes = generator.written_attributes(record)
        scope = phone.scope_of({key: str(value) for key, value in attributes.items()})
        page = record.get("_credentials_kept_operator_page") or ("", "")
        out.append({"scope": fmt(scope), "apn": attributes.get("apn"), "type": attributes.get("type"),
                    "fields": list(record.get("_credentials_left_out") or ()),
                    "page": page[0], "read": page[1],
                    "sources": sorted(record_sources(record, "_support"))})
    return out


def class_a_list(checkout: Path) -> dict[str, Any]:
    """The class (a) list of CHECKOUT's generated/android/apns-conf.xml."""
    rows = read_rows(checkout / "generated" / "android" / "apns-conf.xml")
    tables = phone.provider(rows)
    records = aligned_records(checkout, rows)
    entries = class_a_entries(rows, tables, records) if records is not None else []
    left_out = credentials_left_out(checkout)
    kept = rule1_rows(checkout, "credentials_kept_operator_page")
    return {"sources_known": records is not None, "summary": class_a_summary(entries),
            "entries": [{k: v for k, v in entry.items() if not k.startswith("_")} for entry in entries],
            "left_out": left_out, "kept_by_operator_page": kept,
            "lines": (class_a_lines(entries, left_out, kept) if records is not None else
                      ["class (a) fill-ins: unknown, the generator's records are not this file's rows"])}


def fill_in_report(before_rows: list[dict[str, Any]], before_tables: dict, after_rows: list[dict[str, Any]],
                   after_tables: dict, records: list[dict[str, Any]] | None) -> dict[str, set[str]]:
    """'credentials filled in from a non-current source on the {role} lead'
    for every head lead with a class (a) fill-in that the base lead on that
    network type did not have: another APN or other filled-in values. Each
    scope names the sources of the filling rows. Report only."""
    items: dict[str, set[str]] = defaultdict(set)
    if records is None:
        return items
    after = [entry for entry in class_a_entries(after_rows, after_tables, records)]
    if not after:
        return items
    scopes = {entry["_scope"] for entry in after} & {phone.scope_of(row) for row in before_rows}
    before = {(entry["_scope"], entry["role"], name): entry["_signature"]
              for entry in lead_credentials(before_rows, before_tables, None, scopes=scopes)
              for name in entry["network_types"]}
    for entry in after:
        if any(before.get((entry["_scope"], entry["role"], name)) != entry["_signature"]
               for name in entry["network_types"]):
            items[f"credentials filled in from a non-current source on the {entry['role']} lead"].add(
                f"{entry['scope']} ({'+'.join(entry['fill_in_sources'])})")
    return items


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
    any current vendor backs, and the types current vendors back the APN for
    (for the report only)."""
    generator, records = generator_records(checkout)
    out: dict[phone.Scope, dict[str, dict[str, set]]] = defaultdict(dict)
    for record in records:
        current = {apn_type for apn_type, sources in (record.get("_current") or {}).items() if sources}
        if not current:
            continue
        row = phone.parse_lines([generator.apn_row_line(record)])[0]
        entry = out[phone.scope_of(row)].setdefault(str(row.get("apn", "")).casefold(),
                                                    {"credentials": set(), "proxies": set(), "types": set()})
        entry["credentials"].add((row.get("user") or "", row.get("password") or ""))
        entry["proxies"].add(row.get("proxy") or "")
        entry["types"].update(current)
    return out


def listed_codes(checkout: Path) -> set[tuple[str, str]]:
    """The network codes (MCC, MNC) of the generator's records of CHECKOUT that
    a current vendor backs or Apple's bundles give: networks a current
    Google, Samsung or Apple observation lists."""
    generator, records = generator_records(checkout)
    out: set[tuple[str, str]] = set()
    for record in records:
        if not (any((record.get("_current") or {}).values())
                or any(set(sources) & LISTING_SOURCES for sources in (record.get("_support") or {}).values())):
            continue
        if record.get("mcc") and record.get("mnc"):
            out.add((str(record["mcc"]), str(record["mnc"])))
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


def emergency_named(apn: Any) -> bool:
    """An APN named like an emergency APN: `sos`, `emergency`, any name
    containing `emergency`, or a name starting with `e911` (case-folded).
    The same rule as `carrier_config_types.emergency_named`, which the
    generator ranks by; the guard keeps its own copy so that it runs with
    only `android_phone_model.py` next to it, as the private publish tests
    copy it, and `test_phone_guard.py` checks that the two agree."""
    name = str(apn or "").casefold()
    return name == "sos" or "emergency" in name or name.startswith("e911")


def protocol_text(lead: tuple | None) -> str:
    return "none" if lead is None else f"{lead[0]} {lead[6]}/{lead[7]}"


def handles(profile: dict[str, Any], kind: str) -> bool:
    """ApnSetting.canHandleType (ApnSetting.java:1271-1287): enabled and
    carrying the type. An empty type is TYPE_ALL (`android_phone_model.
    type_set`), which has the ims bit and no emergency bit."""
    return bool(profile["carrier_enabled"]) and kind in profile["types"]


def handles_emergency(profile: dict[str, Any]) -> bool:
    return handles(profile, "emergency")


def ims_profiles(settings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The scope's profiles, plus ANDROID_DEFAULT_IMS when none of them can
    handle `ims` on any network type (DataProfileManager.java:343-355)."""
    if any(handles(p, "ims") for p in settings):
        return settings
    return settings + [ANDROID_DEFAULT_IMS]


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
        with_ims = ims_profiles(settings)
        out[scope] = {}
        for name, network_type in WATCH_TYPES.items():
            entry: dict[str, Any] = {}
            for kind in WATCH_APN_TYPES:
                lead = next((p for p in with_ims if kind in p["types"]
                             and phone.serves(p, network_type) and phone.cellular(p)), None)
                entry[kind] = phone.lead_key(lead)
                entry[f"{kind}_android_default"] = bool(lead and lead.get("android_default"))
                entry[f"{kind}_internet"] = bool(lead and not lead.get("android_default")
                                                 and "default" in lead["types"])
                entry[f"{kind}_srcs"] = tuple(lead["base_srcs"]) if lead and not lead.get("android_default") else ()
            for kind in REPORT_APN_CHANGE_TYPES:
                entry[kind] = phone.lead_key(next((p for p in settings if kind in p["types"]
                                                   and phone.serves(p, network_type) and phone.cellular(p)), None))
            entry["emergency"] = emergency_key(emergency_lead(emergency, network_type))
            out[scope][name] = entry
        out[scope]["_sets"] = stranded_sets(settings)
    return out


def typed_text(lead: tuple | None, android_default: bool) -> str:
    return f"Android default {protocol_text(lead)}" if android_default else protocol_text(lead)


def watch(before: dict, after: dict, before_typed: dict, after_typed: dict) -> list[dict[str, Any]]:
    """The IMS and emergency report items, never trips: per condition, scope
    and old and new value, the network types of WATCH_TYPES it holds on."""
    found: dict[tuple, list[str]] = defaultdict(list)
    for scope in set(before) & set(after):
        for name in WATCH_TYPES:
            for kind in WATCH_APN_TYPES:
                b, a = before_typed[scope][name], after_typed[scope][name]
                old, new = b[kind], a[kind]
                old_default, new_default = b.get(f"{kind}_android_default"), a.get(f"{kind}_android_default")
                old_text, new_text = typed_text(old, old_default), typed_text(new, new_default)
                if old and not new:
                    found[(f"{kind} lead lost", fmt(scope), old_text, "none")].append(name)
                elif not old and new and not new_default:
                    found[(f"{kind} lead gained", fmt(scope), "none", new_text)].append(name)
                elif old and not old_default and new_default:
                    found[(f"{kind} lead lost to Android's default", fmt(scope), old_text, new_text)].append(name)
                elif old and old_default and new and not new_default:
                    found[(f"{kind} lead gained over Android's default", fmt(scope), old_text,
                           new_text)].append(name)
                elif old and str(old[0]).casefold() != str(new[0]).casefold():
                    found[(f"{kind} lead APN changed", fmt(scope), old_text, new_text)].append(name)
                elif old and (old[6], old[7]) != (new[6], new[7]):
                    found[(f"{kind} lead protocol changed", fmt(scope), old_text, new_text)].append(name)
                if (new and a.get(f"{kind}_internet")
                        and (not old or old_default or not b.get(f"{kind}_internet")
                             or str(old[0]).casefold() != str(new[0]).casefold())):
                    found[(f"{kind.upper()} profile gained on an internet APN, displacing Android's DEFAULT "
                           f"{kind.upper()}" if (not old or old_default) else
                           f"{kind.upper()} profile moves onto an internet APN", fmt(scope), old_text,
                           new_text)].append(name)
            # Rule rounds 34 and 38: the xcap, dun and supl leads' APN
            # change, report only.
            for kind in REPORT_APN_CHANGE_TYPES:
                old, new = before_typed[scope][name][kind], after_typed[scope][name][kind]
                if old and new and str(old[0]).casefold() != str(new[0]).casefold():
                    found[(f"{kind} lead APN changed", fmt(scope), protocol_text(old),
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
            # Rule round 34: the attach lead's APN change, report only. A
            # lost attach lead is a trip.
            if b_attach and a_attach and str(b_attach[0]).casefold() != str(a_attach[0]).casefold():
                found[("attach lead APN changed", fmt(scope), protocol_text(b_attach),
                       protocol_text(a_attach))].append(name)
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
            change = f"{item['old']} -> {item['new']}" if item["old"] else item["new"]
            lines.append(f"  {item['scope']}: {change} ({','.join(item['types'])})")
        if len(mine) > WATCH_LIST_LIMIT:
            lines.append(f"  ... {len(mine) - WATCH_LIST_LIMIT} more (--report-json lists them all)")
    return lines


def fallback_changes(scope: phone.Scope, before: dict, after: dict,
                     typed: tuple[dict, dict] | None) -> list[tuple[str, str]]:
    """For an MVNO scope that leaves: the roles (internet, attach, MMS, IMS)
    whose APN its SIMs get from the network's plain rows in the head differs
    from the MVNO scope's own lead in the base, on WATCH_TYPES (rule decisions
    round 35, item B: 22 MVNO scopes fell back to host APNs and MMSCs)."""
    host = (scope[0], scope[1], "", "")
    if host not in after:
        return [("internet", "the network has no plain rows")]
    changes: dict[str, set[str]] = defaultdict(set)
    for name in WATCH_TYPES:
        if name not in before[scope] or name not in after[host]:
            continue
        b_inet, b_mms, b_attach = before[scope][name][:3]
        a_inet, a_mms, a_attach = after[host][name][:3]
        for role, old, new in (("internet", b_inet, a_inet), ("attach", b_attach, a_attach)):
            if old and (not new or str(old[0]).casefold() != str(new[0]).casefold()):
                changes[role].add(f"{lead_text(old)} -> {lead_text(new)}")
        if works(b_mms) and norm(b_mms) != norm(a_mms):
            changes["MMS"].add(f"{mms_text(b_mms)} -> {mms_text(a_mms)}")
        if typed is not None and scope in typed[0] and host in typed[1]:
            old, new = typed[0][scope][name]["ims"], typed[1][host][name]["ims"]
            if old and (not new or str(old[0]).casefold() != str(new[0]).casefold()):
                changes["IMS"].add(f"{lead_text(old)} -> {lead_text(new)}")
    return [(role, "; ".join(sorted(values))) for role, values in sorted(changes.items())]


def star_ims_leads(typed: dict, rows: list[dict[str, Any]],
                   records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The head's IMS leads on a `*`-typed row that no current vendor backs
    for `ims`, in a scope where a current vendor gives an `ims` row (rule
    decisions round 35, item C). The sanitizer writes a source's `*` as
    Android's TYPE_ALL list, so a `*`-typed row is a file row behind the
    lead's stored row whose types include every type of TYPE_ALL
    (`android_phone_model.WILDCARD_TYPES`). Empty without the head's records."""
    if records is None:
        return []
    vendor_ims = {phone.scope_of(row) for row, record in zip(rows, records)
                  if (record.get("_current") or {}).get("ims")}
    found: dict[tuple, list[str]] = defaultdict(list)
    for scope, per_type in typed.items():
        if scope not in vendor_ims:
            continue
        for name in WATCH_TYPES:
            srcs = [index for index in per_type[name].get("ims_srcs") or () if 0 <= index < len(records)]
            behind = [records[index] for index in srcs]
            if not behind or not any(phone.type_set(rows[index].get("type")) >= phone.WILDCARD_TYPES
                                     for index in srcs):
                continue
            if any((record.get("_current") or {}).get("ims") for record in behind):
                continue
            found[(fmt(scope), protocol_text(per_type[name]["ims"]))].append(name)
    return [{"condition": "ims lead on a *-typed row no current vendor backs for ims", "scope": s, "types": t,
             "old": "", "new": v} for (s, v), t in sorted(found.items())]


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


def trips(before: dict, after: dict, vendor: dict, base_vendor: dict | None = None) -> list[dict[str, Any]]:
    """The trips. VENDOR holds the head's vendor tuples; BASE_VENDOR, when
    given, the base's: MMS that leaves a tuple a current vendor gave in the
    base, for one no current vendor gives in the head, is mms_away too."""
    found: dict[tuple, list[str]] = defaultdict(list)
    for scope in set(before) & set(after):
        tuples = {norm(t) for t in vendor.get(scope, ())}
        old_tuples = tuples | {norm(t) for t in (base_vendor or {}).get(scope, ())}
        for name in HOLD_TYPES:
            b_inet, b_mms, b_attach = before[scope][name][:3]
            a_inet, a_mms, a_attach = after[scope][name][:3]
            if b_inet and not a_inet:
                found[("internet_lost", fmt(scope), lead_text(b_inet), "none")].append(name)
            if b_attach and not a_attach:
                found[("attach_lost", fmt(scope), lead_text(b_attach), "none")].append(name)
            if works(b_mms) and not works(a_mms):
                found[("mms_lost", fmt(scope), mms_text(b_mms), mms_text(a_mms))].append(name)
            elif (works(b_mms) and norm(b_mms) != norm(a_mms) and norm(b_mms) in old_tuples
                    and norm(a_mms) not in tuples):
                found[("mms_away", fmt(scope), mms_text(b_mms), mms_text(a_mms))].append(name)
    return [{"condition": c, "scope": s, "types": types, "old": o, "new": n}
            for (c, s, o, n), types in sorted(found.items())]


def trip_line(trip: dict[str, Any]) -> str:
    return "|".join((trip["condition"], trip["scope"], ",".join(trip["types"]), trip["old"], trip["new"]))


def digest(found: list[dict[str, Any]]) -> str:
    text = "".join(line + "\n" for line in sorted(trip_line(trip) for trip in found))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def report(before: dict, after: dict, tables: tuple, vendor: dict, rows: dict,
           extra: dict[str, set[str]] | None = None, codes: set[tuple[str, str]] | None = None,
           typed: tuple[dict, dict] | None = None) -> list[str]:
    items: dict[str, set[str]] = defaultdict(set)
    for key, scopes in (extra or {}).items():
        items[key].update(scopes)
    warnings: list[str] = []
    for scope in sorted(set(before) - set(after)):
        items["scopes gone, MVNO" if scope[2] else "scopes gone, network"].add(fmt(scope))
        if not scope[2] and codes is not None and (scope[0], scope[1]) in codes:
            items["scopes gone, network, while a current Google, Samsung or Apple observation lists the code"].add(
                fmt(scope))
        if scope[2]:
            for role, change in fallback_changes(scope, before, after, typed):
                items[f"MVNO scope gone, its SIMs' fallback changes the {role} APN"].add(
                    f"{fmt(scope)} ({change})")
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
                        and not ((vendor_apn or {}).get("types", set()) & ROLE_TYPES[role])):
                    items[f"{role} lead moves to an APN no current vendor gives for "
                          f"{' or '.join(sorted(ROLE_TYPES[role]))}"].add(s)
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
    base_group = parser.add_mutually_exclusive_group()
    base_group.add_argument("--base-generator", type=Path,
                            help="the base's checkout: MMS also trips off the base's vendor tuples")
    base_group.add_argument("--base-ref",
                            help="a revision of --generator's repository to read as the base's checkout")
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
        with tempfile.TemporaryDirectory(prefix="phone-guard-base-") as scratch:
            base_checkout = args.base_generator.resolve() if args.base_generator else (
                extract_checkout(args.generator.resolve(), args.base_ref, Path(scratch)).resolve()
                if args.base_ref else None)
            base_vendor = vendor_mms_tuples(base_checkout) if base_checkout else None
            codes = listed_codes(args.generator.resolve()) | (listed_codes(base_checkout) if base_checkout
                                                               else set())
        found = trips(before, after, vendor, base_vendor)
        code = digest(found) if found else None
        verdict = "pass" if not found else "accepted" if code in args.accept else "hold"
        records = aligned_records(args.generator.resolve(), after_rows)
        before_typed, after_typed = typed_leads(before_rows, before_tables), typed_leads(after_rows, after_tables)
        lines = report(before, after, (before_tables, after_tables), vendor,
                       vendor_rows(args.generator.resolve()),
                       fill_in_report(before_rows, before_tables, after_rows, after_tables, records),
                       codes, (before_typed, after_typed))
        if base_vendor is not None:
            lines.append("MMS test: also against the base's vendor tuples")
        if records is None:
            lines.append("credential sources: unknown, the generator's records of --generator are not "
                         "the head file's rows")
        watched = watch(before, after, before_typed, after_typed) + star_ims_leads(after_typed, after_rows, records)
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
