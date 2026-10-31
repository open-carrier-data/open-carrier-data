#!/usr/bin/env python3
"""Resolve all public carrier profiles matching a SIM/network identity.

With --explain it also says why: the profile stack, the value each profile
gives for every capability, CarrierConfig key and add-on with the sources
behind it from the evidence index, and the APN rows Android 16 gives this SIM
in file order with the reasons each row sits where it does, and for its
internet, attach and MMS leads the row and the sources behind every username,
password, auth type and MTU they carry (rule decisions round 32, D8).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


MATCH_DIMENSIONS = (
    "gid1_prefixes",
    "gid2_prefixes",
    "iccid_prefixes",
    "imsi_prefix_patterns",
    "spn",
    "android_carrier_ids",
)


def imsi_pattern_matches(pattern: str, imsi: str) -> bool:
    if len(imsi) < len(pattern):
        return False
    return all(
        expected.lower() == "x" or expected == actual
        for expected, actual in zip(pattern, imsi)
    )


def any_prefix_matches(prefixes: list[Any], value: str) -> bool:
    normalized = value.casefold()
    return any(
        isinstance(prefix, str) and normalized.startswith(prefix.casefold())
        for prefix in prefixes
    )


def sim_carrier_ids(identity: dict[str, Any]) -> list[int]:
    """The SIM's Android carrier ID and specific carrier ID, where known (-1 is none)."""
    return [
        value
        for value in (identity.get("android_carrier_id"), identity.get("android_specific_carrier_id"))
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    ]


def profile_matches(match: dict[str, Any], identity: dict[str, Any]) -> bool:
    if identity.get("mccmnc") not in match.get("mccmnc", []):
        return False

    for key, identity_key in (
        ("gid1_prefixes", "gid1"),
        ("gid2_prefixes", "gid2"),
        ("iccid_prefixes", "iccid"),
    ):
        expected = match.get(key, [])
        if expected and (
            not isinstance(identity.get(identity_key), str)
            or not any_prefix_matches(expected, identity[identity_key])
        ):
            return False

    expected_spns = match.get("spn", [])
    if expected_spns and (
        not isinstance(identity.get("spn"), str)
        or identity["spn"].casefold()
        not in {str(value).casefold() for value in expected_spns}
    ):
        return False

    expected_imsis = match.get("imsi_prefix_patterns", [])
    if expected_imsis and (
        not isinstance(identity.get("imsi"), str)
        or not any(
            isinstance(pattern, str)
            and imsi_pattern_matches(pattern, identity["imsi"])
            for pattern in expected_imsis
        )
    ):
        return False

    expected_carrier_ids = match.get("android_carrier_ids", [])
    if expected_carrier_ids and not any(value in expected_carrier_ids for value in sim_carrier_ids(identity)):
        return False
    return True


def specificity(match: dict[str, Any]) -> int:
    return sum(bool(match.get(key)) for key in MATCH_DIMENSIONS)


# ---------------------------------------------------------------- Android's order (rule round 45, item 3)
#
# A SIM's profiles sorted generic to specific by, in this order:
#   1. Android's weight: CarrierResolver.CarrierMatchingRule's score of the
#      fields the profile pins, MCC/MNC 256, IMSI prefix 128, ICCID prefix 64,
#      GID1 32, GID2 16, PLMN 8, access rule 4, SPN 2, APN 1. A carrier-ID
#      selector stays a match condition; it adds the fields of Android's rules
#      behind the ID on the SIM's network (the lowest such weight when the ID
#      has several rules there, or MCC/MNC alone when it has none), and at
#      equal weight a profile with a carrier-ID selector ranks above a raw one.
#   2. Longer prefix or more fixed digits, the selector types in weight order:
#      IMSI (digits other than x), ICCID, GID1, GID2, each the shortest of the
#      profile's values.
#   3. An OCD profile above a fill-only one.
#   4. Fewer list values.
#   5. Fewer network codes.
#   6. The profile ID in byte order; the conflict checker
#      (tools/ocd_dataset.py) makes sure it never decides between profiles
#      whose served values differ.
# Mismatching any selector rejects the profile, as before.

ORDER_STEPS = ("weight", "carrier_id", "prefix", "ocd_before_fill_only", "fewer_values", "fewer_networks", "profile_id")
MCCMNC_WEIGHT = 256
SELECTOR_WEIGHTS = {
    "imsi_prefix_patterns": 128,
    "iccid_prefixes": 64,
    "gid1_prefixes": 32,
    "gid2_prefixes": 16,
    "spn": 2,
}
# CarrierIdProvider's columns and CarrierResolver's score for each.
RULE_WEIGHTS = {
    "mccmnc": 256,
    "imsi_prefix_xpattern": 128,
    "iccid_prefix": 64,
    "gid1": 32,
    "gid2": 16,
    "plmn": 8,
    "privilege_access_rule": 4,
    "spn": 2,
    "apn": 1,
}
PREFIX_DIMENSIONS = ("imsi_prefix_patterns", "iccid_prefixes", "gid1_prefixes", "gid2_prefixes")
CARRIER_ID_TABLE = Path(__file__).resolve().parent / "aosp" / "carrier-id-table.json"

CarrierIdTable = dict[tuple[int, str], list[int]]


def rule_weight(row: dict[str, Any]) -> int:
    """CarrierResolver's score of one rule: the sum of the weights of the fields it has."""
    return sum(weight for column, weight in RULE_WEIGHTS.items() if row.get(column) is not None)


def load_carrier_id_table(path: Path = CARRIER_ID_TABLE) -> CarrierIdTable:
    """(carrier ID, MCC+MNC) to the weights of Android's rules for that ID there."""
    document = json.loads(path.read_text(encoding="utf-8"))
    table: CarrierIdTable = {}
    for row in document["rows"]:
        if row.get("mccmnc") is None:
            continue
        table.setdefault((int(row["carrier_id"]), str(row["mccmnc"])), []).append(rule_weight(row))
    return table


def raw_weight(match: dict[str, Any]) -> int:
    return MCCMNC_WEIGHT + sum(weight for dimension, weight in SELECTOR_WEIGHTS.items() if match.get(dimension))


def android_weight(
    match: dict[str, Any],
    mccmnc: str,
    table: CarrierIdTable | None,
    fallbacks: list[tuple[int, str]] | None = None,
) -> int:
    """Step 1: Android's weight of the profile on network MCCMNC (no dash).
    A carrier ID without a rule on that network counts at the MCC/MNC-only
    weight, and is noted in FALLBACKS."""
    raw = raw_weight(match)
    carrier_ids = match.get("android_carrier_ids") or []
    if not carrier_ids:
        return raw
    weight: int | None = None
    for carrier_id in carrier_ids:
        rules = (table or {}).get((int(carrier_id), mccmnc))
        if not rules:
            if fallbacks is not None:
                fallbacks.append((int(carrier_id), mccmnc))
            rules = [MCCMNC_WEIGHT]
        for rule in rules:
            combined = raw | rule
            weight = combined if weight is None else min(weight, combined)
    return weight if weight is not None else raw


def fixed_length(dimension: str, value: str) -> int:
    """Step 2's measure of one selector value: the digits other than x for
    an IMSI pattern, the length for a prefix."""
    if dimension == "imsi_prefix_patterns":
        return sum(1 for char in value if char not in "xX")
    return len(value)


def list_value_count(match: dict[str, Any]) -> int:
    return sum(len(match.get(dimension) or []) for dimension in MATCH_DIMENSIONS)


def order_key(
    match: dict[str, Any],
    mccmnc: str,
    kind: str,
    profile_id: str,
    table: CarrierIdTable | None,
    fallbacks: list[tuple[int, str]] | None = None,
) -> tuple[Any, ...]:
    """The sort key of one profile on network MCCMNC, generic to specific:
    one element per step of ORDER_STEPS."""
    prefix = tuple(
        min(fixed_length(dimension, str(value)) for value in match[dimension]) if match.get(dimension) else 0
        for dimension in PREFIX_DIMENSIONS
    )
    return (
        android_weight(match, mccmnc, table, fallbacks),
        1 if match.get("android_carrier_ids") else 0,
        prefix,
        0 if kind == "fill_only" else 1,
        -list_value_count(match),
        -len(match.get("mccmnc") or []),
        profile_id.encode("utf-8"),
    )


def deciding_step(lower: tuple[Any, ...], upper: tuple[Any, ...]) -> str | None:
    """The step of ORDER_STEPS that orders two keys; None when they are equal."""
    for step, (a, b) in zip(ORDER_STEPS, zip(lower, upper)):
        if a != b:
            return step
    return None


_TABLE_CACHE: dict[Path, CarrierIdTable] = {}


def default_table() -> CarrierIdTable:
    if CARRIER_ID_TABLE not in _TABLE_CACHE:
        _TABLE_CACHE[CARRIER_ID_TABLE] = load_carrier_id_table(CARRIER_ID_TABLE)
    return _TABLE_CACHE[CARRIER_ID_TABLE]


def android_key(profile: dict[str, Any], mccmnc: str, table: CarrierIdTable | None = None) -> tuple[Any, ...]:
    """order_key of a lookup.json profile (an OCD profile unless it says otherwise)."""
    return order_key(
        profile["match"],
        mccmnc,
        str(profile.get("kind", "ocd")),
        str(profile.get("profile_id", "")),
        default_table() if table is None else table,
    )


ORDERS = ("count", "android")


def resolve(
    lookup: dict[str, Any],
    identity: dict[str, Any],
    order: str = "android",
    table: CarrierIdTable | None = None,
) -> list[dict[str, Any]]:
    """The profiles matching IDENTITY, generic to specific. ORDER "android"
    is lookup.json's documented order since schema_version 2 (rule round 45,
    above), which OcdCarrierSettings, the OCD Check app and the golden
    vectors use; "count" is the order before it (the number of selectors
    used, then the profile ID), for comparison."""
    if order not in ORDERS:
        raise ValueError(f"unknown order {order}")
    profiles = lookup.get("profiles", [])
    if not isinstance(profiles, list):
        raise ValueError("lookup.profiles must be a list")
    matches = [
        profile
        for profile in profiles
        if isinstance(profile, dict)
        and isinstance(profile.get("match"), dict)
        and profile_matches(profile["match"], identity)
    ]
    if order == "android":
        mccmnc = str(identity.get("mccmnc"))
        return sorted(matches, key=lambda profile: android_key(profile, mccmnc, table))
    return sorted(
        matches,
        key=lambda profile: (
            specificity(profile["match"]),
            str(profile.get("profile_id", "")),
        ),
    )


def serving_reason(stack: list[dict[str, Any]], mccmnc: str, table: CarrierIdTable | None = None) -> str:
    """Why the last profile of an Android-ordered stack serves: `default`
    without a profile, `only` with one, otherwise the step that put it above
    the one below it."""
    if not stack:
        return "default"
    if len(stack) == 1:
        return "only"
    step = deciding_step(android_key(stack[-2], mccmnc, table), android_key(stack[-1], mccmnc, table))
    return step or "profile_id"


def mvno_row_matches(row: dict[str, Any], identity: dict[str, Any]) -> bool:
    """Whether a row's MVNO selector matches the SIM the way TelephonyProvider
    compares them: SPN ignoring case, GID1 and ICCID as prefixes, IMSI as a
    pattern with x wildcards."""
    kind = str(row.get("mvno_type", ""))
    data = str(row.get("mvno_match_data", ""))
    if kind == "spn":
        return isinstance(identity.get("spn"), str) and identity["spn"].casefold() == data.casefold()
    if kind == "gid":
        return isinstance(identity.get("gid1"), str) and any_prefix_matches([data], identity["gid1"])
    if kind == "imsi":
        return isinstance(identity.get("imsi"), str) and imsi_pattern_matches(data, identity["imsi"])
    if kind == "iccid":
        return isinstance(identity.get("iccid"), str) and identity["iccid"].startswith(data)
    return False


def emergency_basis(generator: Any, row: dict[str, Any]) -> str | None:
    """Why a written row keeps "emergency" (round 21), or None."""
    if not generator.serves_emergency(row):
        return None
    if row.get("_current", {}).get("emergency"):
        return "current_vendor"
    if row.get("_support", {}).get("emergency", frozenset()) & generator.EMERGENCY_STATING_LIST_SOURCES:
        return "lineageos"
    return "android_default"


def explain(
    lookup: dict[str, Any],
    identity: dict[str, Any],
    root: Path,
    evidence_index_path: Path,
    order: str = "android",
) -> dict[str, Any]:
    """Why a SIM gets what it gets. root is the repository the lookup's paths
    are relative to; ORDER as for resolve."""
    import generate_android_outputs as generator

    stack = resolve(lookup, identity, order)
    evidence_index = json.loads(evidence_index_path.read_text(encoding="utf-8"))
    evidence = {item["profile_id"]: item for item in evidence_index.get("profiles", [])}
    files = {
        item["profile_id"]: json.loads((root / item["path"]).read_text(encoding="utf-8"))
        for item in stack
    }

    def sources_of(profile_id: str, section: str, key: str) -> list[str]:
        record = evidence.get(profile_id, {})
        for fact in record.get("fact_sources", []):
            if fact["section"] == section and fact["key"] == key:
                return list(fact["sources"])
        return list(record.get("sources", []))

    def gates_of(profile_id: str, section: str, key: str) -> list[str]:
        return sorted(
            gate["key"]
            for gate in evidence.get(profile_id, {}).get("quality_gates", [])
            if gate["section"] == section and gate["key"].partition(":")[2] == key
        )

    profiles = [
        {
            "profile_id": item["profile_id"],
            "display_name": item["display_name"],
            "specificity": specificity(item["match"]),
            **({"weight": android_weight(item["match"], str(identity.get("mccmnc")), default_table())} if order == "android" else {}),
            "match": item["match"],
            "sources": evidence.get(item["profile_id"], {}).get("sources", []),
            **{
                key: item[key]
                for key in ("newest_entry", "checks_through", "stale_after")
                if key in item
            },
        }
        for item in stack
    ]

    capabilities: dict[str, Any] = {}
    for key in sorted({key for item in stack for key in item.get("capabilities", {})}):
        by_profile = []
        for item in stack:
            value = item.get("capabilities", {}).get(key, "unknown")
            entry: dict[str, Any] = {"profile_id": item["profile_id"], "value": value}
            entry.update(evidence.get(item["profile_id"], {}).get("capability_sources", {}).get(key, {}))
            gates = gates_of(item["profile_id"], "capabilities", key)
            if gates:
                entry["gates"] = gates
            by_profile.append(entry)
        if any(entry["value"] != "unknown" or len(entry) > 2 for entry in by_profile):
            # docs/consume.md: report the most specific profile's value.
            capabilities[key] = {
                "answer": stack[-1].get("capabilities", {}).get(key, "unknown"),
                "answer_from": stack[-1]["profile_id"],
                "by_profile": by_profile,
            }

    def overlay(section: str, values_of: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in stack:
            for key, value in sorted(values_of(files[item["profile_id"]]).items()):
                entry = result.setdefault(key, {"by_profile": []})
                entry["by_profile"].append(
                    {
                        "profile_id": item["profile_id"],
                        "value": value,
                        "sources": sources_of(item["profile_id"], section, key),
                    }
                )
                # Overlay generic to specific: the most specific value wins.
                entry["applied"] = value
        return dict(sorted(result.items()))

    carrier_config = overlay(
        "android_carrier_config", lambda profile: profile.get("android_carrier_config") or {}
    )
    addons = overlay(
        "addons",
        lambda profile: {
            f"{namespace}.{key}": value
            for namespace, values in (profile.get("addons") or {}).items()
            for key, value in values.items()
        },
    )

    # The APN rows: every profile of this network code, ranked exactly as
    # generated/android/apns-conf.xml ranks them, then the rows Android 16
    # gives this SIM: the rows of its MVNO selector when any match, otherwise
    # the plain rows of the network.
    mccmnc = str(identity.get("mccmnc"))
    network_profiles = [
        json.loads((root / item["path"]).read_text(encoding="utf-8"))
        for item in lookup.get("profiles", [])
        if mccmnc in item.get("match", {}).get("mccmnc", [])
    ]
    generated_rows = generator.apn_xml_rows(
        network_profiles, generator.load_apn_evidence(evidence_index_path)
    )
    rows = generated_rows.records
    network_rows = [row for row in rows if row.get("mcc", "") + row.get("mnc", "") == mccmnc]
    mvno_rows = [row for row in network_rows if row.get("mvno_type") and mvno_row_matches(row, identity)]
    chosen = mvno_rows or [row for row in network_rows if not row.get("mvno_type")]
    scopes: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in network_rows:
        scopes.setdefault(generator.apn_scope_key(row), []).append(row)
    ranks: dict[int, Any] = {}
    for scope_rows in scopes.values():
        for row, rank in zip(scope_rows, generator.scope_row_ranks(scope_rows)):
            ranks[id(row)] = rank
    chosen_scopes = {generator.apn_scope_key(row) for row in chosen}
    apn_rows = []
    for position, row in enumerate(chosen, start=1):
        rank = ranks[id(row)]
        apn_rows.append(
            {
                "position": position,
                "row": generator.written_attributes(row),
                "lead_type": rank.lead_type,
                "reasons": {
                    "real_apn": not rank.placeholder,
                    # The APN is named like an emergency APN and the row leads
                    # with another type, so it ranks after the type's other
                    # real APNs (round 21).
                    "emergency_named_ranks_last": rank.emergency_named,
                    "value_from_current_vendor": bool(rank.value_current),
                    # Google gives the value only from its shared file, and no
                    # maintained per-carrier source confirms it.
                    "shared_file_unconfirmed": bool(rank.value_shared - rank.value_current),
                    # An internet row without an HTTP proxy, which comes
                    # before the scope's proxied internet rows.
                    "proxy_free_first": rank.lead_type == "default" and not rank.proxied,
                    "row_from_current_vendor": bool(rank.row_current),
                    "ia_left_out": bool(row.get("_ia_left_out")),
                    # Android stores this row as one with a better-ranked row
                    # written after it, whose values win: a group's first row
                    # in the file is not what the phone uses.
                    "stored_with_best_row": bool(row.get("_stored_with_best_row")),
                    # The first internet row lost "mms": no current vendor
                    # backs it for MMS and current vendors' MMS rows serve
                    # every mobile network type it serves.
                    "mms_left_out": bool(row.get("_mms_left_out")),
                    # A row Android stores with the first internet row lost
                    # "mms": no current vendor backs any row of that stored
                    # row for MMS and current vendors' MMS rows serve every
                    # mobile network type it serves (round 33).
                    "mms_left_out_stored_with_internet": bool(row.get("_mms_left_out_stored_with_internet")),
                    # A stored row that leads internet on some 3GPP network
                    # type, not the first internet row's, lost "mms": no
                    # current vendor backs it for MMS, the vendor MMS rows
                    # serve every type it serves, and on every type it
                    # carried MMS a vendor MMS row takes it (rule round 36,
                    # change 18 step 2d).
                    "mms_left_out_type_internet_lead": bool(row.get("_mms_left_out_type_internet_lead")),
                    # Types (ims, xcap) a row Android stores with the first
                    # internet row lost: no current vendor backs any row of
                    # that stored row for them (rule round 34, change 18
                    # step 2c).
                    "types_left_out_stored_with_internet": list(row.get("_types_left_out_stored_with_internet", [])),
                    # A current vendor's MMS row moved ahead of the first row
                    # that served "mms", so MMS goes to it.
                    "vendor_mms_ahead": bool(row.get("_vendor_mms_ahead")),
                    # A current vendor's attach row moved, with its stored
                    # group, ahead of a first internet row whose stored group
                    # serves no 3GPP type and served "ia" only through rows
                    # no current vendor backs for it (rule round 34, step 4b).
                    "vendor_attach_ahead": bool(row.get("_vendor_attach_ahead")),
                    # The first internet row kept "mms" because no current
                    # vendor's MMS row serves some mobile network type it serves.
                    "mms_kept_no_vendor_coverage": bool(row.get("_mms_kept_no_vendor_coverage")),
                    "value_families": sorted(generator.source_families(rank.value_sources)),
                    "value_from_primary_source": bool(rank.value_sources & generator.PRIMARY_APN_SOURCES),
                    "row_families": sorted(generator.source_families(rank.row_sources)),
                    "row_from_primary_source": bool(rank.row_sources & generator.PRIMARY_APN_SOURCES),
                    "row_sources": sorted(rank.row_sources),
                    # The row keeps "emergency" because it asks for exactly
                    # Android's default request (android_default), or a
                    # current vendor (current_vendor) or LineageOS's own list
                    # (lineageos) gives it; None when it does not serve
                    # "emergency" (round 21).
                    "emergency_basis": emergency_basis(generator, row),
                    # The row lost "emergency" and kept its other types, and
                    # why (leave_out_emergency).
                    "emergency_left_out": row.get("_emergency_left_out"),
                    # The types of LineageOS's legacy list this row lost
                    # because their role is no gap in the scope without the
                    # list (keep_role_gap_rows, round 35); empty otherwise.
                    "role_gap_types_left_out": list(row.get("_role_gap_left_out") or ()),
                    # The types of LineageOS's legacy list this row got back
                    # because they are load-bearing for a gap role's lead
                    # (keep_load_bearing_rows, rule round 38, F1); empty
                    # otherwise.
                    "role_gap_kept_load_bearing": list(row.get("_role_gap_kept_load_bearing") or ()),
                    # The row lost "ims": Android stores it as one with the
                    # other rows of its unique key, their united types are
                    # TYPE_ALL, no current vendor backs any of them for ims,
                    # and a current vendor's ims row takes the IMS lead on
                    # LTE, NR and IWLAN (change 18's IMS mirror, rule round
                    # 37, item 2).
                    "ims_left_out_star_group": bool(row.get("_ims_left_out_star_group")),
                },
            }
        )
    # Where each username, password, auth type and MTU a lead sends comes
    # from (rule decisions round 32, D8): the phone model reads this SIM's
    # rows as TelephonyProvider stores them, and for the internet, attach and
    # MMS lead on the 3GPP data network types each such field names the row
    # (its position above) that wrote it, whether that is the stored group's
    # best row or a lower-ranked row that fills in (filled_in), and that
    # row's sources and current vendors. class_a: a filled-in value no
    # current vendor backs under a best row a current vendor backs; sent:
    # the lead sends a filled-in credential (auth type not 0) or MTU.
    import android_phone_model as phone
    import check_phone_guard as guard

    file_rows = phone.parse_lines(generator.apn_row_line(row) for row in chosen)
    credential_sources = []
    for entry in guard.lead_credentials(file_rows, phone.provider(file_rows), chosen):
        credential_sources.append(
            {
                "role": entry["role"],
                "apn": entry["apn"],
                "network_types": entry["network_types"],
                "sends_credentials": entry["sends_credentials"],
                "class_a": bool(entry["class_a"]),
                "sent": entry["sent"],
                "fields": {
                    field: {
                        "value": value["value"],
                        "position": value["row"] + 1,
                        "filled_in": not value["best_row"],
                        "sources": value.get("sources", []),
                        "current_sources": value.get("current_sources", []),
                    }
                    for field, value in entry["fields"].items()
                },
            }
        )
    return {
        "schema_version": 1,
        "sim": identity,
        "profiles": profiles,
        "capabilities": capabilities,
        "android_carrier_config": carrier_config,
        "addons": addons,
        "apns": {
            "scope": "mvno" if mvno_rows else "network",
            "rows": apn_rows,
            "credential_sources": credential_sources,
            # The APN quality gates of this SIM's profile stack, from the
            # evidence index: the rows a gate left out of a profile, such as
            # mms_proxy_unroutable:<value> (rule round 40: a row whose MMS
            # would use a proxy no network routes), mms_without_mmsc or
            # lineageos_apn_removed:<commit>.
            "quality_gates": [
                {"profile_id": item["profile_id"], "key": gate["key"],
                 "observed_value_count": gate.get("observed_value_count")}
                for item in stack
                for gate in evidence.get(item["profile_id"], {}).get("quality_gates", [])
                if gate.get("section") == "android_apns"
            ],
            # Rows of this SIM's scope that apns-conf.xml leaves out: stale
            # MMS-only rows Android merges into an earlier row
            # (absorbed_mms_left_out), and rows whose only type was
            # "emergency" when leave_out_emergency took it off
            # (emergency_left_out, with its reason). The profile JSON keeps
            # them. Rows rule 1 of round 32 (D8) left out are listed too
            # (superseded_google_credentials_left_out), and rows of
            # LineageOS's legacy list that fill no role gap
            # (role_gap_types_left_out, round 35).
            "left_out": [
                {
                    "row": generator.written_attributes(row),
                    "reasons": {
                        "absorbed_mms_left_out": True,
                        # An MMS-only row Android stores with the first
                        # internet row, left out because it gave that stored
                        # row "mms" no current vendor backs (round 33).
                        "left_out_stored_with_internet": bool(row.get("_left_out_stored_with_internet")),
                    },
                }
                for row in generated_rows.mms_absorbed_left_out
                if generator.apn_scope_key(row) in chosen_scopes
            ]
            + [
                {
                    "row": generator.written_attributes(row),
                    # A row whose only type (ims or xcap) no current vendor
                    # backs on the first internet row's stored row (rule
                    # round 34, change 18 step 2c).
                    "reasons": {"type_left_out_stored_with_internet": row["_type_left_out_stored_with_internet"]},
                }
                for row in getattr(generated_rows, "rows_left_out_stored_with_internet", ())
                if generator.apn_scope_key(row) in chosen_scopes
            ]
            + [
                {
                    "row": generator.written_attributes(row),
                    "reasons": {"emergency_left_out": row["_emergency_left_out"]},
                }
                for row in generated_rows.emergency_left_out
                if row["type"] == "emergency" and generator.apn_scope_key(row) in chosen_scopes
            ]
            # Rule 1 of round 32, D8: a row whose only effect on its stored
            # row was a username, password, auth type or MTU that only
            # Google's frozen Pixel copies give, under an APN Google's
            # current file gives bare; the fields it filled in.
            + [
                {
                    "row": generator.written_attributes(row),
                    "reasons": {"superseded_google_credentials_left_out": list(row["_credentials_left_out"])},
                }
                for row in getattr(generated_rows, "credentials_left_out", ())
                if generator.apn_scope_key(row) in chosen_scopes
            ]
            # Round 35, B: a row of LineageOS's legacy list none of whose
            # types fills a role gap in the scope without the list; the
            # types it had.
            + [
                {
                    "row": generator.written_attributes(row),
                    "reasons": {"role_gap_types_left_out": list(row["_role_gap_left_out"])},
                }
                for row in getattr(generated_rows, "role_gap_left_out", ())
                if not row["type"] and generator.apn_scope_key(row) in chosen_scopes
            ],
        },
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookup", type=Path, default=Path("generated/android/lookup.json"))
    parser.add_argument(
        "--explain",
        action="store_true",
        help="print the profile stack, the sources behind every value, and the "
        "APN rows this SIM gets with the reasons for their order",
    )
    parser.add_argument(
        "--evidence-index",
        type=Path,
        help="for --explain (default: generated/evidence-index.json next to the lookup)",
    )
    parser.add_argument("--mccmnc", required=True)
    parser.add_argument("--spn")
    parser.add_argument("--gid1")
    parser.add_argument("--gid2")
    parser.add_argument("--iccid")
    parser.add_argument("--imsi")
    parser.add_argument("--android-carrier-id", type=int)
    parser.add_argument(
        "--android-specific-carrier-id",
        type=int,
        help="the SIM's specific carrier ID; a profile's android_carrier_ids match either ID",
    )
    parser.add_argument(
        "--order",
        choices=ORDERS,
        default="android",
        help="android (default): lookup.json's documented order since schema_version 2 (rule round 45), as "
        "OcdCarrierSettings and the OCD Check app sort; count: the order before it (selectors used, then profile ID)",
    )
    args = parser.parse_args(argv[1:])
    lookup = json.loads(args.lookup.read_text(encoding="utf-8"))
    identity = {
        key: value
        for key, value in {
            "mccmnc": args.mccmnc,
            "spn": args.spn,
            "gid1": args.gid1,
            "gid2": args.gid2,
            "iccid": args.iccid,
            "imsi": args.imsi,
            "android_carrier_id": args.android_carrier_id,
            "android_specific_carrier_id": args.android_specific_carrier_id,
        }.items()
        if value is not None
    }
    if args.explain:
        root = args.lookup.resolve().parents[2]
        evidence_index = args.evidence_index or args.lookup.resolve().parents[1] / "evidence-index.json"
        print(json.dumps(explain(lookup, identity, root, evidence_index, args.order), indent=2, sort_keys=True))
        return 0
    stack = resolve(lookup, identity, args.order)
    result: dict[str, Any] = {
        "schema_version": 1,
        "resolution_order": "generic_to_specific",
        "profiles": stack,
    }
    result["order"] = args.order
    if args.order == "android":
        result["serving_reason"] = serving_reason(stack, args.mccmnc)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
