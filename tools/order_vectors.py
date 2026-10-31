#!/usr/bin/env python3
"""The dry run and the golden vectors of OCD's resolution order (rule round 45, item 3).

Rule round 45 replaces the count of filled selectors with Android's weights
and a written-out tie rule (tools/ocd_dataset.py, "resolution order"). This
tool lists what that changes and writes the golden vectors that the public
resolver, OcdCarrierSettings and the OCD Check app must all pass.

  dry-run [--root DIR] [--out FILE]
      Every network and pair of profiles one SIM can match whose order flips
      between the count order (specificity, then id) and the resolution
      order. A synthetic SIM of both is resolved on the whole network under
      each order; the case is listed when its serving profile, OCD
      CarrierConfig overlay, Google fill or APN coupling changes, with the
      values. Writes JSON (default: stdout summary only).
  golden [--root DIR] [--out tests/vectors/resolution-order.json]
      Writes the golden vectors: the spec's 27 matcher vectors (S20 spec
      appendix A) in the resolution order, the owner's SIM groups, a SIM of
      every profile on the owner's networks (262-01, 262-02, 262-03, 262-07),
      every dry-run case, the remaining tie up to the profile ID, and a
      carrier ID without a rule. The carrier-ID rules come from
      tools/aosp/carrier-id-table.json, whose version the file pins.
  check [--vectors FILE]
      Runs the vectors against tools/resolve_carrier_profiles.py (--order
      android) and tools/ocd_dataset.py's matcher. Exit 1 on a difference.

Every SIM value is synthetic: an IMSI is the published pattern's fixed digits
with zeros for x and up to 15 digits, ending in 1 where free; an ICCID is a
published prefix padded with zeros to 19 digits and a final 1; GID1, GID2,
SPN and carrier IDs are published selectors. None is read from a SIM or a log.
Only the standard library is used.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import ocd_dataset as ocd  # noqa: E402
import resolve_carrier_profiles as resolver  # noqa: E402

VECTORS = TOOLS.parent / "tests" / "vectors" / "resolution-order.json"
SCHEMA = "ocd-resolution-order-vectors/1"
OWNER_NETWORKS = ("262-01", "262-02", "262-03", "262-07")


# ---------------------------------------------------------------- synthetic SIMs


def synthetic_sim(network: dict[str, Any], *profiles: dict[str, Any]) -> dict[str, Any]:
    """A SIM that every profile given matches (they must be able to overlap),
    from their published selectors."""
    mcc, mnc = network["mcc"], network["mnc"]
    sim: dict[str, Any] = {"mcc": mcc, "mnc": mnc}
    matches = [p["match"] for p in profiles]

    def pick(dimension: str, kind: str) -> list[str] | None:
        lists = [m[dimension] for m in matches if m.get(dimension)]
        if not lists:
            return None
        combos: list[tuple[str, ...]] = [(v,) for v in lists[0]]
        for more in lists[1:]:
            combos = [c + (v,) for c in combos for v in more if all(ocd.values_overlap(kind, w, v) for w in c)]
        return list(combos[0])

    patterns = pick("imsi_prefix_patterns", "imsi")
    digits = list(mcc + mnc)
    if patterns:
        length = max(len(p) for p in patterns)
        digits = []
        for i in range(length):
            fixed = [p[i] for p in patterns if i < len(p) and p[i] not in "xX"]
            digits.append(fixed[0] if fixed else "0")
    digits = (digits + ["0"] * 15)[:15]
    if not patterns or max(len(p) for p in patterns) < 15:
        digits[-1] = "1"
    sim["imsi"] = "".join(digits)
    for dimension, key, kind in (("iccid_prefixes", "iccid", "iccid"), ("gid1_prefixes", "gid1", "gid1"),
                                 ("gid2_prefixes", "gid2", "gid1"), ("spn", "spn", "spn")):
        chosen = pick(dimension, kind)
        if chosen:
            value = max(chosen, key=len)
            sim[key] = (value + "0" * 19)[:19] + "1" if key == "iccid" else value
    ids = [m["android_carrier_ids"] for m in matches if m.get("android_carrier_ids")]
    if ids:
        common = [c for c in ids[0] if all(c in more for more in ids[1:])]
        if common:
            sim["carrier_id"] = sim["specific_carrier_id"] = common[0]
        else:
            sim["carrier_id"], sim["specific_carrier_id"] = ids[0][0], ids[1][0]
    return sim


# ---------------------------------------------------------------- one SIM's result


class Dataset:
    """profiles.json, the APN index, apns-conf.xml and the Google lane of a checkout."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.profiles = ocd.read_json_file(root / ocd.FILES["profiles"][1])
        self.index = ocd.read_json_file(root / ocd.FILES["apn_index"][1])
        lane_path = root / ocd.FILES["google_lane"][1]
        self.entries = ocd.read_json_file(lane_path)["entries"] if lane_path.is_file() else None
        _, rows = ocd.parse_apn_rows((root / "generated/android/apns-conf.xml").read_bytes())
        self.rows = [attributes for _, attributes in rows]
        self.row_profiles = [row["profiles"] for row in self.index["rows"]]
        self.by_numeric: dict[str, list[int]] = defaultdict(list)
        self.with_carrier_id = []
        for i, attributes in enumerate(self.rows):
            self.by_numeric[attributes.get("mcc", "") + attributes.get("mnc", "")].append(i)
            if attributes.get("carrier_id"):
                self.with_carrier_id.append(i)

    def apn_rows(self, sim: dict[str, Any]) -> list[int]:
        """TelephonyProvider's getSubscriptionMatchingAPNListSynchronized (spec 4.6)."""
        numeric = sim["mcc"] + sim["mnc"]
        carrier_id = sim.get("specific_carrier_id", -1)
        mvno, plain, other_numeric, no_numeric = [], [], [], []
        for i in self.by_numeric.get(numeric, []):
            attributes = self.rows[i]
            kind = attributes.get("mvno_type")
            if kind:
                if mvno_matches(kind, attributes.get("mvno_match_data", ""), sim):
                    mvno.append(i)
            else:
                plain.append(i)
        for i in self.with_carrier_id:
            attributes = self.rows[i]
            row_numeric = attributes.get("mcc", "") + attributes.get("mnc", "")
            if carrier_id != -1 and attributes["carrier_id"] == str(carrier_id):
                if not row_numeric:
                    no_numeric.append(i)
                elif row_numeric != numeric:
                    other_numeric.append(i)
        return (mvno or plain or other_numeric) + no_numeric

    def outcome(self, stack: list[dict[str, Any]], sim: dict[str, Any]) -> dict[str, Any]:
        serving = stack[-1] if stack else None
        values: dict[str, Any] = {}
        for profile in stack:
            values.update(profile["values"])
        fill = ocd.pick_fill(serving["fill"], sim, self.entries) if serving else None
        apn_profile = next((p["id"] for p in reversed(stack) if p["apn_rows"] > 0), None)
        selected = self.apn_rows(sim)
        if apn_profile is None and not selected:
            coupling = "same"
        elif apn_profile is not None and selected and all(apn_profile in self.row_profiles[i] for i in selected):
            coupling = "same"
        else:
            coupling = "mismatch"
        return {"stack": [p["id"] for p in stack], "serving": serving["id"] if serving else "default", "values": values,
                "fill": fill, "apn_profile": apn_profile, "coupling": coupling}


def mvno_matches(kind: str, data: str, sim: dict[str, Any]) -> bool:
    kind = kind.lower()
    if kind == "spn":
        return isinstance(sim.get("spn"), str) and ocd.java_equals_ignore_case(sim["spn"], data)
    if kind == "imsi":
        return isinstance(sim.get("imsi"), str) and ocd.imsi_pattern_matches(data, sim["imsi"])
    if kind == "gid":
        return isinstance(sim.get("gid1"), str) and ocd.java_starts_with_ignore_case(sim["gid1"], data)
    if kind == "iccid":
        return isinstance(sim.get("iccid"), str) and any(sim["iccid"].startswith(p) for p in data.split(",") if p)
    return False


def count_stack(matching: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(matching, key=ocd.stack_order)


def order_stack(matching: list[dict[str, Any]], mccmnc: str) -> list[dict[str, Any]]:
    return sorted(matching, key=lambda p: ocd.resolution_key(p, mccmnc))


# ---------------------------------------------------------------- dry run


def dry_run(data: Dataset) -> dict[str, Any]:
    cases = []
    flipped = 0
    for key, network in data.profiles["networks"].items():
        items = network["profiles"]
        mccmnc = network["mcc"] + network["mnc"]
        keys = {p["id"]: ocd.resolution_key(p, mccmnc) for p in items}
        for i, p in enumerate(items):
            for q in items[i + 1:]:
                if not ocd.selectors_can_overlap(p["match"], q["match"]):
                    continue
                count_lower = ocd.stack_order(p) < ocd.stack_order(q)
                order_lower = keys[p["id"]] < keys[q["id"]]
                if count_lower == order_lower:
                    continue
                flipped += 1
                sim = synthetic_sim(network, p, q)
                matching = [x for x in items if ocd.profile_holds(x, sim)]
                before = data.outcome(count_stack(matching), sim)
                after_stack = order_stack(matching, mccmnc)
                after = data.outcome(after_stack, sim)
                changes: dict[str, Any] = {}
                if before["serving"] != after["serving"]:
                    changes["serving"] = [before["serving"], after["serving"]]
                keys_changed = sorted(k for k in set(before["values"]) | set(after["values"])
                                      if ocd.compact(before["values"].get(k)) != ocd.compact(after["values"].get(k)))
                if keys_changed:
                    changes["carrier_config"] = {k: [before["values"].get(k), after["values"].get(k)] for k in keys_changed}
                if before["fill"] != after["fill"]:
                    changes["google_fill"] = [before["fill"], after["fill"]]
                if before["apn_profile"] != after["apn_profile"] or before["coupling"] != after["coupling"]:
                    changes["apn"] = {"apn_profile": [before["apn_profile"], after["apn_profile"]],
                                      "coupling": [before["coupling"], after["coupling"]]}
                if not changes:
                    continue
                lower, upper = (p, q) if order_lower else (q, p)
                cases.append({
                    "network": key, "pair": [lower["id"], upper["id"]],
                    "shared": sorted(d for d in ocd.DIMENSIONS if d in p["match"] and d in q["match"]),
                    "step": ocd.deciding_step(keys[lower["id"]], keys[upper["id"]]),
                    "sim": sim, "count_stack": before["stack"], "stack": after["stack"],
                    "reason": ocd.serving_reason(after_stack, mccmnc), "count_fill": before["fill"], "fill": after["fill"],
                    "changes": changes,
                })
    return {"pairs_flipped": flipped, "cases": cases}


def summary(result: dict[str, Any]) -> str:
    cases = result["cases"]
    kinds = Counter(k for c in cases for k in c["changes"])
    coupling = Counter(tuple(c["changes"]["apn"]["coupling"]) for c in cases if "apn" in c["changes"])
    return (f"{result['pairs_flipped']} pairs change order; {len(cases)} SIM cases on {len({c['network'] for c in cases})} networks change: "
            f"serving profile {kinds['serving']}, CarrierConfig {kinds['carrier_config']}, Google fill {kinds['google_fill']}, "
            f"APN profile {kinds['apn']} (coupling " + ", ".join(f"{a} to {b} {n}" for (a, b), n in sorted(coupling.items())) + ")")


# ---------------------------------------------------------------- golden vectors


def vector_of(vid: str, group: str, sim: dict[str, Any], network_profiles: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    mccmnc = sim["mcc"] + sim["mnc"]
    stack = order_stack([p for p in network_profiles if ocd.profile_holds(p, sim)], mccmnc)
    serving = stack[-1] if stack else None
    return {"id": vid, "group": group, "sim": sim, "stack": [p["id"] for p in stack],
            "serving": serving["id"] if serving else "default", "reason": ocd.serving_reason(stack, mccmnc),
            "fill_pick": ocd.pick_fill(serving["fill"], sim) if serving else None, **extra}


def slim(profile: dict[str, Any]) -> dict[str, Any]:
    return {"id": profile["id"], "kind": profile["kind"], "match": profile["match"], "fill": profile["fill"]}


def spec_set() -> dict[str, Any]:
    """Appendix A of the S20 spec, its fill lists computed, in the resolution order."""
    import test_ocd_dataset as spec  # the appendix, verbatim, lives with its test

    appendix = spec.appendix()
    profiles, ids = spec.appendix_dataset()
    vectors = []
    for item in appendix["vectors"]:
        sim = dict(item["sim"])
        network = profiles["networks"].get(f"{sim['mcc']}-{sim['mnc']}", {"profiles": []})
        vector = vector_of(item["id"], "spec", sim, network["profiles"])
        want = [ids.get(i, i) for i in item["stack"]]
        if vector["stack"] != want or vector["fill_pick"] != item["fill_pick"]:
            raise SystemExit(f"{item['id']}: the resolution order changes the spec's vector: {vector['stack']} against {want}")
        if "must_not_contain" in item:
            vector["must_not_contain"] = item["must_not_contain"]
        vectors.append(vector)
    networks = {k: [slim(p) for p in n["profiles"]] for k, n in sorted(profiles["networks"].items())}
    return {"name": "spec", "about": "The 27 matcher vectors of the S20 spec (appendix A, 2026-10-25) with their own profiles and Google rules; "
            "the resolution order keeps every result.", "networks": networks, "vectors": vectors}


def dataset_set(data: Dataset, cases: list[dict[str, Any]], commit: str) -> dict[str, Any]:
    networks = data.profiles["networks"]
    vectors = []
    lidl = {"mcc": "262", "mnc": "02", "imsi": "262020000000001", "spn": "Lidl Connect", "carrier_id": 2397, "specific_carrier_id": 2397}
    vectors.append(vector_of("owner-lidl-connect", "owner", lidl, networks["262-02"]["profiles"],
                             note="The owner's LIDL Connect SIM group on Vodafone Germany: SPN as the spec's M9, carrier ID 2397 (docs/consume.md)."))
    o2 = {"mcc": "262", "mnc": "07", "imsi": "262070000000001"}
    vectors.append(vector_of("owner-o2", "owner", o2, networks["262-07"]["profiles"],
                             note="The owner's o2 SIM group as the phone served it (open.26207.c07dcc040b58): no selector beyond the network."))
    for key in OWNER_NETWORKS:
        network = networks[key]
        for profile in network["profiles"]:
            sim = synthetic_sim(network, profile)
            vectors.append(vector_of(f"group-{key}-{profile['id']}", "real", sim, network["profiles"],
                                     note=f"A SIM of {profile['name']} from its own selectors."))
    for t in ocd.tie_report(data.profiles, data.index):
        network = networks[t["network"]]
        pair = [p for p in network["profiles"] if p["id"] in (t["first"], t["serves"])]
        vectors.append(vector_of(f"tie-{t['network']}", "tie", synthetic_sim(network, *pair), network["profiles"],
                                 note="Tied up to the profile ID; tools/ocd_dataset.py ties shows that a SIM of both is served the same."))
    seen: dict[str, dict[str, Any]] = {}
    for case in cases:
        # One vector per SIM case: pairs that build the same SIM share it.
        text = json.dumps([case["network"], case["sim"]], sort_keys=True)
        if text in seen:
            seen[text]["changes"] = sorted(set(seen[text]["changes"]) | set(case["changes"]))
            continue
        network = networks[case["network"]]
        seen[text] = vector_of(f"dry-{len(seen) + 1:05d}", "dry_run", case["sim"], network["profiles"],
                               count_serving=case["count_stack"][-1], changes=sorted(case["changes"]))
        vectors.append(seen[text])
    used: dict[str, set[str]] = defaultdict(set)
    for vector in vectors:
        used[f"{vector['sim']['mcc']}-{vector['sim']['mnc']}"].update(vector["stack"])
    for key in OWNER_NETWORKS:
        used[key].update(p["id"] for p in networks[key]["profiles"])
    out_networks = {k: [slim(p) for p in networks[k]["profiles"] if p["id"] in used[k]] for k in sorted(used)}
    return {"name": "dataset", "about": f"OCD main {commit}: every profile a vector's stack holds (and every profile of the owner's networks), "
            "with its match and fill list as profiles.json has them.", "networks": out_networks, "vectors": vectors}


def synthetic_set() -> dict[str, Any]:
    """A carrier ID without a rule on its network counts at the MCC/MNC-only
    weight (and OcdCarrierSettings logs it); one with a rule takes the rule's."""
    net = {"mcc": "999", "mnc": "03"}
    profiles = [
        {"id": "open.99903.000000000001", "kind": "ocd", "match": {"mccmnc": [net]}, "fill": []},
        {"id": "open.99903.000000000002", "kind": "ocd", "match": {"mccmnc": [net], "spn": ["Example"]}, "fill": []},
        {"id": "open.99903.000000000003", "kind": "ocd", "match": {"mccmnc": [net], "android_carrier_ids": [999999]}, "fill": []},
        {"id": "fill.99903.000000000004", "kind": "fill_only", "match": {"mccmnc": [net], "spn": ["Example"]},
         "fill": [{"entry": "synthetic_example", "when": None}]},
    ]
    vectors = [
        vector_of("fallback-carrier-id", "synthetic", {"mcc": "999", "mnc": "03", "spn": "Example", "carrier_id": 999999, "specific_carrier_id": 999999},
                  profiles, note="Carrier ID 999999 has no rule on 999-03: it counts at 256 with the carrier-ID step (logged on the phone), "
                  "below the SPN profiles (258); the OCD SPN profile ranks above the fill-only one."),
        vector_of("fill-only-below-ocd", "synthetic", {"mcc": "999", "mnc": "03", "spn": "example"}, profiles,
                  note="Equal weight, prefix and counts: the OCD profile above the fill-only one (step 3), whatever the IDs."),
    ]
    return {"name": "synthetic", "about": "Synthetic network 999-03.", "networks": {"999-03": profiles}, "vectors": vectors}


def table_rows(sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The carrier ID table's rows for every carrier ID a profile of the file names, on that profile's networks."""
    wanted = set()
    for s in sets:
        for profiles in s["networks"].values():
            for p in profiles:
                for carrier_id in p["match"].get("android_carrier_ids", []):
                    for n in p["match"]["mccmnc"]:
                        wanted.add((carrier_id, n["mcc"] + n["mnc"]))
    rows = ocd.read_json_file(TOOLS / ocd.CARRIER_ID_TABLE_FILE)["rows"]
    return [r for r in rows if (r["carrier_id"], r.get("mccmnc")) in wanted]


def golden(root: Path, commit: str) -> dict[str, Any]:
    data = Dataset(root)
    cases = dry_run(data)["cases"]
    sets = [spec_set(), dataset_set(data, cases, commit), synthetic_set()]
    table = ocd.read_json_file(TOOLS / ocd.CARRIER_ID_TABLE_FILE)
    return {
        "schema": SCHEMA,
        "about": "Golden vectors of OCD's resolution order (rule round 45, item 3): a synthetic SIM in, the stack generic to specific, "
                 "the serving profile, the step of the order that made it serve (reason) and the Google fill it picks out. "
                 "tools/resolve_carrier_profiles.py --order android, tools/ocd_dataset.py, OcdCarrierSettings and the OCD Check app "
                 "pass every vector. All SIM values are synthetic, built from published selectors.",
        "order": list(ocd.ORDER_STEPS),
        "carrier_id_table": {"version": table["version"], "source": table["source"], "rows": table_rows(sets)},
        "sets": sets,
    }


def dump(document: dict[str, Any]) -> str:
    """One vector and one profile per line, so a change reads as a line."""
    def lines(items: list[Any], indent: str) -> str:
        return "[\n" + ",\n".join(indent + json.dumps(i, ensure_ascii=False, separators=(",", ":")) for i in items) + "\n" + indent[:-2] + "]"

    head = {k: v for k, v in document.items() if k not in ("carrier_id_table", "sets")}
    out = "{\n" + ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in head.items())
    table = document["carrier_id_table"]
    out += ',\n  "carrier_id_table": {' + f'"version": {table["version"]}, "source": {json.dumps(table["source"], ensure_ascii=False)}, "rows": ' \
           + lines(table["rows"], "    ") + "}"
    out += ',\n  "sets": [\n'
    parts = []
    for s in document["sets"]:
        nets = ",\n".join(f"      {json.dumps(k)}: " + lines(v, "        ") for k, v in s["networks"].items())
        parts.append("    {" + f'"name": {json.dumps(s["name"])}, "about": {json.dumps(s["about"], ensure_ascii=False)},\n'
                     + '     "networks": {\n' + nets + "\n     },\n"
                     + '     "vectors": ' + lines(s["vectors"], "      ") + "}")
    return out + ",\n".join(parts) + "\n  ]\n}\n"


# ---------------------------------------------------------------- check


def check(document: dict[str, Any]) -> list[str]:
    """Every vector against the dataset matcher and the public resolver."""
    table: dict[tuple[int, str], list[int]] = {}
    for row in document["carrier_id_table"]["rows"]:
        weight = sum(w for column, w in ocd.RULE_WEIGHTS.items() if row.get(column) is not None)
        table.setdefault((row["carrier_id"], row["mccmnc"]), []).append(weight)
    problems = []
    for s in document["sets"]:
        for vector in s["vectors"]:
            sim = vector["sim"]
            key, mccmnc = f"{sim['mcc']}-{sim['mnc']}", sim["mcc"] + sim["mnc"]
            profiles = s["networks"].get(key, [])
            where = f"{s['name']} {vector['id']}"
            # tools/ocd_dataset.py
            stack = sorted((p for p in profiles if ocd.profile_holds(p, sim)), key=lambda p: ocd.resolution_key(p, mccmnc, table))
            got = [p["id"] for p in stack]
            reason = "default" if not stack else "only" if len(stack) == 1 else \
                ocd.deciding_step(ocd.resolution_key(stack[-2], mccmnc, table), ocd.resolution_key(stack[-1], mccmnc, table)) or "profile_id"
            pick = ocd.pick_fill(stack[-1]["fill"], sim) if stack else None
            if (got, reason, pick) != (vector["stack"], vector["reason"], vector["fill_pick"]):
                problems.append(f"{where}: ocd_dataset gives {got} ({reason}, fill {pick})")
            # tools/resolve_carrier_profiles.py over the same profiles in lookup.json's form; it
            # compares SPNs with Python's casefold where the phone uses Java's equalsIgnoreCase, which
            # only the spec's M23 tells apart.
            if vector["id"] == "M23":
                continue
            lookup = {"profiles": [{"profile_id": p["id"], "kind": p["kind"],
                                    "match": {**{d: v for d, v in p["match"].items() if d != "mccmnc"},
                                              "mccmnc": [n["mcc"] + n["mnc"] for n in p["match"]["mccmnc"]]}} for p in profiles]}
            identity = {"mccmnc": mccmnc, **{k: sim[k] for k in ("spn", "gid1", "gid2", "iccid", "imsi") if k in sim}}
            if "carrier_id" in sim:
                identity["android_carrier_id"] = sim["carrier_id"]
            if "specific_carrier_id" in sim:
                identity["android_specific_carrier_id"] = sim["specific_carrier_id"]
            resolved = resolver.resolve(lookup, identity, "android", table)
            if [p["profile_id"] for p in resolved] != vector["stack"] or resolver.serving_reason(resolved, mccmnc, table) != vector["reason"]:
                problems.append(f"{where}: resolve_carrier_profiles gives {[p['profile_id'] for p in resolved]}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    dry = sub.add_parser("dry-run")
    dry.add_argument("--root", type=Path, default=TOOLS.parent)
    dry.add_argument("--out", type=Path)
    gold = sub.add_parser("golden")
    gold.add_argument("--root", type=Path, default=TOOLS.parent)
    gold.add_argument("--commit", required=True, help="the main commit whose dataset the vectors take their profiles from")
    gold.add_argument("--out", type=Path, default=VECTORS)
    chk = sub.add_parser("check")
    chk.add_argument("--vectors", type=Path, default=VECTORS)
    args = parser.parse_args(argv)
    if args.command == "dry-run":
        result = dry_run(Dataset(args.root))
        if args.out:
            args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(summary(result))
        return 0
    if args.command == "golden":
        document = golden(args.root, args.commit)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(dump(document), encoding="utf-8")
        print(f"{args.out}: " + ", ".join(f"{s['name']} {len(s['vectors'])}" for s in document["sets"]) + " vectors")
        return 0
    problems = check(json.loads(args.vectors.read_text(encoding="utf-8")))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not problems:
        print(f"{args.vectors}: every vector passes")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
