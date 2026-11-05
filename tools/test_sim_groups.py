#!/usr/bin/env python3
"""tools/sim_groups.py: brands per SIM group (migration step 6). Every value here
is synthetic; the networks are the test networks 001-01 and 001-02."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import sim_groups as sg

PLAIN = "open.00101.000000000001"
GID = "open.00101.000000000002"
GID_SPN = "open.00101.000000000003"
OTHER = "open.00102.000000000004"
MATCHES = {
    PLAIN: {"mccmnc": ["00101"]},
    GID: {"mccmnc": ["00101"], "gid1_prefixes": ["44"]},
    GID_SPN: {"mccmnc": ["00101"], "gid1_prefixes": ["44"], "spn": ["Second"]},
    OTHER: {"mccmnc": ["00102"]},
}


def entry(key, kind, profiles, networks=("00101",), host_only=False):
    return {
        "key": key, "name": key, "kind": kind, "country": "ZZ", "operator_key": "zz.net", "host_networks": list(networks),
        "host_only": host_only, "labels": [],
        "selectors": [{"match": MATCHES[pid], "profile_id": pid, "families": ["lineageos"]} for pid in profiles],
    }


def tree(root: Path, entries) -> None:
    (root / "carriers/open").mkdir(parents=True)
    (root / "generated/operators").mkdir(parents=True)
    for pid, match in MATCHES.items():
        (root / f"carriers/open/{pid.removeprefix('open.')}.json").write_text(json.dumps({"profile_id": pid, "match": match}), encoding="utf-8")
    (root / "generated/operators/carrier-identity.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")


class SimGroupsTest(unittest.TestCase):
    def rows(self, entries):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree(root, entries)
            return {row["profile_id"]: row for row in sg.build(root)["profiles"]}

    def test_a_plain_profile_alone_is_tellable(self):
        rows = self.rows([entry("zz.net", "operator", [PLAIN])])
        self.assertEqual(rows[PLAIN], {"profile_id": PLAIN, "brands": ["zz.net"], "tellable": "yes"})

    def test_a_host_only_brand_makes_the_plain_profile_not_tellable(self):
        rows = self.rows([entry("zz.net", "operator", [PLAIN]), entry("zz.brand", "brand", [], host_only=True)])
        self.assertEqual(rows[PLAIN]["brands"], ["zz.brand", "zz.net"])
        self.assertEqual(rows[PLAIN]["tellable"], "no")

    def test_a_host_only_brand_on_another_network_changes_nothing(self):
        rows = self.rows([entry("zz.net", "operator", [PLAIN]), entry("zz.brand", "brand", [], networks=("00102",), host_only=True)])
        self.assertEqual(rows[PLAIN]["tellable"], "yes")

    def test_a_rule_inside_another_brands_rule_is_ambiguous(self):
        rows = self.rows([entry("zz.first", "brand", [GID]), entry("zz.second", "brand", [GID_SPN])])
        self.assertEqual(rows[GID], {"profile_id": GID, "brands": ["zz.first", "zz.second"], "tellable": "ambiguous"})
        self.assertEqual(rows[GID_SPN]["tellable"], "yes")

    def test_a_shared_profile_is_ambiguous(self):
        rows = self.rows([entry("zz.first", "brand", [GID]), entry("zz.second", "brand", [GID])])
        self.assertEqual(rows[GID]["tellable"], "ambiguous")

    def test_a_profile_the_table_does_not_reach_has_no_row(self):
        rows = self.rows([entry("zz.net", "operator", [PLAIN])])
        self.assertNotIn(OTHER, rows)
        self.assertNotIn(GID, rows)

    def test_check_refuses_a_hand_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree(root, [entry("zz.net", "operator", [PLAIN])])
            document = sg.build(root)
            (root / sg.FILE).write_text(sg.dump(document), encoding="utf-8")
            self.assertEqual(sg.problems(root), [])
            document["profiles"][0]["tellable"] = "no"
            (root / sg.FILE).write_text(sg.dump(document), encoding="utf-8")
            self.assertTrue(any("differs" in line for line in sg.problems(root)))


if __name__ == "__main__":
    unittest.main()
