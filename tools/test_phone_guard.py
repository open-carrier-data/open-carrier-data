#!/usr/bin/env python3
"""The phone-level publish guard (check_phone_guard.py) on small
apns-conf.xml fixtures and a stand-in generator checkout."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import check_phone_guard as guard

HOLD = ",".join(guard.HOLD_TYPES)
WEB = 'mcc="262" mnc="01" apn="web" type="default,supl"'
MMS = 'mcc="262" mnc="01" apn="mms" type="mms" mmsc="http://mms.example/"'

# A generator checkout reduced to what vendor_mms_tuples and vendor_rows read:
# each carriers/*.json holds the records of apn_xml_rows.
FAKE_GENERATOR = '''
import json
from pathlib import Path


class Rows:
    def __init__(self, records):
        self.records = records


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def profile_paths(carriers):
    return sorted(Path(carriers).glob("*.json"))


def load_apn_evidence(path):
    return None


def placeholder_apn(apn):
    return apn in ("", "default")


def apn_xml_rows(profiles, evidence):
    return Rows([record for profile in profiles for record in profile])


def apn_row_line(record):
    return "<apn " + " ".join(f'{k}="{v}"' for k, v in record.items() if not k.startswith("_")) + " />"
'''


def xml(*rows: str) -> str:
    return "<?xml version='1.0' encoding='utf-8'?>\n<apns version=\"8\">\n" + "".join(
        f"  <apn {row} />\n" for row in rows) + "</apns>\n"


class GuardCase(unittest.TestCase):
    def run_guard(self, base: str, head: str, vendor: list[dict] | None = None,
                  extra: list[str] | None = None, generator: bool = True) -> tuple[int, str, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "base.xml").write_text(base, encoding="utf-8")
            (root / "head.xml").write_text(head, encoding="utf-8")
            checkout = root / "checkout"
            if generator:
                (checkout / "tools").mkdir(parents=True)
                (checkout / "carriers").mkdir()
                (checkout / "tools" / "generate_android_outputs.py").write_text(FAKE_GENERATOR, encoding="utf-8")
                (checkout / "carriers" / "records.json").write_text(json.dumps(vendor or []), encoding="utf-8")
            guard.generator_records.cache_clear()
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = guard.run(["check_phone_guard.py", str(root / "base.xml"), str(root / "head.xml"),
                                  "--generator", str(checkout), "--report-json", str(root / "r.json"),
                                  *(extra or [])])
            result = json.loads((root / "r.json").read_text()) if (root / "r.json").exists() else {}
        return code, out.getvalue() + err.getvalue(), result

    def conditions(self, result: dict) -> set[tuple[str, str]]:
        return {(trip["condition"], ",".join(trip["types"])) for trip in result["trips"]}


class HoldTests(GuardCase):
    def test_bell_shape_mms_gone_on_every_3gpp_type_holds(self) -> None:
        code, _, result = self.run_guard(xml(WEB, MMS), xml(WEB))
        self.assertEqual(code, 1)
        self.assertEqual(self.conditions(result), {("mms_lost", HOLD)})

    def test_spark_shape_mms_to_an_mmsc_no_vendor_gives_holds(self) -> None:
        vendor = [{"mcc": "262", "mnc": "01", "apn": "mms", "type": "mms", "mmsc": "http://mms.example/",
                   "_current": {"mms": ["samsung"]}}]
        stale = 'mcc="262" mnc="01" apn="mms" type="mms" mmsc="http://old.example"'
        code, out, result = self.run_guard(xml(WEB, MMS), xml(WEB, stale, MMS), vendor)
        self.assertEqual(code, 1)
        self.assertEqual(self.conditions(result), {("mms_away", HOLD)})
        self.assertIn("mmsc=http://old.example", out)

    def test_o2_shape_mms_proxy_dropped_holds(self) -> None:
        with_proxy = MMS + ' mmsproxy="82.132.254.1" mmsport="8080"'
        vendor = [{"mcc": "262", "mnc": "01", "apn": "mms", "type": "mms", "mmsc": "http://mms.example/",
                   "mmsproxy": "82.132.254.1", "mmsport": "8080", "_current": {"mms": ["samsung"]}}]
        code, _, result = self.run_guard(xml(WEB, with_proxy), xml(WEB, MMS), vendor)
        self.assertEqual(code, 1)
        self.assertEqual(self.conditions(result), {("mms_away", HOLD)})

    def test_internet_lead_gone_on_lte_holds(self) -> None:
        nr_only = WEB + ' network_type_bitmask="20"'
        code, _, result = self.run_guard(xml(WEB), xml(nr_only))
        self.assertEqual(code, 1)
        self.assertIn(("internet_lost", "GPRS,EDGE,UMTS,HSPA,LTE,HSPA+"), self.conditions(result))

    def test_attach_lead_gone_holds(self) -> None:
        off = WEB.replace('type="default,supl"', 'type="default,supl" carrier_enabled="false"')
        code, _, result = self.run_guard(xml(WEB), xml(off))
        self.assertEqual(code, 1)
        self.assertIn(("attach_lost", HOLD), self.conditions(result))
        self.assertIn(("internet_lost", HOLD), self.conditions(result))


class PassTests(GuardCase):
    def test_mms_only_row_without_mmsc_removed_passes(self) -> None:
        bare = 'mcc="262" mnc="01" apn="mms" type="mms"'
        code, _, result = self.run_guard(xml(WEB, bare), xml(WEB))
        self.assertEqual((code, result["trips"]), (0, []))

    def test_apn_case_and_mmsc_trailing_slash_pass(self) -> None:
        vendor = [{"mcc": "262", "mnc": "01", "apn": "MMS", "type": "mms", "mmsc": "http://mms.example",
                   "_current": {"mms": ["samsung"]}}]
        head = 'mcc="262" mnc="01" apn="MMS" type="mms" mmsc="http://mms.example"'
        code, _, result = self.run_guard(xml(WEB, MMS), xml(WEB, head), vendor)
        self.assertEqual((code, result["trips"]), (0, []))

    def test_loss_only_on_iwlan_or_cdma_passes(self) -> None:
        threegpp = WEB + ' network_type_bitmask="1|2|3|10|13|15|20"'
        code, out, result = self.run_guard(xml(WEB), xml(threegpp))
        self.assertEqual((code, result["trips"]), (0, []))
        self.assertIn("internet lost only on IWLAN or CDMA: 1: 262/01", out)
        lte_iwlan = WEB + ' network_type_bitmask="1|2|3|10|13|15|18|20"'
        code, _, result = self.run_guard(xml(WEB), xml(lte_iwlan))
        self.assertEqual((code, result["trips"]), (0, []))

    def test_scope_removed_passes(self) -> None:
        other = 'mcc="262" mnc="02" apn="net" type="default"'
        code, out, result = self.run_guard(xml(WEB, MMS, other), xml(other))
        self.assertEqual((code, result["trips"]), (0, []))
        self.assertIn("scopes gone, network: 1: 262/01", out)

    def test_credentials_and_proxy_gained_pass_with_report(self) -> None:
        vendor = [{"mcc": "262", "mnc": "01", "apn": "web", "type": "default", "user": "a", "password": "b",
                   "_current": {"default": ["samsung"]}}]
        head = WEB + ' user="x" password="y" proxy="10.0.0.1" port="8080"'
        code, out, result = self.run_guard(xml(WEB), xml(head), vendor)
        self.assertEqual((code, result["trips"]), (0, []))
        self.assertIn("credentials gained or changed on the internet lead: 1: 262/01", out)
        self.assertIn("HTTP proxy gained or changed on the internet lead: 1: 262/01", out)
        self.assertIn("WARNING: 262/01 internet lead web: credentials a current vendor's", out)
        self.assertIn("WARNING: 262/01 internet lead web: proxy 10.0.0.1", out)

    def test_identical_files_pass_without_reading_the_generator(self) -> None:
        code, out, result = self.run_guard(xml(WEB, MMS), xml(WEB, MMS), generator=False)
        self.assertEqual((code, result["verdict"]), (0, "pass"))
        self.assertIn("unchanged", out)


class DigestTests(GuardCase):
    def test_exact_digest_passes(self) -> None:
        code, out, result = self.run_guard(xml(WEB, MMS), xml(WEB))
        self.assertEqual(code, 1)
        self.assertIn(f"phone-guard-accept: {result['digest']}", out)
        code, _, accepted = self.run_guard(xml(WEB, MMS), xml(WEB), extra=["--accept", result["digest"]])
        self.assertEqual((code, accepted["verdict"]), (0, "accepted"))

    def test_digest_of_another_trip_list_holds(self) -> None:
        _, _, other = self.run_guard(xml(WEB), xml(WEB + ' network_type_bitmask="20"'))
        code, _, result = self.run_guard(xml(WEB, MMS), xml(WEB), extra=["--accept", other["digest"]])
        self.assertNotEqual(other["digest"], result["digest"])
        self.assertEqual((code, result["verdict"]), (1, "hold"))

    def test_digest_covers_values(self) -> None:
        stale = 'mcc="262" mnc="01" apn="mms" type="mms" mmsc="http://old.example"'
        older = 'mcc="262" mnc="01" apn="mms" type="mms" mmsc="http://older.example"'
        vendor = [{"mcc": "262", "mnc": "01", "apn": "mms", "type": "mms", "mmsc": "http://mms.example/",
                   "_current": {"mms": ["samsung"]}}]
        _, _, one = self.run_guard(xml(WEB, MMS), xml(WEB, stale, MMS), vendor)
        _, _, two = self.run_guard(xml(WEB, MMS), xml(WEB, older, MMS), vendor)
        self.assertNotEqual(one["digest"], two["digest"])


class ErrorTests(GuardCase):
    def test_malformed_xml_exits_2(self) -> None:
        code, out, _ = self.run_guard(xml(WEB, MMS), xml(WEB, MMS)[:-8])
        self.assertEqual(code, 2)
        self.assertIn("ERROR", out)

    def test_rows_not_one_per_line_exit_2(self) -> None:
        joined = xml(WEB, MMS).replace(" />\n  <apn", " /><apn")
        code, _, _ = self.run_guard(xml(WEB, MMS), joined)
        self.assertEqual(code, 2)

    def test_generator_failure_exits_2(self) -> None:
        code, out, _ = self.run_guard(xml(WEB, MMS), xml(WEB), generator=False)
        self.assertEqual(code, 2)
        self.assertIn("ERROR", out)


if __name__ == "__main__":
    unittest.main()
