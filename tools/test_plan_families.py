#!/usr/bin/env python3
"""tools/plan_families.py: plan families as labels over existing profiles
(migration step 7). Every value here is synthetic; the networks are the test
networks 001-01 and 001-02."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import plan_families as pf

PARENT = "open.00101.000000000001"
CHILD = "open.00101.000000000002"
OTHER = "open.00101.000000000003"
MATCHES = {
    PARENT: {"mccmnc": ["00101"], "android_carrier_ids": [100]},
    CHILD: {"mccmnc": ["00101"], "imsi_prefix_patterns": ["0010149"]},
    OTHER: {"mccmnc": ["00101"], "gid1_prefixes": ["AA"]},
}
TABLE = {
    "source": {"sha256": "0" * 64},
    "version": 7,
    "rows": [
        {"carrier_id": 100, "mccmnc": "00101"},
        {"carrier_id": 10003, "parent_carrier_id": 100, "mccmnc": "00101", "imsi_prefix_xpattern": "0010149"},
        {"carrier_id": 10004, "parent_carrier_id": 100, "mccmnc": "00101", "gid1": "aa"},
        {"carrier_id": 10004, "parent_carrier_id": 100, "mccmnc": "00102", "gid1": "aa"},
    ],
}
NAMES = {
    "source_sha256": "0" * 64,
    "names": {"100": "Test", "10003": "testprepaid_zz", "10004": "Test 5G SA"},
    "parents": {"10003": 100, "10004": 100},
}


def tree(root: Path) -> None:
    (root / "carriers/open").mkdir(parents=True)
    (root / "generated/operators").mkdir(parents=True)
    for pid, match in MATCHES.items():
        (root / f"carriers/open/{pid.removeprefix('open.')}.json").write_text(json.dumps({"profile_id": pid, "match": match}), encoding="utf-8")


class PlanFamiliesTest(unittest.TestCase):
    def families(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree(root)
            return {item["android_carrier_id"]: item for item in pf.build(root, TABLE, NAMES)["families"]}

    def test_a_child_id_labels_the_profile_that_states_its_rule(self):
        family = self.families()[10003]
        self.assertEqual(family["profiles"], [CHILD])
        self.assertEqual(family["parent_profiles"], [PARENT])
        self.assertEqual(family["segment"], "prepaid")
        self.assertEqual(family["rules_without_profile"], 0)

    def test_gid1_compares_as_android_stores_it(self):
        self.assertEqual(self.families()[10004]["profiles"], [OTHER])

    def test_a_rule_no_profile_states_is_counted_and_not_filled_in(self):
        family = self.families()[10004]
        self.assertEqual(family["rules_without_profile"], 1)
        self.assertEqual(family["segment"], "5g_sa")

    def test_only_a_child_id_is_a_family(self):
        self.assertNotIn(100, self.families())

    def test_segments(self):
        for name, segment in (("Telia SE B2B", "business"), ("AT&T 5G", "5g"), ("AT&T 5G SA", "5g_sa"), ("pcmobile_postpaid_telus", "postpaid"), ("Tracfone-ATT", "other")):
            self.assertEqual(pf.segment_of(name), segment)

    def test_the_names_must_read_the_same_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree(Path(tmp))
            with self.assertRaises(pf.two_answers.TwoAnswersError):
                pf.build(Path(tmp), TABLE, {**NAMES, "source_sha256": "1" * 64})


class RepositoryTest(unittest.TestCase):
    def test_this_repository(self):
        root = Path(__file__).resolve().parents[1]
        if (root / pf.FILE).is_file():
            self.assertEqual(pf.problems(root), [])


if __name__ == "__main__":
    unittest.main()
