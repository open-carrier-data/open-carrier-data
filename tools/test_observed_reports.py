#!/usr/bin/env python3
"""tools/observed_reports.py: the OCD Check report form, its checks, the
pointers into a main commit or a release, the noise filters and observed/."""

from __future__ import annotations

import contextlib
import copy
from datetime import date
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import observed_reports as obs

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 20)
DIGEST = "sha256:36d5f7ebb084a1a915c4961f8a5f3a11c70150b0fca7f68ccc050ffbe3989d37"
PROFILE = "open.26202.8cebd7550c67"
PROFILE_2 = "open.26203.0a1b2c3d4e5f"
# A commit of main the owner build pinned (round 29 S13), with data-2026.10's data.
COMMIT = "e32fd75687d01e7271b640c3adb41c52d42af6a8"


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
    """data-2026.10, and main's commit COMMIT with the same data, as far as the S20 report needs them."""

    def __init__(self) -> None:
        super().__init__(REPO)

    def tags(self) -> list[str]:
        return ["data-2026.10"]

    def on_main(self, commit: str) -> bool:
        return commit == COMMIT

    def digest(self, tag: str) -> str | None:
        return DIGEST if tag in ("data-2026.10", COMMIT) else None

    def profiles(self, tag: str) -> dict:
        return {PROFILE: {"sms_over_ims": "supported", "video_calling": "unknown", "volte": "conditional", "vonr": "supported", "vowifi": "supported"},
                PROFILE_2: {"volte": "unsupported", "vowifi": "unknown"}}

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
          login: str = "alice", created: str = "2026-10-20T10:00:00Z", user_id: int | None = None, **extra: object) -> dict:
    text = report if isinstance(report, str) else json.dumps(report, indent=1)
    user = {"login": login} if user_id is None else {"login": login, "id": user_id}
    return {"number": number, "title": title, "body": body(text), "state": "open", "state_reason": None,
            "labels": [{"name": obs.LABEL}], "user": user, "created_at": created, **extra}


# Rule round 29: the owner's account, by its GitHub user ID.
OWNER_ID = 122638570
BUILD = "CP2A.260605.016 1792814506"


def settled(level: str, method: str, measured_on: str, bearer: str | None = None) -> dict:
    out = {"level": level, "method": method, "measured_on": measured_on}
    return out if bearer is None else {**out, "bearer": bearer}


# The S20 on LineageOS 24.0 with AOSP ImsStack and the LIDL SIM, as the owner
# build writes it since round 29: the data commit, the ROM build, and the
# settled results of rounds 26 to 28 (VoLTE works, Wi-Fi calling calls out,
# SMS both ways).
OWNER_REPORT = {
    "schema": "ocd-check-test-report",
    "schema_version": 1,
    "app": {"name": "OCD Check", "build": "owner", "version": "0.3.0-owner"},
    "tested_on": "2026-10-24",
    "release": {"commit": COMMIT, "data_digest": DIGEST},
    "data_source": "pulled",
    "device": {"model": "SM-G981B", "codename": "x1s", "android_major": 16, "rom_family": "lineageos", "build_type": "userdebug",
               "ims_stack": "aosp_imsstack", "build": BUILD},
    "sim": {"mccmnc": "26202", "android_carrier_id": 2397, "spn": "LIDL Connect"},
    "ocd_profile": PROFILE,
    "results": [
        entry("volte:on", True, True, "works", calls=[{"test": "t2", "network": "lte"}],
              settled=settled("l3", "mailbox_call+real_call", "2026-10-23", "lte")),
        entry("volte:off", False, False, "not_tested", "off_tests_not_chosen"),
        entry("vowifi:on", True, True, "signed_in", settled=settled("l2", "mailbox_call", "2026-10-24", "iwlan")),
        entry("vowifi:off", False, False, "not_tested", "off_tests_not_chosen"),
        entry("sms_over_ims:on", True, True, "works", settled=settled("l3", "self_sms", "2026-10-22")),
        entry("sms_over_ims:off", False, False, "not_tested", "off_tests_not_chosen"),
    ],
}


def owner_changed(change) -> dict:
    report = copy.deepcopy(OWNER_REPORT)
    change(report)
    return report


# A correction on the owner's second SIM: OCD's profile gives VoLTE off
# (unsupported, no device record), the phone tested VoLTE on, it works, and
# the phone keeps it.
CORRECTION = owner_changed(lambda r: r.update(ocd_profile=PROFILE_2, sim={"mccmnc": "26203"}, results=[
    entry("volte:on", False, False, "works", calls=[{"test": "t2", "network": "lte"}], kept=True, restored=True,
          settled=settled("l3", "real_call+real_call", "2026-10-24", "lte")),
    entry("volte:off", True, True, "service_off"),
]))
# A clean measured failure of OCD's value: Wi-Fi calling on, tested, its
# mailbox call failed; the phone's state came back.
FAILURE = owner_changed(lambda r: r.update(results=[
    entry("vowifi:on", True, False, "failed", "calls_out_failed", restored=True, settled=settled("l2", "mailbox_call", "2026-10-24", "iwlan")),
    entry("vowifi:off", False, True, "service_off"),
]))


def errors_of(report: dict) -> list[str]:
    return obs.check_issue(issue(report=report), TODAY, RELEASES).errors


def changed(change) -> dict:
    report = copy.deepcopy(REPORT)
    change(report)
    return report


class ReportTest(unittest.TestCase):
    def test_the_schemas_use_only_the_validators_keywords(self) -> None:
        for name in (obs.REPORT_SCHEMA, obs.SUMMARY_SCHEMA, obs.RETESTED_SCHEMA):
            obs.load_schema(name, REPO / "schemas")

    def test_the_s20_report_is_valid(self) -> None:
        check = obs.check_issue(issue(), TODAY, RELEASES)
        self.assertEqual([], check.errors)
        self.assertEqual([], check.flags)
        self.assertTrue(check.valid)
        self.assertEqual(REPORT, check.report)
        self.assertEqual("data-2026.10", check.ref)
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
        self.assertEqual("data-2026.10", check.ref, "a bundled snapshot is found by its digest")

    def test_a_report_names_the_main_commit_it_read_its_data_at(self) -> None:
        """Round 29 S13: the commit and its data digest instead of a release tag; the bot checks every pointer against that commit."""
        pinned = changed(lambda r: r.update(release={"commit": COMMIT, "data_digest": DIGEST}))
        check = obs.check_issue(issue(report=pinned), TODAY, RELEASES)
        self.assertEqual(([], []), (check.errors, check.flags))
        self.assertEqual(COMMIT, check.ref)
        self.assertIn("Data: commit e32fd75687d0.", obs.comment(check, 7, "open-carrier-data/open-carrier-data"))
        bundled = changed(lambda r: (r.update(release={"commit": COMMIT, "data_digest": DIGEST}, data_source="bundled")))
        self.assertTrue(obs.check_issue(issue(report=bundled), TODAY, RELEASES).valid, "a bundled snapshot names the commit it was built from")
        other = "1" * 40
        self.assertIn("$.release.commit: is not a commit of OCD's main", errors_of(changed(lambda r: r.update(release={"commit": other, "data_digest": DIGEST}))))
        self.assertIn("$.release.data_digest: is not the data digest of commit e32fd75687d0",
                      errors_of(changed(lambda r: r.update(release={"commit": COMMIT, "data_digest": "sha256:" + "0" * 64}))))
        self.assertIn("$.ocd_profile: is not a profile of commit e32fd75687d0",
                      errors_of(changed(lambda r: (r.update(release={"commit": COMMIT, "data_digest": DIGEST}), r.update(ocd_profile="open.26202.000000000000")))))
        self.assertIn("$.results[10].entry: is not an APN row commit e32fd75687d0 has for 26202",
                      errors_of(changed(lambda r: (r.update(release={"commit": COMMIT, "data_digest": DIGEST}), r["results"][10].update(entry="apn:internet.example|default|IPV4V6")))))
        # One form or the other: a commit and a tag together, a short commit, a branch name or a commit without its digest fail the schema.
        for release in ({"commit": COMMIT, "tag": "data-2026.10", "data_digest": DIGEST}, {"commit": COMMIT[:12], "data_digest": DIGEST},
                        {"commit": "main", "data_digest": DIGEST}, {"commit": COMMIT}):
            found = errors_of(changed(lambda r: r.update(release=release)))
            self.assertTrue(any(e.startswith("$.release: matches none of the allowed forms") for e in found), (release, found))

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

    def test_every_ims_stack_the_schema_names_is_valid_and_only_phh_ims_flags_video(self) -> None:
        schema = json.loads((REPO / "schemas" / obs.REPORT_SCHEMA).read_text(encoding="utf-8"))
        stacks = schema["properties"]["device"]["properties"]["ims_stack"]["enum"]
        self.assertEqual(["phh_ims", "samsung_ims", "aosp_imsstack", "other", "not_known"], stacks)
        for stack in stacks:
            check = obs.check_issue(issue(report=changed(lambda r: r["device"].update(ims_stack=stack))), TODAY, RELEASES)
            self.assertEqual(([], []), (check.errors, check.flags), stack)
        # The S20 on LineageOS 24.0 runs Google's AOSP ImsStack (com.android.imsstack, 2026-10-22). Only PHH IMS
        # is known to have no video, so video calling that signed in there is not held as suspect.
        video = changed(lambda r: (r["device"].update(ims_stack="aosp_imsstack"), r["results"][5].update(result="signed_in"), r["results"][5].pop("reason")))
        check = obs.check_issue(issue(report=video), TODAY, RELEASES)
        self.assertEqual(([], []), (check.errors, check.flags))
        self.assertIn("IMS stack aosp_imsstack.", obs.comment(check, 7, "open-carrier-data/open-carrier-data"))
        found = errors_of(changed(lambda r: r["device"].update(ims_stack="imsstack")))
        self.assertTrue(any(e.startswith("$.device.ims_stack: must be one of") for e in found), found)

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

    def test_a_settled_result_agrees_with_rounds_26_to_28(self) -> None:
        """Rule round 29: a pass at L2 or L3, SMS both ways, or a clean measured failure, with the data commit and the ROM build."""
        for report in (OWNER_REPORT, CORRECTION, FAILURE):
            check = obs.check_issue(issue(report=report, user_id=OWNER_ID), date(2026, 10, 25), RELEASES)
            self.assertEqual(([], []), (check.errors, check.flags))

        def has(fragment: str, change) -> None:
            found = obs.check_issue(issue(report=owner_changed(change)), date(2026, 10, 25), RELEASES).errors
            self.assertTrue(any(fragment in e for e in found), (fragment, found))

        has("needs the data commit and its digest in $.release (round 29 S13)", lambda r: r.update(release={"tag": "data-2026.10", "data_digest": DIGEST}))
        has("needs the ROM build in $.device.build", lambda r: r["device"].pop("build"))
        has("only volte:on, vowifi:on and sms_over_ims:on carry a settled result",
            lambda r: r["results"][1].update(result="service_off", reason=None, settled=settled("l2", "real_call", "2026-10-24", "lte")) or r["results"][1].pop("reason"))
        has("$.results[0].settled.bearer: volte:on is measured on lte", lambda r: r["results"][0]["settled"].update(bearer="iwlan"))
        has("$.results[0].settled.bearer: volte:on is measured on lte", lambda r: r["results"][0]["settled"].pop("bearer"))
        has("l3 (works) is the result works with both legs", lambda r: r["results"][0]["settled"].update(method="mailbox_call"))
        has("l2 (calls out) is the result signed_in with one leg", lambda r: r["results"][2]["settled"].update(method="mailbox_call+real_call"))
        has("l2 (calls out) is the result signed_in", lambda r: r["results"][0]["settled"].update(level="l2", method="mailbox_call"))
        has("a call level is measured by calls", lambda r: r["results"][2]["settled"].update(method="self_sms"))
        has("SMS over IMS settles only as SMS both ways", lambda r: r["results"][4]["settled"].update(level="l2"))
        has("works for sms_over_ims:on needs SMS both ways settled", lambda r: r["results"][4].pop("settled"))
        has("$.results[0].settled.measured_on: is in the future", lambda r: r["results"][0]["settled"].update(measured_on="2026-10-27"))
        # The call ledger can settle a level after the run the report names (same build): not an error.
        later = obs.check_issue(issue(report=owner_changed(lambda r: r["results"][0]["settled"].update(measured_on="2026-10-25"))), date(2026, 10, 25), RELEASES)
        self.assertEqual([], later.errors)
        has("is more than 90 days before tested_on", lambda r: r["results"][0]["settled"].update(measured_on="2026-07-20"))
        has("only a pass or a clean measured failure is settled",
            lambda r: r["results"][2].update(result="failed", reason="revert_not_proven"))
        has("only a pass or a clean measured failure is settled",
            lambda r: r["results"][2].update(result="failed", reason="calls_out_failed", restored=False))
        has("a measured failure names the one call that failed",
            lambda r: r["results"][2].update(result="failed", reason="calls_out_failed", settled=settled("l2", "mailbox_call+real_call", "2026-10-24", "iwlan")))
        has("an incoming call is one of the owner's own calls",
            lambda r: r["results"][2].update(result="failed", reason="incoming_failed", settled=settled("l3", "mailbox_call", "2026-10-24", "iwlan")))
        for bad in ({"level": "l4", "method": "real_call", "measured_on": "2026-10-24"}, {"level": "l2", "method": "dtmf", "measured_on": "2026-10-24"},
                    {"level": "l2", "method": "real_call"}, {"level": "l2", "method": "real_call", "measured_on": "2026-10-24", "value": True}):
            found = obs.check_issue(issue(report=owner_changed(lambda r: r["results"][2].update(settled=bad))), date(2026, 10, 25), RELEASES).errors
            self.assertTrue(any(e.startswith("$.results[2].settled") for e in found), (bad, found))

    def test_the_rom_build_is_not_taken_for_a_phone_number(self) -> None:
        # "016 1792814506" has a phone number's shape; the build is a fixed-shape field.
        self.assertEqual([], obs.privacy_problems(OWNER_REPORT))
        found = obs.check_issue(issue(report=owner_changed(lambda r: r["device"].update(build="eng.bela.20261024"))), date(2026, 10, 25), RELEASES).errors
        self.assertIn("$.device.build: does not have the allowed form", found)

    def test_the_comment_names_the_settled_results_and_who_sent_them(self) -> None:
        check = obs.check_issue(issue(report=OWNER_REPORT, user_id=OWNER_ID), date(2026, 10, 25), RELEASES)
        text = obs.comment(check, 30, "open-carrier-data/open-carrier-data", owner=True)
        self.assertIn("- VoLTE on: works (L3): calls both ways over LTE (audio from packet counts); mailbox_call+real_call, measured 2026-10-23", text)
        self.assertIn("- Wi-Fi calling on: calls out (L2) over Wi-Fi, incoming not tested", text)
        self.assertIn("- SMS over IMS on: SMS both ways over IMS (L3); self_sms, measured 2026-10-22", text)
        self.assertIn("observed/retested.json", text)
        self.assertIn("as the owner's report it is not counted in `observed/summary.json`", text)
        self.assertIn("IMS stack aosp_imsstack, build CP2A.260605.016 1792814506.", text)
        outside = obs.comment(obs.check_issue(issue(report=OWNER_REPORT), date(2026, 10, 25), RELEASES), 31, "open-carrier-data/open-carrier-data")
        self.assertIn("Not from the owner's account", outside)

    def test_commit_pointers_are_read_from_main_s_history_and_a_commit_off_main_is_refused(self) -> None:
        """A real git history: two commits on main and one on a branch never merged, all with files under generated/."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args: str) -> str:
                return subprocess.run(["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
                                      check=True, capture_output=True, text=True).stdout.strip()

            def data(digest: str, apn: str) -> None:
                android = root / "generated" / "android"
                android.mkdir(parents=True, exist_ok=True)
                (root / "generated" / "devices").mkdir(parents=True, exist_ok=True)
                (android / "metadata.json").write_text(json.dumps({"data_digest": digest}), encoding="utf-8")
                (android / "lookup.json").write_text(json.dumps({"profiles": [{"profile_id": PROFILE, "capabilities": FakeReleases().profiles("")[PROFILE]}]}), encoding="utf-8")
                (root / "generated" / "devices" / "carrier-variants.json").write_text(json.dumps({"profiles": {PROFILE: {"volte": [], "video_calling": [], "vowifi": [], "vonr": []}}}), encoding="utf-8")
                (android / "apns-conf.xml").write_text(f'<apns version="8">\n  <apn apn="web.vodafone.de" mcc="262" mnc="02" type="default,supl" protocol="IPV4V6" />\n  {apn}\n</apns>\n', encoding="utf-8")
                git("add", "-A")
                git("commit", "-q", "-m", digest[-4:])

            git("init", "-q", "-b", "main")
            data("sha256:" + "a" * 64, "")
            first = git("rev-parse", "HEAD")
            data(DIGEST, '<apn apn="web.vodafone.de" mcc="262" mnc="02" type="default,supl,xcap" protocol="IPV4V6" />')
            second = git("rev-parse", "HEAD")
            git("checkout", "-q", "-b", "side", first)
            data(DIGEST, "")
            side = git("rev-parse", "HEAD")
            git("checkout", "-q", "main")

            releases = obs.Releases(root, "main")
            self.assertTrue(releases.on_main(first) and releases.on_main(second))
            self.assertFalse(releases.on_main(side), "a commit GitHub serves by SHA that main never merged")
            self.assertFalse(releases.on_main("0" * 40))
            self.assertEqual(DIGEST, releases.digest(second))
            self.assertEqual({"web.vodafone.de|default,supl|IPV4V6", "web.vodafone.de|default,supl,xcap|IPV4V6"}, releases.apn_keys(second, "26202"))
            two = [r for r in REPORT["results"] if not r["entry"].startswith("apn:")] + REPORT["results"][10:12]
            report = changed(lambda r: r.update(release={"commit": second, "data_digest": DIGEST}, results=two))
            check = obs.check_issue(issue(report=report), TODAY, releases)
            self.assertEqual([], check.errors)
            self.assertEqual(second, check.ref)
            off_main = changed(lambda r: r.update(release={"commit": side, "data_digest": DIGEST}, results=two))
            self.assertIn("$.release.commit: is not a commit of OCD's main", obs.check_issue(issue(report=off_main), TODAY, releases).errors)
            older = changed(lambda r: r.update(release={"commit": first, "data_digest": DIGEST}, results=two))
            self.assertIn(f"$.release.data_digest: is not the data digest of commit {first[:12]}", obs.check_issue(issue(report=older), TODAY, releases).errors)


class ObservedTest(unittest.TestCase):
    def issues(self) -> list[dict]:
        other_phone = changed(lambda r: (r["device"].update(model="SM-A505F", codename="a50", rom_family="stock", ims_stack="samsung_ims", android_major=14),
                                         r.update(results=[entry("vowifi:on", True, False, "failed", "settle_timeout", restored=True)]),
                                         r.update(release={"commit": COMMIT, "data_digest": DIGEST})))
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
            self.assertEqual({"written": [4, 5, 6, 7, 11, 14], "left_out": [8], "counted": [4, 7, 11], "owner": []}, result)
            self.assertFalse(stale.exists(), "a withdrawn report leaves observed/")

            def item(n: int) -> dict:
                return json.loads((root / "observed" / "reports" / f"issue-{n}.json").read_text(encoding="utf-8"))

            seven = item(7)
            self.assertEqual("counted", seven["status"])
            self.assertEqual("unverified", seven["verification"])
            self.assertEqual("data-2026.10", seven["release"])
            self.assertEqual(REPORT, seven["report"])
            self.assertEqual(COMMIT, item(11)["release"], "a report that names a commit is recorded with it")
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

    def test_the_aosp_imsstack_is_a_cell_of_its_own(self) -> None:
        # The same account's S20 before (PHH IMS) and after the move to Google's AOSP ImsStack: two cells,
        # so the newer report does not supersede the older one.
        aosp = changed(lambda r: (r["device"].update(ims_stack="aosp_imsstack"), r.update(tested_on="2026-10-22")))
        phh = issue(15, login="old", created="2026-10-01T00:00:00Z")
        moved = issue(16, report=aosp, login="old", created="2026-10-22T00:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = obs.rebuild([phh, moved], root, date(2026, 10, 25), RELEASES)
            self.assertEqual([15, 16], result["counted"])
            summary = json.loads((root / "observed" / "summary.json").read_text(encoding="utf-8"))
            volte = {c["stack"]["ims_stack"]: c for c in summary["cells"] if c["entry"] == "volte:on"}
            self.assertEqual({"aosp_imsstack", "phh_ims"}, set(volte))
            self.assertEqual({"rom_family": "lineageos", "ims_stack": "aosp_imsstack", "android_major": 16}, volte["aosp_imsstack"]["stack"])
            self.assertEqual(([15], [16]), (volte["phh_ims"]["reported"]["issues"], volte["aosp_imsstack"]["reported"]["issues"]))
            self.assertEqual([], obs.validate_tree(root))

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
            obs.rebuild(self.issues(), root, date(2026, 10, 25), RELEASES)
            eleven = root / "observed" / "reports" / "issue-11.json"
            item = json.loads(eleven.read_text(encoding="utf-8"))
            self.assertEqual([], obs.validate_tree(root), "a record of a commit report is valid")
            item["release"] = "1" * 40
            eleven.write_text(obs.dump(item), encoding="utf-8")
            self.assertIn("observed/reports/issue-11.json: release must be the commit the report names", obs.validate_tree(root))
            item["release"] = "main"
            eleven.write_text(obs.dump(item), encoding="utf-8")
            self.assertIn("observed/reports/issue-11.json: release must be a data release tag or a commit of main", obs.validate_tree(root))
            path.rename(root / "observed" / "reports" / "report.json")
            self.assertIn("observed/reports/report.json: the name must be issue-N.json", obs.validate_tree(root))

    def test_the_committed_observed_folder_is_valid(self) -> None:
        self.assertEqual([], obs.validate_tree(REPO))


class RetestedTest(unittest.TestCase):
    """Rule round 29: the owner's settled results as "re-tested by OCD" in observed/retested.json."""

    TODAY = date(2026, 10, 25)

    def owner(self, number: int, report: dict, created: str = "2026-10-24T03:00:00Z", **extra) -> dict:
        return issue(number, report=report, login="belagrf", user_id=OWNER_ID, created=created, **extra)

    def issues(self) -> list[dict]:
        again = owner_changed(lambda r: (r.update(tested_on="2026-10-25"), r["results"][0]["settled"].update(measured_on="2026-10-25")))
        repeat = owner_changed(lambda r: r.update(tested_on="2026-10-25"))  # the same measurements, sent again
        tagged = owner_changed(lambda r: (r.update(release={"tag": "data-2026.10", "data_digest": DIGEST}),
                                          [x.pop("settled", None) for x in r["results"]], r["results"][4].update(result="signed_in")))
        # An outside account with the same settled fields (written without indent, so not a duplicate): never re-tested.
        stranger = issue(40, report=json.dumps(OWNER_REPORT), login="mallory", user_id=1, created="2026-10-24T05:00:00Z")
        # A login that reads like the owner's but another account.
        imposter = issue(41, report=json.dumps(CORRECTION), login="belagrf", user_id=2, created="2026-10-24T06:00:00Z")
        return [self.owner(30, OWNER_REPORT), self.owner(31, again, "2026-10-25T03:00:00Z"), self.owner(32, repeat, "2026-10-25T04:00:00Z"),
                self.owner(33, CORRECTION), self.owner(34, FAILURE), self.owner(35, tagged), stranger, imposter]

    def rebuilt(self, root: Path, today: date | None = None) -> tuple[dict, dict, dict]:
        result = obs.rebuild(self.issues(), root, today or self.TODAY, RELEASES)
        retested = json.loads((root / "observed" / "retested.json").read_text(encoding="utf-8"))
        summary = json.loads((root / "observed" / "summary.json").read_text(encoding="utf-8"))
        return result, retested, summary

    def test_the_owner_s_settled_results_become_re_tested_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, retested, summary = self.rebuilt(root)
            # No account hold for the owner although the first report is a day old, and no supersede: every report counts.
            self.assertEqual([30, 31, 32, 33, 34, 35], result["owner"])
            self.assertEqual("owner", json.loads((root / "observed" / "reports" / "issue-30.json").read_text(encoding="utf-8"))["tester"])
            self.assertEqual("outside", json.loads((root / "observed" / "reports" / "issue-41.json").read_text(encoding="utf-8"))["tester"])
            self.assertEqual(("re-tested by OCD", "owner", "2026-10-25", 90), (retested["status"], retested["tester"], retested["as_of"], retested["expire_days"]))
            records = {(r["mccmnc"], r["entry"], r["result"]): r for r in retested["records"]}
            self.assertEqual({("26202", "volte:on", "works"), ("26202", "vowifi:on", "calls_out"), ("26202", "sms_over_ims:on", "sms_both_ways"),
                              ("26202", "vowifi:on", "failed"), ("26203", "volte:on", "works")}, set(records))
            volte = records[("26202", "volte:on", "works")]
            self.assertEqual({
                "status": "re-tested by OCD", "tester": "owner",
                "device": {"model": "SM-G981B", "codename": "x1s"}, "carrier_profile": PROFILE, "mccmnc": "26202",
                "stack": {"rom_family": "lineageos", "rom_build": BUILD, "ims_stack": "aosp_imsstack", "android_major": 16},
                "entry": "volte:on", "bearer": "lte", "result": "works", "level": "L3", "incoming": "tested",
                "method": "mailbox_call+real_call", "reason": None, "text": "works (L3): calls both ways over LTE (audio from packet counts)",
                "ocd": True, "correction": False,
                "n": 2, "first_measured": "2026-10-23", "last_measured": "2026-10-25", "valid_until": "2027-01-23",
                "data": {"commit": COMMIT, "data_digest": DIGEST}, "issues": [30, 31, 32],
            }, volte, "#30 and #32 repeat the 23rd's measurement and count once; #31 is the 25th")
            calls_out = records[("26202", "vowifi:on", "calls_out")]
            self.assertEqual(("L2", "not tested", "mailbox_call", 1, [30, 31, 32]), (calls_out["level"], calls_out["incoming"], calls_out["method"], calls_out["n"], calls_out["issues"]))
            self.assertIn("incoming not tested", calls_out["text"])
            sms = records[("26202", "sms_over_ims:on", "sms_both_ways")]
            self.assertEqual((None, "tested", "self_sms", "L3"), (sms["bearer"], sms["incoming"], sms["method"], sms["level"]))
            failed = records[("26202", "vowifi:on", "failed")]
            self.assertEqual(("calls_out_failed", "not tested", True, False, [34]), (failed["reason"], failed["incoming"], failed["ocd"], failed["correction"]) + (failed["issues"],))
            correction = records[("26203", "volte:on", "works")]
            self.assertEqual((PROFILE_2, False, True, "real_call+real_call", 1, [33]),
                             (correction["carrier_profile"], correction["ocd"], correction["correction"], correction["method"], correction["n"], correction["issues"]))
            self.assertTrue(all("value" not in json.dumps(r) for r in retested["records"]), "a record never carries a value")
            # The owner's reports are not "reported, not checked by OCD"; the outside ones are, settled fields or not.
            # The outside accounts' first reports wait out the account hold, settled fields or not.
            self.assertEqual({"counted": 0, "duplicate": 0, "expired": 0, "held": 2, "superseded": 0}, summary["reports"])
            self.assertEqual({"26202", "26203"}, {c["mccmnc"] for c in summary["cells"] if c["held"]})
            self.assertTrue(all(c["retested_by_ocd"] is None for c in summary["cells"]))
            self.assertEqual([], obs.validate_tree(root, self.TODAY))

    def test_re_tested_records_expire_90_days_after_the_last_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.rebuilt(root)
            path = root / "observed" / "retested.json"
            first = path.read_text(encoding="utf-8")
            # A quiet day changes nothing: the file and its as_of stay, so the bot opens no pull request.
            self.rebuilt(root, date(2026, 11, 3))
            self.assertEqual(first, path.read_text(encoding="utf-8"))
            self.assertEqual([], obs.validate_tree(root, date(2026, 11, 3)))
            # 2027-01-21 is 90 days after the 23rd: the 22nd's SMS record has lapsed, the rest has not.
            _, retested, _ = self.rebuilt(root, date(2027, 1, 21))
            self.assertEqual("2027-01-21", retested["as_of"])
            self.assertNotIn("sms_over_ims:on", {r["entry"] for r in retested["records"]})
            volte = [r for r in retested["records"] if r["entry"] == "volte:on" and r["mccmnc"] == "26202"][0]
            self.assertEqual(("2026-10-23", 2), (volte["first_measured"], volte["n"]), "the 23rd still holds on 2027-01-21")
            self.assertEqual([], obs.validate_tree(root, date(2027, 1, 21)))
            _, retested, _ = self.rebuilt(root, date(2027, 1, 24))
            self.assertEqual([], retested["records"], "every report is more than 90 days old: expired")

    def test_validate_catches_a_hand_edited_or_missing_retested_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.rebuilt(root)
            path = root / "observed" / "retested.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["records"][0]["n"] += 1
            path.write_text(obs.dump(data), encoding="utf-8")
            self.assertIn("is not what the reports give as of 2026-10-25", obs.validate_tree(root, self.TODAY)[0])
            data["records"][0]["value"] = True
            path.write_text(obs.dump(data), encoding="utf-8")
            self.assertTrue(any("unknown key value" in e for e in obs.validate_tree(root, self.TODAY)))
            self.rebuilt(root)
            self.assertIn("observed/retested.json: as_of is in the future", obs.validate_tree(root, date(2026, 10, 20)))
            path.unlink()
            self.assertIn("observed/retested.json: is missing", obs.validate_tree(root, self.TODAY))

    def test_a_maintainer_withdraws_an_owner_report_and_a_suspect_one_waits(self) -> None:
        issues = self.issues()
        issues[4].update(state="closed", state_reason="not_planned")  # #34, the failure
        video = owner_changed(lambda r: (r["device"].update(ims_stack="phh_ims"), r["results"].append(entry("video_calling:on", False, False, "signed_in"))))
        issues.append(self.owner(36, video))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs.rebuild(issues, root, self.TODAY, RELEASES)
            retested = json.loads((root / "observed" / "retested.json").read_text(encoding="utf-8"))
            self.assertNotIn("failed", {r["result"] for r in retested["records"]})
            self.assertNotIn("phh_ims", {r["stack"]["ims_stack"] for r in retested["records"]})
            held = json.loads((root / "observed" / "reports" / "issue-36.json").read_text(encoding="utf-8"))
            self.assertEqual("held", held["status"])
            self.assertIn("video calling passed on PHH IMS", held["status_reasons"][0])


class SourceReviewTest(unittest.TestCase):
    """One source-review issue per correction or measured failure of OCD's value (rule 10, rule round 29)."""

    def document(self) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs.rebuild(RetestedTest().issues(), root, RetestedTest.TODAY, RELEASES)
            return json.loads((root / "observed" / "retested.json").read_text(encoding="utf-8"))

    def test_one_issue_per_profile_and_feature(self) -> None:
        plan = obs.review_plan(self.document(), [], "open-carrier-data/open-carrier-data")
        # The correction on the second SIM and the measured failure of OCD's Wi-Fi calling; VoLTE on the first SIM is OCD's value and works.
        self.assertEqual([("create", f"{PROFILE}|26202|vowifi"), ("create", f"{PROFILE_2}|26203|volte")], [(p["action"], p["key"]) for p in plan])
        vowifi, volte = plan
        self.assertEqual(f"[Source review] VoLTE for {PROFILE_2} (26203)", volte["title"])
        self.assertTrue(volte["body"].startswith(f"<!-- ocd-source-review key={PROFILE_2}|26203|volte signature="))
        self.assertIn("the other value or none: the phone keeps this one", volte["body"])
        self.assertIn("`volte:on` works (L3): calls both ways over LTE", volte["body"])
        self.assertIn("from the report issues #33.", volte["body"])
        self.assertIn("changes nothing by itself", volte["body"])
        self.assertIn("`vowifi:on` failed (L2) at the outgoing call over Wi-Fi, incoming not tested: calls_out_failed", vowifi["body"])
        self.assertIn("this value, and it failed", vowifi["body"])
        # No identifier at all; the ROM build has a phone number's shape, so only the phone heuristics are off.
        self.assertEqual([], obs.scan_text("$", volte["body"] + vowifi["body"], phone_heuristics=False))

    def test_open_issues_are_updated_and_closed_ones_reopen_only_for_new_results(self) -> None:
        document = self.document()
        first = obs.review_plan(document, [], "open-carrier-data/open-carrier-data")
        bot = {"login": "github-actions[bot]"}
        opened = [{"number": 50 + i, "state": "open", "user": bot, "body": step["body"]} for i, step in enumerate(first)]
        self.assertEqual([], obs.review_plan(document, opened, "open-carrier-data/open-carrier-data"), "the text is current")
        stale = [dict(opened[0], body=opened[0]["body"].replace("as of 2026-10-25", "as of 2026-10-24")), opened[1]]
        self.assertEqual([("update", 50)], [(p["action"], p["number"]) for p in obs.review_plan(document, stale, "open-carrier-data/open-carrier-data")])
        closed = [dict(i, state="closed") for i in opened]
        self.assertEqual([], obs.review_plan(document, closed, "open-carrier-data/open-carrier-data"), "a closed review of the same results stays closed")
        renewed = copy.deepcopy(document)
        renewed["records"][0]["n"] += 1
        self.assertEqual([], obs.review_plan(renewed, closed, "open-carrier-data/open-carrier-data"), "a renewal is not a new result")
        moved = copy.deepcopy(document)
        for record in moved["records"]:
            record["stack"]["rom_build"] = "CP2A.260605.016 1793000000"
        self.assertEqual(["create", "create"], [p["action"] for p in obs.review_plan(moved, closed, "open-carrier-data/open-carrier-data")],
                         "a new ROM build measured it again")
        someone = [dict(i, user={"login": "mallory"}) for i in opened]
        self.assertEqual(["create", "create"], [p["action"] for p in obs.review_plan(document, someone, "open-carrier-data/open-carrier-data")],
                         "an issue the bot did not open is never taken over")

    def test_the_command_writes_a_plan_and_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            obs.rebuild(RetestedTest().issues(), root, RetestedTest.TODAY, RELEASES)
            (Path(tmp) / "issues.json").write_text("[]", encoding="utf-8")
            out = Path(tmp) / "out"
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                code = obs.main(["source-reviews", "--root", str(root), "--issues", str(Path(tmp) / "issues.json"), "--out", str(out)])
            self.assertEqual(0, code)
            self.assertIn(f"create: {PROFILE_2}|26203|volte", printed.getvalue())
            plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(["review-1.md", "review-2.md"], [p["body_file"] for p in plan])
            self.assertTrue((out / "review-1.md").read_text(encoding="utf-8").startswith("<!-- ocd-source-review"))


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

    def test_the_workflow_opens_source_reviews_from_main(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "ocd-check-report.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?ms)^  push:\n    branches: \[main\]\n    paths:\n      - observed/retested\.json$")
        job = workflow.split("\n  source-review:\n", 1)[1]
        self.assertIn("issues: write", job)
        self.assertNotIn("contents: write", job)
        self.assertIn("observed_reports.py source-reviews", job)
        self.assertIn(f"labels={obs.SOURCE_REVIEW_LABEL}", job)
        self.assertIn(f"--label {obs.SOURCE_REVIEW_LABEL}", job)


if __name__ == "__main__":
    unittest.main()
