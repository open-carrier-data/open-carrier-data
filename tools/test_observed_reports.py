#!/usr/bin/env python3
"""tools/observed_reports.py: the OCD Check report form, its checks, the
release pointers, the noise filters and observed/."""

from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path
import re
import tempfile
import unittest

import observed_reports as obs

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 20)
DIGEST = "sha256:36d5f7ebb084a1a915c4961f8a5f3a11c70150b0fca7f68ccc050ffbe3989d37"
PROFILE = "open.26202.8cebd7550c67"


def entry(name: str, ocd: bool, phone: bool, result: str, reason: str | None = None, calls: list | None = None, **extra) -> dict:
    """One result as the app writes it: reason, call_types and kept only when they say something."""
    out = {"entry": name, "ocd": ocd, "phone": phone, "how": "observed" if phone else "tested", "result": result}
    if reason is not None:
        out["reason"] = reason
    if calls:
        out["call_types"] = calls
    return {**out, **extra}


# The S20 (LineageOS 23.2, PHH IMS) with a LIDL Connect SIM on 2026-10-20, as
# the owner build writes it: every entry of data-2026.10 it tested or saw.
REPORT = {
    "schema": "ocd-check-test-report",
    "schema_version": 1,
    "app": {"name": "OCD Check", "build": "owner", "version": "0.3.0-owner"},
    "tested_on": "2026-10-20",
    "release": {"tag": "data-2026.10", "data_digest": DIGEST},
    "data_source": "pulled",
    "device": {"model": "SM-G981B", "codename": "x1s", "android_major": 16, "rom_family": "lineageos", "build_type": "userdebug", "ims_stack": "phh_ims"},
    "sim": {"mccmnc": "26202", "android_carrier_id": 2397, "spn": "LIDL Connect"},
    "ocd_profile": PROFILE,
    "results": [
        entry("volte:on", True, True, "works", calls=[{"test": "t2", "network": "lte"}], method="wfc_override"),
        entry("volte:off", False, False, "not_tested", "off_tests_not_chosen"),
        entry("sms_over_ims:on", True, True, "signed_in"),
        entry("sms_over_ims:off", False, False, "not_tested", "off_tests_not_chosen"),
        entry("video_calling:off", False, True, "service_off"),
        entry("video_calling:on", False, False, "not_possible", "not_available_on_this_build"),
        entry("vowifi:on", True, True, "signed_in"),
        entry("vowifi:off", False, False, "service_off", "service_gone", restored=True),
        entry("vonr:off", False, True, "service_off"),
        entry("vonr:on", True, False, "not_possible", "device_not_capable"),
        entry("apn:web.vodafone.de|default,supl|IPV4V6", True, True, "not_tested", "present"),
        entry("apn:web.vodafone.de|default,supl,xcap|IPV4V6", True, True, "not_tested", "same_as_phone_row"),
    ],
}


# The report the owner build (this change) opened on the S20 on 2026-10-20,
# taken from the prefilled URL in logcat, byte for byte. Its hash is the one
# the app logged.
CAPTURED_S20 = (
    '{\n'
    '  "schema": "ocd-check-test-report",\n'
    '  "schema_version": 1,\n'
    '  "app": {"name":"OCD Check","build":"owner","version":"0.3.0-owner"},\n'
    '  "tested_on": "2026-10-20",\n'
    '  "release": {"tag":"data-2026.10","data_digest":"sha256:36d5f7ebb084a1a915c4961f8a5f3a11c70150b0fca7f68ccc050ffbe3989d37"},\n'
    '  "data_source": "pulled",\n'
    '  "device": {"model":"SM-G981B","codename":"x1s","android_major":16,"rom_family":"lineageos","build_type":"userdebug","ims_stack":"phh_ims"},\n'
    '  "sim": {"mccmnc":"26202","android_carrier_id":2397,"spn":"LIDL Connect"},\n'
    '  "ocd_profile": "open.26202.8cebd7550c67",\n'
    '  "results": [\n'
    '    {"entry":"volte:on","ocd":true,"phone":true,"how":"observed","result":"signed_in","method":"wfc_override"},\n'
    '    {"entry":"volte:off","ocd":false,"phone":false,"how":"tested","result":"not_tested","reason":"off_tests_not_chosen"},\n'
    '    {"entry":"sms_over_ims:on","ocd":true,"phone":true,"how":"observed","result":"signed_in"},\n'
    '    {"entry":"sms_over_ims:off","ocd":false,"phone":false,"how":"tested","result":"not_tested","reason":"off_tests_not_chosen"},\n'
    '    {"entry":"video_calling:on","ocd":false,"phone":false,"how":"tested","result":"not_possible","reason":"not_available_on_this_build"},\n'
    '    {"entry":"video_calling:off","ocd":false,"phone":true,"how":"observed","result":"service_off"},\n'
    '    {"entry":"vowifi:on","ocd":true,"phone":true,"how":"observed","result":"signed_in"},\n'
    '    {"entry":"vowifi:off","ocd":false,"phone":false,"how":"tested","result":"not_tested","reason":"off_tests_not_chosen"},\n'
    '    {"entry":"vonr:on","ocd":true,"phone":false,"how":"tested","result":"not_possible","reason":"device_not_capable"},\n'
    '    {"entry":"vonr:off","ocd":false,"phone":true,"how":"observed","result":"service_off"},\n'
    '    {"entry":"apn:web.vodafone.de|default,supl|IPV4V6","ocd":true,"phone":true,"how":"observed","result":"not_tested","reason":"same_as_phone_row"},\n'
    '    {"entry":"apn:web.vodafone.de|default,supl,xcap|IPV4V6","ocd":true,"phone":true,"how":"observed","result":"not_tested","reason":"present"},\n'
    '    {"entry":"apn:web.vodafone.de|default|IPV4V6","ocd":true,"phone":true,"how":"observed","result":"not_tested","reason":"same_as_phone_row"},\n'
    '    {"entry":"apn:web.vodafone.de|default,dun|IPV4V6","ocd":true,"phone":true,"how":"observed","result":"not_tested","reason":"present"},\n'
    '    {"entry":"apn:web.vodafone.de|default,ia,supl|","ocd":true,"phone":true,"how":"observed","result":"not_tested","reason":"same_as_phone_row"},\n'
    '    {"entry":"apn:web.vodafone.de|default,supl|","ocd":true,"phone":true,"how":"observed","result":"not_tested","reason":"same_as_phone_row"}\n'
    '  ]\n'
    '}'
)
CAPTURED_S20_HASH = "sha256:40683d9b410665fa60d450d8c92092d19342df89be6aa929280313a52f39ec16"


class FakeReleases(obs.Releases):
    """data-2026.10 as far as the S20 report needs it."""

    def __init__(self) -> None:
        super().__init__(REPO)

    def tags(self) -> list[str]:
        return ["data-2026.10"]

    def digest(self, tag: str) -> str | None:
        return DIGEST if tag == "data-2026.10" else None

    def profiles(self, tag: str) -> dict:
        return {PROFILE: {"sms_over_ims": "supported", "video_calling": "unknown", "volte": "conditional", "vonr": "supported", "vowifi": "supported"}}

    def recorded(self, tag: str) -> set:
        return {(PROFILE, "volte"), (PROFILE, "video_calling"), (PROFILE, "vowifi"), (PROFILE, "vonr")}

    def apn_keys(self, tag: str, mccmnc: str) -> set:
        rows = {"web.vodafone.de|default,supl|IPV4V6", "web.vodafone.de|default,supl,xcap|IPV4V6", "web.vodafone.de|default|IPV4V6",
                "web.vodafone.de|default,dun|IPV4V6", "web.vodafone.de|default,ia,supl|", "web.vodafone.de|default,supl|", "emergency|emergency|IPV4V6"}
        return rows if mccmnc == "26202" else set()


RELEASES = FakeReleases()


def body(report_text: str, ticked: bool = True) -> str:
    """An issue body as GitHub writes the form: a `render: json` field is fenced."""
    box = "X" if ticked else " "
    return (
        "### Report\n\n```json\n" + report_text + "\n```\n\n### Privacy check\n\n"
        f"- [{box}] I read the report and it holds none of the private values listed in SECURITY.md.\n"
    )


def issue(number: int = 7, report: object = REPORT, title: str = "[OCD Check report] SM-G981B on 26202 (LIDL Connect)",
          login: str = "alice", created: str = "2026-10-20T10:00:00Z", **extra: object) -> dict:
    text = report if isinstance(report, str) else json.dumps(report, indent=1)
    return {"number": number, "title": title, "body": body(text), "state": "open", "state_reason": None,
            "labels": [{"name": obs.LABEL}], "user": {"login": login}, "created_at": created, **extra}


def errors_of(report: dict) -> list[str]:
    return obs.check_issue(issue(report=report), TODAY, RELEASES).errors


def changed(change) -> dict:
    report = copy.deepcopy(REPORT)
    change(report)
    return report


class ReportTest(unittest.TestCase):
    def test_the_schemas_use_only_the_validators_keywords(self) -> None:
        for name in (obs.REPORT_SCHEMA, obs.SUMMARY_SCHEMA):
            obs.load_schema(name, REPO / "schemas")

    def test_the_s20_report_is_valid(self) -> None:
        check = obs.check_issue(issue(), TODAY, RELEASES)
        self.assertEqual([], check.errors)
        self.assertEqual([], check.flags)
        self.assertTrue(check.valid)
        self.assertEqual(REPORT, check.report)
        self.assertEqual("data-2026.10", check.tag)
        self.assertEqual(obs.report_hash(json.dumps(REPORT, indent=1)), check.sha256)

    def test_the_hash_is_of_the_text_the_app_prefilled(self) -> None:
        text = json.dumps(REPORT)
        self.assertEqual(obs.report_hash(text), obs.report_hash("\r\n" + text.replace("\n", "\r\n") + "\n  "))
        self.assertRegex(obs.report_hash(text), r"^sha256:[0-9a-f]{64}$")

    def test_a_report_pasted_with_its_own_fence_and_a_bundled_report_pass(self) -> None:
        fenced = issue(report="```json\n" + json.dumps(REPORT) + "\n```")
        self.assertTrue(obs.check_issue(fenced, TODAY, RELEASES).valid)
        bundled = changed(lambda r: (r["release"].update(tag=None), r.update(data_source="bundled"), r.update(sim={"mccmnc": "26202"})))
        check = obs.check_issue(issue(report=bundled), TODAY, RELEASES)
        self.assertEqual([], check.errors)
        self.assertEqual("data-2026.10", check.tag, "a bundled snapshot is found by its digest")

    def test_a_report_points_only_into_the_release(self) -> None:
        self.assertIn("$.release.tag: data-2026.11 is not an OCD data release", errors_of(changed(lambda r: r["release"].update(tag="data-2026.11"))))
        self.assertIn("$.release.data_digest: is not the data digest of data-2026.10", errors_of(changed(lambda r: r["release"].update(data_digest="sha256:" + "0" * 64))))
        self.assertIn("$.release.data_digest: is the digest of no OCD data release; pull a release and test again",
                      errors_of(changed(lambda r: r["release"].update(tag=None, data_digest="sha256:" + "0" * 64))))
        self.assertIn("$.ocd_profile: is not a profile of data-2026.10", errors_of(changed(lambda r: r.update(ocd_profile="open.26202.000000000000"))))
        self.assertIn("$.results[10].entry: is not an APN row data-2026.10 has for 26202",
                      errors_of(changed(lambda r: r["results"][10].update(entry="apn:internet.example|default|IPV4V6"))))
        self.assertIn("$.results[10].entry: is not an APN row data-2026.10 has for 26203",
                      errors_of(changed(lambda r: r["sim"].update(mccmnc="26203"))))

    def test_no_report_carries_a_value(self) -> None:
        for name in ("carrier_volte_available_bool:on", "volte:true", "volte", "apn:web.vodafone.de", "apn:Web Vodafone|default|IPV4V6",
                     "iwlan.epdg_address:on", "volte:on;vonr:on"):
            self.assertTrue(any("$.results[0].entry: does not have the allowed form" in e for e in errors_of(changed(lambda r: r["results"][0].update(entry=name)))), name)
        self.assertTrue(any("unknown key apn_value" in e for e in errors_of(changed(lambda r: r["results"][10].update(apn_value="web.example")))))
        self.assertTrue(any("unknown key mmsc" in e for e in errors_of(changed(lambda r: r.update(mmsc="x")))))

    def test_the_comment_names_every_problem_without_the_values(self) -> None:
        report = changed(lambda r: (r["sim"].update(spn="+49 170 1234567"), r["device"].update(imsi="262021234567890"), r["results"][0].update(result="great")))
        check = obs.check_issue(issue(report=report), TODAY, RELEASES)
        self.assertFalse(check.valid)
        text = obs.comment(check, 7, "open-carrier-data/open-carrier-data")
        self.assertIn(obs.BOT_MARKER, text)
        self.assertIn("report:invalid", text)
        self.assertIn("`$.sim.spn`: looks like a phone number", text)
        self.assertIn("unknown key (a key not shown here)", text)
        self.assertIn("a key names a private identifier", text)
        self.assertIn("`$.results[0].result`: must be one of", text)
        self.assertIn("Something here looks like private data", text)
        for value in ("1234567", "262021234567890", "imsi", "great"):
            self.assertNotIn(value, text)

    def test_identifiers_are_refused_wherever_they_are(self) -> None:
        for value in ["sip:+4917012345678@ims.example", "10.0.0.1", "a@b.example", "8949" + "0" * 15, "+4917012345678", "0170 1234567"]:
            self.assertTrue(any("private data" in e or "phone number" in e or "allowed form" in e for e in errors_of(changed(lambda r: r["sim"].update(spn=value)))), value)
        self.assertTrue(errors_of(changed(lambda r: r["device"].update(model="SM-G981B 353456789012345"))))
        title = issue(title="[OCD Check report] call me +4917012345678")
        self.assertIn("the title: looks like private data (international_phone)", obs.check_issue(title, TODAY, RELEASES).errors)
        outside = issue()
        outside["body"] += "\nMy number is 0170 1234567\n"
        self.assertTrue(any(e.startswith("the issue text outside the report") for e in obs.check_issue(outside, TODAY, RELEASES).errors))

    def test_a_hash_or_gid1_prefix_made_of_digits_is_not_a_phone_number(self) -> None:
        report = changed(lambda r: r["sim"].update(gid1_prefix="0000000099"))
        self.assertEqual([], obs.privacy_problems(report))
        self.assertEqual([], obs.privacy_problems(changed(lambda r: r.update(ocd_profile="open.26202.012345678901"))))

    def test_the_form_shape_is_checked(self) -> None:
        unticked = issue()
        unticked["body"] = body(json.dumps(REPORT), ticked=False)
        self.assertIn("the \"Privacy check\" box is not ticked", obs.check_issue(unticked, TODAY, RELEASES).errors)
        no_field = issue()
        no_field["body"] = "Here is my report: " + json.dumps(REPORT)
        self.assertIn("no \"Report\" field", obs.check_issue(no_field, TODAY, RELEASES).errors[0])
        broken = obs.check_issue(issue(report='{"schema": "ocd-check-test-report",'), TODAY, RELEASES)
        self.assertTrue(broken.errors[0].startswith("the report is not valid JSON (line"))
        twice = obs.check_issue(issue(report='{"schema": 1, "schema": 2}'), TODAY, RELEASES)
        self.assertIn("the key schema appears twice", twice.errors[0])
        nan = obs.check_issue(issue(report='{"schema": NaN}'), TODAY, RELEASES)
        self.assertIn("NaN is not allowed", nan.errors[0])
        read_only = obs.check_issue(issue(report={"schema": "ocd-check-report.v1"}), TODAY, RELEASES)
        self.assertIn("read-only check's report", read_only.errors[0])

    def test_the_report_must_agree_with_itself(self) -> None:
        def has(fragment: str, change) -> None:
            found = errors_of(changed(change))
            self.assertTrue(any(fragment in e for e in found), (fragment, found))

        has("$.tested_on: is in the future", lambda r: r.update(tested_on="2026-10-25"))
        has("older than the OCD Check owner build", lambda r: r.update(tested_on="2026-01-01"))
        has("works needs a passed T2 call test", lambda r: r["results"][0].pop("call_types"))
        has("a T2 call must be on the feature's bearer", lambda r: r["results"][0].update(call_types=[{"test": "t2", "network": "iwlan"}]))
        has("covers only volte:on and vowifi:on", lambda r: r["results"][2].update(call_types=[{"test": "t2", "network": "lte"}]))
        has("belongs only to the off entry of a voice feature", lambda r: r["results"][3].update(call_types=[{"test": "with_feature_off", "network": "gsm"}]))
        has("works for an off entry needs a call measured", lambda r: r["results"][7].update(result="works"))
        has("for an off entry it must be one of", lambda r: r["results"][7].update(result="signed_in"))
        has("for an on entry it must be one of", lambda r: r["results"][6].update(result="service_off"))
        has("for an APN row it must be one of", lambda r: r["results"][10].update(result="signed_in"))
        has("not_possible needs a reason", lambda r: r["results"][5].pop("reason"))
        has("$.results[0].call_types: has fewer than 1 items", lambda r: r["results"][0].update(call_types=[]))
        has("$.results[5].reason: must be of type string", lambda r: r["results"][5].update(reason=None))
        has("the phone's own value is observed", lambda r: r["results"][1].update(how="observed"))
        has("only a tested entry that passed is kept", lambda r: r["results"][6].update(kept=True))
        has("is listed twice", lambda r: r["results"].__setitem__(1, copy.deepcopy(r["results"][0])))
        has("phone points at both vonr:on and vonr:off", lambda r: r["results"][9].update(phone=True, how="observed"))
        has("ocd points at both", lambda r: r["results"][1].update(ocd=True))
        has("the app never tests an emergency APN row", lambda r: r["results"][10].update(entry="apn:emergency|emergency|IPV4V6"))
        has("an APN row entry always points at OCD's row", lambda r: r["results"][10].update(ocd=False))
        has("the phone's own exactly when it is not tested because it is present", lambda r: r["results"][10].update(phone=False, how="tested"))
        has("OCD has no value without a profile", lambda r: r.update(ocd_profile=None))

    def test_plausibility_flags_hold_but_do_not_reject(self) -> None:
        video = changed(lambda r: (r["results"][5].update(result="signed_in"), r["results"][5].pop("reason")))
        check = obs.check_issue(issue(report=video), TODAY, RELEASES)
        self.assertTrue(check.valid)
        self.assertEqual(["$.results[5]: video calling passed on PHH IMS, which has no video"], check.flags)
        sms = changed(lambda r: (r["results"][2].update(ocd=False), r["results"][3].update(ocd=True)))
        flags = obs.check_issue(issue(report=sms), TODAY, RELEASES).flags
        self.assertEqual(["$.results[3].ocd: data-2026.10 gives sms_over_ims on for this profile, with no device record"], flags)
        text = obs.comment(obs.check_issue(issue(report=video), TODAY, RELEASES), 7, "open-carrier-data/open-carrier-data")
        self.assertIn("report:suspect", text)
        self.assertIn("Held as suspect", text)

    def test_the_valid_comment_says_hint_only_and_shows_the_hash(self) -> None:
        check = obs.check_issue(issue(), TODAY, RELEASES)
        text = obs.comment(check, 7, "open-carrier-data/open-carrier-data")
        self.assertIn("report:valid", text)
        self.assertIn(check.sha256, text)
        self.assertIn("observed/reports/issue-7.json", text)
        self.assertIn("never changes an OCD value", text)
        self.assertIn("never makes a phone skip its own test", text)
        self.assertIn("| VoLTE on | yes | yes | observed | works |", text)
        self.assertIn("| VoNR on | yes |  | tested | not_possible (device_not_capable) |", text)
        self.assertIn("| APN web.vodafone.de (default,supl, IPV4V6) | yes | yes | observed | not_tested (present) |", text)

    def test_the_report_the_s20_opened_is_valid_and_keeps_its_hash(self) -> None:
        check = obs.check_issue(issue(report=CAPTURED_S20), TODAY, RELEASES)
        self.assertEqual([], check.errors)
        self.assertEqual([], check.flags)
        self.assertEqual(CAPTURED_S20_HASH, check.sha256)
        self.assertEqual(16, len(check.report["results"]))

    @unittest.skipUnless("data-2026.10" in obs.Releases(REPO).tags(), "needs the data-2026.10 tag (fetched by the report workflow)")
    def test_the_captured_report_points_into_the_real_release(self) -> None:
        check = obs.check_issue(issue(report=CAPTURED_S20), TODAY, obs.Releases(REPO))
        self.assertEqual(([], []), (check.errors, check.flags))

    @unittest.skipUnless("data-2026.10" in obs.Releases(REPO).tags(), "needs the data-2026.10 tag (fetched by the report workflow)")
    def test_the_s20_report_points_into_the_real_release(self) -> None:
        check = obs.check_issue(issue(), TODAY, obs.Releases(REPO))
        self.assertEqual([], check.errors)
        self.assertEqual([], check.flags)


class ObservedTest(unittest.TestCase):
    def issues(self) -> list[dict]:
        other_phone = changed(lambda r: (r["device"].update(model="SM-A505F", codename="a50", rom_family="stock", ims_stack="samsung_ims", android_major=14),
                                         r.update(results=[entry("vowifi:on", True, False, "failed", "settle_timeout", restored=True)])))
        withdrawn = issue(9, login="bob", created="2026-09-01T10:00:00Z")
        withdrawn.update(state="closed", state_reason="not_planned")
        done = issue(11, report=other_phone, login="carol", created="2026-10-01T10:00:00Z")
        done.update(state="closed", state_reason="completed")
        unlabeled = issue(12)
        unlabeled["labels"] = []
        pull = issue(13)
        pull["pull_request"] = {"url": "x"}
        bad = issue(8, report={"schema": "ocd-check-test-report"})
        newcomer = issue(14, report=changed(lambda r: r.update(tested_on="2026-10-19")), login="dave", created="2026-10-19T10:00:00Z")
        older = issue(5, report=changed(lambda r: r.update(tested_on="2026-10-02")), login="alice", created="2026-10-02T10:00:00Z")
        copy_of_5 = issue(6, report=changed(lambda r: r.update(tested_on="2026-10-02")), login="erin", created="2026-10-03T10:00:00Z")
        copy_of_5["body"] = older["body"]
        stale = issue(4, report=changed(lambda r: r.update(tested_on="2026-10-01")), login="frank", created="2026-10-01T09:00:00Z")
        return [done, issue(7), bad, withdrawn, unlabeled, pull, newcomer, older, copy_of_5, stale]

    def test_rebuild_applies_the_noise_filters_and_counts_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "observed" / "reports").mkdir(parents=True)
            stale = root / "observed" / "reports" / "issue-9.json"
            stale.write_text("{}", encoding="utf-8")
            today = date(2026, 10, 25)
            result = obs.rebuild(self.issues(), root, today, RELEASES)
            self.assertEqual({"written": [4, 5, 6, 7, 11, 14], "left_out": [8], "counted": [4, 7, 11]}, result)
            self.assertFalse(stale.exists(), "a withdrawn report leaves observed/")

            def item(n: int) -> dict:
                return json.loads((root / "observed" / "reports" / f"issue-{n}.json").read_text(encoding="utf-8"))

            seven = item(7)
            self.assertEqual("counted", seven["status"])
            self.assertEqual("unverified", seven["verification"])
            self.assertEqual("data-2026.10", seven["release"])
            self.assertEqual(REPORT, seven["report"])
            self.assertEqual("superseded", item(5)["status"], "one counted report per account and cell: the newest")
            self.assertEqual(("duplicate", ["the same report as #5"]), (item(6)["status"], item(6)["status_reasons"]))
            self.assertEqual("held", item(14)["status"])
            self.assertIn("new_account", item(14)["status_reasons"][0])
            self.assertEqual("counted", item(4)["status"], "an account's age counts from its first accepted report")
            expired = obs.rebuild(self.issues(), root, date(2027, 2, 1), RELEASES)
            self.assertEqual([], expired["counted"], "every report is older than 90 days by then")
            obs.rebuild(self.issues(), root, today, RELEASES)

            summary = json.loads((root / "observed" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual("unverified", summary["verification"])
            self.assertEqual({"counted": 3, "duplicate": 1, "expired": 0, "held": 1, "superseded": 1}, summary["reports"])
            self.assertEqual({"reported", "contested", "retested_by_ocd"}, set(summary["statuses"]))
            self.assertTrue(all(cell["verification"] == "unverified" and cell["retested_by_ocd"] is None for cell in summary["cells"]))
            s20 = {c["entry"]: c for c in summary["cells"] if c["device"]["codename"] == "x1s"}
            volte = s20["volte:on"]["reported"]
            self.assertEqual("reported, not checked by OCD", volte["status"])
            self.assertEqual(2, volte["count"], "#4 and #7, from two accounts")
            self.assertEqual(2, volte["results"]["works"])
            self.assertEqual(("2026-10-01", "2026-10-20"), (volte["first_report"], volte["last_report"]))
            self.assertEqual([4, 7], volte["issues"])
            self.assertEqual(1, s20["volte:on"]["held"], "the new account's report waits")
            self.assertEqual({"rom_family": "lineageos", "ims_stack": "phh_ims", "android_major": 16}, s20["volte:on"]["stack"])
            self.assertIsNone(s20["volte:on"]["contested"])
            a50 = [c for c in summary["cells"] if c["device"]["codename"] == "a50"][0]
            self.assertEqual("vowifi:on", a50["entry"])
            self.assertEqual({"status": "contested: a clean measured failure was reported", "count": 1, "first_report": "2026-10-01",
                              "last_report": "2026-10-01", "issues": [11]}, a50["contested"])
            self.assertEqual([], obs.validate_tree(root))
            before = {p.name: p.read_text(encoding="utf-8") for p in (root / "observed").rglob("*.json")}
            obs.rebuild(self.issues(), root, today, RELEASES)
            self.assertEqual(before, {p.name: p.read_text(encoding="utf-8") for p in (root / "observed").rglob("*.json")}, "a rebuild is deterministic")
            body = obs.pr_body(result, before={9})
            self.assertIn("Closes #7", body)
            self.assertIn("Removed (withdrawn, closed as not planned, or no longer valid): #9.", body)
            self.assertIn("Left out as not valid: #8.", body)
            self.assertIn("counted: #4, #7, #11", body)
            self.assertIn("**unverified**", body)

    def test_a_maintainer_label_releases_a_hold_and_an_unclean_failure_contests_nothing(self) -> None:
        newcomer = issue(14, login="dave", created="2026-10-19T10:00:00Z", labels=[{"name": obs.LABEL}, {"name": obs.HOLD_RELEASED_LABEL}])
        broke = changed(lambda r: r.update(results=[entry("vowifi:off", False, False, "failed", "revert_not_proven")]))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = obs.rebuild([newcomer, issue(20, report=broke, login="old", created="2026-10-01T00:00:00Z")], root, date(2026, 10, 25), RELEASES)
            self.assertEqual([14, 20], result["counted"])
            summary = json.loads((root / "observed" / "summary.json").read_text(encoding="utf-8"))
            off = [c for c in summary["cells"] if c["entry"] == "vowifi:off"][0]
            self.assertEqual(1, off["reported"]["results"]["failed"])
            self.assertIsNone(off["contested"], "a test that broke says nothing about the entry")

    def test_validate_catches_hand_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs.rebuild(self.issues(), root, date(2026, 10, 25), RELEASES)
            summary = root / "observed" / "summary.json"
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["cells"][0]["held"] += 1
            summary.write_text(obs.dump(data), encoding="utf-8")
            self.assertIn("is not what the reports give", obs.validate_tree(root)[0])
            obs.rebuild(self.issues(), root, date(2026, 10, 25), RELEASES)
            path = root / "observed" / "reports" / "issue-7.json"
            item = json.loads(path.read_text(encoding="utf-8"))
            item["verification"] = "verified"
            path.write_text(obs.dump(item), encoding="utf-8")
            self.assertIn("observed/reports/issue-7.json: verification must be unverified", obs.validate_tree(root))
            path.rename(root / "observed" / "reports" / "report.json")
            self.assertIn("observed/reports/report.json: the name must be issue-N.json", obs.validate_tree(root))

    def test_the_committed_observed_folder_is_valid(self) -> None:
        self.assertEqual([], obs.validate_tree(REPO))


class FormTest(unittest.TestCase):
    """The issue form and the tool agree: the field the app prefills, its heading, the label and the title."""

    def test_the_form_matches_the_tool(self) -> None:
        form = (REPO / ".github" / "ISSUE_TEMPLATE" / obs.TEMPLATE).read_text(encoding="utf-8")
        self.assertRegex(form, r"(?m)^name: OCD Check report$")
        self.assertIn(f'title: "{obs.TITLE_PREFIX} "', form)
        self.assertRegex(form, rf"(?m)^labels:\n  - {re.escape(obs.LABEL)}$")
        report = re.search(r"(?ms)^  - type: textarea\n    id: report\n    attributes:\n      label: (.+?)\n.*?      render: json\n", form)
        self.assertIsNotNone(report, "the textarea the app prefills is id report, rendered as JSON")
        self.assertEqual(obs.REPORT_HEADING, report.group(1))
        self.assertRegex(form, rf"(?m)^      label: {obs.PRIVACY_HEADING}$")
        workflow = (REPO / ".github" / "workflows" / "ocd-check-report.yml").read_text(encoding="utf-8")
        self.assertIn(f"startsWith(github.event.issue.title, '{obs.TITLE_PREFIX}')", workflow)
        self.assertIn(f"'{obs.LABEL}'", workflow)
        for label in (obs.VALID_LABEL, obs.SUSPECT_LABEL, obs.INVALID_LABEL):
            self.assertIn(label, workflow)
        self.assertNotIn("github.event.issue.body", workflow, "the body reaches the tool only as a file")


if __name__ == "__main__":
    unittest.main()
