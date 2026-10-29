#!/usr/bin/env python3
"""The phone-level publish guard (check_phone_guard.py) on small
apns-conf.xml fixtures and a stand-in generator checkout."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
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
                  extra: list[str] | None = None, generator: bool = True,
                  base_vendor: list[dict] | None = None) -> tuple[int, str, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "base.xml").write_text(base, encoding="utf-8")
            (root / "head.xml").write_text(head, encoding="utf-8")
            checkout = root / "checkout"
            extra = list(extra or [])
            for path, records in ((checkout, vendor), (root / "base-checkout", base_vendor)):
                if not generator or (path != checkout and base_vendor is None):
                    continue
                (path / "tools").mkdir(parents=True)
                (path / "carriers").mkdir()
                (path / "tools" / "generate_android_outputs.py").write_text(FAKE_GENERATOR, encoding="utf-8")
                (path / "carriers" / "records.json").write_text(json.dumps(records or []), encoding="utf-8")
            if base_vendor is not None:
                extra += ["--base-generator", str(root / "base-checkout")]
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


def records_of(rows: list[tuple[str, dict, dict]]) -> list[dict]:
    """Stand-in generator records for the head file: each row's attributes
    with its `_support` and `_current`, in file order."""
    out = []
    for text, support, current in rows:
        row = guard.phone.parse_lines([f"<apn {text} />"])[0]
        out.append({**{k: v for k, v in row.items() if not k.startswith("_")},
                    "_support": support, "_current": current})
    return out


class CredentialFillInTests(GuardCase):
    """Report-only (rule decisions round 32, D8): a lead that takes a
    username, password, auth type or MTU from a lower-ranked row of its
    stored group that no current vendor backs, under a current vendor's best
    row (class (a))."""

    FILL = WEB + ' user="u" password="p" authtype="1"'
    LINEAGE = {"default": ["lineageos"], "supl": ["lineageos"]}
    GOOGLE = {"default": ["google_carriersettings"], "supl": ["google_carriersettings"]}
    OTHER = 'mcc="262" mnc="02" apn="net" type="default"'
    LINE = "credentials filled in from a non-current source on the {} lead: 1: 262/01 (lineageos)"

    def head_records(self, fill_current: dict | None = None) -> list[dict]:
        return records_of([(self.FILL, self.LINEAGE, fill_current or {}), (WEB, self.GOOGLE, self.GOOGLE)])

    def test_a_created_fill_in_is_reported_with_its_source(self) -> None:
        code, out, result = self.run_guard(xml(WEB), xml(self.FILL, WEB), self.head_records())
        self.assertEqual((code, result["verdict"], result["trips"], result["digest"]), (0, "pass", [], None))
        self.assertIn(self.LINE.format("internet"), out)
        self.assertIn(self.LINE.format("attach"), out)
        self.assertNotIn("credential sources: unknown", out)

    def test_an_unchanged_fill_in_is_not_reported(self) -> None:
        code, out, _ = self.run_guard(xml(self.FILL, WEB, self.OTHER), xml(self.FILL, WEB), self.head_records())
        self.assertEqual(code, 0)
        self.assertNotIn("credentials filled in", out)

    def test_changed_filled_in_values_are_reported(self) -> None:
        old = WEB + ' user="old" password="p" authtype="1"'
        _, out, _ = self.run_guard(xml(old, WEB), xml(self.FILL, WEB), self.head_records())
        self.assertIn(self.LINE.format("internet"), out)

    def test_a_current_vendors_fill_in_is_not_class_a(self) -> None:
        _, out, _ = self.run_guard(xml(WEB), xml(self.FILL, WEB), self.head_records(self.GOOGLE))
        self.assertNotIn("credentials filled in", out)

    def test_records_that_are_not_the_head_file_name_no_source(self) -> None:
        code, out, result = self.run_guard(xml(WEB), xml(self.FILL, WEB), [])
        self.assertEqual((code, result["trips"]), (0, []))
        self.assertNotIn("credentials filled in", out)
        self.assertIn("credential sources: unknown", out)

    def test_trips_and_digest_do_not_change(self) -> None:
        records = self.head_records() + records_of([])
        _, _, plain = self.run_guard(xml(WEB, MMS), xml(WEB), records_of([(WEB, self.GOOGLE, self.GOOGLE)]))
        code, out, result = self.run_guard(xml(WEB, MMS), xml(self.FILL, WEB), records)
        self.assertIn(self.LINE.format("internet"), out)
        self.assertEqual((code, result["trips"], result["digest"]), (1, plain["trips"], plain["digest"]))

    def test_class_a_list_of_a_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            (checkout / "tools").mkdir()
            (checkout / "carriers").mkdir()
            (checkout / "generated" / "android").mkdir(parents=True)
            (checkout / "tools" / "generate_android_outputs.py").write_text(FAKE_GENERATOR, encoding="utf-8")
            (checkout / "carriers" / "records.json").write_text(json.dumps(self.head_records()), encoding="utf-8")
            (checkout / "generated" / "android" / "apns-conf.xml").write_text(xml(self.FILL, WEB),
                                                                              encoding="utf-8")
            guard.generator_records.cache_clear()
            result = guard.class_a_list(checkout)
            printed = subprocess.run([sys.executable, str(Path(guard.__file__).with_name("credential_fill_ins.py")),
                                      str(checkout)], capture_output=True, text=True)
        self.assertEqual(printed.returncode, 0, printed.stderr)
        self.assertEqual(printed.stdout.splitlines(), result["lines"])
        self.assertTrue(result["sources_known"])
        self.assertIsNone(result["left_out"])
        self.assertEqual([(e["scope"], e["role"], e["apn"], e["fill_ins"], e["fill_in_sources"], e["sent"])
                          for e in result["entries"]],
                         [("262/01", "internet", "web", ["authtype", "password", "user"], ["lineageos"], True),
                          ("262/01", "attach", "web", ["authtype", "password", "user"], ["lineageos"], True)])
        self.assertEqual(result["lines"][0], "class (a) fill-ins: 2 LTE lead role(s) in 1 scope(s), 2 of them "
                                             "sent, in 1 scope(s)")
        self.assertIn("  262/01 internet web: authtype, password, user from lineageos; sent (all hold types)",
                      result["lines"])

    def test_rule_1_rows_are_listed(self) -> None:
        left = [{"scope": "262/20", "apn": "internet.mvno.mobi", "type": "default,supl", "fields": ["user", "password"],
                 "page": "", "read": "", "sources": ["google_pixel_vendor_carriersettings"]}]
        kept = [{"scope": "268/91", "apn": "net2.vodafone.pt", "type": "default,mms,supl", "fields": [],
                 "page": "https://operator.example/apn", "read": "2026-10-28", "sources": ["google_pixel_vendor_carriersettings"]}]
        lines = guard.class_a_lines([], left, kept)
        self.assertEqual(lines[1:], [
            "rows rule 1 left out of apns-conf.xml (superseded Google copies): 1",
            "  262/20 internet.mvno.mobi (default,supl): user, password from google_pixel_vendor_carriersettings",
            "rows rule 1 keeps because the operator's own page names credentials: 1",
            "  268/91 net2.vodafone.pt (default,mms,supl): https://operator.example/apn (read 2026-10-28)",
        ])

    def test_auth_type_0_keeps_the_fill_in_stored_only(self) -> None:
        best = WEB + ' authtype="0"'
        records = records_of([(self.FILL, self.LINEAGE, {}), (best, self.GOOGLE, self.GOOGLE)])
        rows = guard.phone.parse_lines([f"  <apn {self.FILL} />", f"  <apn {best} />"])
        entries = guard.class_a_entries(rows, guard.phone.provider(rows), records)
        self.assertEqual({(e["role"], tuple(e["fill_ins"]), e["sent"]) for e in entries},
                         {("internet", ("password", "user"), False), ("attach", ("password", "user"), False)})


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

    IMS_DEFAULT = "Android default ims IPV4V6/IPV4V6"

    def test_ims_lead_lost_lands_on_android_default(self) -> None:
        """No row can handle ims: Android adds its DEFAULT IMS profile
        (DataProfileManager.java:343-355; round 35, item C)."""
        result = self.assert_report_only([WEB, self.IMS], [WEB], "ims lead lost to Android's default: 1 scope(s)",
                                         f"262/01: ims IPV6/IPV6 -> {self.IMS_DEFAULT} ({self.WATCH})")
        self.assertEqual([item["condition"] for item in result["watch"]], ["ims lead lost to Android's default"])

    def test_ims_lead_gained_over_android_default(self) -> None:
        self.assert_report_only([WEB], [WEB, self.IMS], "ims lead gained over Android's default: 1 scope(s)",
                                f"262/01: {self.IMS_DEFAULT} -> ims IPV6/IPV6 ({self.WATCH})")

    def test_no_change_while_android_default_serves_ims(self) -> None:
        code, out, result = self.run_guard(xml(WEB), xml(WEB, MMS))
        self.assertEqual([item for item in result["watch"] if item["condition"].startswith("ims")], [])

    def test_ims_gained_on_an_internet_apn_displaces_android_default(self) -> None:
        """The 310/050 class (round 35, item C): an internet APN that takes
        ims (an empty type read as TYPE_ALL, or a `*`) becomes the IMS
        profile, and Android no longer adds its default."""
        empty = 'mcc="262" mnc="01" apn="web" protocol="IPV4V6" roaming_protocol="IPV4V6"'
        result = self.assert_report_only(
            [WEB], [empty], "IMS profile gained on an internet APN, displacing Android's DEFAULT IMS: 1 scope(s)",
            f"262/01: {self.IMS_DEFAULT} -> web IPV4V6/IPV4V6 ({self.WATCH})")
        self.assertIn("ims lead gained over Android's default",
                      [item["condition"] for item in result["watch"]])

    def test_ims_moving_onto_an_internet_apn_is_reported(self) -> None:
        everything = 'mcc="262" mnc="01" apn="web" type="default,hipri,mms,supl,dun,fota,ims,cbs"'
        self.assert_report_only([self.IMS, WEB], [everything, self.IMS],
                                "IMS profile moves onto an internet APN: 1 scope(s)",
                                "262/01: ims IPV6/IPV6 -> web IP/IP")

    def test_star_typed_ims_lead_no_vendor_backs_is_listed(self) -> None:
        everything = 'mcc="262" mnc="01" apn="web" type="default,hipri,mms,supl,dun,fota,ims,cbs"'
        types = ("default", "hipri", "mms", "supl", "dun", "fota", "ims", "cbs")
        old_copy = {t: ["sony_open_devices_aosp"] for t in types}
        vendor = records_of([(everything, old_copy, {}),
                             (self.IMS, {"ims": ["google_carriersettings"]}, {"ims": ["google_carriersettings"]})])
        code, out, result = self.run_guard(xml(everything, self.IMS), xml(everything, self.IMS), vendor)
        self.assertEqual(code, 0)
        _, out, result = self.run_guard(xml(WEB, everything, self.IMS), xml(everything, self.IMS), vendor)
        item = next(item for item in result["watch"]
                    if item["condition"] == "ims lead on a *-typed row no current vendor backs for ims")
        self.assertEqual((item["scope"], item["new"]), ("262/01", "web IP/IP"))
        self.assertIn("    262/01: web IP/IP (", out)
        self.assertEqual((result["verdict"], result["trips"]), ("pass", []))
        backed = records_of([(everything, old_copy, {"ims": ["google_carriersettings"]}),
                             (self.IMS, {"ims": ["google_carriersettings"]}, {"ims": ["google_carriersettings"]})])
        _, _, result = self.run_guard(xml(WEB, everything, self.IMS), xml(everything, self.IMS), backed)
        self.assertNotIn("ims lead on a *-typed row no current vendor backs for ims",
                         [item["condition"] for item in result["watch"]])

    def test_ims_lead_apn_changed(self) -> None:
        other = self.IMS.replace('apn="ims"', 'apn="ims.example"')
        self.assert_report_only([WEB, self.IMS], [WEB, other], "ims lead APN changed: 1 scope(s)",
                                "262/01: ims IPV6/IPV6 -> ims.example IPV6/IPV6")

    XCAP = 'mcc="262" mnc="01" apn="xcap" type="xcap" protocol="IPV4V6" roaming_protocol="IPV4V6"'

    def test_xcap_lead_apn_changed(self) -> None:
        """Rule round 34: report only, never held."""
        other = self.XCAP.replace('apn="xcap"', 'apn="hos"')
        result = self.assert_report_only([WEB, self.XCAP], [WEB, other], "xcap lead APN changed: 1 scope(s)",
                                         f"262/01: xcap IPV4V6/IPV4V6 -> hos IPV4V6/IPV4V6 ({self.WATCH})")
        self.assertEqual([item["condition"] for item in result["watch"]], ["xcap lead APN changed"])

    def test_xcap_lead_case_and_protocol_changes_are_not_reported(self) -> None:
        upper = self.XCAP.replace('apn="xcap"', 'apn="XCAP"').replace('roaming_protocol="IPV4V6"', 'roaming_protocol="IP"')
        code, _, result = self.run_guard(xml(WEB, self.XCAP), xml(WEB, upper))
        self.assertEqual((code, result["watch"]), (0, []))

    def test_attach_lead_apn_changed(self) -> None:
        """Rule round 34: report only, never held."""
        attach = 'mcc="262" mnc="01" apn="attach.example" type="ia" protocol="IPV4V6" roaming_protocol="IPV6"'
        result = self.assert_report_only([WEB], [attach, WEB], "attach lead APN changed: 1 scope(s)",
                                         f"262/01: web IP/IP -> attach.example IPV4V6/IPV6 ({self.WATCH})")
        self.assertEqual([item["condition"] for item in result["watch"]], ["attach lead APN changed"])

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

    DEFAULT = "Android default sos IPV4V6/IPV4V6"

    def test_emergency_lead_lost_lands_on_android_default(self) -> None:
        result = self.assert_report_only(
            [WEB, self.SOS], [WEB], "emergency lead lost: 1 scope(s)",
            f"262/01: sos IPV4V6/IPV4V6 [equal] -> {self.DEFAULT} ({self.WATCH})")
        self.assertEqual([item["condition"] for item in result["watch"]], ["emergency lead lost"])

    def test_emergency_lead_gained_with_its_label(self) -> None:
        narrow = self.SOS.replace('protocol="IPV4V6" roaming', 'protocol="IPV6" roaming')
        self.assert_report_only([WEB], [WEB, narrow], "emergency lead gained: 1 scope(s)",
                                f"262/01: {self.DEFAULT} -> sos IPV6/IPV4V6 [IPv6 only] ({self.WATCH})")

    def test_emergency_lead_gained_equal_to_the_default(self) -> None:
        self.assert_report_only([WEB], [WEB, self.SOS], "emergency lead gained: 1 scope(s)",
                                f"262/01: {self.DEFAULT} -> sos IPV4V6/IPV4V6 [equal]")

    def test_emergency_lead_changed_labels(self) -> None:
        cases = {
            'apn="EMERGENCY" type="emergency" protocol="IPV4V6" roaming_protocol="IPV4V6"': "[carrier name]",
            'apn="sos" type="emergency" protocol="IPV4V6" roaming_protocol="IP"': "[IPv4 only]",
            'apn="sos" type="emergency" protocol="IPV6" roaming_protocol="IPV6"': "[IPv6 only]",
            'apn="sos" type="emergency" protocol="IPV4V6" roaming_protocol="IPV4V6" mtu="1300"':
                "[request attribute]",
            'apn="sos" type="emergency" protocol="IPV4V6" roaming_protocol="IPV4V6" always_on="true"':
                "[request attribute]",
            'apn="sos" type="emergency" protocol="IPV4V6" roaming_protocol="IPV4V6" authtype="1"':
                "[request attribute]",
            'apn="vzwemergency" type="emergency" protocol="IPV6" roaming_protocol="IP"':
                "[carrier name, IPv4 only, IPv6 only]",
        }
        for row, label in cases.items():
            with self.subTest(row=row):
                self.assert_report_only([WEB, self.SOS], [WEB, 'mcc="262" mnc="01" ' + row],
                                        "emergency lead changed: 1 scope(s)",
                                        f"262/01: sos IPV4V6/IPV4V6 [equal] -> ")
                _, out, _ = self.run_guard(xml(WEB, self.SOS), xml(WEB, 'mcc="262" mnc="01" ' + row))
                self.assertIn(f"{label} ({self.WATCH})", out)

    def test_network_type_gap_has_no_android_fallback(self) -> None:
        lte_nr = self.SOS + ' bearer_bitmask="14|20"'
        result = self.assert_report_only(
            [WEB], [WEB, lte_nr], "emergency lead changed: 1 scope(s)",
            f"262/01: {self.DEFAULT} -> none [network-type gap] (GPRS,EDGE,UMTS,HSPA,HSPA+,IWLAN)")
        self.assertIn(f"262/01: {self.DEFAULT} -> sos IPV4V6/IPV4V6 [request attribute] (LTE,NR)",
                      "\n".join(f"262/01: {i['old']} -> {i['new']} ({','.join(i['types'])})"
                                 for i in result["watch"]))

    def test_lines_on_lte_nr_or_iwlan_come_first(self) -> None:
        gsm = 'mcc="262" mnc="02" apn="sos" type="emergency" protocol="IPV6" roaming_protocol="IPV6"' \
              ' network_type_bitmask="1|2"'
        lte = 'mcc="262" mnc="03" apn="sos" type="emergency" protocol="IPV6" roaming_protocol="IPV6"' \
              ' network_type_bitmask="13"'
        webs = [WEB.replace('mnc="01"', f'mnc="0{n}"') for n in (2, 3)]
        _, out, _ = self.run_guard(xml(*webs), xml(*webs, gsm, lte))
        lines = [line.strip() for line in out.splitlines() if "-> sos IPV6/IPV6" in line]
        self.assertEqual([line[:6] for line in lines], ["262/03", "262/02"], lines)

    def test_an_empty_type_cannot_handle_emergency(self) -> None:
        everything = 'mcc="262" mnc="01" apn="web" protocol="IPV6" roaming_protocol="IPV6"'
        code, out, result = self.run_guard(xml(WEB), xml(everything))
        self.assertEqual([item for item in result["watch"] if item["condition"].startswith("emergency")], [])
        self.assertEqual(guard.phone.type_set(""), guard.phone.WILDCARD_TYPES)
        self.assertFalse(guard.handles_emergency({"carrier_enabled": 1, "types": guard.phone.type_set("")}))

    def test_unset_protocol_is_ipv4_only(self) -> None:
        unset = 'mcc="262" mnc="01" apn="sos" type="emergency"'
        self.assert_report_only([WEB], [WEB, unset], "emergency lead gained: 1 scope(s)",
                                f"262/01: {self.DEFAULT} -> sos IP/IP [IPv4 only]")

    def test_an_emergency_row_of_another_apn_set_strands_the_scope(self) -> None:
        set1 = self.SOS + ' apn_set_id="1"'
        result = self.assert_report_only(
            [WEB], [WEB, set1], "emergency lead changed: 1 scope(s)",
            f"262/01: {self.DEFAULT} -> none [network-type gap] ({self.WATCH})")
        self.assertIn("emergency profile missing under APN set 0",
                      {item["condition"] for item in result["watch"]})

    def test_a_preferred_internet_set_strands_a_set_0_emergency_row(self) -> None:
        set1_web = 'mcc="262" mnc="01" apn="web2" type="default" apn_set_id="1"'
        result = self.assert_report_only([WEB, set1_web], [WEB, set1_web, self.SOS],
                                         "emergency profile missing under APN set 1: 1 scope(s)",
                                         "262/01: an emergency profile -> none")
        self.assertNotIn("emergency profile missing under APN set 0",
                         {item["condition"] for item in result["watch"]})
        minus1 = self.SOS + ' apn_set_id="-1"'
        code, _, result = self.run_guard(xml(WEB, set1_web), xml(WEB, set1_web, minus1))
        self.assertEqual({item["condition"] for item in result["watch"]}, {"emergency lead gained"})

    def test_emergency_named_apn_becomes_the_internet_and_attach_lead(self) -> None:
        sos_default = 'mcc="262" mnc="01" apn="SOS" type="default" protocol="IPV6"'
        result = self.assert_report_only(
            [WEB], [sos_default, WEB], "emergency-named APN becomes the internet lead: 1 scope(s)",
            f"262/01: web -> SOS ({self.WATCH})")
        self.assertIn("emergency-named APN becomes the attach lead",
                      {item["condition"] for item in result["watch"]})

    def test_the_guard_and_the_generator_agree_on_emergency_names(self) -> None:
        import carrier_config_types
        import generate_android_outputs
        self.assertIs(generate_android_outputs.emergency_named, carrier_config_types.emergency_named)
        names = {"sos": True, "SOS": True, "EMERGENCY": True, "emergency.volte.ims.cnt.net.ec": True,
                 "ims-emergency": True, "e911.mobilefrdm.ca": True, "VZWEMERGENCY": True, "E911": True,
                 "sos.example": False, "internet.voo.be": False, "ims": False, "my-e911": False, "": False,
                 None: False}
        self.assertEqual({name: guard.emergency_named(name) for name in names}, names)
        self.assertEqual({name: carrier_config_types.emergency_named(name) for name in names}, names)

    def test_an_emergency_named_lead_that_stays_is_not_reported(self) -> None:
        sos_default = 'mcc="262" mnc="01" apn="SOS" type="default" protocol="IPV6"'
        e911 = 'mcc="262" mnc="01" apn="e911.example" type="default"'
        code, _, result = self.run_guard(xml(sos_default, WEB), xml(e911, WEB))
        # Only the attach lead's APN change (rule round 34) is reported.
        self.assertEqual((code, [item["condition"] for item in result["watch"]]), (0, ["attach lead APN changed"]))

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
        self.assertIn("ims lead lost to Android's default: 1 scope(s)", out)
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
        self.assertIn(f"ims lead lost to Android's default: {guard.WATCH_LIST_LIMIT + 5} scope(s)", out)
        self.assertIn("  ... 5 more (--report-json lists them all)", out)
        self.assertEqual(len(result["watch"]), guard.WATCH_LIST_LIMIT + 5)


class Round35HardeningTests(GuardCase):
    """Rule decisions round 35, item E's guard hardening: the base's vendor
    tuples in the MMS test, role-specific backing of the internet and attach
    leads, network scopes that leave while a current vendor lists the code,
    and the fallback of MVNO scopes that leave."""

    VENDOR_MMS = [{"mcc": "262", "mnc": "01", "apn": "mms", "type": "mms", "mmsc": "http://mms.example/",
                   "_current": {"mms": ["samsung_omc"]}}]
    STALE = 'mcc="262" mnc="01" apn="mms" type="mms" mmsc="http://old.example"'

    def test_mms_off_a_base_vendor_tuple_trips_with_the_base_checkout(self) -> None:
        """The Ztar hole: the head no longer has the vendor's row, so the
        head's tuples alone see no vendor tuple to leave."""
        code, _, result = self.run_guard(xml(WEB, MMS), xml(WEB, self.STALE), [])
        self.assertEqual((code, result["trips"]), (0, []))
        code, out, result = self.run_guard(xml(WEB, MMS), xml(WEB, self.STALE), [], base_vendor=self.VENDOR_MMS)
        self.assertEqual(code, 1)
        self.assertEqual(self.conditions(result), {("mms_away", HOLD)})
        self.assertIn("MMS test: also against the base's vendor tuples", out)

    def test_mms_onto_a_head_vendor_tuple_passes_with_the_base_checkout(self) -> None:
        moved = [dict(self.VENDOR_MMS[0], mmsc="http://old.example")]
        code, _, result = self.run_guard(xml(WEB, MMS), xml(WEB, self.STALE), moved, base_vendor=self.VENDOR_MMS)
        self.assertEqual((code, result["trips"]), (0, []))

    def test_base_ref_reads_a_revision_of_the_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "tools").mkdir(parents=True)
            (repo / "carriers").mkdir()
            (repo / "generated").mkdir()
            (repo / "tools" / "generate_android_outputs.py").write_text(FAKE_GENERATOR, encoding="utf-8")
            (repo / "carriers" / "records.json").write_text(json.dumps(self.VENDOR_MMS), encoding="utf-8")
            (repo / "generated" / "evidence-index.json").write_text("{}", encoding="utf-8")
            git = ["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
            subprocess.run([*git, "init", "-q"], check=True)
            subprocess.run([*git, "add", "-A"], check=True)
            subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
            (repo / "carriers" / "records.json").write_text("[]", encoding="utf-8")
            (repo / "base.xml").write_text(xml(WEB, MMS), encoding="utf-8")
            (repo / "head.xml").write_text(xml(WEB, self.STALE), encoding="utf-8")
            guard.generator_records.cache_clear()
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = guard.run(["check_phone_guard.py", str(repo / "base.xml"), str(repo / "head.xml"),
                                  "--generator", str(repo), "--base-ref", "HEAD", "--report-json",
                                  str(repo / "r.json")])
            result = json.loads((repo / "r.json").read_text())
        self.assertEqual(code, 1, out.getvalue())
        self.assertEqual(self.conditions(result), {("mms_away", HOLD)})

    def test_base_ref_without_tools_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "carriers").mkdir(parents=True)
            (repo / "carriers" / "records.json").write_text("[]", encoding="utf-8")
            git = ["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
            subprocess.run([*git, "init", "-q"], check=True)
            subprocess.run([*git, "add", "-A"], check=True)
            subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
            (repo / "tools").mkdir()
            (repo / "tools" / "generate_android_outputs.py").write_text(FAKE_GENERATOR, encoding="utf-8")
            (repo / "base.xml").write_text(xml(WEB, MMS), encoding="utf-8")
            (repo / "head.xml").write_text(xml(WEB, self.STALE), encoding="utf-8")
            guard.generator_records.cache_clear()
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = guard.run(["check_phone_guard.py", str(repo / "base.xml"), str(repo / "head.xml"),
                                  "--generator", str(repo), "--base-ref", "HEAD"])
        self.assertEqual(code, 2, out.getvalue())

    def test_attach_to_an_apn_a_vendor_gives_only_for_mms_is_reported(self) -> None:
        """China Mobile's cmwap (round 35, item E): a vendor gives it for MMS,
        which does not back an attach."""
        cmnet = 'mcc="460" mnc="08" apn="cmnet" type="default,ia"'
        cmwap = 'mcc="460" mnc="08" apn="cmwap" type="default,ia,supl" proxy="10.0.0.172" port="80"'
        vendor = [{"mcc": "460", "mnc": "08", "apn": "cmwap", "type": "mms", "_current": {"mms": ["google"]}},
                  {"mcc": "460", "mnc": "08", "apn": "cmnet", "type": "default", "_current": {"default": ["google"]}}]
        code, out, _ = self.run_guard(xml(cmnet, cmwap), xml(cmwap, cmnet), vendor)
        self.assertEqual(code, 0)
        self.assertIn("attach lead moves to an APN no current vendor gives for default or ia: 1: 460/08", out)
        self.assertIn("internet lead moves to an APN no current vendor gives for default: 1: 460/08", out)
        backed = vendor + [{"mcc": "460", "mnc": "08", "apn": "cmwap", "type": "default",
                            "_current": {"default": ["google"]}}]
        _, out, _ = self.run_guard(xml(cmnet, cmwap), xml(cmwap, cmnet), backed)
        self.assertNotIn("lead moves to an APN no current vendor gives", out)

    def test_a_network_scope_a_vendor_lists_leaving_is_reported(self) -> None:
        other = 'mcc="262" mnc="02" apn="net" type="default"'
        listed = [{"mcc": "262", "mnc": "02", "mvno_type": "gid", "mvno_match_data": "ab", "apn": "x",
                   "type": "default", "_current": {"default": ["google_carriersettings"]}}]
        _, out, _ = self.run_guard(xml(WEB, other), xml(WEB), listed)
        self.assertIn("scopes gone, network, while a current Google, Samsung or Apple observation lists the code: "
                      "1: 262/02", out)
        _, out, _ = self.run_guard(xml(WEB, other), xml(WEB), [])
        self.assertNotIn("while a current Google", out)
        apple = [dict(listed[0], _current={}, _support={"default": ["apple_carrier_bundles"]})]
        _, out, _ = self.run_guard(xml(WEB, other), xml(WEB), [], base_vendor=apple)
        self.assertIn("observation lists the code: 1: 262/02", out)

    def test_an_mvno_scope_leaving_reports_its_fallback(self) -> None:
        gid = 'mcc="262" mnc="01" mvno_type="gid" mvno_match_data="ab" apn="brand.web" type="default,supl"'
        gid_mms = ('mcc="262" mnc="01" mvno_type="gid" mvno_match_data="ab" apn="brand.mms" type="mms" '
                   'mmsc="http://brand.example/"')
        _, out, result = self.run_guard(xml(WEB, gid, gid_mms), xml(WEB))
        self.assertEqual((result["verdict"], result["trips"]), ("pass", []))
        self.assertIn("MVNO scope gone, its SIMs' fallback changes the internet APN: 1: 262/01 GID ab "
                      "(brand.web -> web)", out)
        self.assertIn("MVNO scope gone, its SIMs' fallback changes the MMS APN: 1: 262/01 GID ab", out)
        _, out, _ = self.run_guard(xml(WEB, gid.replace('apn="brand.web"', 'apn="web"')), xml(WEB))
        self.assertNotIn("fallback changes the internet APN", out)


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
