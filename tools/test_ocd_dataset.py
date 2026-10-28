#!/usr/bin/env python3
"""tools/ocd_dataset.py: the matcher vectors of the round 30 dataset spec
(appendix A, normative), the fill lists, the matcher over every published
selector with the network-code length check (302/37 against 302/370), the tie
report, the generator and the reader's checks 4 to 10 on a small checkout and
on this repository's dataset, and the device-record rules."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import ocd_dataset as ocd

REPO = Path(__file__).resolve().parents[1]

# Appendix A of the S20 project's "OCD round 30 dataset spec" (2026-10-25),
# verbatim: the vectors every implementation (this generator,
# OcdCarrierSettings and the OCD Check owner app) must pass. The IMSIs and
# ICCIDs are synthetic, and so are networks 999-01 and 999-02.
APPENDIX_A = r"""
{
  "schema": "ocd-matcher-vectors/1",
  "google_rules": [
    {"canonical_name": "test001_amarisoft", "mcc": "001", "mnc": "01", "mvno": {"kind": "gid1", "value": "ABCD2025"}},
    {"canonical_name": "test001_zz", "mcc": "001", "mnc": "01", "mvno": null},
    {"canonical_name": "21670IMSI=21670XX1XXX", "mcc": "216", "mnc": "70", "mvno": {"kind": "imsi", "value": "21670xx1"}},
    {"canonical_name": "vodafone_hu", "mcc": "216", "mnc": "70", "mvno": null},
    {"canonical_name": "vodafone_de", "mcc": "262", "mnc": "02", "mvno": null},
    {"canonical_name": "enreach_de", "mcc": "262", "mnc": "03", "mvno": {"kind": "imsi", "value": "26203482"}},
    {"canonical_name": "enreach_de", "mcc": "262", "mnc": "03", "mvno": {"kind": "imsi", "value": "26203483"}},
    {"canonical_name": "eplus_de", "mcc": "262", "mnc": "03", "mvno": null},
    {"canonical_name": "tchibo_de", "mcc": "262", "mnc": "07", "mvno": {"kind": "imsi", "value": "26207500"}},
    {"canonical_name": "o2prepaid_de", "mcc": "262", "mnc": "07", "mvno": {"kind": "imsi", "value": "2620749"}},
    {"canonical_name": "26207SPN=ALICE", "mcc": "262", "mnc": "07", "mvno": {"kind": "spn", "value": "ALICE"}},
    {"canonical_name": "o2_de", "mcc": "262", "mnc": "07", "mvno": null},
    {"canonical_name": "mts_ca", "mcc": "302", "mnc": "370", "mvno": {"kind": "gid1", "value": "2C"}},
    {"canonical_name": "fido_ca", "mcc": "302", "mnc": "370", "mvno": {"kind": "gid1", "value": "DD"}},
    {"canonical_name": "fido_ca", "mcc": "302", "mnc": "370", "mvno": null},
    {"canonical_name": "synthetic_0103", "mcc": "999", "mnc": "02", "mvno": {"kind": "gid1", "value": "0103"}},
    {"canonical_name": "synthetic_net", "mcc": "999", "mnc": "02", "mvno": null}
  ],
  "profiles": [
    {"id": "open.26207.c07dcc040b58", "match": {"mccmnc": [{"mcc": "262", "mnc": "07"}]}},
    {"id": "open.26207.394d5585811d", "match": {"mccmnc": [{"mcc": "262", "mnc": "07"}, {"mcc": "262", "mnc": "11"}], "android_carrier_ids": [1454]}},
    {"id": "open.26207.69841ad3698a", "match": {"mccmnc": [{"mcc": "262", "mnc": "07"}], "spn": ["ALICE"]}},
    {"id": "open.26207.1c95803fdfb1", "match": {"mccmnc": [{"mcc": "262", "mnc": "07"}], "imsi_prefix_patterns": ["2620749"]}},
    {"id": "open.26207.78040a3afcc4", "match": {"mccmnc": [{"mcc": "262", "mnc": "07"}], "imsi_prefix_patterns": ["26207500"]}},
    {"id": "open.26207.2aa389aa6407", "match": {"mccmnc": [{"mcc": "262", "mnc": "07"}], "imsi_prefix_patterns": ["26207520"]}},
    {"id": "open.26207.6aa33dfeb206", "match": {"mccmnc": [{"mcc": "262", "mnc": "07"}], "gid1_prefixes": ["000002"]}},
    {"id": "open.26203.dbb2be7109a6", "match": {"mccmnc": [{"mcc": "262", "mnc": "03"}]}},
    {"id": "open.26203.ec645827a22d", "match": {"mccmnc": [{"mcc": "262", "mnc": "03"}], "gid1_prefixes": ["010301"]}},
    {"id": "open.26203.c20311365064", "match": {"mccmnc": [{"mcc": "262", "mnc": "03"}], "imsi_prefix_patterns": ["26203482"]}},
    {"id": "open.26202.8cebd7550c67", "match": {"mccmnc": [{"mcc": "262", "mnc": "02"}]}},
    {"id": "open.26202.5e6cc8d0e19b", "match": {"mccmnc": [{"mcc": "262", "mnc": "02"}], "gid1_prefixes": ["11"]}},
    {"id": "open.26202.db9b35c48658", "match": {"mccmnc": [{"mcc": "262", "mnc": "02"}], "iccid_prefixes": ["893144"]}},
    {"id": "open.302370.9dc7c0c7b085", "match": {"mccmnc": [{"mcc": "302", "mnc": "370"}]}},
    {"id": "open.302370.f6d6383ed91a", "match": {"mccmnc": [{"mcc": "302", "mnc": "370"}], "gid1_prefixes": ["DD"]}},
    {"id": "open.302370.19c2b9f93626", "match": {"mccmnc": [{"mcc": "302", "mnc": "370"}], "android_carrier_ids": [1962], "gid1_prefixes": ["DD"]}},
    {"id": "open.302370.632d3386012f", "match": {"mccmnc": [{"mcc": "302", "mnc": "370"}], "gid1_prefixes": ["2C"]}},
    {"id": "open.302370.4944bb902cb1", "match": {"mccmnc": [{"mcc": "302", "mnc": "370"}, {"mcc": "302", "mnc": "660"}], "android_carrier_ids": [578], "gid1_prefixes": ["2C", "4D"]}},
    {"id": "open.30237.b8efad512dbf", "match": {"mccmnc": [{"mcc": "302", "mnc": "37"}]}},
    {"id": "open.21670.1b3b9f7d0a6f", "match": {"mccmnc": [{"mcc": "216", "mnc": "70"}]}},
    {"id": "open.21670.3d9b6e4451e0", "match": {"mccmnc": [{"mcc": "216", "mnc": "70"}], "imsi_prefix_patterns": ["21670xx1"]}},
    {"id": "open.21670.a90e85c2329e", "match": {"mccmnc": [{"mcc": "216", "mnc": "70"}], "android_carrier_ids": [1535], "imsi_prefix_patterns": ["21670xx2"]}},
    {"id": "fill.00101.<computed:test001_zz>", "kind": "fill_only", "match": {"mccmnc": [{"mcc": "001", "mnc": "01"}]}},
    {"id": "fill.00101.<computed:test001_amarisoft>", "kind": "fill_only", "match": {"mccmnc": [{"mcc": "001", "mnc": "01"}], "gid1_prefixes": ["ABCD2025"]}},
    {"id": "open.99901.000000000001", "match": {"mccmnc": [{"mcc": "999", "mnc": "01"}], "spn": ["STRASSE"]}},
    {"id": "open.99902.000000000001", "match": {"mccmnc": [{"mcc": "999", "mnc": "02"}]}},
    {"id": "open.99902.000000000002", "match": {"mccmnc": [{"mcc": "999", "mnc": "02"}], "gid1_prefixes": ["01"]}}
  ],
  "vectors": [
    {"id": "M1", "sim": {"mcc": "262", "mnc": "07", "imsi": "262070000000001", "spn": "Example", "iccid": "89490700000000000001"}, "stack": ["open.26207.c07dcc040b58"], "serving": "open.26207.c07dcc040b58", "fill_pick": "o2_de"},
    {"id": "M2", "sim": {"mcc": "262", "mnc": "07", "imsi": "262075000000001"}, "stack": ["open.26207.c07dcc040b58", "open.26207.78040a3afcc4"], "serving": "open.26207.78040a3afcc4", "fill_pick": "tchibo_de"},
    {"id": "M3", "sim": {"mcc": "262", "mnc": "07", "imsi": "262074900000001"}, "stack": ["open.26207.c07dcc040b58", "open.26207.1c95803fdfb1"], "serving": "open.26207.1c95803fdfb1", "fill_pick": "o2prepaid_de"},
    {"id": "M4", "sim": {"mcc": "262", "mnc": "07", "imsi": "262075200000001"}, "stack": ["open.26207.c07dcc040b58", "open.26207.2aa389aa6407"], "serving": "open.26207.2aa389aa6407", "fill_pick": "o2_de"},
    {"id": "M5", "sim": {"mcc": "262", "mnc": "07", "imsi": "262070000000002", "carrier_id": 1454, "specific_carrier_id": 1454}, "stack": ["open.26207.c07dcc040b58", "open.26207.394d5585811d"], "serving": "open.26207.394d5585811d", "fill_pick": "o2_de"},
    {"id": "M6", "sim": {"mcc": "262", "mnc": "07", "imsi": "262070000000003", "spn": "alice"}, "stack": ["open.26207.c07dcc040b58", "open.26207.69841ad3698a"], "serving": "open.26207.69841ad3698a", "fill_pick": "26207SPN=ALICE"},
    {"id": "M7", "sim": {"mcc": "262", "mnc": "03", "imsi": "262030000000001", "gid1": "0103010000FFFFFF"}, "stack": ["open.26203.dbb2be7109a6", "open.26203.ec645827a22d"], "serving": "open.26203.ec645827a22d", "fill_pick": "eplus_de"},
    {"id": "M8", "sim": {"mcc": "262", "mnc": "03", "imsi": "262034820000001"}, "stack": ["open.26203.dbb2be7109a6", "open.26203.c20311365064"], "serving": "open.26203.c20311365064", "fill_pick": "enreach_de"},
    {"id": "M9", "sim": {"mcc": "262", "mnc": "02", "imsi": "262020000000002", "spn": "Lidl Connect", "iccid": "89490200000000000002"}, "stack": ["open.26202.8cebd7550c67"], "serving": "open.26202.8cebd7550c67", "fill_pick": "vodafone_de"},
    {"id": "M10", "sim": {"mcc": "262", "mnc": "02", "imsi": "262020000000003", "iccid": "89314400000000000009"}, "stack": ["open.26202.8cebd7550c67", "open.26202.db9b35c48658"], "serving": "open.26202.db9b35c48658", "fill_pick": "vodafone_de"},
    {"id": "M11", "sim": {"mcc": "262", "mnc": "02", "imsi": "262020000000004", "gid1": "11AB"}, "stack": ["open.26202.8cebd7550c67", "open.26202.5e6cc8d0e19b"], "serving": "open.26202.5e6cc8d0e19b", "fill_pick": "vodafone_de"},
    {"id": "M12", "sim": {"mcc": "302", "mnc": "370", "imsi": "302370000000001"}, "stack": ["open.302370.9dc7c0c7b085"], "serving": "open.302370.9dc7c0c7b085", "fill_pick": "fido_ca", "must_not_contain": ["open.30237.b8efad512dbf"]},
    {"id": "M13", "sim": {"mcc": "302", "mnc": "370", "imsi": "302370000000002", "gid1": "DDFF", "carrier_id": 1962, "specific_carrier_id": 1962}, "stack": ["open.302370.9dc7c0c7b085", "open.302370.f6d6383ed91a", "open.302370.19c2b9f93626"], "serving": "open.302370.19c2b9f93626", "fill_pick": "fido_ca"},
    {"id": "M14", "sim": {"mcc": "302", "mnc": "370", "imsi": "302370000000003", "gid1": "2c00", "carrier_id": 578, "specific_carrier_id": 578}, "stack": ["open.302370.9dc7c0c7b085", "open.302370.632d3386012f", "open.302370.4944bb902cb1"], "serving": "open.302370.4944bb902cb1", "fill": [{"entry": "mts_ca", "when": {"kind": "gid1", "value": "2C"}}, {"entry": "fido_ca", "when": null}], "fill_pick": "mts_ca"},
    {"id": "M15", "sim": {"mcc": "302", "mnc": "37", "imsi": "30237000000001"}, "stack": ["open.30237.b8efad512dbf"], "serving": "open.30237.b8efad512dbf", "fill": [], "fill_pick": null},
    {"id": "M16", "sim": {"mcc": "216", "mnc": "70", "imsi": "216709910000000"}, "stack": ["open.21670.1b3b9f7d0a6f", "open.21670.3d9b6e4451e0"], "serving": "open.21670.3d9b6e4451e0", "fill_pick": "21670IMSI=21670XX1XXX"},
    {"id": "M17", "sim": {"mcc": "216", "mnc": "70", "imsi": "216709920000000"}, "stack": ["open.21670.1b3b9f7d0a6f"], "serving": "open.21670.1b3b9f7d0a6f", "fill_pick": "vodafone_hu"},
    {"id": "M18", "sim": {"mcc": "216", "mnc": "70", "imsi": "216709920000001", "carrier_id": 1535, "specific_carrier_id": 1535}, "stack": ["open.21670.1b3b9f7d0a6f", "open.21670.a90e85c2329e"], "serving": "open.21670.a90e85c2329e", "fill_pick": "vodafone_hu"},
    {"id": "M19", "sim": {"mcc": "001", "mnc": "01", "imsi": "001010000000001", "gid1": "ABCD2025FF"}, "stack": ["fill.00101.<computed:test001_zz>", "fill.00101.<computed:test001_amarisoft>"], "serving": "fill.00101.<computed:test001_amarisoft>", "fill_pick": "test001_amarisoft", "note": "stack order is by computed id; both have different specificity, so the order holds whatever the hashes"},
    {"id": "M20", "sim": {"mcc": "001", "mnc": "01", "imsi": "001010000000002"}, "stack": ["fill.00101.<computed:test001_zz>"], "serving": "fill.00101.<computed:test001_zz>", "fill_pick": "test001_zz"},
    {"id": "M21", "sim": {"mcc": "999", "mnc": "99", "imsi": "999990000000001"}, "stack": [], "serving": "default", "fill_pick": null},
    {"id": "M22", "sim": {"mcc": "262", "mnc": "007", "imsi": "262007000000001"}, "stack": [], "serving": "default", "fill_pick": null},
    {"id": "M23", "sim": {"mcc": "999", "mnc": "01", "imsi": "999010000000001", "spn": "Straße"}, "stack": [], "serving": "default", "fill_pick": null},
    {"id": "M24", "sim": {"mcc": "262", "mnc": "07", "imsi": "2620750"}, "stack": ["open.26207.c07dcc040b58"], "serving": "open.26207.c07dcc040b58", "fill_pick": "o2_de"},
    {"id": "M25", "sim": {"mcc": "999", "mnc": "02", "imsi": "999020000000001", "gid1": "0103AA"}, "stack": ["open.99902.000000000001", "open.99902.000000000002"], "serving": "open.99902.000000000002", "fill": [{"entry": "synthetic_0103", "when": {"kind": "gid1", "value": "0103"}}, {"entry": "synthetic_net", "when": null}], "fill_pick": "synthetic_0103"},
    {"id": "M26", "sim": {"mcc": "999", "mnc": "02", "imsi": "999020000000002", "gid1": "0199"}, "stack": ["open.99902.000000000001", "open.99902.000000000002"], "serving": "open.99902.000000000002", "fill_pick": "synthetic_net"},
    {"id": "M27", "sim": {"mcc": "302", "mnc": "370", "imsi": "302370000000004", "gid1": "4D", "carrier_id": 578, "specific_carrier_id": 578}, "stack": ["open.302370.9dc7c0c7b085", "open.302370.4944bb902cb1"], "serving": "open.302370.4944bb902cb1", "fill_pick": "fido_ca"}
  ]
}
"""


def appendix() -> dict:
    return json.loads(APPENDIX_A)


def resolve_fill_only_ids(data: dict) -> dict[str, str]:
    """The appendix writes fill-only ids as fill.00101.<computed:NAME>: spec 2.6 computes them."""
    out = {}
    for rule in data["google_rules"]:
        out[f"fill.{rule['mcc']}{rule['mnc']}.<computed:{rule['canonical_name']}>"] = ocd.fill_only_id(rule)
    return out


def appendix_dataset() -> tuple[dict, dict[str, str]]:
    """The appendix fragment as profiles.json networks, with each profile's
    fill computed by the generator from the appendix's rules."""
    data = appendix()
    ids = resolve_fill_only_ids(data)
    rules = ocd.lane_rules_by_network({"rules": data["google_rules"]})
    networks: dict = {}
    for item in data["profiles"]:
        profile_id = ids.get(item["id"], item["id"])
        match = {"mccmnc": item["match"]["mccmnc"], **{d: item["match"][d] for d in ocd.DIMENSIONS if d in item["match"]}}
        for network in match["mccmnc"]:
            key = f"{network['mcc']}-{network['mnc']}"
            slot = networks.setdefault(key, {"mcc": network["mcc"], "mnc": network["mnc"], "profiles": []})
            slot["profiles"].append({
                "id": profile_id, "kind": item.get("kind", "ocd"), "name": profile_id, "match": match,
                "specificity": ocd.specificity_of(match), "fill": ocd.compute_fill(match, rules.get(key, [])),
                "values": {}, "sources": {}, "alternatives": {}, "apn_rows": 0,
            })
    for slot in networks.values():
        slot["profiles"].sort(key=ocd.stack_order)
    return {"networks": networks}, ids


def sim_of(vector: dict) -> dict:
    sim = dict(vector["sim"])
    sim.setdefault("carrier_id", -1)
    sim.setdefault("specific_carrier_id", -1)
    return sim


class AppendixVectorsTest(unittest.TestCase):
    """The 27 matcher vectors M1 to M27 (spec 4.5 and appendix A)."""

    def test_there_are_27_vectors(self) -> None:
        self.assertEqual([v["id"] for v in appendix()["vectors"]], [f"M{n}" for n in range(1, 28)])

    def test_vectors(self) -> None:
        profiles, ids = appendix_dataset()
        entries = {rule["canonical_name"] for rule in appendix()["google_rules"]}
        for vector in appendix()["vectors"]:
            with self.subTest(vector=vector["id"]):
                explained = ocd.explain_sim(profiles, {"entries": {name: {} for name in entries}}, sim_of(vector))
                self.assertEqual([item["id"] for item in explained["stack"]], [ids.get(i, i) for i in vector["stack"]])
                self.assertEqual(explained["serving"], ids.get(vector["serving"], vector["serving"]))
                self.assertEqual(explained["fill_pick"], vector["fill_pick"])
                if "fill" in vector:
                    self.assertEqual(explained["fill"], vector["fill"])
                for absent in vector.get("must_not_contain", []):
                    self.assertNotIn(absent, [item["id"] for item in explained["stack"]])

    def test_fill_only_profiles_of_the_appendix_rules(self) -> None:
        """Spec 2.6: one fill-only profile per Google rule without an OCD
        profile of exactly its match. The appendix lists the two test PLMN
        ones; its rules also leave enreach_de's second IMSI and synthetic_0103
        without an exact OCD profile."""
        data = appendix()
        ocd_by_network: dict = {}
        for item in data["profiles"]:
            if item.get("kind") == "fill_only":
                continue
            for network in item["match"]["mccmnc"]:
                ocd_by_network.setdefault(f"{network['mcc']}-{network['mnc']}", []).append(item)
        missing = [rule["canonical_name"] + ":" + (rule["mvno"]["value"] if rule["mvno"] else "-")
                   for rule in data["google_rules"] if not ocd.exact_profile_exists(rule, ocd_by_network)]
        self.assertEqual(missing, ["test001_amarisoft:ABCD2025", "test001_zz:-", "enreach_de:26203483", "synthetic_0103:0103"])
        ids = resolve_fill_only_ids(data)
        self.assertTrue(all(ocd.FILL_ID_RE.fullmatch(i) for i in ids.values()))
        zz = ids["fill.00101.<computed:test001_zz>"]
        amarisoft = ids["fill.00101.<computed:test001_amarisoft>"]
        self.assertNotEqual(zz, amarisoft)
        self.assertEqual(zz, "fill.00101." + __import__("hashlib").sha256(b"google-rule\ntest001_zz\n001-01\nnone\n").hexdigest()[:12])

    def test_302_37_is_never_a_302_370_sim_s(self) -> None:
        """M12 and M15: the MNC length is part of the network; a prefix of the IMSI never matches."""
        profiles, _ = appendix_dataset()
        fido = ocd.explain_sim(profiles, None, {"mcc": "302", "mnc": "370", "imsi": "302370000000001"})
        self.assertNotIn("open.30237.b8efad512dbf", [p["id"] for p in fido["stack"]])
        cnt = ocd.explain_sim(profiles, None, {"mcc": "302", "mnc": "37", "imsi": "30237000000001"})
        self.assertEqual([p["id"] for p in cnt["stack"]], ["open.30237.b8efad512dbf"])
        self.assertEqual(ocd.explain_sim(profiles, None, {"mcc": "262", "mnc": "007"})["serving"], "default")


class PrimitivesTest(unittest.TestCase):
    def test_java_equals_ignore_case(self) -> None:
        self.assertTrue(ocd.java_equals_ignore_case("alice", "ALICE"))
        self.assertFalse(ocd.java_equals_ignore_case("Straße", "STRASSE"))  # M23: Python's casefold joins them
        self.assertTrue(ocd.java_equals_ignore_case("STRAßE", "straße"))
        self.assertFalse(ocd.java_equals_ignore_case("C Spire\r", "C Spire"))

    def test_imsi_patterns(self) -> None:
        self.assertTrue(ocd.imsi_pattern_matches("21670xx1", "216709910000000"))
        self.assertFalse(ocd.imsi_pattern_matches("26207500", "2620750"))  # M24: shorter than the pattern
        self.assertTrue(ocd.values_overlap("imsi", "21670xx1", "2167099"))
        self.assertFalse(ocd.values_overlap("imsi", "21670xx2", "21670xx1"))
        self.assertTrue(ocd.value_implies("imsi", "21670991", "21670xx1"))
        self.assertFalse(ocd.value_implies("imsi", "21670xx1", "2167099"))  # a wildcard implies no digit

    def test_fill_conditions(self) -> None:
        rules = [
            {"canonical_name": "a", "mcc": "999", "mnc": "02", "mvno": {"kind": "gid1", "value": "0103"}},
            {"canonical_name": "b", "mcc": "999", "mnc": "02", "mvno": {"kind": "spn", "value": "X"}},
            {"canonical_name": "c", "mcc": "999", "mnc": "02", "mvno": None},
            {"canonical_name": "d", "mcc": "999", "mnc": "02", "mvno": None},
        ]
        self.assertEqual(ocd.compute_fill({"gid1_prefixes": ["01"]}, rules),
                         [{"entry": "a", "when": {"kind": "gid1", "value": "0103"}}, {"entry": "c", "when": None}])
        self.assertEqual(ocd.compute_fill({"gid1_prefixes": ["010300"]}, rules), [{"entry": "a", "when": None}])
        self.assertEqual(ocd.compute_fill({"spn": ["x"]}, rules), [{"entry": "b", "when": None}])
        self.assertEqual(ocd.compute_fill({}, rules[:2]), [])
        fill = [{"entry": "a", "when": {"kind": "gid1", "value": "0103"}}, {"entry": "c", "when": None}]
        self.assertEqual(ocd.pick_fill(fill, {"gid1": "0103aa"}), "a")
        self.assertEqual(ocd.pick_fill(fill, {"gid1": "0103aa"}, {"c"}), "c")  # an entry the lane lacks is skipped

    def test_record_keys_of_the_spec(self) -> None:
        document = json.loads((REPO / "devices/records/configured/x1s.json").read_text(encoding="utf-8"))
        keys = sorted(ocd.record_key_of(r) for r in document["records"])
        self.assertEqual(keys, sorted(ocd.S20_RECORD_KEYS))

    def test_row_key_of_the_spec(self) -> None:
        row = {"apn": "emergency.volte.ims.cnt.net.ec", "carrier": "CNT Emergency", "mcc": "302", "mnc": "37",
               "protocol": "IP", "roaming_protocol": "IPV4V6", "type": "emergency"}
        self.assertEqual(ocd.row_key_of(row), "a:a913d9286c805fdb")


def synthetic_sim(network: dict, profile: dict) -> dict:
    """A SIM that satisfies PROFILE on NETWORK and nothing more specific by intent."""
    match = profile["match"]
    sim = {"mcc": network["mcc"], "mnc": network["mnc"], "carrier_id": -1, "specific_carrier_id": -1}
    if "spn" in match:
        sim["spn"] = match["spn"][0]
    if "imsi_prefix_patterns" in match:
        sim["imsi"] = match["imsi_prefix_patterns"][0].replace("x", "0").replace("X", "0").ljust(15, "0")
    if "gid1_prefixes" in match:
        sim["gid1"] = match["gid1_prefixes"][0]
    if "gid2_prefixes" in match:
        sim["gid2"] = match["gid2_prefixes"][0]
    if "iccid_prefixes" in match:
        sim["iccid"] = match["iccid_prefixes"][0].ljust(19, "0")
    if "android_carrier_ids" in match:
        sim["carrier_id"] = sim["specific_carrier_id"] = match["android_carrier_ids"][0]
    return sim


@unittest.skipUnless((REPO / ocd.FILES["profiles"][1]).is_file(), "needs this checkout's generated/ocd-dataset/")
class PublishedSelectorsTest(unittest.TestCase):
    """The ruling's unit test over every published selector (spec 4.5)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profiles = ocd.read_json_file(REPO / ocd.FILES["profiles"][1])
        cls.index = ocd.read_json_file(REPO / ocd.FILES["apn_index"][1])

    def test_every_selector_matches_its_sim_and_only_on_its_network(self) -> None:
        networks = self.profiles["networks"]
        checked = 0
        for key, network in networks.items():
            siblings = [f"{network['mcc']}-{network['mnc']}{d}" for d in "0123456789"] if len(network["mnc"]) == 2 else [f"{network['mcc']}-{network['mnc'][:2]}"]
            for profile in network["profiles"]:
                sim = synthetic_sim(network, profile)
                stack = ocd.resolve_stack(network["profiles"], sim)
                self.assertIn(profile["id"], [p["id"] for p in stack], f"{profile['id']} does not match its own SIM on {key}")
                self.assertGreaterEqual(stack[-1]["specificity"], profile["specificity"], key)
                own = {f"{n['mcc']}-{n['mnc']}" for n in profile["match"]["mccmnc"]}
                for sibling in siblings:
                    if sibling in own:
                        continue  # the profile lists that network code itself
                    mcc, mnc = sibling.split("-")
                    self.assertFalse(ocd.profile_holds(profile, {**sim, "mcc": mcc, "mnc": mnc}), f"{profile['id']} matched {sibling}")
                    self.assertNotIn(profile["id"], [p["id"] for p in networks.get(sibling, {"profiles": []})["profiles"]])
                checked += 1
        self.assertEqual(checked, sum(len(n["profiles"]) for n in networks.values()))

    def test_apn_rows_go_only_to_their_own_network_code(self) -> None:
        """TelephonyProvider compares numeric with the SIM's MCC+MNC as
        strings: no row of <mcc>-<2-digit mnc> reaches a SIM of that MNC plus
        one digit, nor the reverse. The rows of a two-digit network code whose
        country also has three-digit codes starting with it are listed as
        dead rows (the 302/37 class)."""
        xml = (REPO / "generated/android/apns-conf.xml").read_bytes()
        _, rows = ocd.parse_apn_rows(xml)
        by_numeric: dict[str, list[dict]] = {}
        for _, attributes in rows:
            if "mcc" in attributes:
                by_numeric.setdefault(attributes["mcc"] + attributes["mnc"], []).append(attributes)
        for numeric, items in by_numeric.items():
            for attributes in items:
                self.assertEqual(attributes["mcc"] + attributes["mnc"], numeric)
                if len(attributes["mnc"]) == 2:
                    for digit in "0123456789":
                        self.assertNotEqual(attributes["mcc"] + attributes["mnc"], numeric + digit)
        # North American codes (MCC 302 and 310 to 316) have three-digit
        # MNCs: a SIM there never reports a two-digit one, so such rows are
        # dead (the Samsung prefix import bug of 302/37, round 30).
        dead = sorted(
            f"{a['mcc']}-{a['mnc']} {a.get('carrier', '')}: {a.get('apn', '')} ({a.get('type', '')})"
            for items in by_numeric.values() for a in items
            if len(a["mnc"]) == 2 and a["mcc"] in {"302", "310", "311", "312", "313", "314", "315", "316"}
        )
        print(f"\ndead APN rows (a two-digit MNC under a three-digit-MNC country code): {len(dead)}")
        for line in dead:
            print(f"  {line}")

    def test_index_owners_hold_their_rows(self) -> None:
        known = {p["id"] for n in self.profiles["networks"].values() for p in n["profiles"]}
        for row in self.index["rows"]:
            self.assertTrue(set(row["profiles"]) <= known)

    def test_tie_report(self) -> None:
        ties = ocd.tie_report(self.profiles)
        same = [item for item in ties if item["shared"]]
        print(f"\nprofiles of equal specificity one SIM can match together: {len(ties)} pairs (the later id serves), "
              f"{len(same)} of them with overlapping selectors of one dimension; tools/ocd_dataset.py ties lists them all")
        for item in same[:10]:
            print(f"  {item['network']} specificity {item['specificity']}: {item['first']} < {item['serves']} ({'+'.join(item['shared'])})")
        for item in ties:
            self.assertLess(item["first"].encode(), item["serves"].encode())


class TieFixtureTest(unittest.TestCase):
    def test_disjoint_selectors_do_not_tie(self) -> None:
        profiles = {"networks": {"999-02": {"mcc": "999", "mnc": "02", "profiles": [
            {"id": "open.99902.000000000001", "specificity": 1, "match": {"mccmnc": [{"mcc": "999", "mnc": "02"}], "gid1_prefixes": ["01"]}},
            {"id": "open.99902.000000000002", "specificity": 1, "match": {"mccmnc": [{"mcc": "999", "mnc": "02"}], "gid1_prefixes": ["02"]}},
            {"id": "open.99902.000000000003", "specificity": 1, "match": {"mccmnc": [{"mcc": "999", "mnc": "02"}], "spn": ["X"]}},
        ]}}}
        pairs = [(t["first"][-1], t["serves"][-1], t["shared"]) for t in ocd.tie_report(profiles)]
        self.assertEqual(pairs, [("1", "3", []), ("2", "3", [])])


# ---------------------------------------------------------------- the generator on a small checkout

CARRIERS = ("26207.c07dcc040b58.json", "26207.78040a3afcc4.json", "26207.69841ad3698a.json", "26202.8cebd7550c67.json")


def small_lane(digest: str) -> dict:
    return {
        "schema_version": 1, "based_on_data_digest": digest, "family": "google",
        "provenance": {"lane": "google_carriersettings", "device": "kodiak", "build": "CD1A.260714.001.A9",
                       "carrier_list_version": 80000000582, "others_version": 80000000032, "snapshot": "adevtool 92b73cfa", "state": "public_main"},
        "rules": [
            {"canonical_name": "tchibo_de", "mcc": "262", "mnc": "07", "mvno": {"kind": "imsi", "value": "26207500"}},
            {"canonical_name": "26207SPN=ALICE", "mcc": "262", "mnc": "07", "mvno": {"kind": "spn", "value": "ALICE"}},
            {"canonical_name": "o2_de", "mcc": "262", "mnc": "07", "mvno": None},
            {"canonical_name": "vodafone_de", "mcc": "262", "mnc": "02", "mvno": None},
            {"canonical_name": "test001_zz", "mcc": "001", "mnc": "01", "mvno": None},
        ],
        "entries": {
            "default": {"values": {"gps.longterm_psds_server_1": "https://example.invalid/LTEPO.DAT", "carrier_volte_available_bool": False,
                                   "imsvoice.voice_on_default_bearer_supported_bool": False}},
            "no_sim": {"values": {"carrier_volte_available_bool": False}},
            "o2_de": {"values": {"carrier_volte_available_bool": True, "imsemergency.emergency_domain_preference_int_array": [2, 1, 3],
                                 "imsvoice.amrnb_payload_description_bundle": {"98": {"type": "bundle", "value": {
                                     "imsvoice.amr_codec_attribute_modeset_int_array": {"type": "int_array", "value": [0, 2, 4, 7]}}}}}},
            "tchibo_de": {"values": {"carrier_volte_available_bool": True, "imsemergency.emergency_domain_preference_int_array": [2, 1]}},
            "26207SPN=ALICE": {"values": {}},
            "vodafone_de": {"values": {"carrier_volte_available_bool": True, "iwlan.ike_rekey_hard_timer_in_sec": 86400}},
            "test001_zz": {"values": {}},
        },
    }


LANE_TYPES = {
    "carrier_volte_available_bool": "bool", "gps.longterm_psds_server_1": "string",
    "imsemergency.emergency_domain_preference_int_array": "int_array", "imsvoice.amrnb_payload_description_bundle": "bundle",
    "iwlan.ike_rekey_hard_timer_in_sec": "int", "imsvoice.voice_on_default_bearer_supported_bool": "bool",
}


def make_checkout(base: Path) -> Path:
    """A small checkout: four of this repository's profiles, its tools and
    schemas, the Android outputs generated from them, a small Google lane
    with its key types, and the S20 records."""
    root = base / "repo"
    (root / "carriers/open").mkdir(parents=True)
    for name in CARRIERS:
        shutil.copy2(REPO / "carriers/open" / name, root / "carriers/open" / name)
    shutil.copytree(REPO / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__", "fixtures"))
    shutil.copytree(REPO / "schemas", root / "schemas")
    shutil.copytree(REPO / "devices", root / "devices")
    subprocess.run([sys.executable, str(root / "tools/generate_android_outputs.py"), str(root / "carriers"), str(root / "generated"), "--apn-version", "8"],
                   check=True, capture_output=True)
    digest = json.loads((root / "generated/android/metadata.json").read_text())["data_digest"]
    (root / "generated/ocd-dataset").mkdir(parents=True)
    (root / ocd.FILES["google_lane"][1]).write_bytes(ocd.dump_lines(small_lane(digest), ("entries", "rules")))
    registry = {"schema_version": 1, "description": "test", "keys": {k: {"type": t, "group": None, "origin": ["google"], "fork": None} for k, t in LANE_TYPES.items()}}
    (root / ocd.REGISTRY_PATH).write_text(json.dumps(registry), encoding="utf-8")
    return root


def generate_into(root: Path, generated_at: str | None = None) -> dict:
    result = ocd.generate(root, generated_at, ocd.previous_manifest_of(root))
    ocd.write_files(root, result["files"])
    return result


class GeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = make_checkout(Path(cls.temporary.name))
        cls.result = generate_into(cls.root, "2026-10-25T10:00:00Z")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def fresh(self) -> Path:
        target = Path(tempfile.mkdtemp(dir=self.temporary.name))
        shutil.copytree(self.root, target / "repo")
        return target / "repo"

    def test_validates(self) -> None:
        self.assertEqual(ocd.validate(self.root), [])

    def test_counts_and_profiles(self) -> None:
        counts = self.result["manifest"]["counts"]
        self.assertEqual(counts["records"], 5)
        self.assertEqual(counts["fill_only_profiles"], 1)  # test001_zz on 001-01
        profiles = ocd.read_json_file(self.root / ocd.FILES["profiles"][1])
        o2 = profiles["networks"]["262-07"]["profiles"]
        self.assertEqual([p["id"] for p in o2][0], "open.26207.c07dcc040b58")
        by_id = {p["id"]: p for p in o2}
        self.assertEqual(by_id["open.26207.78040a3afcc4"]["fill"], [{"entry": "tchibo_de", "when": None}])
        self.assertEqual(by_id["open.26207.69841ad3698a"]["fill"], [{"entry": "26207SPN=ALICE", "when": None}])
        self.assertEqual(by_id["open.26207.c07dcc040b58"]["fill"], [{"entry": "o2_de", "when": None}])
        self.assertGreater(by_id["open.26207.c07dcc040b58"]["apn_rows"], 0)
        keys = profiles["keys"]
        self.assertEqual(keys["imsvoice.voice_on_default_bearer_in_roaming_without_qos_bool"],
                         {"type": "bool", "group": None, "origin": ["device_record"], "fork": "ocd"})
        self.assertEqual(keys["imsemergency.emergency_domain_preference_int_array"]["group"], "A")
        self.assertEqual(keys["carrier_metered_apn_types_strings"]["group"], "B")
        self.assertEqual(keys["carrier_volte_available_bool"]["origin"], ["google", "ocd_schema"])
        self.assertIn("use_only_dialed_sim_ecc_list_bool", profiles["groups"]["A"]["names"])

    def test_generated_at_is_kept_when_nothing_changes(self) -> None:
        root = self.fresh()
        again = generate_into(root, "2026-10-26T10:00:00Z")
        self.assertEqual(again["manifest"]["generated_at"], "2026-10-25T10:00:00Z")
        configured = root / "devices/records/configured/x1s.json"
        document = json.loads(configured.read_text())
        document["records"][0]["basis"] = document["records"][0]["basis"] + " (re-read)"
        configured.write_text(json.dumps(document), encoding="utf-8")
        changed = generate_into(root, "2026-10-26T10:00:00Z")
        self.assertEqual(changed["manifest"]["generated_at"], "2026-10-26T10:00:00Z")
        self.assertNotEqual(changed["manifest"]["dataset_digest"], again["manifest"]["dataset_digest"])
        base = again["manifest"]
        self.assertEqual(ocd.validate(root, base), [])
        stale = dict(changed["manifest"])
        self.assertTrue(any("generated_at" in p for p in ocd.validate(root, {**base, "generated_at": "2026-10-27T00:00:00Z"})))
        del stale

    def test_drift_is_refused(self) -> None:
        root = self.fresh()
        lane = json.loads((root / ocd.FILES["google_lane"][1]).read_text())
        lane["entries"]["o2_de"]["values"]["carrier_volte_available_bool"] = False
        (root / ocd.FILES["google_lane"][1]).write_bytes(ocd.dump_lines(lane, ("entries", "rules")))
        problems = ocd.validate(root)
        self.assertTrue(any("size or SHA-256" in p for p in problems), problems)

    def test_privacy_and_imsi_rules_on_main(self) -> None:
        root = self.fresh()
        lane = json.loads((root / ocd.FILES["google_lane"][1]).read_text())
        lane["entries"]["o2_de"]["values"]["gps.longterm_psds_server_1"] = "+491793000333"
        lane["rules"].insert(0, {"canonical_name": "o2_de", "mcc": "262", "mnc": "07", "mvno": {"kind": "imsi", "value": "26207000000001"}})
        (root / ocd.FILES["google_lane"][1]).write_bytes(ocd.dump_lines(lane, ("entries", "rules")))
        generate_into(root)
        published = json.loads((root / ocd.FILES["google_lane"][1]).read_text())
        self.assertNotIn("26207000000001", json.dumps(published), "the generator leaves a rule outside rule 3 out")
        problems = ocd.validate(root)
        self.assertTrue(any("privacy guard" in p for p in problems), problems)
        # The check validate applies to a lane that still carries one.
        self.assertFalse(ocd.lane_rule_within_limits({"mvno": {"kind": "imsi", "value": "26207000001"}}))
        self.assertTrue(ocd.lane_rule_within_limits({"mvno": {"kind": "imsi", "value": "2620700000"}}))

    def test_wrong_type_is_refused(self) -> None:
        root = self.fresh()
        lane = json.loads((root / ocd.FILES["google_lane"][1]).read_text())
        lane["entries"]["vodafone_de"]["values"]["iwlan.ike_rekey_hard_timer_in_sec"] = 1.5
        (root / ocd.FILES["google_lane"][1]).write_bytes(ocd.dump_lines(lane, ("entries", "rules")))
        generate_into(root)
        problems = ocd.validate(root)
        self.assertTrue(any("wrong_type" in p for p in problems), problems)

    def test_group_a_reads_as_a_listed_role(self) -> None:
        """The step 8 change lists group-a-reads.json in the manifest (role
        group_a_reads); the reader's checks take it, typed, either way."""
        root = self.fresh()
        saved = ocd.LIST_GROUP_A_READS
        ocd.LIST_GROUP_A_READS = True
        try:
            result = generate_into(root, "2026-10-29T10:00:00Z")
            self.assertIn("group_a_reads", [e["role"] for e in result["manifest"]["files"]])
            self.assertEqual(ocd.validate(root), [])
        finally:
            ocd.LIST_GROUP_A_READS = saved
        self.assertTrue(any("LIST_GROUP_A_READS" in p for p in ocd.validate(root, regenerate=False)))

    def test_group_a_record_needs_a_proceed_read(self) -> None:
        root = self.fresh()
        configured = root / "devices/records/configured/x1s.json"
        document = json.loads(configured.read_text())
        record = next(r for r in document["records"] if r["record_key"] == "r:937a114148bf73b8")
        read = json.loads((root / "devices/records/reads/r-937a114148bf73b8.json").read_text())
        record["second_agent_read"] = {"reader": read["reader"], "read_at": read["read_at"], "basis": "read",
                                       "reference": "devices/records/reads/r-937a114148bf73b8.json"}
        configured.write_text(json.dumps(document), encoding="utf-8")
        generate_into(root)
        problems = ocd.validate(root)
        if read["verdict"] == "hold":
            self.assertTrue(any("verdict proceed" in p for p in problems), problems)
        else:
            self.assertEqual(problems, [])

    def test_group_b_and_measured_group_a_records_are_refused(self) -> None:
        registry = ocd.read_json_file(self.root / ocd.FILES["profiles"][1])["keys"]
        document = json.loads((self.root / "devices/records/configured/x1s.json").read_text())
        base = copy.deepcopy(document["records"][0])
        measured = {**base, "kind": "measured", "claim": "measured", "first_measured": "2026-10-24", "last_measured": "2026-10-24",
                    "valid_until": "2027-01-22", "level": "L2", "result": "calls_out", "method": "mailbox_call", "bearer": "lte", "n": 1,
                    "carrier": {"scope": "profile", "profile_id": "open.26207.c07dcc040b58"}}
        measured["record_key"] = ocd.record_key_of(measured)
        self.assertEqual(ocd.record_problems(measured, registry, {}, "r"), [])
        group_b = {**measured, "target": {"type": "config", "key": "carrier_metered_apn_types_strings"}, "value": ["default"]}
        group_b["record_key"] = ocd.record_key_of(group_b)
        self.assertTrue(any("record_group_b" in p for p in ocd.record_problems(group_b, registry, {}, "r")))
        group_a = {**measured, "target": {"type": "config", "key": "imsemergency.emergency_domain_preference_int_array"}, "value": [2, 1]}
        group_a["record_key"] = ocd.record_key_of(group_a)
        self.assertTrue(any("record_group_a" in p for p in ocd.record_problems(group_a, registry, {}, "r")))
        wrong = {**measured, "valid_until": "2027-01-23"}
        self.assertTrue(any("valid_until" in p for p in ocd.record_problems(wrong, registry, {}, "r")))
        phone = {**measured, "basis": "called +491701234567"}
        self.assertTrue(any("private data" in p for p in ocd.record_problems(phone, registry, {}, "r")))


def cell_record(**changes) -> dict:
    """A valid round 31 cell record (schema_version 2) for the S20 on o2."""
    record = {
        "kind": "measured", "device": {"codename": "x1s", "model": "SM-G981B"},
        "rom": {"family": "lineageos", "line": "24.0", "forks": ["ocd"], "incremental": "eng.bela.20261028.120000"},
        "ims_stack": {"id": "aosp_imsstack", "fork": "ocd", "version": None},
        "carrier": {"scope": "profile", "profile_id": "open.26207.c07dcc040b58"},
        "target": {"type": "config", "key": "carrier_volte_available_bool"}, "value_kind": "value", "value": True,
        "claim": "measured", "label": None, "basis": "calls out over LTE and Wi-Fi calling stayed up past 15 s",
        "level": "L3", "result": "works", "method": "mailbox_call+real_call", "bearer": "lte", "n": 2,
        "first_measured": "2026-10-28", "last_measured": "2026-10-28", "valid_until": "2027-01-26",
        "data": {"commit": "a2f96412b58f" + "0" * 28, "data_digest": "sha256:" + "0" * 64}, "tester": "owner",
        "differs_between_sims": None,
    }
    record.update(changes)
    record["record_key"] = ocd.cell_record_key_of(record)
    return record


class Round31RecordsTest(unittest.TestCase):
    """Rule round 31 (keys): records keyed by cell, kind measured only, and no
    record without a carrier key; the five S20 records are the one exception
    until implementation order step 8."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ocd.read_json_file(REPO / ocd.FILES["profiles"][1])["keys"]

    def test_cell_record_key_vectors(self) -> None:
        self.assertEqual(cell_record()["record_key"], "r:3e3c08bfd829cafe")
        other = cell_record(carrier={"scope": "sim_key", "mcc": "262", "mnc": "02", "gid1": "ff"},
                            rom={"family": "lineageos", "line": "24.0", "forks": [], "incremental": "1"},
                            ims_stack={"id": "aosp_imsstack", "fork": None, "version": 1},
                            target={"type": "apn", "row_key": "a:f3b816097ac0ee1b", "op": "omit"})
        self.assertEqual(other["record_key"], "r:282f49c73c83c8bb")
        # The incremental and the stack version are recorded, not matched.
        later = cell_record(rom={"family": "lineageos", "line": "24.0", "forks": ["ocd"], "incremental": "eng.bela.20261101.080000"},
                            ims_stack={"id": "aosp_imsstack", "fork": "ocd", "version": 35})
        self.assertEqual(later["record_key"], cell_record()["record_key"])

    def test_a_valid_cell_record_passes_its_rules_and_schema(self) -> None:
        record = cell_record()
        self.assertEqual(ocd.cell_record_problems(record, self.registry, "r"), [])
        self.assertTrue(ocd.is_cell_record(record))
        self.assertEqual(ocd.schema_check(REPO, {"schema_version": 2, "based_on_data_digest": "sha256:" + "0" * 64, "expire_days": 90,
                                                 "records": [record]}, "cell-records.schema.json", "r"), [])

    def test_a_cell_record_without_a_carrier_key_is_refused(self) -> None:
        record = cell_record()
        record["carrier"] = {"scope": "all"}
        problems = ocd.cell_record_problems(record, self.registry, "r")
        self.assertTrue(any("record_no_carrier" in p for p in problems), problems)
        self.assertTrue(ocd.schema_check(REPO, {"schema_version": 2, "based_on_data_digest": "sha256:" + "0" * 64, "expire_days": 90,
                                                "records": [record]}, "cell-records.schema.json", "r"))

    def test_cell_record_refusals(self) -> None:
        cases = {
            "record_kind": cell_record(kind="configured_device", claim="configured"),
            "sorted list": cell_record(rom={"family": "lineageos", "line": "24.0", "forks": ["ocd", "abc"], "incremental": "1"}),
            "INCREMENTAL": cell_record(rom={"family": "lineageos", "line": "24.0", "forks": [], "incremental": ""}),
            "record_group_a": cell_record(target={"type": "config", "key": "imsemergency.emergency_domain_preference_int_array"}, value=[2, 1]),
            "record_group_b": cell_record(target={"type": "config", "key": "carrier_metered_apn_types_strings"}, value=["default"]),
            "valid_until": cell_record(valid_until="2027-01-27"),
            "private data": cell_record(basis="called +491701234567"),
            "fork": cell_record(target={"type": "config", "key": "imsvoice.voice_on_default_bearer_in_roaming_without_qos_bool"},
                                ims_stack={"id": "aosp_imsstack", "fork": None, "version": None}),
        }
        for expected, record in cases.items():
            problems = ocd.cell_record_problems(record, self.registry, "r")
            text = " ".join(problems)
            self.assertTrue(expected.lower() in text.lower() or (expected == "INCREMENTAL" and "incremental" in text), (expected, problems))
        stale = cell_record()
        stale["record_key"] = "r:" + "0" * 16
        self.assertTrue(any("cell lines" in p for p in ocd.cell_record_problems(stale, self.registry, "r")))

    def test_round_30_records_without_a_carrier_key_are_refused_but_the_five(self) -> None:
        document = json.loads((REPO / "devices/records/configured/x1s.json").read_text(encoding="utf-8"))
        for record in document["records"]:
            self.assertIn(record["record_key"], ocd.LEGACY_DEVICE_ONLY_RECORDS)
            self.assertEqual(ocd.record_problems(record, self.registry, {}, "r"), [])
        sixth = copy.deepcopy(document["records"][0])
        sixth["target"] = {"type": "config", "key": "carrier_volte_available_bool"}
        sixth["record_key"] = ocd.record_key_of(sixth)
        problems = ocd.record_problems(sixth, self.registry, {}, "r")
        self.assertTrue(any("record_no_carrier" in p for p in problems), problems)
        profiled = {**copy.deepcopy(document["records"][0]), "carrier": {"scope": "profile", "profile_id": "open.26207.c07dcc040b58"}}
        profiled["record_key"] = ocd.record_key_of(profiled)
        problems = ocd.record_problems(profiled, self.registry, {}, "r")
        self.assertTrue(any("record_kind" in p for p in problems), problems)

    def test_served_records_follow_the_schema_version(self) -> None:
        document = json.loads((REPO / "devices/records/configured/x1s.json").read_text(encoding="utf-8"))
        mixed = document["records"] + [cell_record()]
        self.assertEqual(ocd.SERVED_RECORDS_SCHEMA_VERSION, 1)
        self.assertEqual([r["record_key"] for r in ocd.served_records(mixed, 1)], [r["record_key"] for r in document["records"]])
        self.assertEqual([r["record_key"] for r in ocd.served_records(mixed, 2)], ["r:3e3c08bfd829cafe"])


def tiny_profiles(values: dict, fill: list) -> dict:
    profile = {"id": "open.26207.c07dcc040b58", "kind": "ocd", "name": "O2", "match": {"mccmnc": [{"mcc": "262", "mnc": "07"}]},
               "specificity": 0, "fill": fill, "values": values, "sources": {k: ["lineageos_device_overlays"] for k in values},
               "alternatives": {}, "apn_rows": 0}
    keys = {"rtt_supported_bool": {"type": "bool", "group": "A", "origin": ["google"], "fork": None},
            "carrier_volte_available_bool": {"type": "bool", "group": None, "origin": ["google"], "fork": None},
            "allow_emergency_numbers_in_call_log_bool": {"type": "bool", "group": "A", "origin": ["google"], "fork": None}}
    return {"keys": keys, "groups": {"A": {"pattern": ocd.GROUP_A_PATTERN, "names": list(ocd.GROUP_A_NAMES),
                                           "keys": ["allow_emergency_numbers_in_call_log_bool", "rtt_supported_bool"]}},
            "networks": {"262-07": {"mcc": "262", "mnc": "07", "profiles": [profile]}}}


def group_a_read(**changes) -> dict:
    read = {"schema": "ocd-group-a-read/2", "subject": "value", "key": "rtt_supported_bool", "value": True,
            "families": ["lineageos_device_overlays"], "profiles": ["open.26207.c07dcc040b58"], "rom_family": "lineageos",
            "ims_stack": "aosp_imsstack", "effect": "call_path", "reader": "an independent reader", "builder": "the importer",
            "read_at": "2026-10-28T19:00:00Z", "sources_read": ["frameworks/base/telephony/java/android/telephony/CarrierConfigManager.java:1"],
            "findings": {"effect": "e", "basis": "b", "risk": "r"}, "verdict": "proceed", "notes": "n"}
    read.update(changes)
    return read


class Round31GroupATest(unittest.TestCase):
    """Rule round 31 (emergencyValues): a group A value that differs from the
    Google lane waits for an independent read; a display_only key read
    takes the key out of group A."""

    LANE = {"entries": {"default": {"values": {}}, "o2_de": {"values": {"rtt_supported_bool": False}}}}

    def test_candidates(self) -> None:
        differs = ocd.group_a_candidates(tiny_profiles({"rtt_supported_bool": True, "carrier_volte_available_bool": True},
                                                       [{"entry": "o2_de", "when": None}]), self.LANE)
        self.assertEqual([(c["key"], c["value"], list(c["profiles"])) for c in differs],
                         [("rtt_supported_bool", True, ["open.26207.c07dcc040b58"])])
        same = ocd.group_a_candidates(tiny_profiles({"rtt_supported_bool": False}, [{"entry": "o2_de", "when": None}]), self.LANE)
        self.assertEqual(same, [])
        # A conditional fill leaves the default-only bundle, which lacks the key.
        conditional = ocd.group_a_candidates(tiny_profiles({"rtt_supported_bool": False}, [{"entry": "o2_de", "when": {"kind": "spn", "value": "x"}}]), self.LANE)
        self.assertEqual(len(conditional), 1)

    def test_reads_cover_candidates_and_key_reads_leave_group_a(self) -> None:
        profiles = tiny_profiles({"rtt_supported_bool": True, "allow_emergency_numbers_in_call_log_bool": True}, [{"entry": "o2_de", "when": None}])
        _, none = ocd.group_a_documents("sha256:" + "0" * 64, profiles, self.LANE, {})
        self.assertEqual(sorted(p["key"] for p in none["pending"]), ["allow_emergency_numbers_in_call_log_bool", "rtt_supported_bool"])
        value_path = "devices/records/reads/group-a/rtt_supported_bool.000000000001.json"
        key_path = "devices/records/reads/group-a/allow_emergency_numbers_in_call_log_bool.000000000002.json"
        reads = {
            value_path: group_a_read(),
            key_path: group_a_read(subject="key", key="allow_emergency_numbers_in_call_log_bool", value=None, families=[], profiles=[], effect="display_only"),
        }
        for path, read in reads.items():
            self.assertEqual(ocd.group_a_read_problems(read, path), [])
            self.assertEqual(ocd.schema_check(REPO, read, "group-a-read.schema.json", path), [])
        served, status = ocd.group_a_documents("sha256:" + "0" * 64, profiles, self.LANE, reads)
        self.assertEqual(status["pending"], [])
        self.assertEqual(status["left_group_a"], ["allow_emergency_numbers_in_call_log_bool"])
        # The S20 spec's R31.7 shape: one item per read, profile and family.
        self.assertEqual(served["reads"], [{
            "read_id": ocd.group_a_read_id(value_path, "open.26207.c07dcc040b58", "lineageos_device_overlays"), "key": "rtt_supported_bool",
            "value": True, "family": "lineageos_device_overlays", "profile_id": "open.26207.c07dcc040b58", "rom_family": "lineageos",
            "ims_stack": "aosp_imsstack", "ims_stack_fork": None, "verdict": "proceed", "reader": "an independent reader",
            "read_at": "2026-10-28T19:00:00Z", "reference": value_path}])
        self.assertEqual([(f["key"], f["finding"], f["verdict"]) for f in served["key_findings"]],
                         [("allow_emergency_numbers_in_call_log_bool", "display_only", "proceed")])
        self.assertRegex(served["reads"][0]["read_id"], r"^gar:[0-9a-f]{16}$")
        self.assertEqual(ocd.schema_check(REPO, served, "ocd-dataset-group-a-reads.schema.json", "r"), [])
        self.assertEqual(ocd.schema_check(REPO, status, "ocd-dataset-group-a-pending.schema.json", "p"), [])
        self.assertEqual(ocd.left_group_a_keys(reads), {"allow_emergency_numbers_in_call_log_bool"})
        self.assertIsNone(ocd.group_of("allow_emergency_numbers_in_call_log_bool", {"allow_emergency_numbers_in_call_log_bool"}))
        self.assertEqual(ocd.group_of("allow_emergency_numbers_in_call_log_bool"), "A")
        # Another basis (source family) needs its own read.
        other = dict(reads)
        other[value_path] = group_a_read(families=["google"])
        served, status = ocd.group_a_documents("sha256:" + "0" * 64, profiles, self.LANE, other)
        self.assertEqual([p["key"] for p in status["pending"]], ["rtt_supported_bool"])
        self.assertEqual(served["reads"], [])
        # A profile whose value has no recorded family gets no item: no read can admit it.
        bare = tiny_profiles({"rtt_supported_bool": True}, [{"entry": "o2_de", "when": None}])
        bare["networks"]["262-07"]["profiles"][0]["sources"] = {}
        served, status = ocd.group_a_documents("sha256:" + "0" * 64, bare, self.LANE, {value_path: group_a_read(families=[])})
        self.assertEqual((served["reads"], [u["profile_id"] for u in status["unrecorded_basis"]]), ([], ["open.26207.c07dcc040b58"]))

    def test_read_refusals(self) -> None:
        self.assertTrue(ocd.group_a_read_problems(group_a_read(reader="the importer"), "r"))
        self.assertTrue(ocd.group_a_read_problems(group_a_read(subject="key", value=None, families=[], profiles=[], effect="call_path"), "r"))
        self.assertTrue(ocd.group_a_read_problems(group_a_read(profiles=[]), "r"))
        self.assertTrue(ocd.group_a_read_problems(group_a_read(notes="call +491701234567"), "r"))
        self.assertFalse(ocd.group_a_read_problems(group_a_read(verdict="hold"), "r"))
        # The prefix and replace keys never leave group A (round 31; the S20 spec's R31.7).
        for key in ocd.GROUP_A_NEVER_LEAVE:
            named = {"x": group_a_read(subject="key", key=key, value=None, families=[], profiles=[], effect="display_only")}
            self.assertEqual(ocd.left_group_a_keys(named), set())

    def test_the_reads_on_main(self) -> None:
        document = ocd.read_json_file(REPO / ocd.GROUP_A_READS_FILE)
        status = ocd.read_json_file(REPO / ocd.GROUP_A_PENDING_FILE)
        profiles = ocd.read_json_file(REPO / ocd.FILES["profiles"][1])
        for key in status["left_group_a"]:
            self.assertIsNone(profiles["keys"][key]["group"], key)
            self.assertNotIn(key, profiles["groups"]["A"]["keys"])
        self.assertEqual(len({r["read_id"] for r in document["reads"]}), len(document["reads"]))
        print(f"\ngroup A reads on main: {len(document['reads'])} read items "
              f"({sum(r['verdict'] == 'proceed' for r in document['reads'])} proceed), {len(status['key_reads'])} key reads, "
              f"left group A: {status['left_group_a']}, pending: {len(status['pending'])}, unrecorded basis: {len(status['unrecorded_basis'])}")


class Round31WithheldTest(unittest.TestCase):
    def test_withheld_list(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(REPO / "schemas", root / "schemas")
            shutil.copytree(REPO / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__", "fixtures"))
            (root / ocd.DATASET_DIR).mkdir(parents=True)
            lane = {"entries": {"vodafone_de": {"values": {"carrier_volte_available_bool": True}}}}
            digest = "sha256:" + "1" * 64
            document = {"schema_version": 1, "based_on_data_digest": digest, "lane": {"device": "kodiak", "build": "b", "snapshot": "s"},
                        "withheld": [{"entry": "vodafone_de", "key": "default_vm_number_string", "rules": ["long_decimal_identity"]}],
                        "by_key": {"default_vm_number_string": 1}}
            (root / ocd.WITHHELD_FILE).write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(ocd.withheld_problems(root, lane, digest), [])
            document["withheld"][0]["key"] = "carrier_volte_available_bool"
            document["by_key"] = {"carrier_volte_available_bool": 1}
            (root / ocd.WITHHELD_FILE).write_text(json.dumps(document), encoding="utf-8")
            self.assertTrue(any("the lane carries it" in p for p in ocd.withheld_problems(root, lane, digest)))


@unittest.skipUnless((REPO / ocd.FILES["manifest"][1]).is_file(), "needs this checkout's generated/ocd-dataset/")
class ReaderChecksTest(unittest.TestCase):
    """Checks 4 to 10 of spec 2.12 on this repository's dataset, and their refusals."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.files = {role: (REPO / path).read_bytes() for role, (_, path, _) in ocd.FILES.items() if path and (REPO / path).is_file()}

    def test_this_dataset_passes(self) -> None:
        problems, parsed = ocd.check_dataset_files(self.files)
        self.assertEqual(problems, [])
        self.assertEqual(parsed["manifest"]["google_lane"], "included")

    def test_refusals(self) -> None:
        def refused(role: str, data: bytes, code: str) -> None:
            problems, _ = ocd.check_dataset_files({**self.files, role: data})
            self.assertTrue(any(code in p for p in problems), (code, problems[:3]))

        refused("apn_index", self.files["apn_index"] + b" ", "sha256_mismatch")
        manifest = json.loads(self.files["manifest"])
        manifest["format"] = "other"
        refused("manifest", json.dumps(manifest).encode(), "schema_unknown")
        manifest = json.loads(self.files["manifest"])
        manifest["dataset_digest"] = "sha256:" + "0" * 64
        refused("manifest", json.dumps(manifest).encode(), "dataset_digest_mismatch")
        refused("manifest", b'{"a":1,"a":2}', "parse_error")


class LanePrefixLimitsTest(unittest.TestCase):
    """Rule 3 on the Google lane (rule round 32, the judged ruling of
    2026-10-28): the same subscriber_prefix_ok as every published selector.
    The values are synthetic, on the test network 001-01."""

    def lane(self, *rules: dict) -> dict:
        names = {rule["canonical_name"] for rule in rules}
        return {"rules": list(rules), "entries": {name: {"values": {}} for name in names | {"default", "no_sim", "orphan_xx"}}}

    @staticmethod
    def rule(name: str, kind: str | None, value: str | None = None) -> dict:
        return {"canonical_name": name, "mcc": "001", "mnc": "01", "mvno": {"kind": kind, "value": value} if kind else None}

    def test_imsi_rules_of_11_to_13_characters_are_left_out(self) -> None:
        for value in ("00101123456", "001011234567", "0010112345678"):
            lane, left_out = ocd.within_prefix_limits(self.lane(self.rule("long_xx", "imsi", value), self.rule("net_xx", None)))
            self.assertEqual([r["canonical_name"] for r in lane["rules"]], ["net_xx"])
            self.assertEqual(left_out, [{"canonical_name": "long_xx", "network": "001-01", "kind": "imsi", "characters": len(value)}])
            self.assertNotIn(value, json.dumps(left_out), "a left-out value is never reported")

    def test_ten_characters_and_trailing_x_are_kept(self) -> None:
        for value in ("0010112345", "00101123xx", "001011234xxxx"):
            lane, left_out = ocd.within_prefix_limits(self.lane(self.rule("ok_xx", "imsi", value)))
            self.assertEqual(left_out, [], value)

    def test_iccid_of_13_kept_and_14_left_out(self) -> None:
        _, kept = ocd.within_prefix_limits(self.lane(self.rule("ok_xx", "iccid", "8949000000001")))
        self.assertEqual(kept, [])
        _, left_out = ocd.within_prefix_limits(self.lane(self.rule("long_xx", "iccid", "89490000000012")))
        self.assertEqual(len(left_out), 1)

    def test_entries_only_left_out_rules_named_go_too(self) -> None:
        lane, _ = ocd.within_prefix_limits(self.lane(self.rule("long_xx", "imsi", "00101123456"), self.rule("net_xx", None)))
        self.assertEqual(sorted(lane["entries"]), ["default", "net_xx", "no_sim"])

    def test_the_published_lane_keeps_rule_3(self) -> None:
        path = REPO / "generated/ocd-dataset/google-lane.json"
        if path.is_file():
            lane = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(all(ocd.lane_rule_within_limits(rule) for rule in lane["rules"]))
            named = {rule["canonical_name"] for rule in lane["rules"]} | set(ocd.UNNAMED_LANE_ENTRIES)
            self.assertEqual(set(lane["entries"]) - named, set())


if __name__ == "__main__":
    unittest.main()
