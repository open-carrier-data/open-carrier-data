#!/usr/bin/env python3
"""Resolve all public carrier profiles matching a SIM/network identity.

With --explain it also says why: the profile stack, the value each profile
gives for every capability, CarrierConfig key and add-on with the sources
behind it from the evidence index, and the APN rows Android 16 gives this SIM
in file order with the reasons each row sits where it does.
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
    if expected_carrier_ids and identity.get("android_carrier_id") not in expected_carrier_ids:
        return False
    return True


def specificity(match: dict[str, Any]) -> int:
    return sum(bool(match.get(key)) for key in MATCH_DIMENSIONS)


def resolve(lookup: dict[str, Any], identity: dict[str, Any]) -> list[dict[str, Any]]:
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
    return sorted(
        matches,
        key=lambda profile: (
            specificity(profile["match"]),
            str(profile.get("profile_id", "")),
        ),
    )


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


def explain(
    lookup: dict[str, Any],
    identity: dict[str, Any],
    root: Path,
    evidence_index_path: Path,
) -> dict[str, Any]:
    """Why a SIM gets what it gets. root is the repository the lookup's paths
    are relative to."""
    import generate_android_outputs as generator

    stack = resolve(lookup, identity)
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
    rows = generator.apn_xml_rows(
        network_profiles, generator.load_apn_evidence(evidence_index_path)
    ).records
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
                    "value_families": sorted(generator.source_families(rank.value_sources)),
                    "value_from_primary_source": bool(rank.value_sources & generator.PRIMARY_APN_SOURCES),
                    "row_families": sorted(generator.source_families(rank.row_sources)),
                    "row_from_primary_source": bool(rank.row_sources & generator.PRIMARY_APN_SOURCES),
                    "row_sources": sorted(rank.row_sources),
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
        }.items()
        if value is not None
    }
    if args.explain:
        root = args.lookup.resolve().parents[2]
        evidence_index = args.evidence_index or args.lookup.resolve().parents[1] / "evidence-index.json"
        print(json.dumps(explain(lookup, identity, root, evidence_index), indent=2, sort_keys=True))
        return 0
    print(
        json.dumps(
            {
                "schema_version": 1,
                "resolution_order": "generic_to_specific",
                "profiles": resolve(lookup, identity),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
