#!/usr/bin/env python3
"""release_notes.py on small trees with a stand-in generator."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

import release_notes as notes
from test_phone_guard import FAKE_GENERATOR

WEB = 'mcc="262" mnc="01" apn="web" type="default,supl"'
IA = 'mcc="262" mnc="01" apn="attach" type="ia"'
MMS = 'mcc="262" mnc="01" apn="mms" type="mms" mmsc="http://mms.example/"'
IMS = 'mcc="262" mnc="01" apn="ims" type="ims" protocol="IPV6" roaming_protocol="IPV6"'
SOS = 'mcc="262" mnc="01" apn="sos" type="emergency" protocol="IPV6" roaming_protocol="IPV6"'
SOS_DEFAULT = 'mcc="262" mnc="01" apn="sos" type="emergency" protocol="IPV4V6" roaming_protocol="IPV4V6"'
OTHER = 'mcc="262" mnc="02" apn="internet" type="default,supl"'


def apns(*rows: str) -> str:
    return "<?xml version='1.0' encoding='utf-8'?>\n<apns version=\"8\">\n" + "".join(
        f"  <apn {row} />\n" for row in rows) + "</apns>\n"


def config(*blocks: tuple[str, dict[str, str]]) -> str:
    out = ["<?xml version='1.0' encoding='utf-8'?>", "<carrier_config_list>"]
    for attrs, keys in blocks:
        out.append(f"  <carrier_config {attrs}>")
        out += [f'    <boolean name="{k}" value="{v}" />' for k, v in keys.items()]
        out.append("  </carrier_config>")
    return "\n".join(out + ["</carrier_config_list>", ""])


def write_tree(root: Path, apn_rows: list[str], profiles: dict[str, dict[str, str]],
               blocks: list[tuple[str, dict[str, str]]], stale_after: str = "2027-06-30",
               digest: str = "a", vendor: list[dict] | None = None, announced: list[str] | None = None) -> Path:
    android = root / "generated" / "android"
    android.mkdir(parents=True)
    (android / "apns-conf.xml").write_text(apns(*apn_rows), encoding="utf-8")
    (android / "carrier-config-list.xml").write_text(config(*blocks), encoding="utf-8")
    (android / "lookup.json").write_text(json.dumps({"schema_version": 1, "profiles": [
        {"profile_id": pid, "capabilities": caps} for pid, caps in sorted(profiles.items())]}), encoding="utf-8")
    data_digest = "sha256:" + digest * 64
    (android / "metadata.json").write_text(json.dumps({
        "schema_version": 1, "data_digest": data_digest, "checks_through": "2026-07-01",
        "stale_after": stale_after, "target": {"apn_database_version": 8},
        "omissions": {key: 0 for key in notes.EMERGENCY_OMISSIONS}}), encoding="utf-8")
    (root / "generated" / "devices").mkdir()
    (root / "generated" / "devices" / "carrier-variants.json").write_text(
        json.dumps({"schema_version": 1, "based_on_data_digest": data_digest}), encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools" / "generate_android_outputs.py").write_text(FAKE_GENERATOR, encoding="utf-8")
    (root / "carriers").mkdir()
    (root / "carriers" / "records.json").write_text(json.dumps(vendor or []), encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "compatibility.md").write_text(
        "# Compatibility\n\n## Announced changes\n\n"
        + ("".join(f"- {line}\n" for line in announced) if announced else "None.\n"), encoding="utf-8")
    return root


CAPS = {"volte": "supported", "mms": "supported"}


class ComputeTests(unittest.TestCase):
    def notes_for(self, base_rows: list[str], head_rows: list[str], base_profiles=None, head_profiles=None,
                  base_blocks=None, head_blocks=None, announced=None) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as tmp:
            base = write_tree(Path(tmp) / "base", base_rows, base_profiles or {"open.26201.aaaaaaaaaaaa": CAPS},
                              base_blocks or [('mcc="262" mnc="01"', {"carrier_volte_available_bool": "true"})])
            head = write_tree(Path(tmp) / "head", head_rows, head_profiles or {"open.26201.aaaaaaaaaaaa": CAPS},
                              head_blocks or [('mcc="262" mnc="01"', {"carrier_volte_available_bool": "true"})],
                              announced=announced)
            result = notes.compute(base, head, ["Update sanitized carrier data (#1)", "Fix a thing (#2)"],
                                   notes.announced_changes(head))
        return result, notes.render(result, "data-2026.11", "base", "head", date(2026, 11, 2))

    def test_lost_emergency_lead_needs_review(self) -> None:
        result, text = self.notes_for([WEB, SOS], [WEB])
        self.assertEqual(result["guard"]["verdict"], "pass")
        self.assertEqual(len(result["needs_review"]), 1)
        self.assertIn("emergency lead lost", result["needs_review"][0])
        self.assertIn("\n## Needs review\n", text)
        self.assertLess(text.index("## Needs review"), text.index("## Phone guard"))
        self.assertIn("262/01: sos IPV6/IPV6 [IPv6 only] -> Android default sos IPV4V6/IPV4V6", text)
        for section in notes.REQUIRED_SECTIONS:
            self.assertIn(f"\n{section}\n", text)

    def test_gained_and_equal_leads_do_not_need_review(self) -> None:
        result, text = self.notes_for([WEB], [WEB, SOS])
        self.assertEqual(result["needs_review"], [])
        self.assertNotIn("## Needs review", text)
        self.assertIn("emergency lead gained: 1 scope(s)", text)
        self.assertIn("IPv6 only 1", text)
        result, text = self.notes_for([WEB], [WEB, SOS_DEFAULT])
        self.assertEqual(result["needs_review"], [])
        self.assertIn("[equal]", text)

    def test_network_type_gap_needs_review(self) -> None:
        lte_only = SOS + ' network_type_bitmask="13"'
        result, _ = self.notes_for([WEB, SOS], [WEB, lte_only])
        self.assertTrue(any("network type left with no emergency profile" in r for r in result["needs_review"]),
                        result["needs_review"])

    def test_guard_trip_is_reported(self) -> None:
        result, text = self.notes_for([WEB, MMS], [WEB])
        self.assertEqual(result["guard"]["verdict"], "hold")
        self.assertIn("**HOLD**", text)
        self.assertIn("mms_lost|262/01", text)

    def test_ims_and_lead_changes(self) -> None:
        other_ims = IMS.replace('apn="ims"', 'apn="ims2"')
        result, text = self.notes_for([WEB, IA, IMS], [OTHER, WEB.replace('"web"', '"web2"'), other_ims])
        self.assertIn("ims lead APN changed: 1 scope(s)", text)
        changes = result["leads"]["changes"]
        self.assertEqual([(c["scope"], c["old"], c["new"]) for c in changes["internet"]], [("262/01", "web", "web2")])
        self.assertEqual([(c["scope"], c["old"], c["new"]) for c in changes["attach"]], [("262/01", "attach", "web2")])
        self.assertEqual(result["leads"]["reset_to_default"], ["262/01"])
        self.assertEqual(result["leads"]["scopes_added"], ["262/02"])
        self.assertIn("\"Reset to default\" brings the new internet or attach lead on 1 scope(s): 262/01.", text)

    def test_profiles_capabilities_carrier_config_and_pull_requests(self) -> None:
        result, text = self.notes_for(
            [WEB], [WEB],
            base_profiles={"open.26201.aaaaaaaaaaaa": CAPS, "open.26202.bbbbbbbbbbbb": CAPS},
            head_profiles={"open.26201.aaaaaaaaaaaa": {"volte": "unknown", "mms": "supported"},
                           "open.26203.cccccccccccc": CAPS},
            head_blocks=[('mcc="262" mnc="01"', {"carrier_volte_available_bool": "false",
                                                "carrier_use_ims_first_for_emergency_bool": "false"})],
            announced=["data-2026.12 removes lookup.json's path"])
        self.assertEqual(result["profiles"]["added"], ["open.26203.cccccccccccc"])
        self.assertEqual(result["profiles"]["removed"], ["open.26202.bbbbbbbbbbbb"])
        self.assertIn("volte: supported -> unknown: 1", text)
        self.assertIn("| 26202 | 0 | 1 |", text)
        self.assertIn("| 26203 | 1 | 0 |", text)
        self.assertIn("+ 262/01 carrier_use_ims_first_for_emergency_bool=false", text)
        self.assertIn("carrier_volte_available_bool: +0 -0 ~1", text)
        self.assertIn("1 data publish(es)", text)
        self.assertIn("- Fix a thing (#2)", text)
        self.assertIn("- data-2026.12 removes lookup.json's path", text)
        self.assertEqual(result["head"]["counts"]["safety_class_lines"], 1)


class RenderTests(unittest.TestCase):
    def test_emergency_lines_are_never_cut_and_lte_comes_first(self) -> None:
        watch = [{"condition": "emergency lead lost", "scope": f"262/{n:02d}", "types": ["GPRS"],
                  "old": "sos IPV6/IPV6 [IPv6 only]", "new": "Android default sos IPV4V6/IPV4V6"} for n in range(80)]
        watch.append({"condition": "emergency lead lost", "scope": "999/99", "types": ["LTE"],
                      "old": "sos IPV6/IPV6 [IPv6 only]", "new": "Android default sos IPV4V6/IPV4V6"})
        lines = notes.watch_block(watch)
        self.assertEqual(lines[0], "emergency lead lost: 81 scope(s)")
        self.assertEqual(len(lines), 82)
        self.assertTrue(lines[1].startswith("  999/99"))
        self.assertNotIn("more", "\n".join(lines))

    def test_announced_changes_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "compatibility.md").write_text(
                "# C\n\n## Announced changes\n\nNone.\n", encoding="utf-8")
            self.assertEqual(notes.announced_changes(root), [])
            (root / "docs" / "compatibility.md").write_text(
                "# C\n\n## Announced changes\n\n- one\n- two\n\n## Later\n\n- not this\n", encoding="utf-8")
            self.assertEqual(notes.announced_changes(root), ["one", "two"])

    def test_missing_file_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = write_tree(Path(tmp) / "base", [WEB], {}, [])
            head = write_tree(Path(tmp) / "head", [WEB], {}, [])
            (head / "generated" / "android" / "lookup.json").unlink()
            with self.assertRaises(notes.NotesError):
                notes.compute(base, head)


if __name__ == "__main__":
    unittest.main()
