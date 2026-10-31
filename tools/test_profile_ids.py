#!/usr/bin/env python3
"""Tests for tools/profile_ids.py: frozen profile IDs (rule round 45, item 1)."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocd_dataset  # noqa: E402
import profile_ids as ids  # noqa: E402
import validate_public_carrier_data  # noqa: E402

TODAY = date(2026, 11, 1)
PLAIN = {"mccmnc": ["26202"]}
GID_11 = {"gid1_prefixes": ["11"], "mccmnc": ["26202"]}
GID_22 = {"gid1_prefixes": ["22"], "mccmnc": ["26202"]}
GID_BOTH = {"gid1_prefixes": ["11", "22"], "mccmnc": ["26202"]}
SPN_UPPER = {"mccmnc": ["26202"], "spn": ["LIDL"]}
SPN_LOWER = {"mccmnc": ["26202"], "spn": ["lidl"]}


def tree(root: Path, matches: dict[str, dict], aliases: dict | None = None) -> Path:
    folder = root / "carriers" / "open"
    folder.mkdir(parents=True, exist_ok=True)
    for path in folder.glob("*.json"):
        path.unlink()
    for profile_id, match in matches.items():
        name = profile_id.split(".", 1)[1]
        (folder / f"{name}.json").write_text(json.dumps({"profile_id": profile_id, "match": match}), encoding="utf-8")
    if aliases is not None:
        ids.write_aliases(root, aliases)
    return root


def build(previous: dict[str, dict], matches: list[dict], aliases: dict | None = None, continuity=()) -> tuple[ids.Registry, dict, dict]:
    """One build: assign IDs to MATCHES against PREVIOUS, then finish."""
    registry = ids.Registry(previous, aliases, continuity)
    registry.plan(matches)
    new_live = {registry.assign(match): match for match in matches}
    document, report = registry.finish(new_live, TODAY)
    return registry, new_live, {"aliases": document, "report": report}


class IdFunctionTest(unittest.TestCase):
    def test_today_ids_are_the_hash_and_the_validator_uses_this_function(self) -> None:
        self.assertEqual(ids.hash_id(GID_11), validate_public_carrier_data.canonical_profile_id(GID_11))
        self.assertTrue(ids.hash_id(GID_11).startswith("open.26202."))
        self.assertEqual(ids.hash_id(GID_11).split(".")[2], ids.match_set_hash(GID_11))
        # A counter keeps the open.<mccmnc>.<12 hex> form OcdCarrierSettings requires.
        self.assertRegex(ids.hash_id(GID_11, 1), r"^open\.26202\.[0-9a-f]{12}$")
        self.assertNotEqual(ids.hash_id(GID_11, 1), ids.hash_id(GID_11))
        self.assertEqual(ids.issued_counter(ids.hash_id(GID_11, 2), GID_11), 2)
        self.assertIsNone(ids.issued_counter(ids.hash_id(GID_22), GID_11))

    def test_normalising_order_and_duplicates_keeps_the_hash(self) -> None:
        shuffled = {"mccmnc": ["26202"], "gid1_prefixes": ["22", "11", "11"]}
        self.assertEqual(ids.match_set_hash(shuffled), ids.match_set_hash(GID_BOTH))
        self.assertEqual(ids.same_sims_key(SPN_UPPER), ids.same_sims_key(SPN_LOWER))
        self.assertNotEqual(ids.match_set_hash(SPN_UPPER), ids.match_set_hash(SPN_LOWER))

    def test_a_record_takes_its_hash_from_the_id_until_it_stores_one(self) -> None:
        pid = ids.hash_id(GID_11)
        self.assertEqual(ids.record_match_set_hash(None, pid), ids.match_set_hash(GID_11))
        self.assertEqual(ids.record_match_set_hash("0123456789ab", pid), "0123456789ab")
        self.assertIsNone(ids.record_match_set_hash(None, "fill.26202.0123456789ab"))
        current = {pid: ids.match_set_hash(GID_11)}
        self.assertTrue(ocd_dataset.under_current_match_set(pid, None, current))
        self.assertFalse(ocd_dataset.under_current_match_set(pid, None, {pid: ids.match_set_hash(GID_BOTH)}))
        self.assertTrue(ocd_dataset.under_current_match_set("fill.26202.0123456789ab", None, current))
        self.assertTrue(ocd_dataset.under_current_match_set(pid, None, None))


class CoverageTest(unittest.TestCase):
    def test_rule_relations(self) -> None:
        self.assertTrue(ids.rule_implies(GID_11, PLAIN))
        self.assertFalse(ids.rule_implies(PLAIN, GID_11))
        self.assertTrue(ids.rule_implies(GID_11, GID_BOTH))
        self.assertTrue(ids.rules_overlap(GID_BOTH, GID_22))
        self.assertFalse(ids.rules_overlap(GID_11, GID_22))
        self.assertTrue(ids.rule_implies({"mccmnc": ["26202"], "imsi_prefix_patterns": ["2620212"]},
                                         {"mccmnc": ["26202"], "imsi_prefix_patterns": ["262021x"]}))
        self.assertFalse(ids.rule_implies({"mccmnc": ["26202"], "imsi_prefix_patterns": ["262021x"]},
                                          {"mccmnc": ["26202"], "imsi_prefix_patterns": ["2620212"]}))
        self.assertTrue(ids.rules_overlap({"mccmnc": ["26202"], "imsi_prefix_patterns": ["262021x"]},
                                          {"mccmnc": ["26202"], "imsi_prefix_patterns": ["2620212"]}))
        self.assertTrue(ids.rule_implies({"mccmnc": ["26202"], "gid1_prefixes": ["ab"]}, {"mccmnc": ["26202"], "gid1_prefixes": ["A"]}))

    def test_a_rule_on_other_selectors_is_no_target(self) -> None:
        plain, gid = ids.hash_id(PLAIN), ids.hash_id(GID_11)
        self.assertEqual(ids.alias_targets(SPN_UPPER, {plain: PLAIN, gid: GID_11}), [plain])


class AssignmentTest(unittest.TestCase):
    def test_the_same_match_sets_keep_every_id(self) -> None:
        previous = {ids.hash_id(m): m for m in (PLAIN, GID_11, SPN_UPPER)}
        registry, new_live, out = build(previous, [PLAIN, GID_11, SPN_UPPER])
        self.assertEqual(set(new_live), set(previous))
        self.assertEqual(out["report"]["new_ids"], [])
        self.assertEqual(out["aliases"]["aliases"], [])

    def test_the_same_sims_written_otherwise_keep_the_id(self) -> None:
        old = ids.hash_id(SPN_UPPER)
        registry, new_live, out = build({old: SPN_UPPER, ids.hash_id(PLAIN): PLAIN}, [PLAIN, SPN_LOWER])
        self.assertIn(old, new_live)
        self.assertEqual(new_live[old], SPN_LOWER)
        [entry] = out["aliases"]["continued"]
        self.assertEqual((entry["id"], entry["basis"], entry["match_set_hash"]), (old, "same_sims", ids.match_set_hash(SPN_LOWER)))
        self.assertEqual(out["report"]["kept_ids_with_changed_match_set"][0]["id"], old)
        self.assertEqual(ids.alias_document_problems(out["aliases"], new_live), [])
        # A record made under the old spelling lapses: the hash differs.
        self.assertNotEqual(ids.record_match_set_hash(None, old), ids.match_set_hash(SPN_LOWER))

    def test_a_new_match_set_gets_the_hash_once(self) -> None:
        plain = ids.hash_id(PLAIN)
        registry, new_live, out = build({plain: PLAIN}, [PLAIN, GID_11])
        self.assertIn(ids.hash_id(GID_11), new_live)
        self.assertEqual(out["report"]["new_ids"], [ids.hash_id(GID_11)])

    def test_a_hash_that_collides_with_an_aliased_id_is_hashed_again(self) -> None:
        plain = ids.hash_id(PLAIN)
        aliases = ids.empty_aliases()
        aliases["aliases"] = [{"id": ids.hash_id(GID_11), "kind": "withdrawn", "to": [plain], "match": GID_11,
                               "match_set_hash": ids.match_set_hash(GID_11), "retired_on": "2026-10-31"}]
        registry, new_live, out = build({plain: PLAIN}, [PLAIN, GID_11], aliases)
        self.assertIn(ids.hash_id(GID_11, 1), new_live)
        self.assertNotIn(ids.hash_id(GID_11), new_live)
        self.assertEqual(out["report"]["new_ids_with_counter"], [ids.hash_id(GID_11, 1)])
        self.assertEqual(ids.alias_document_problems(out["aliases"], new_live), [])

    def test_a_kept_id_s_old_hash_is_taken(self) -> None:
        # open.X continued from GID_11 to GID_BOTH: a later GID_11 profile cannot take open.X.
        kept = ids.hash_id(GID_11)
        aliases = ids.empty_aliases()
        aliases["continued"] = [{"id": kept, "basis": "continuity_entry", "match_set_hash": ids.match_set_hash(GID_BOTH),
                                 "from_match_set_hash": ids.match_set_hash(GID_11), "since": "2026-10-31"}]
        registry, new_live, out = build({kept: GID_BOTH}, [GID_BOTH, GID_11], aliases)
        self.assertEqual(new_live[kept], GID_BOTH)
        self.assertIn(ids.hash_id(GID_11, 1), new_live)


    def test_two_spellings_of_one_rule_in_one_build_never_share_an_id(self) -> None:
        upper = {"gid1_prefixes": ["4D"], "mccmnc": ["26202"]}
        lower = {"gid1_prefixes": ["4d"], "mccmnc": ["26202"]}
        live = ids.hash_id(upper)
        registry, new_live, out = build({live: upper}, [lower, upper])
        self.assertEqual(new_live[live], upper)
        self.assertEqual(len(new_live), 2)
        self.assertEqual(registry.assign(lower), ids.hash_id(lower))

    def test_builders_after_the_sanitizer_take_the_published_id(self) -> None:
        kept = ids.hash_id(SPN_UPPER)
        registry = ids.Registry({kept: SPN_LOWER})
        self.assertEqual(registry.published_id(SPN_LOWER), kept)
        # A match set no profile is published with gets the hash, as before the freeze.
        self.assertEqual(registry.published_id(GID_11), ids.hash_id(GID_11))
        self.assertNotIn(registry.published_id(GID_11), registry.live)


class RetirementTest(unittest.TestCase):
    def test_replaced(self) -> None:
        old, plain = ids.hash_id(GID_BOTH), ids.hash_id(PLAIN)
        registry, new_live, out = build({old: GID_BOTH, plain: PLAIN}, [PLAIN, GID_11])
        [entry] = out["aliases"]["aliases"]
        self.assertEqual((entry["id"], entry["kind"]), (old, "replaced"))
        self.assertEqual(entry["to"], sorted([ids.hash_id(GID_11), plain]))
        self.assertEqual(entry["match_set_hash"], ids.match_set_hash(GID_BOTH))
        [proposal] = out["report"]["continuity_proposals"]
        self.assertEqual(proposal["to_match_set_hash"], ids.match_set_hash(GID_11))

    def test_split(self) -> None:
        old, plain = ids.hash_id(GID_BOTH), ids.hash_id(PLAIN)
        _, _, out = build({old: GID_BOTH, plain: PLAIN}, [PLAIN, GID_11, GID_22])
        [entry] = out["aliases"]["aliases"]
        self.assertEqual(entry["kind"], "split")
        self.assertEqual(out["report"]["continuity_proposals"], [])

    def test_merge(self) -> None:
        a, b, plain = ids.hash_id(GID_11), ids.hash_id(GID_22), ids.hash_id(PLAIN)
        _, _, out = build({a: GID_11, b: GID_22, plain: PLAIN}, [PLAIN, GID_BOTH])
        self.assertEqual([e["kind"] for e in out["aliases"]["aliases"]], ["merge", "merge"])
        self.assertTrue(all(e["to"] == [ids.hash_id(GID_BOTH)] for e in out["aliases"]["aliases"]))

    def test_withdrawn_points_where_the_sims_fall(self) -> None:
        old, plain = ids.hash_id(SPN_UPPER), ids.hash_id(PLAIN)
        _, _, out = build({old: SPN_UPPER, plain: PLAIN}, [PLAIN, GID_11])
        [entry] = out["aliases"]["aliases"]
        self.assertEqual((entry["kind"], entry["to"]), ("withdrawn", [plain]))

    def test_a_retired_id_is_never_reused(self) -> None:
        old, plain = ids.hash_id(SPN_UPPER), ids.hash_id(PLAIN)
        _, _, first = build({old: SPN_UPPER, plain: PLAIN}, [PLAIN])
        registry, new_live, second = build({plain: PLAIN}, [PLAIN, SPN_UPPER], first["aliases"])
        self.assertNotIn(old, new_live)
        self.assertIn(ids.hash_id(SPN_UPPER, 1), new_live)
        self.assertEqual(len(second["aliases"]["aliases"]), 1)


class ContinuityTest(unittest.TestCase):
    def test_an_accepted_replacement_keeps_the_id(self) -> None:
        old, plain = ids.hash_id(GID_BOTH), ids.hash_id(PLAIN)
        entry = {"id": old, "from_match_set_hash": ids.match_set_hash(GID_BOTH), "to_match_set_hash": ids.match_set_hash(GID_11)}
        registry, new_live, out = build({old: GID_BOTH, plain: PLAIN}, [PLAIN, GID_11], continuity=[entry])
        self.assertEqual(new_live[old], GID_11)
        self.assertEqual(out["aliases"]["aliases"], [])
        [continued] = out["aliases"]["continued"]
        self.assertEqual(continued["basis"], "continuity_entry")
        self.assertEqual(out["report"]["continuity_applied"], [old])

    def test_a_split_never_carries_the_id(self) -> None:
        old, plain = ids.hash_id(GID_BOTH), ids.hash_id(PLAIN)
        entry = {"id": old, "from_match_set_hash": ids.match_set_hash(GID_BOTH), "to_match_set_hash": ids.match_set_hash(GID_11)}
        registry, new_live, out = build({old: GID_BOTH, plain: PLAIN}, [PLAIN, GID_11, GID_22], continuity=[entry])
        self.assertNotIn(old, new_live)
        self.assertEqual(out["report"]["continuity_not_applied"], [old])

    def test_a_hand_mapping_to_another_rule_is_ignored(self) -> None:
        old, plain = ids.hash_id(SPN_UPPER), ids.hash_id(PLAIN)
        entry = {"id": old, "from_match_set_hash": ids.match_set_hash(SPN_UPPER), "to_match_set_hash": ids.match_set_hash(GID_11)}
        registry, new_live, out = build({old: SPN_UPPER, plain: PLAIN}, [PLAIN, GID_11], continuity=[entry])
        self.assertNotIn(old, new_live)


class CheckTest(unittest.TestCase):
    def test_base_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain, gid, spn = ids.hash_id(PLAIN), ids.hash_id(GID_11), ids.hash_id(SPN_UPPER)
            base = tree(Path(tmp) / "base", {plain: PLAIN, gid: GID_11, spn: SPN_UPPER}, ids.empty_aliases())
            head = Path(tmp) / "head"
            # A profile left without an alias.
            tree(head, {plain: PLAIN, gid: GID_11}, ids.empty_aliases())
            self.assertTrue(any("without an entry" in p for p in ids.base_problems(base, head)))
            # With the alias the build writes, it passes.
            _, new_live, out = build({plain: PLAIN, gid: GID_11, spn: SPN_UPPER}, [PLAIN, GID_11])
            tree(head, new_live, out["aliases"])
            self.assertEqual(ids.base_problems(base, head) + ids.tree_problems(head, True), [])
            # A recomputed hash for the same SIMs.
            tree(head, {plain: PLAIN, gid: GID_11, ids.hash_id(SPN_LOWER): SPN_LOWER}, ids.empty_aliases())
            self.assertTrue(any("must keep the ID" in p for p in ids.base_problems(base, head)))
            # A retired ID reused, and an alias entry removed.
            tree(head, {plain: PLAIN, gid: GID_11}, ids.empty_aliases())
            later = Path(tmp) / "later"
            tree(later, {plain: PLAIN, gid: GID_11, spn: SPN_UPPER}, ids.empty_aliases())
            tree(head, new_live, out["aliases"])
            problems = ids.base_problems(head, later)
            self.assertTrue(any("never reused" in p for p in problems))
            self.assertTrue(any("only added" in p for p in problems))
            # A kept ID moved to other SIMs without an accepted entry.
            tree(later, {plain: PLAIN, gid: GID_BOTH, spn: SPN_UPPER}, ids.empty_aliases())
            self.assertTrue(any("without an accepted continuity entry" in p for p in ids.base_problems(base, later)))
            # A new ID that skips a free counter.
            tree(later, {plain: PLAIN, gid: GID_11, spn: SPN_UPPER, ids.hash_id(GID_22, 1): GID_22}, ids.empty_aliases())
            self.assertTrue(any("was free" in p for p in ids.base_problems(base, later)))

    def test_tree_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = ids.hash_id(PLAIN)
            root = tree(Path(tmp), {plain: PLAIN, ids.hash_id(GID_22, 7): GID_11}, ids.empty_aliases())
            self.assertTrue(any("no continued entry" in p for p in ids.tree_problems(root, True)))
            tree(root, {plain: PLAIN}, ids.empty_aliases())
            (root / "generated/operators").mkdir(parents=True)
            (root / "generated/operators/carrier-identity.json").write_text(json.dumps({"x": ids.hash_id(GID_22)}), encoding="utf-8")
            self.assertTrue(any("registry does not hold" in p for p in ids.tree_problems(root, True)))
            aliases = ids.empty_aliases()
            aliases["aliases"] = [{"id": plain, "kind": "withdrawn", "to": [ids.hash_id(GID_11)], "match": PLAIN,
                                   "match_set_hash": ids.match_set_hash(PLAIN), "retired_on": "2026-10-31"}]
            problems = ids.alias_document_problems(aliases, {plain: PLAIN})
            self.assertTrue(any("live and aliased" in p for p in problems))
            self.assertTrue(any("neither live nor aliased" in p for p in problems))

    def test_changes_list_kept_ids_and_new_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain, old = ids.hash_id(PLAIN), ids.hash_id(SPN_UPPER)
            base = tree(Path(tmp) / "base", {plain: PLAIN, old: SPN_UPPER, ids.hash_id(GID_BOTH): GID_BOTH}, ids.empty_aliases())
            _, new_live, out = build(ids.load_live(base), [PLAIN, SPN_LOWER, GID_11])
            head = tree(Path(tmp) / "head", new_live, out["aliases"])
            changes = ids.id_changes(base, head)
            self.assertEqual([c["id"] for c in changes["kept_with_changed_match_set"]], [old])
            self.assertEqual([a["kind"] for a in changes["new_aliases"]], ["replaced"])
            text = "\n".join(ids.change_lines(changes))
            self.assertIn("spn=LIDL -> mccmnc=26202 spn=lidl", text)


if __name__ == "__main__":
    unittest.main()
