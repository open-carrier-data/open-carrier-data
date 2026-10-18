#!/usr/bin/env python3
"""The CarrierConfig diff (diff_carrier_config.py) on small
carrier-config-list.xml fixtures."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import diff_carrier_config as diff

VOLTE = '<boolean name="carrier_volte_available_bool" value="true" />'
IMS_FIRST = '<boolean name="carrier_use_ims_first_for_emergency_bool" value="false" />'
EPDG = '<string name="iwlan.epdg_static_address_string">epdg.epc.mnc001.mcc262.pub.3gppnetwork.org</string>'
METERED = ('<string-array name="carrier_metered_apn_types_strings" num="2"><item value="default" />'
           '<item value="dun" /></string-array>')


def block(attrs: str, *keys: str) -> str:
    return f"  <carrier_config {attrs}>\n" + "".join(f"    {key}\n" for key in keys) + "  </carrier_config>\n"


def xml(*blocks: str) -> str:
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<!-- header -->\n<carrier_config_list>\n"
            + "".join(blocks) + "</carrier_config_list>\n")


class DiffCase(unittest.TestCase):
    def run_diff(self, old: str, new: str) -> tuple[int, str, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "old.xml").write_text(old, encoding="utf-8")
            (root / "new.xml").write_text(new, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = diff.run(["diff_carrier_config.py", str(root / "old.xml"), str(root / "new.xml"),
                                 "--json", str(root / "d.json")])
            result = json.loads((root / "d.json").read_text()) if (root / "d.json").exists() else {}
        return code, out.getvalue() + err.getvalue(), result


class SafetyClassTests(unittest.TestCase):
    def test_the_sixteen_keys_in_use_are_in_the_class(self) -> None:
        keys = [
            "allow_emergency_video_calls_bool", "allow_hold_call_during_emergency_bool",
            "allow_merging_rtt_calls_bool", "allow_non_emergency_calls_in_ecm_bool",
            "auto_retry_failed_wifi_emergency_call", "carrier_use_ims_first_for_emergency_bool",
            "carrier_volte_tty_supported_bool", "carrier_vowifi_tty_supported_bool",
            "iwlan.epdg_pco_id_ipv4_int", "iwlan.epdg_pco_id_ipv6_int", "iwlan.epdg_static_address_string",
            "rtt_supported_bool", "rtt_supported_while_roaming_bool",
            "rtt_upgrade_supported_for_downgraded_vt_call", "support_wps_over_ims_bool",
            "vt_upgrade_supported_for_downgraded_rtt_call",
        ]
        self.assertEqual([key for key in keys if not diff.safety_class(key)], [])

    def test_other_keys_are_not(self) -> None:
        for key in ("carrier_volte_available_bool", "enabledMMS", "carrier_wfc_ims_available_bool",
                    "hide_enhanced_4g_lte_bool", "carrier_metered_apn_types_strings"):
            self.assertFalse(diff.safety_class(key), key)


class DiffTests(DiffCase):
    def test_identical_files_report_no_change(self) -> None:
        same = xml(block('mcc="262" mnc="01" name="Telekom"', VOLTE, IMS_FIRST))
        code, out, result = self.run_diff(same, same)
        self.assertEqual((code, result["changes"]), (0, []))
        self.assertIn("blocks: 1 -> 1 (0 added, 0 removed, 0 changed)", out)
        self.assertIn("in full: +0 -0 ~0", out)
        self.assertIn("other keys, lines per key: 0 key(s)", out)

    def test_safety_lines_are_listed_in_full(self) -> None:
        old = xml(block('mcc="262" mnc="01" name="T"', VOLTE, IMS_FIRST),
                  block('mcc="262" mnc="23" name="1&amp;1"', VOLTE))
        new = xml(block('mcc="262" mnc="01" name="T"', VOLTE, IMS_FIRST.replace("false", "true")),
                  block('mcc="262" mnc="23" name="1&amp;1"', VOLTE, IMS_FIRST, EPDG))
        code, out, _ = self.run_diff(old, new)
        self.assertEqual(code, 0)
        self.assertIn("in full: +2 -0 ~1", out)
        self.assertIn("  ~ 262/01 carrier_use_ims_first_for_emergency_bool: false -> true", out)
        self.assertIn("  + 262/23 carrier_use_ims_first_for_emergency_bool=false", out)
        self.assertIn("  + 262/23 iwlan.epdg_static_address_string=epdg.epc.mnc001.mcc262.pub.3gppnetwork.org", out)

    def test_other_keys_are_counted_per_key(self) -> None:
        old = xml(block('mcc="262" mnc="01" name="T"', VOLTE, METERED))
        new = xml(block('mcc="262" mnc="01" name="T"', METERED.replace('"dun"', '"supl"')),
                  block('mcc="262" mnc="02" name="V"', VOLTE))
        code, out, result = self.run_diff(old, new)
        self.assertEqual(code, 0)
        self.assertIn("  carrier_volte_available_bool: +1 -1 ~0", out)
        self.assertIn("  carrier_metered_apn_types_strings: +0 -0 ~1", out)
        self.assertIn("blocks: 1 -> 2 (1 added, 0 removed, 1 changed)", out)
        changed = [c for c in result["changes"] if c["change"] == "changed"]
        self.assertEqual((changed[0]["old"], changed[0]["new"]), ("[default, dun]", "[default, supl]"))
        self.assertNotIn("carrier_volte_available_bool=", out)

    def test_a_removed_block_removes_its_lines(self) -> None:
        old = xml(block('mcc="262" mnc="01" name="T"', VOLTE),
                  block('cid="2397" mcc="262" mnc="02" name="LIDL"', VOLTE, IMS_FIRST))
        new = xml(block('mcc="262" mnc="01" name="T"', VOLTE))
        _, out, _ = self.run_diff(old, new)
        self.assertIn("blocks: 2 -> 1 (0 added, 1 removed, 0 changed)", out)
        self.assertIn("  - 262/02 cid=2397 carrier_use_ims_first_for_emergency_bool=false", out)

    def test_blocks_are_keyed_by_filters_not_by_name(self) -> None:
        old = xml(block('mcc="262" mnc="01" name="Telekom"', VOLTE))
        new = xml(block('mcc="262" mnc="01" name="Telekom.de"', VOLTE))
        code, _, result = self.run_diff(old, new)
        self.assertEqual((code, result["changes"]), (0, []))
        spn = xml(block('mcc="262" mnc="01" name="Telekom" spn="\\QTelekom.de\\E"', VOLTE))
        _, out, _ = self.run_diff(old, spn)
        self.assertIn("blocks: 1 -> 1 (1 added, 1 removed, 0 changed)", out)

    def test_malformed_xml_exits_2(self) -> None:
        good = xml(block('mcc="262" mnc="01" name="T"', VOLTE))
        code, out, _ = self.run_diff(good, good[:-10])
        self.assertEqual(code, 2)
        self.assertIn("ERROR", out)

    def test_wrong_root_exits_2(self) -> None:
        good = xml(block('mcc="262" mnc="01" name="T"', VOLTE))
        code, _, _ = self.run_diff(good, "<apns version=\"8\"></apns>\n")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
