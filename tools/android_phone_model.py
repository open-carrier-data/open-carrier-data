#!/usr/bin/env python3
"""A model of what an Android phone makes of an `apns-conf.xml`, read from the
LineageOS 23.2 sources (rule decisions of 2026-10-06, round 6, change 21).

Every dry run of an APN ordering rule is measured with this model and
`tools/measure_android_phone.py`, never only by the first rows in the file.
The steps, in the order the phone runs them:

1. TelephonyProvider loads the file (`provider`). `getRow` turns each XML row
   into content values: an attribute the row does not write is not written,
   `network_type_bitmask` wins over `bearer_bitmask`. A row equal to a stored
   row on `CARRIERS_UNIQUE_FIELDS` (`TelephonyProvider.java:276-417`) is
   merged into it by `mergeFieldsAndUpdateDb`: the stored row keeps its place,
   the types unite, the bitmasks merge (0 means all), and every attribute the
   later row writes overwrites. `separateRowsNeeded` keeps a row apart for the
   networks of `persist_apns_for_plmn` (res/values/config.xml: 20404, 310004,
   310120, 311480) when the two rows differ only by `dun`.
2. The rows of a SIM's scope, in stored order (`scope_rows`; an MVNO scope
   reads only its own selector, a network scope only rows without one).
3. ApnSetting from each stored row (`apn_setting`). The auth type -1 becomes 0
   without a user and 3 with one (`ApnSetting.java:1054-1058`).
4. DataProfileManager's `dedupeDataProfiles` (`DataProfileManager.java:877-897`)
   as written (`profiles`): it reads `first` once, so every later row similar
   to it (`ApnSetting.similar`, `ApnSetting.java:1427-1458`) is merged with the
   original row and replaces the previous merge; when several rows are similar
   to one row the last one wins. `mergeDataProfiles` (960-1040) takes the
   later row's non-empty values and unites the types.
5. Per network type (`leads`): the internet profile (first `default` profile
   that serves the type), MMS (the internet profile when it serves `mms`, else
   the first usable `mms` profile; MmsService falls back to the MMSC of a
   stored `mms` row of the same APN name, `mms_of`), and the attach profile
   (first `ia`, else first `default`). A disabled row, a row of another APN
   set and a row without cellular infrastructure serve nothing.

Rows are dicts of XML attribute strings with `_i`, the row's index in the
file. Stored rows keep `_srcs`, the file rows merged into them.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import Any, Iterable

PERSIST_APNS_FOR_PLMN = frozenset({"20404", "310004", "310120", "311480"})
WILDCARD_TYPES = frozenset({"default", "hipri", "mms", "supl", "dun", "fota", "ims", "cbs"})
KNOWN_TYPES = frozenset({
    "default", "mms", "supl", "dun", "hipri", "fota", "ims", "cbs", "ia", "emergency",
    "mcx", "xcap", "enterprise", "vsim", "bip", "rcs", "oem_paid", "oem_private",
})
# CARRIERS_UNIQUE_FIELDS with the defaults TelephonyProvider stores.
UNIQUE_DEFAULTS = {
    "numeric": "", "mcc": "", "mnc": "", "apn": "", "proxy": "", "port": "", "mmsproxy": "",
    "mmsport": "", "mmsc": "", "carrier_enabled": "1", "bearer": "0", "mvno_type": "",
    "mvno_match_data": "", "profile_id": "0", "protocol": "IP", "roaming_protocol": "IP",
    "user_editable": "1", "owned_by": "1", "apn_set_id": "0", "carrier_id": "-1",
    "infrastructure_bitmask": "3", "esim_bootstrap_provisioning": "0",
}
STR_FIELDS = ("apn", "user", "server", "password", "proxy", "port", "mmsproxy", "mmsport", "mmsc",
              "protocol", "roaming_protocol")
INT_FIELDS = ("authtype", "bearer", "profile_id", "max_conns", "wait_time", "max_conns_time", "mtu",
              "mtu_v4", "mtu_v6", "apn_set_id", "carrier_id", "skip_464xlat")
BOOL_FIELDS = ("carrier_enabled", "modem_cognitive", "user_visible", "user_editable", "always_on",
               "esim_bootstrap_provisioning")
# ServiceState.rilRadioTechnologyToNetworkType
RIL_TO_NETWORK_TYPE = {1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 6: 7, 7: 5, 8: 6, 9: 8, 10: 9, 11: 10, 12: 12,
                       13: 14, 14: 13, 15: 15, 16: 16, 17: 17, 18: 18, 19: 19, 20: 20}
NETWORK_TYPE_TO_RIL: dict[int, int] = {}
for _ril, _network_type in RIL_TO_NETWORK_TYPE.items():
    NETWORK_TYPE_TO_RIL.setdefault(_network_type, _ril)
# TelephonyManager network types every dry run is measured on, and the wider set.
MAIN_NETWORK_TYPES = {"LTE": 13, "NR": 20, "HSPA": 10, "UMTS": 3, "EDGE": 2}
ALL_NETWORK_TYPES = {**MAIN_NETWORK_TYPES, "GPRS": 1, "HSPA+": 15, "IWLAN": 18, "eHRPD": 14,
                     "EVDO-A": 6, "1xRTT": 7}

ATTR_RE = re.compile(r'([a-z_0-9]+)="([^"]*)"')


def unescape(value: str) -> str:
    return (value.replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&#9;", "\t").replace("&#10;", "\n")
            .replace("&#13;", "\r").replace("&amp;", "&"))


def parse_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    """The `<apn .../>` rows of a generated apns-conf.xml (one row per line)."""
    rows: list[dict[str, Any]] = []
    for line in lines:
        if line.lstrip().startswith("<apn "):
            row: dict[str, Any] = {key: unescape(value) for key, value in ATTR_RE.findall(line)}
            row["_i"] = len(rows)
            row["_line"] = line.strip()
            rows.append(row)
    return rows


def parse_xml(path: Path | str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return parse_lines(handle)


def bits_from_string(text: str) -> int:
    out = 0
    for part in text.split("|"):
        try:
            number = int(part.strip())
        except ValueError:
            return 0
        if number == 0:
            return 0
        out |= 1 << (number - 1)
    return out


def bearer_to_network_types(bearer: int) -> int:
    if bearer == 0:
        return 0
    out = 0
    for ril in range(1, 21):
        if bearer & (1 << (ril - 1)):
            network_type = RIL_TO_NETWORK_TYPE.get(ril, 0)
            if network_type:
                out |= 1 << (network_type - 1)
    return out


def network_types_to_bearer(network_types: int) -> int:
    if network_types == 0:
        return 0
    out = 0
    for network_type in range(1, 21):
        if network_types & (1 << (network_type - 1)):
            ril = NETWORK_TYPE_TO_RIL.get(network_type)
            if ril:
                out |= 1 << (ril - 1)
    return out


def content_values(row: dict[str, Any]) -> dict[str, Any]:
    """TelephonyProvider.getRow: what one XML row writes. An attribute the row
    does not carry is not written, apart from the ones getRow always puts."""
    values: dict[str, Any] = {}
    mcc, mnc = row.get("mcc"), row.get("mnc")
    values["numeric"] = "" if mcc is None or mnc is None else mcc + mnc
    values["mcc"] = mcc or ""
    values["mnc"] = mnc or ""
    values["name"] = row.get("carrier")
    for field in STR_FIELDS:
        if field in row:
            values[field] = row[field]
    if "type" in row:
        values["type"] = re.sub(r"\s+", "", row["type"])
    for field in INT_FIELDS:
        if field in row:
            values[field] = int(row[field])
    for field in BOOL_FIELDS:
        if field in row:
            values[field] = 1 if row[field].lower() == "true" else 0
    infrastructure = 3
    if "infrastructure_bitmask" in row:
        infrastructure = 0
        for part in row["infrastructure_bitmask"].split("|"):
            infrastructure |= {"cellular": 1, "satellite": 2}.get(part.lower(), 0)
    values["infrastructure_bitmask"] = infrastructure
    network_types = (bits_from_string(row["network_type_bitmask"])
                     if "network_type_bitmask" in row else 0)
    values["lingering_network_type_bitmask"] = (
        bits_from_string(row["lingering_network_type_bitmask"])
        if "lingering_network_type_bitmask" in row else 0)
    if "network_type_bitmask" in row:
        bearer = network_types_to_bearer(network_types)
    else:
        bearer = bits_from_string(row["bearer_bitmask"]) if "bearer_bitmask" in row else 0
        network_types = bearer_to_network_types(bearer)
    values["network_type_bitmask"] = network_types
    values["bearer_bitmask"] = bearer
    if "mvno_type" in row and "mvno_match_data" in row:
        values["mvno_type"] = row["mvno_type"]
        values["mvno_match_data"] = row["mvno_match_data"]
    return values


def unique_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(field, default)) if row.get(field) is not None else default
                 for field, default in UNIQUE_DEFAULTS.items())


def _separate_rows_needed(table, old, new, old_types, new_types, persist) -> bool:
    """TelephonyProvider.separateRowsNeeded for persist_apns_for_plmn."""
    if new.get("numeric", "").lower() not in persist:
        return False
    if len(old_types) == len(new_types) + 1:
        with_dun, without, dun_in_old = list(old_types), list(new_types), True
    elif len(old_types) + 1 == len(new_types):
        with_dun, without, dun_in_old = list(new_types), list(old_types), False
    else:
        return False
    if "dun" not in with_dun or "dun" in without:
        return False
    without.append("dun")
    if not all(item in with_dun for item in without):
        return False
    if int(old.get("profile_id", 0) or 0) != 0:
        return False
    if dun_in_old:
        old["type"] = ",".join(item for item in with_dun if item.lower() != "dun")
        old.setdefault("_events", []).append(("persist_dun_dropped_new", new["_src"]))
        return True
    new["profile_id"] = 1
    # insertWithOnConflict(CONFLICT_REPLACE): a separate row with profile_id 1
    key = unique_key(new)
    for index, stored in enumerate(table):
        if unique_key(stored) == key:
            del table[index]
            break
    new["_events"] = [("persist_separate_row", None)]
    new["_srcs"] = [new["_src"]]
    table.append(new)
    return True


def provider(rows: list[dict[str, Any]], persist=PERSIST_APNS_FOR_PLMN) -> dict[str, list[dict[str, Any]]]:
    """Stored rows per numeric, in _id order. Each stored row keeps `_srcs`,
    the indices of the XML rows merged into it, in insertion order, and
    `_events` when separateRowsNeeded fired."""
    tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        values = content_values(row)
        values["_src"] = row["_i"]
        table = tables[values["numeric"]]
        key = unique_key(values)
        old = next((stored for stored in table if unique_key(stored) == key), None)
        if old is None:
            values["_srcs"] = [row["_i"]]
            table.append(values)
            continue
        new = dict(values)
        merged: dict[str, Any] = {}
        if "type" in new:
            old_type, new_type = old.get("type", ""), new["type"]
            if old_type.lower() != new_type.lower():
                if old_type == "" or new_type == "":
                    new["type"] = ""
                else:
                    old_types = old_type.lower().split(",")
                    new_types = new_type.lower().split(",")
                    if _separate_rows_needed(table, old, new, old_types, new_types, persist):
                        continue
                    union = list(old_types)
                    for item in new_types:
                        if item.strip() not in union:
                            union.append(item)
                    new["type"] = ",".join(union)
            merged["type"] = new["type"]
        for field in ("bearer_bitmask", "network_type_bitmask"):
            if field in new:
                old_bits, new_bits = old.get(field, 0), new[field]
                if old_bits != new_bits:
                    new[field] = 0 if (old_bits == 0 or new_bits == 0) else (old_bits | new_bits)
                merged[field] = new[field]
        if "network_type_bitmask" in merged:
            merged["bearer_bitmask"] = network_types_to_bearer(merged["network_type_bitmask"])
        merged.update({key2: value for key2, value in new.items() if not key2.startswith("_")})
        old.update(merged)
        old["_srcs"].append(row["_i"])
    return tables


def stored_count(tables: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(table) for table in tables.values())


def persist_events(tables: dict[str, list[dict[str, Any]]]) -> list[tuple[str, Any]]:
    """(numeric, event) for every row separateRowsNeeded kept apart or cut."""
    return [(numeric, event) for numeric, table in tables.items()
            for stored in table for event in stored.get("_events", [])]


Scope = tuple[str, str, str, str]


def scope_of(row: dict[str, Any]) -> Scope:
    return (row.get("mcc", ""), row.get("mnc", ""), str(row.get("mvno_type", "")).casefold(),
            str(row.get("mvno_match_data", "")).casefold())


def scope_rows(tables: dict[str, list[dict[str, Any]]], scope: Scope) -> list[dict[str, Any]]:
    mcc, mnc, mvno_type, match = scope
    out = []
    for stored in tables.get(mcc + mnc, []):
        if mvno_type:
            if (str(stored.get("mvno_type", "")).casefold() == mvno_type
                    and str(stored.get("mvno_match_data", "")).casefold() == match):
                out.append(stored)
        elif not stored.get("mvno_type"):
            out.append(stored)
    return out


def port_from_string(text: Any) -> int:
    if text is None or text == "":
        return -1
    try:
        return int(text)
    except ValueError:
        return -1


def type_set(types: Any) -> frozenset[str]:
    if types is None or types == "":
        return KNOWN_TYPES
    out: set[str] = set()
    for item in str(types).split(","):
        item = item.lower()
        if item == "*":
            out |= WILDCARD_TYPES
        elif item in KNOWN_TYPES:
            out.add(item)
    return frozenset(out)


def resolved_auth_type(authtype: Any, user: Any) -> int:
    """ApnSetting's constructor (ApnSetting.java:1054-1058): -1 becomes 0
    without a user and 3 (PAP or CHAP) with one."""
    value = int(authtype) if authtype not in (None, "") else -1
    return value if value != -1 else (3 if (user or "") else 0)


def apn_setting(stored: dict[str, Any]) -> dict[str, Any]:
    """ApnSetting.makeApnSetting from a stored row."""
    network_types = (stored.get("network_type_bitmask", 0)
                     or bearer_to_network_types(stored.get("bearer_bitmask", 0) or 0))
    mtu_v4 = stored.get("mtu_v4", 0) or 0
    if mtu_v4 == 0:
        mtu_v4 = stored.get("mtu", 0) or 0
    return {
        "srcs": list(stored["_srcs"]),
        "base_srcs": list(stored["_srcs"]),
        "name": stored.get("name"),
        "apn": stored.get("apn", ""),
        "proxy": stored.get("proxy") or "",
        "port": port_from_string(stored.get("port")),
        "mmsc": stored.get("mmsc") or None,
        "mmsproxy": stored.get("mmsproxy") or "",
        "mmsport": port_from_string(stored.get("mmsport")),
        "user": stored.get("user") or "",
        "password": stored.get("password") or "",
        "authtype": resolved_auth_type(stored.get("authtype", -1), stored.get("user")),
        "types": type_set(stored.get("type")),
        "protocol": (stored.get("protocol") or "IP").upper(),
        "roaming_protocol": (stored.get("roaming_protocol") or "IP").upper(),
        "carrier_enabled": stored.get("carrier_enabled", 1),
        "nt": network_types,
        "lingering": stored.get("lingering_network_type_bitmask", 0),
        "profile_id": stored.get("profile_id", 0),
        "persistent": stored.get("modem_cognitive", 0),
        "apn_set_id": stored.get("apn_set_id", 0),
        "carrier_id": stored.get("carrier_id", -1),
        "skip464": stored.get("skip_464xlat", -1),
        "always_on": stored.get("always_on", 0),
        "infra": stored.get("infrastructure_bitmask", 3),
        "esim": stored.get("esim_bootstrap_provisioning", 0),
        "mtu4": mtu_v4,
        "mtu6": stored.get("mtu_v6", 0) or 0,
        "merged_from": [],
    }


def _same_or_empty(a: str, b: str) -> bool:
    return a == "" or b == "" or a == b


def _same_or_unset(a: int, b: int) -> bool:
    return a == -1 or b == -1 or a == b


def similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """ApnSetting.similar (ApnSetting.java:1427-1458), auth types resolved."""
    return ("dun" not in a["types"] and "dun" not in b["types"]
            and a["apn"] == b["apn"]
            and _same_or_empty(a["proxy"], b["proxy"]) and _same_or_unset(a["port"], b["port"])
            and (a["mmsc"] is None or b["mmsc"] is None or a["mmsc"] == b["mmsc"])
            and _same_or_empty(a["mmsproxy"], b["mmsproxy"])
            and _same_or_unset(a["mmsport"], b["mmsport"])
            and _same_or_empty(a["user"], b["user"])
            and _same_or_empty(a["password"], b["password"])
            and a["authtype"] == b["authtype"]
            and not (a["types"] & b["types"])
            and a["protocol"] == b["protocol"] and a["roaming_protocol"] == b["roaming_protocol"]
            and (a["mtu4"] <= 0 or b["mtu4"] <= 0 or a["mtu4"] == b["mtu4"])
            and (a["mtu6"] <= 0 or b["mtu6"] <= 0 or a["mtu6"] == b["mtu6"])
            and a["carrier_enabled"] == b["carrier_enabled"] and a["nt"] == b["nt"]
            and a["lingering"] == b["lingering"] and a["profile_id"] == b["profile_id"]
            and a["persistent"] == b["persistent"] and a["apn_set_id"] == b["apn_set_id"]
            and a["carrier_id"] == b["carrier_id"] and a["skip464"] == b["skip464"]
            and a["always_on"] == b["always_on"] and a["infra"] == b["infra"]
            and a["esim"] == b["esim"])


def merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """DataProfileManager.mergeDataProfiles: b's non-empty values win."""
    merged = dict(a)
    if "default" in b["types"] and "default" not in a["types"]:
        merged["name"] = b["name"]
    merged["proxy"] = a["proxy"] if b["proxy"] == "" else b["proxy"]
    merged["port"] = a["port"] if b["port"] == -1 else b["port"]
    merged["mmsc"] = a["mmsc"] if b["mmsc"] is None else b["mmsc"]
    merged["mmsproxy"] = a["mmsproxy"] if b["mmsproxy"] == "" else b["mmsproxy"]
    merged["mmsport"] = a["mmsport"] if b["mmsport"] == -1 else b["mmsport"]
    merged["user"] = a["user"] if b["user"] == "" else b["user"]
    merged["password"] = a["password"] if b["password"] == "" else b["password"]
    merged["authtype"] = b["authtype"]
    merged["types"] = a["types"] | b["types"]
    merged["mtu4"] = a["mtu4"] if b["mtu4"] <= 0 else b["mtu4"]
    merged["mtu6"] = a["mtu6"] if b["mtu6"] <= 0 else b["mtu6"]
    merged["srcs"] = a["srcs"] + b["srcs"]
    merged["merged_from"] = list(a.get("merged_from", [])) + [("first", a["srcs"]), ("second", b["srcs"])]
    return merged


def profiles(stored: list[dict[str, Any]], dedupe: bool = True,
             as_written: bool = True) -> list[dict[str, Any]]:
    """The data profiles of a scope's stored rows. With `as_written` the
    dedupe loop compares every later row with `first` as it was read, as
    DataProfileManager.java:880 does; without it, with the running merge."""
    settings = [apn_setting(row) for row in stored]
    if not dedupe:
        return settings
    i = 0
    while i < len(settings) - 1:
        first = settings[i]
        j = i + 1
        while j < len(settings):
            second = settings[j]
            if similar(first, second):
                settings[i] = merge(first, second)
                del settings[j]
                if not as_written:
                    first = settings[i]
            else:
                j += 1
        i += 1
    return settings


def serves(profile: dict[str, Any], network_type: int) -> bool:
    return profile["nt"] == 0 or bool(profile["nt"] & (1 << (network_type - 1)))


def cellular(profile: dict[str, Any]) -> bool:
    """Usable for a cellular request: cellular infrastructure, enabled
    (ApnSetting.canHandleType is false when disabled), APN set 0 or -1."""
    return (bool(profile["infra"] & 1) and bool(profile["carrier_enabled"])
            and profile["apn_set_id"] in (0, -1))


def leads(settings: list[dict[str, Any]], network_type: int):
    """(internet, MMS, attach) profiles on one network type."""
    internet = next((p for p in settings
                     if "default" in p["types"] and serves(p, network_type) and cellular(p)), None)
    if internet is not None and "mms" in internet["types"]:
        mms = internet
    else:
        mms = next((p for p in settings
                    if "mms" in p["types"] and serves(p, network_type) and cellular(p)), None)
    attach = next((p for p in settings if "ia" in p["types"] and cellular(p)), None)
    if attach is None:
        attach = next((p for p in settings if "default" in p["types"] and cellular(p)), None)
    return internet, mms, attach


def mms_tuple(profile: dict[str, Any] | None):
    if profile is None:
        return None
    return (profile["apn"], profile["mmsc"], profile["mmsproxy"], profile["mmsport"])


def mms_of(profile: dict[str, Any] | None, stored: list[dict[str, Any]]):
    """Where MMS goes: (APN, MMSC, MMS proxy, MMS port). Without an MMSC on
    the profile, MmsService loads the APN by name and takes a stored `mms`
    row's MMSC."""
    if profile is None:
        return None
    if profile["mmsc"]:
        return mms_tuple(profile)
    for row in stored:
        if row.get("apn") == profile["apn"] and "mms" in type_set(row.get("type")) and row.get("mmsc"):
            return (profile["apn"], row["mmsc"], row.get("mmsproxy") or "",
                    port_from_string(row.get("mmsport")))
    return (profile["apn"], None, "", -1)


def lead_key(profile: dict[str, Any] | None):
    """What a lead sends: APN, proxy, port, username, password, auth type,
    protocols and network types."""
    if profile is None:
        return None
    return (profile["apn"], profile["proxy"], profile["port"], profile["user"], profile["password"],
            profile["authtype"], profile["protocol"], profile["roaming_protocol"], profile["nt"])


def phone_state(rows: list[dict[str, Any]], network_types: dict[str, int] = MAIN_NETWORK_TYPES,
                as_written: bool = True, persist=PERSIST_APNS_FOR_PLMN):
    """Per scope and network type: (internet lead, MMS tuple, attach lead,
    the internet lead's MMS fields, MMS lead). Returns (state, tables)."""
    tables = provider(rows, persist)
    state: dict[Scope, dict[str, tuple]] = {}
    for scope in {scope_of(row) for row in rows}:
        stored = scope_rows(tables, scope)
        settings = profiles(stored, True, as_written)
        per_type = {}
        for name, network_type in network_types.items():
            internet, mms, attach = leads(settings, network_type)
            per_type[name] = (
                lead_key(internet),
                mms_of(mms, stored),
                lead_key(attach),
                None if internet is None else (internet["mmsc"], internet["mmsproxy"], internet["mmsport"]),
                lead_key(mms),
            )
        state[scope] = per_type
    return state, tables


def absorbed_rows(rows: list[dict[str, Any]], persist=PERSIST_APNS_FOR_PLMN) -> set[int]:
    """File rows that stand as no profile of their own on this file's phone:
    rows of a stored row merged into an earlier stored row's profile, and rows
    of a stored row a later similar row replaced (last-row-wins)."""
    tables = provider(rows, persist)
    out: set[int] = set()
    for scope in {scope_of(row) for row in rows}:
        stored = scope_rows(tables, scope)
        settings = profiles(stored, True)
        present: set[int] = set()
        for profile in settings:
            present.update(profile["srcs"])
            out.update(i for i in profile["srcs"] if i not in profile["base_srcs"])
        for row in stored:
            out.update(i for i in row["_srcs"] if i not in present)
    return out
