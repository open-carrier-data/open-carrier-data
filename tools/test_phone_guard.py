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


class CredentialsLostTests(GuardCase):
    """Report-only (rule decisions, round 14): a lead that stops sending
    credentials it sent before, judged on the resolved auth type."""

    CREDS = WEB + ' user="u" password="p"'
    SAMSUNG = {"mcc": "262", "mnc": "01", "apn": "web", "type": "default", "user": "u", "password": "p",
               "_current": {"default": ["samsung"]}}
    WARNING = ("WARNING: 262/01 {} lead web: sends no credentials, every current vendor row of this APN "
               "carries credentials")

    def test_lost_credentials_warn_when_every_current_row_of_the_apn_has_them(self) -> None:
        code, out, result = self.run_guard(xml(self.CREDS), xml(WEB), [self.SAMSUNG])
        self.assertEqual((code, result["verdict"], result["trips"], result["digest"]), (0, "pass", [], None))
        self.assertIn("credentials lost on the internet lead: 1: 262/01", out)
        self.assertIn("credentials lost on the attach lead: 1: 262/01", out)
        self.assertIn(self.WARNING.format("internet"), out)
        self.assertIn(self.WARNING.format("attach"), out)

    def test_lost_credentials_without_warning_when_a_current_vendor_gives_the_apn_bare(self) -> None:
        google = {"mcc": "262", "mnc": "01", "apn": "web", "type": "default", "_current": {"default": ["google"]}}
        code, out, result = self.run_guard(xml(self.CREDS), xml(WEB), [self.SAMSUNG, google])
        self.assertEqual((code, result["trips"]), (0, []))
        self.assertIn("credentials lost on the internet lead: 1: 262/01", out)
        self.assertNotIn("sends no credentials", out)

    def test_credentials_kept_with_auth_type_0_are_lost(self) -> None:
        held = self.CREDS + ' authtype="0"'
        code, out, result = self.run_guard(xml(self.CREDS), xml(held), [self.SAMSUNG])
        self.assertEqual((code, result["trips"]), (0, []))
        self.assertIn("credentials lost on the internet lead: 1: 262/01", out)
        self.assertIn(self.WARNING.format("internet"), out)
        code, out, _ = self.run_guard(xml(held), xml(WEB), [self.SAMSUNG])
        self.assertEqual(code, 0)
        self.assertNotIn("credentials lost", out)

    def test_lost_credentials_leave_trips_verdict_and_digest_unchanged(self) -> None:
        _, plain_out, plain = self.run_guard(xml(WEB, MMS), xml(WEB), [self.SAMSUNG])
        code, out, result = self.run_guard(xml(self.CREDS, MMS), xml(WEB), [self.SAMSUNG])
        self.assertNotIn("credentials lost", plain_out)
        self.assertIn("credentials lost on the internet lead: 1: 262/01", out)
        self.assertIn(self.WARNING.format("internet"), out)
        self.assertEqual((code, result["verdict"]), (1, "hold"))
        self.assertEqual((result["trips"], result["digest"]), (plain["trips"], plain["digest"]))
        code, _, accepted = self.run_guard(xml(self.CREDS, MMS), xml(WEB), [self.SAMSUNG],
                                           extra=["--accept", plain["digest"]])
        self.assertEqual((code, accepted["verdict"]), (0, "accepted"))


class ImsEmergencyReportTests(GuardCase):
    """Report-only (rule decisions of 2026-10-18, round 20): the `ims` and
    `emergency` leads and emergency-named internet or attach leads, on the
    hold types plus IWLAN, never in the trips or the digest."""

    WATCH = ",".join(guard.WATCH_TYPES)
    IMS = 'mcc="262" mnc="01" apn="ims" type="ims" protocol="IPV6" roaming_protocol="IPV6"'
    SOS = 'mcc="262" mnc="01" apn="sos" type="emergency" protocol="IPV4V6" roaming_protocol="IPV4V6"'

    def assert_report_only(self, base: list[str], head: list[str], line: str, value: str) -> dict:
        code, out, result = self.run_guard(xml(*base), xml(*head))
        self.assertEqual((code, result["verdict"], result["trips"], result["digest"]), (0, "pass", [], None))
        self.assertIn(line, out)
        self.assertIn(value, out)
        return result

    def test_ims_lead_lost(self) -> None:
        result = self.assert_report_only([WEB, self.IMS], [WEB], "ims lead lost: 1 scope(s)",
                                         f"262/01: ims IPV6/IPV6 -> none ({self.WATCH})")
        self.assertEqual([item["condition"] for item in result["watch"]], ["ims lead lost"])

    def test_ims_lead_apn_changed(self) -> None:
        other = self.IMS.replace('apn="ims"', 'apn="ims.example"')
        self.assert_report_only([WEB, self.IMS], [WEB, other], "ims lead APN changed: 1 scope(s)",
                                "262/01: ims IPV6/IPV6 -> ims.example IPV6/IPV6")

    def test_ims_lead_apn_case_change_is_not_reported(self) -> None:
        upper = self.IMS.replace('apn="ims"', 'apn="IMS"')
        code, out, result = self.run_guard(xml(WEB, self.IMS), xml(WEB, upper))
        self.assertEqual((code, result["watch"]), (0, []))
        self.assertIn("IMS and emergency report, never held: no change", out)

    def test_ims_lead_protocol_changed(self) -> None:
        dual = self.IMS.replace('roaming_protocol="IPV6"', 'roaming_protocol="IPV4V6"')
        self.assert_report_only([WEB, self.IMS], [WEB, dual], "ims lead protocol changed: 1 scope(s)",
                                "262/01: ims IPV6/IPV6 -> ims IPV6/IPV4V6")

    def test_unset_protocol_and_ip_are_the_same_on_a_phone(self) -> None:
        unset = 'mcc="262" mnc="01" apn="sos" type="emergency"'
        explicit = unset + ' protocol="IP" roaming_protocol="IP"'
        code, _, result = self.run_guard(xml(WEB, unset), xml(WEB, explicit))
        self.assertEqual((code, result["watch"]), (0, []))

    def test_emergency_lead_lost(self) -> None:
        self.assert_report_only([WEB, self.SOS], [WEB], "emergency lead lost: 1 scope(s)",
                                "262/01: sos IPV4V6/IPV4V6 -> none")

    def test_emergency_lead_apn_changed(self) -> None:
        named = self.SOS.replace('apn="sos"', 'apn="emergency"')
        self.assert_report_only([WEB, self.SOS], [WEB, named], "emergency lead APN changed: 1 scope(s)",
                                "262/01: sos IPV4V6/IPV4V6 -> emergency IPV4V6/IPV4V6")

    def test_emergency_lead_protocol_changed(self) -> None:
        narrow = 'mcc="262" mnc="01" apn="sos" type="emergency"'
        self.assert_report_only([WEB, self.SOS], [WEB, narrow], "emergency lead protocol changed: 1 scope(s)",
                                "262/01: sos IPV4V6/IPV4V6 -> sos IP/IP")

    def test_emergency_named_apn_becomes_the_internet_and_attach_lead(self) -> None:
        sos_default = 'mcc="262" mnc="01" apn="SOS" type="default" protocol="IPV6"'
        result = self.assert_report_only(
            [WEB], [sos_default, WEB], "emergency-named APN becomes the internet lead: 1 scope(s)",
            f"262/01: web -> SOS ({self.WATCH})")
        self.assertIn("emergency-named APN becomes the attach lead",
                      {item["condition"] for item in result["watch"]})

    def test_an_emergency_named_lead_that_stays_is_not_reported(self) -> None:
        sos_default = 'mcc="262" mnc="01" apn="SOS" type="default" protocol="IPV6"'
        e911 = 'mcc="262" mnc="01" apn="e911.example" type="default"'
        code, _, result = self.run_guard(xml(sos_default, WEB), xml(e911, WEB))
        self.assertEqual((code, result["watch"]), (0, []))

    def test_loss_only_on_iwlan_is_reported_and_cdma_is_not(self) -> None:
        wifi = self.IMS + ' network_type_bitmask="18"'
        cdma = self.IMS + ' network_type_bitmask="14"'
        both = self.IMS + ' network_type_bitmask="1|2|3|10|13|15|20"'
        self.assert_report_only([WEB, self.IMS], [WEB, both], "ims lead lost: 1 scope(s)",
                                "262/01: ims IPV6/IPV6 -> none (IWLAN)")
        code, _, result = self.run_guard(xml(WEB, wifi), xml(WEB))
        self.assertEqual([item["types"] for item in result["watch"]], [["IWLAN"]])
        code, _, result = self.run_guard(xml(WEB, cdma), xml(WEB))
        self.assertEqual((code, result["watch"]), (0, []))

    def test_report_lines_leave_trips_verdict_and_digest_unchanged(self) -> None:
        _, plain_out, plain = self.run_guard(xml(WEB, MMS), xml(WEB))
        code, out, result = self.run_guard(xml(WEB, MMS, self.IMS, self.SOS), xml(WEB))
        self.assertIn("IMS and emergency report, never held: no change", plain_out)
        self.assertIn("ims lead lost: 1 scope(s)", out)
        self.assertIn("emergency lead lost: 1 scope(s)", out)
        self.assertEqual((code, result["verdict"]), (1, "hold"))
        self.assertEqual((result["trips"], result["digest"]), (plain["trips"], plain["digest"]))
        code, _, accepted = self.run_guard(xml(WEB, MMS, self.IMS, self.SOS), xml(WEB),
                                           extra=["--accept", plain["digest"]])
        self.assertEqual((code, accepted["verdict"]), (0, "accepted"))

    def test_long_lists_are_cut_in_the_text_and_kept_in_the_json(self) -> None:
        rows = [f'mcc="262" mnc="{n:02d}" apn="ims" type="ims"' for n in range(guard.WATCH_LIST_LIMIT + 5)]
        webs = [f'mcc="262" mnc="{n:02d}" apn="web" type="default"' for n in range(guard.WATCH_LIST_LIMIT + 5)]
        code, out, result = self.run_guard(xml(*webs, *rows), xml(*webs))
        self.assertEqual(code, 0)
        self.assertIn(f"ims lead lost: {guard.WATCH_LIST_LIMIT + 5} scope(s)", out)
        self.assertIn("  ... 5 more (--report-json lists them all)", out)
        self.assertEqual(len(result["watch"]), guard.WATCH_LIST_LIMIT + 5)


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
