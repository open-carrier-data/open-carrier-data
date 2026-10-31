#!/usr/bin/env python3
"""Tests for tools/two_answers.py: depends_on and for_you (rule round 45, item 4)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_ids as ids  # noqa: E402
import two_answers as ta  # noqa: E402
import validate_public_carrier_data as validator  # noqa: E402

CAPS = {key: "unknown" for key in sorted(validator.CAPABILITY_KEYS)}


def profile(match: dict, **caps: str) -> dict:
    return {"schema_version": 1, "profile_id": ids.hash_id(match), "display_name": "x", "match": match,
            "capabilities": {**CAPS, **caps}}


def statement(sid: str, key: str, service: str, status: str, scope: str, codes: list[str], host_only: bool = False, **extra) -> dict:
    return {"id": sid, "identity_key": key, "service": service, "status": status, "scope": scope, "mccmnc": codes,
            "host_only": host_only, **extra}


def entry(key: str, name: str, networks: list[str], selectors: list[dict] = (), host_only: bool = False) -> dict:
    return {"key": key, "name": name, "host_networks": networks, "host_only": host_only,
            "selectors": [{"match": p["match"], "profile_id": p["profile_id"], "families": ["x"]} for p in selectors]}


PLAIN = profile({"mccmnc": ["26202"]}, vowifi="supported", volte="supported", mms="unsupported")
GID11 = profile({"mccmnc": ["26202"], "gid1_prefixes": ["11"]}, vowifi="supported")
TELEKOM_PLAIN = profile({"mccmnc": ["26201"]}, volte="supported")
CONGSTAR = profile({"mccmnc": ["26201"], "gid1_prefixes": ["44"]}, volte="supported")
FRAENK = profile({"mccmnc": ["26201"], "gid1_prefixes": ["44"], "spn": ["fraenk"]}, volte="supported")
OTHER44 = profile({"mccmnc": ["26201"], "gid1_prefixes": ["44", "45"]}, volte="supported")
TWO_NETWORKS = profile({"mccmnc": ["26202", "26204"], "spn": ["Brand"]}, mms="unsupported")
STATEMENTS = [
    statement("de.vodafone.mms", "de.vodafone", "mms", "ended", "network", ["26202"]),
    statement("de.vodafone.wifi_calling", "de.vodafone", "wifi_calling", "offered", "brand", ["26202"]),
    statement("de.vodafone.volte_roaming", "de.vodafone", "volte_roaming", "offered", "brand", ["26202"]),
    statement("de.lidl-connect.wifi_calling", "de.lidl-connect", "wifi_calling", "offered", "brand", ["26202"], host_only=True),
    statement("de.1und1.wifi_calling", "de.1und1", "wifi_calling", "not_offered", "brand", ["26202"]),
    statement("de.congstar.volte", "de.congstar", "volte", "offered", "brand", ["26201"]),
    statement("de.congstar.vonr", "de.congstar", "vonr", "not_offered", "brand", ["26201"]),
    statement("de.fraenk.volte", "de.fraenk", "volte", "offered", "brand", ["26201"]),
    statement("de.telekom.volte", "de.telekom", "volte", "unknown", "brand", ["26201"], previous_status="offered",
              lapsed={"reason": "not_confirmed_180_days", "since": "2026-10-01"}),
]
IDENTITY = [
    entry("de.vodafone", "Vodafone Deutschland", ["26202"], [PLAIN]),
    entry("de.1und1", "1&1", ["26202"], [GID11]),
    entry("de.lidl-connect", "LIDL Connect", ["26202"], host_only=True),
    entry("de.telekom", "Telekom Deutschland", ["26201"], [TELEKOM_PLAIN]),
    entry("de.congstar", "congstar", ["26201"], [CONGSTAR]),
    entry("de.fraenk", "fraenk", ["26201"], [FRAENK]),
]


def write_tree(root: Path, profiles: list[dict], statements=STATEMENTS, identity=IDENTITY, variants=None, evidence=None) -> Path:
    folder = root / "carriers" / "open"
    folder.mkdir(parents=True, exist_ok=True)
    for path in folder.glob("*.json"):
        path.unlink()
    for item in profiles:
        (folder / f"{item['profile_id'].split('.', 1)[1]}.json").write_text(ta.dump_profile(item), encoding="utf-8")
    (root / "generated/operators").mkdir(parents=True, exist_ok=True)
    (root / ta.STATEMENTS).write_text(json.dumps({"statements": statements}), encoding="utf-8")
    (root / ta.IDENTITY).write_text(json.dumps({"entries": identity}), encoding="utf-8")
    (root / "generated/devices").mkdir(parents=True, exist_ok=True)
    (root / ta.VARIANTS).write_text(json.dumps({"profiles": variants or {}}), encoding="utf-8")
    (root / ta.EVIDENCE).write_text(json.dumps({"profiles": evidence or []}), encoding="utf-8")
    return root


class DependsOnTest(unittest.TestCase):
    def test_reasons_come_only_from_recorded_bases(self) -> None:
        p = profile({"mccmnc": ["26202"]}, volte="conditional", vowifi="conditional", rcs="conditional", mms="supported")
        variants = {
            "volte": [{"state": "on", "stack": "stock", "devices": ["a"]}, {"state": "off", "stack": "stock", "devices": ["b"]}],
            "vowifi": [{"state": "on", "stack": "stock", "devices": ["a"]}, {"state": "off", "stack": "lineageos", "devices": ["a"]}],
        }
        evidence = {"conflicts": [{"section": "capabilities", "key": "volte", "kind": "conflict"},
                                  {"section": "android_carrier_config", "key": "rcs", "kind": "conflict"}]}
        self.assertEqual(ta.depends_on_of(p, evidence, variants), {
            "volte": ["device", "sources_disagree"],
            "vowifi": ["firmware"],
            "rcs": ["sources_disagree"],
        })
        self.assertEqual(ta.depends_on_of(profile({"mccmnc": ["26202"]}, volte="supported"), None, variants), {})


class ForYouTest(unittest.TestCase):
    def derived(self, profiles: list[dict], **kwargs) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            return ta.derive(write_tree(Path(tmp), profiles, **kwargs))

    def test_lidl_on_the_plain_vodafone_profile_reads_depends_on_plan(self) -> None:
        out = self.derived([PLAIN, GID11])
        vowifi = out[PLAIN["profile_id"]]["for_you"]["vowifi"]
        self.assertEqual(vowifi["state"], "depends_on_plan")
        self.assertEqual(vowifi["reason"], "brand_not_tellable")
        self.assertEqual(vowifi["brands"], ["LIDL Connect", "Vodafone Deutschland"])
        # The network-wide MMS end reaches every profile of the network.
        self.assertEqual(out[PLAIN["profile_id"]]["for_you"]["mms"], {"state": "ended", "statements": ["de.vodafone.mms"]})
        self.assertEqual(out[GID11["profile_id"]]["for_you"]["mms"]["state"], "ended")
        # A feature OCD has no capability for gives nothing.
        self.assertNotIn("volte_roaming", json.dumps(out))

    def test_a_brand_alone_gets_its_own_statement(self) -> None:
        out = self.derived([PLAIN, GID11])
        self.assertEqual(out[GID11["profile_id"]]["for_you"]["vowifi"], {"state": "not_offered", "statements": ["de.1und1.wifi_calling"]})

    def test_offered_is_never_more_than_depends_on_plan(self) -> None:
        out = self.derived([TELEKOM_PLAIN, CONGSTAR, FRAENK])
        self.assertEqual(out[CONGSTAR["profile_id"]]["for_you"]["volte"]["state"], "depends_on_plan")
        self.assertEqual(out[CONGSTAR["profile_id"]]["for_you"]["vonr"]["state"], "not_offered")
        self.assertEqual(out[FRAENK["profile_id"]]["for_you"]["volte"]["statements"], ["de.fraenk.volte"])
        # A lapsed statement states nothing; no host-only brand rides 26201 here.
        self.assertNotIn("for_you", out[TELEKOM_PLAIN["profile_id"]])

    def test_a_crossing_rule_of_another_brand_on_the_same_selector_blocks_both(self) -> None:
        third = profile({"mccmnc": ["26201"], "gid1_prefixes": ["45", "46"]})
        identity = IDENTITY + [entry("de.other", "Other", ["26201"], [OTHER44]), entry("de.third", "Third", ["26201"], [third])]
        statements = STATEMENTS + [statement("de.other.volte", "de.other", "volte", "offered", "brand", ["26201"]),
                                   statement("de.third.volte", "de.third", "volte", "offered", "brand", ["26201"])]
        out = self.derived([TELEKOM_PLAIN, CONGSTAR, OTHER44, third], identity=identity, statements=statements)
        # OTHER44 is wider than congstar's rule: congstar's SIMs stay congstar's.
        self.assertEqual(out[CONGSTAR["profile_id"]]["for_you"]["volte"]["statements"], ["de.congstar.volte"])
        # A SIM with GID1 45 matches OTHER44 and the third rule alike: neither brand speaks for it.
        self.assertNotIn("for_you", out[OTHER44["profile_id"]])
        self.assertNotIn("for_you", out[third["profile_id"]])

    def test_a_statement_must_name_every_network_of_the_profile(self) -> None:
        out = self.derived([PLAIN, TWO_NETWORKS])
        self.assertNotIn("for_you", out[TWO_NETWORKS["profile_id"]])


class TreeTest(unittest.TestCase):
    def test_apply_check_and_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_tree(Path(tmp) / "head", [PLAIN, GID11])
            self.assertEqual(ta.tree_problems(root), [])  # nothing written yet
            changed = ta.apply(root, ta.derive(root))
            self.assertEqual(len(changed), 2)
            self.assertEqual(ta.tree_problems(root), [])
            written = json.loads((root / "carriers/open" / f"{PLAIN['profile_id'].split('.', 1)[1]}.json").read_text())
            self.assertEqual(written["capabilities"], PLAIN["capabilities"])
            validator.validate_profile_object(Path("x.json"), written)
            # A hand edit of for_you fails the check.
            written["for_you"]["vowifi"] = {"state": "included", "statements": ["de.vodafone.wifi_calling"]}
            path = root / "carriers/open" / f"{PLAIN['profile_id'].split('.', 1)[1]}.json"
            path.write_text(ta.dump_profile(written), encoding="utf-8")
            self.assertTrue(any("for_you" in p for p in ta.tree_problems(root)))
            ta.apply(root, ta.derive(root))
            # Against a base: capabilities may not move with for_you while the evidence stays.
            base = write_tree(Path(tmp) / "base", [PLAIN, GID11])
            self.assertEqual(ta.base_problems(base, root), [])
            moved = dict(written, capabilities={**PLAIN["capabilities"], "vowifi": "unsupported"})
            moved.update(ta.derive(root)[PLAIN["profile_id"]])
            path.write_text(ta.dump_profile(moved), encoding="utf-8")
            self.assertTrue(any("capabilities changed" in p for p in ta.base_problems(base, root)))
            # A head that drops the fields the base carries fails.
            ta.apply(base, ta.derive(base))
            plain_head = write_tree(Path(tmp) / "bare", [PLAIN, GID11])
            self.assertTrue(any("carries none" in p for p in ta.base_problems(base, plain_head)))

    def test_the_validator_refuses_a_malformed_answer(self) -> None:
        good = dict(PLAIN, depends_on={"volte": ["device"]}, capabilities={**PLAIN["capabilities"], "volte": "conditional"})
        validator.validate_profile_object(Path("x.json"), good)
        for bad in (
            dict(PLAIN, depends_on={"volte": ["device"]}),
            dict(good, depends_on={"volte": ["guess"]}),
            dict(PLAIN, for_you={"vowifi": {"state": "works", "statements": ["s"]}}),
            dict(PLAIN, for_you={"vowifi": {"state": "included", "statements": ["s"], "reason": "brand_not_tellable", "brands": ["A"]}}),
            dict(PLAIN, for_you={"vowifi": {"state": "depends_on_plan", "statements": ["s"], "reason": "brand_not_tellable"}}),
        ):
            with self.assertRaises(validator.ValidationError):
                validator.validate_profile_object(Path("x.json"), bad)


if __name__ == "__main__":
    unittest.main()
