#!/usr/bin/env python3
"""The phone model (android_phone_model.py) on small apns-conf.xml fixtures."""

from __future__ import annotations

import unittest

import android_phone_model as phone

LTE, UMTS = 13, 3


def rows(*lines: str) -> list[dict]:
    return phone.parse_lines(f"  <apn {line} />" for line in lines)


def scope_profiles(xml_rows: list[dict], scope=("262", "01", "", "")):
    tables = phone.provider(xml_rows)
    stored = phone.scope_rows(tables, scope)
    return stored, phone.profiles(stored)


class DedupeLoopTests(unittest.TestCase):
    def test_last_similar_row_wins(self) -> None:
        # Both MMS rows are similar to the internet row as read; the loop
        # merges each with that original row, so the last one replaces the
        # first merge (DataProfileManager.java:877-897).
        xml = rows(
            'mcc="262" mnc="01" apn="web" type="default"',
            'mcc="262" mnc="01" apn="web" type="mms" mmsc="http://old/"',
            'mcc="262" mnc="01" apn="web" type="mms" mmsc="http://new/"',
        )
        stored, settings = scope_profiles(xml)
        self.assertEqual(len(stored), 3)
        self.assertEqual(len(settings), 1)
        self.assertEqual(settings[0]["mmsc"], "http://new/")
        self.assertEqual(settings[0]["types"], frozenset({"default", "mms"}))
        self.assertEqual(phone.absorbed_rows(xml), {1, 2})
        running = phone.profiles(stored, as_written=False)
        self.assertEqual([p["mmsc"] for p in running], ["http://old/", "http://new/"])

    def test_resolved_auth_types_differ_talkmobile_shape(self) -> None:
        # No auth type: 3 with a user, 0 without (ApnSetting.java:1054-1058).
        xml = rows(
            'mcc="262" mnc="01" apn="payg" type="default"',
            'mcc="262" mnc="01" apn="payg" type="mms" user="wap" mmsc="http://mms/"',
        )
        _, settings = scope_profiles(xml)
        self.assertEqual([p["authtype"] for p in settings], [0, 3])
        self.assertEqual(phone.absorbed_rows(xml), set())
        _, mms, _ = phone.leads(settings, LTE)
        self.assertEqual(mms["user"], "wap")


class ProviderTests(unittest.TestCase):
    def test_persist_apns_for_plmn_keeps_dun_row_apart(self) -> None:
        def stored(mnc: str) -> list[dict]:
            xml = rows(
                f'mcc="204" mnc="{mnc}" apn="internet" type="default,supl"',
                f'mcc="204" mnc="{mnc}" apn="internet" type="default,supl,dun"',
            )
            return phone.scope_rows(phone.provider(xml), ("204", mnc, "", ""))

        split = stored("04")
        self.assertEqual(len(split), 2)
        self.assertEqual(split[1]["profile_id"], 1)
        merged = stored("08")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["type"], "default,supl,dun")

    def test_bitmasks_merge_lra_shape(self) -> None:
        xml = rows(
            'mcc="311" mnc="140" apn="lra" type="default" network_type_bitmask="13"',
            'mcc="311" mnc="140" apn="lra" type="default" network_type_bitmask="3" user="u"',
        )
        tables = phone.provider(xml)
        stored = phone.scope_rows(tables, ("311", "140", "", ""))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["network_type_bitmask"], (1 << 12) | (1 << 2))
        self.assertEqual(stored[0]["user"], "u")
        internet, _, _ = phone.leads(phone.profiles(stored), UMTS)
        self.assertEqual(internet["apn"], "lra")
        xml_all = rows(
            'mcc="311" mnc="140" apn="lra" type="default" network_type_bitmask="13"',
            'mcc="311" mnc="140" apn="lra" type="default"',
        )
        stored_all = phone.scope_rows(phone.provider(xml_all), ("311", "140", "", ""))
        self.assertEqual(stored_all[0]["network_type_bitmask"], 0)


class FillInTests(unittest.TestCase):
    """Round 32, D8: which file row wrote each credential field of a stored
    row (`_writers`), and which of them a lower-ranked row fills in."""

    def test_a_lower_ranked_row_fills_in_what_the_best_row_leaves_unset(self) -> None:
        xml = rows(
            'mcc="262" mnc="01" apn="web" type="default" user="u" password="p" authtype="1" mtu="1400"',
            'mcc="262" mnc="01" apn="web" type="default,supl" authtype="0"',
        )
        stored, _ = scope_profiles(xml)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["_writers"], {"user": 0, "password": 0, "authtype": 1, "mtu": 0})
        self.assertEqual(phone.fill_ins(stored[0]), {"user": 0, "password": 0, "mtu": 0})

    def test_a_row_alone_or_a_best_row_that_sets_everything_fills_in_nothing(self) -> None:
        alone = rows('mcc="262" mnc="01" apn="web" type="default" user="u"')
        self.assertEqual(phone.fill_ins(scope_profiles(alone)[0][0]), {})
        both = rows(
            'mcc="262" mnc="01" apn="web" type="default" user="old" password="p"',
            'mcc="262" mnc="01" apn="web" type="default" user="new" password="q"',
        )
        stored = scope_profiles(both)[0][0]
        self.assertEqual((stored["user"], phone.fill_ins(stored)), ("new", {}))


class LeadTests(unittest.TestCase):
    def test_mms_over_the_internet_apn_when_it_serves_mms(self) -> None:
        xml = rows(
            'mcc="262" mnc="01" apn="web" type="default,mms" mmsc="http://a/"',
            'mcc="262" mnc="01" apn="mms" type="mms" mmsc="http://b/"',
        )
        stored, settings = scope_profiles(xml)
        _, mms, _ = phone.leads(settings, LTE)
        self.assertEqual(phone.mms_of(mms, stored), ("web", "http://a/", "", -1))

    def test_mmsc_fallback_by_apn_name(self) -> None:
        xml = rows(
            'mcc="262" mnc="01" apn="web" type="default,mms"',
            'mcc="262" mnc="01" apn="web" type="mms" mmsc="http://m/" mmsproxy="10.0.0.1" mmsport="80"',
        )
        stored, settings = scope_profiles(xml)
        self.assertEqual(len(settings), 2)
        _, mms, _ = phone.leads(settings, LTE)
        self.assertIsNone(mms["mmsc"])
        self.assertEqual(phone.mms_of(mms, stored), ("web", "http://m/", "10.0.0.1", 80))

    def test_disabled_row_serves_nothing(self) -> None:
        xml = rows(
            'mcc="262" mnc="01" apn="off" type="default,mms,ia" carrier_enabled="false" mmsc="http://x/"',
            'mcc="262" mnc="01" apn="on" type="default"',
        )
        _, settings = scope_profiles(xml)
        internet, mms, attach = phone.leads(settings, LTE)
        self.assertEqual(internet["apn"], "on")
        self.assertIsNone(mms)
        self.assertEqual(attach["apn"], "on")

    def test_network_types_limit_the_lead(self) -> None:
        xml = rows(
            'mcc="262" mnc="01" apn="lte" type="default" network_type_bitmask="13|20"',
            'mcc="262" mnc="01" apn="any" type="default"',
        )
        _, settings = scope_profiles(xml)
        self.assertEqual(phone.leads(settings, LTE)[0]["apn"], "lte")
        self.assertEqual(phone.leads(settings, UMTS)[0]["apn"], "any")


class EmptyTypeTests(unittest.TestCase):
    """An empty or missing type is Android's TYPE_ALL (ApnSetting
    getApnTypesBitmaskFromString), as `*` is: default, hipri, mms, supl, dun,
    fota, ims and cbs, without ia, emergency, xcap or mcx (rule decisions
    round 35, item C). Before, the model credited such a row with ia,
    emergency and xcap."""

    def test_empty_missing_and_star_are_type_all(self) -> None:
        for types in ("", None, "*"):
            self.assertEqual(phone.type_set(types), phone.WILDCARD_TYPES, types)
        self.assertEqual(phone.WILDCARD_TYPES,
                         frozenset({"default", "hipri", "mms", "supl", "dun", "fota", "ims", "cbs"}))

    def test_an_empty_type_row_is_no_ia_row(self) -> None:
        xml = rows(
            'mcc="262" mnc="01" apn="web"',
            'mcc="262" mnc="01" apn="attach" type="ia"',
        )
        _, settings = scope_profiles(xml)
        internet, mms, attach = phone.leads(settings, LTE)
        self.assertEqual((internet["apn"], mms["apn"], attach["apn"]), ("web", "web", "attach"))
        self.assertNotIn("xcap", settings[0]["types"])
        self.assertNotIn("emergency", settings[0]["types"])


if __name__ == "__main__":
    unittest.main()
