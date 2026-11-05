#!/usr/bin/env python3
"""tools/validate_operators.py: generated/operators/ (rule round 32) and rule 3's
prefix limits on every published file. Every value here is synthetic; the
networks are the test network 001-01 and 001-02."""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
import tempfile
import unittest

import validate_operators as vo

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 28)


def statement(**changes):
    item = {
        "id": "zz.net.mms",
        "identity_key": "zz.net",
        "operator": "Test network",
        "country": "ZZ",
        "service": "mms",
        "status": "ended",
        "scope": "network",
        "mccmnc": ["00101"],
        "mmsc_hosts": ["mms.example.test"],
        "host_only": False,
        "last_day": "2026-06-30",
        "first_day_without": "2026-07-01",
        "checked_at": "2026-10-28",
        "swept_at": "2026-10-28",
        "paraphrase": "The test network states that its MMS service ended on 30 June 2026.",
        "second_check": {"on": "2026-10-28", "verdict": "confirmed"},
        "sets_value": True,
        "sources": [
            {
                "url": "https://operator.example.test/mms-end",
                "publisher": "Test network help page",
                "kind": "operator",
                "role": "admits",
                "date": None,
                "read_on": "2026-10-28",
                "passage_sha256": "sha256:" + "0" * 64,
            }
        ],
        "history": [{"on": "2026-10-28", "event": "admitted", "status": "ended"}],
    }
    item.update(changes)
    return item


def statements_file(items):
    return {
        "schema_version": 1,
        "description": "test",
        "license": "CC0-1.0",
        "display_rule": "test",
        "countries": sorted({item["country"] for item in items}),
        "counts": {
            "statements": len(items),
            "lapsed": sum(1 for item in items if "lapsed" in item),
            "sets_value": sum(1 for item in items if item["sets_value"]),
        },
        "mms_ended_networks": [
            {"mccmnc": code, "statement": item["id"], "first_day_without": item["first_day_without"]}
            for item in items
            if item["service"] == "mms" and item["scope"] == "network" and item.get("previous_status", item["status"]) == "ended"
            for code in item["mccmnc"]
        ],
        "statements": items,
    }


PROFILE = {
    "schema_version": 1,
    "profile_id": "open.00101.000000000001",
    "display_name": "Test",
    "match": {"mccmnc": ["00101"]},
    "capabilities": {"mms": "unsupported"},
    "android_carrier_config": {"enabledMMS": False},
    "android_apns": [{"apn": "mms", "types": ["mms"], "mmsc": "http://mms.example.test/mms"}],
}


def identity_file(selectors=None):
    return {
        "schema_version": 1,
        "description": "test",
        "license": "CC0-1.0",
        "countries": ["ZZ"],
        "entries": [
            {
                "key": "zz.net",
                "name": "Test network",
                "kind": "operator",
                "country": "ZZ",
                "operator_key": "zz.net",
                "host_networks": ["00101"],
                "host_only": False,
                "selectors": selectors if selectors is not None else [{"match": {"mccmnc": ["00101"]}, "profile_id": PROFILE["profile_id"], "families": ["lineageos"]}],
                "labels": [],
            }
        ],
    }


EVIDENCE = {
    "profiles": [
        {
            "profile_id": PROFILE["profile_id"],
            "capability_sources": {"mms": {"off": ["operator_statement"], "on": ["lineageos"]}},
            "conflicts": [{"kind": "conflict", "section": "capabilities", "key": "mms", "observed_value_count": 2, "resolution": "operator_statement"}],
            "fact_sources": [{"section": "android_carrier_config", "key": "enabledMMS", "sources": ["operator_statement"]}],
        }
    ]
}


class Tree:
    def __init__(self, statements=None, identity=None, profile=PROFILE, evidence=EVIDENCE):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write(f"carriers/open/{profile['profile_id'].removeprefix('open.')}.json", profile)
        self.write("generated/evidence-index.json", evidence)
        if statements is not None:
            self.write(vo.STATEMENTS, statements)
        if identity is not None:
            self.write(vo.IDENTITY, identity)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")

    def validate(self, freshness="warn", today=TODAY):
        return vo.validate(self.root, today, freshness, require=False)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


class PrefixLimitsTest(unittest.TestCase):
    def test_json_selectors(self):
        with Tree() as tree:
            tree.write("carriers/open/00101.000000000002.json", {"match": {"mccmnc": ["00101"], "imsi_prefix_patterns": ["00101123456"]}})
            tree.write("generated/x.json", {"match": {"iccid_prefixes": ["89490000000012"]}})
            tree.write("generated/ocd-dataset/google-lane.json", {"rules": [{"mvno": {"kind": "imsi", "value": "001011234567"}}]})
            problems = vo.prefix_problems(tree.root)
            self.assertEqual(len(problems), 3, problems)
            self.assertFalse(any("00101123456" in p for p in problems), "a problem line never repeats the selector")

    def test_limits_that_pass(self):
        with Tree() as tree:
            tree.write("generated/y.json", {"m": {"imsi_prefix_patterns": ["0010112345", "00101123xx", "001011234xxxx"], "iccid_prefixes": ["8949000000001", "89490"]}})
            self.assertEqual(vo.prefix_problems(tree.root), [])

    def test_xml(self):
        with Tree() as tree:
            tree.write(
                "generated/android/apns-conf.xml",
                '<apns version="8"><apn mcc="001" mnc="01" mvno_type="iccid" mvno_match_data="89490000000012"/>'
                '<apn mcc="001" mnc="01" mvno_type="imsi" mvno_match_data="0010112345"/></apns>',
            )
            tree.write(
                "generated/android/carrier-config-list.xml",
                '<carrier_config_list><carrier_config imsi="0010123[0-9]*" mcc="001" mnc="01"/>'
                '<carrier_config imsi="00101234567[0-9]*" mcc="001" mnc="01"/></carrier_config_list>',
            )
            problems = vo.prefix_problems(tree.root)
            self.assertEqual(len(problems), 2, problems)

    def test_this_repository(self):
        self.assertEqual(vo.prefix_problems(REPO), [])


class StatementsTest(unittest.TestCase):
    def test_a_valid_file(self):
        with Tree(statements_file([statement()]), identity_file()) as tree:
            errors, warnings = tree.validate()
            self.assertEqual((errors, warnings), ([], []))

    def test_sets_value_needs_a_second_check(self):
        with Tree(statements_file([statement(second_check=None)]), identity_file()) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("sets a value" in e for e in errors), errors)

    def test_a_brand_statement_sets_no_value(self):
        item = statement(scope="brand")
        with Tree(statements_file([item]), identity_file()) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("mmsc_hosts" in e or "sets a value" in e for e in errors), errors)

    def test_stale_is_a_warning_or_with_fail_an_error(self):
        with Tree(statements_file([statement()]), identity_file()) as tree:
            errors, warnings = tree.validate(today=date(2027, 4, 26))
            self.assertTrue(warnings and not [e for e in errors if "lapsed on" in e], (errors, warnings))
            errors, _ = tree.validate(freshness="fail", today=date(2027, 4, 26))
            self.assertTrue(any("lapsed on" in e for e in errors), errors)

    def test_a_lapsed_statement(self):
        item = statement(status="unknown", previous_status="ended", lapsed={"reason": "not_confirmed_180_days", "since": "2027-04-26"}, sets_value=False)
        with Tree(statements_file([item]), identity_file(), evidence={"profiles": []}) as tree:
            errors, warnings = tree.validate(today=date(2027, 5, 1))
            self.assertEqual((errors, warnings), ([], []))

    def test_quotes_and_phone_numbers(self):
        for text in ('The operator says "MMS is gone".', "Call +49 176 123456 for help."):
            with Tree(statements_file([statement(paraphrase=text)]), identity_file()) as tree:
                errors, _ = tree.validate()
                self.assertTrue(errors, text)

    def test_identity_key_must_exist(self):
        with Tree(statements_file([statement(identity_key="zz.other")]), identity_file()) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("identity_key" in e for e in errors), errors)


class IdentityTest(unittest.TestCase):
    def test_selector_must_equal_the_profile_match(self):
        selectors = [{"match": {"mccmnc": ["00101"], "spn": ["Other"]}, "profile_id": PROFILE["profile_id"], "families": ["lineageos"]}]
        with Tree(statements_file([statement()]), identity_file(selectors)) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("differs from the profile" in e for e in errors), errors)

    def test_host_only_means_no_selector(self):
        identity = identity_file()
        brand = copy.deepcopy(identity["entries"][0])
        brand.update(key="zz.brand", name="Brand", kind="brand", host_only=False, selectors=[])
        identity["entries"].insert(0, brand)
        with Tree(statements_file([statement()]), identity) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("host_only" in e for e in errors), errors)

    def test_host_only_networks_stay_off_the_entrys_own_selectors(self):
        # Rule round 51, item 5.
        identity = identity_file()
        identity["entries"][0].update(kind="mvno", host_networks=["00101", "00102"], host_only_networks=["00101"])
        with Tree(statements_file([statement()]), identity) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("no selector of the entry stands" in e for e in errors), errors)


def entities_file():
    source = {"url": "https://operator.example.test/hosts", "publisher": "Test network", "kind": "operator", "read_on": "2026-10-28"}
    return {
        "schema_version": 1,
        "description": "test",
        "license": "CC0-1.0",
        "regulators": [{
            "country": "ZZ", "publisher": "Test regulator", "url": "https://regulator.example.test/list.pdf",
            "as_of": "2026-08-03", "read_on": "2026-10-28", "sha256": "sha256:" + "0" * 64,
        }],
        "networks": [{
            "mcc": "001", "mnc": "01", "country": "ZZ", "on_regulator_list": True, "holder": "Test network GmbH",
            "operator_key": "zz.net", "vendor_names": [{"name": "Old name", "families": ["aosp"], "agrees": False}],
        }],
        "operators": [{"key": "zz.net", "name": "Test network", "country": "ZZ", "kind": "radio_network_operator", "own_core": True, "sources": [source]}],
        "brands": [{
            "key": "zz.net", "name": "Test network", "country": "ZZ", "identity_kind": "operator", "operator_key": "zz.net", "part_of": None,
            "runs_on": [{
                "host": "zz.net", "core": "own", "same_subscribers": None, "valid_from": "≤2024-01-31", "valid_to": None,
                "note": "On its own network.", "sources": [source],
            }],
        }],
    }


class EntitiesTest(unittest.TestCase):
    def errors(self, document, identity=None):
        with Tree(statements_file([statement()]), identity or identity_file()) as tree:
            tree.write(vo.ENTITIES, document)
            return tree.validate()[0]

    def test_a_valid_file(self):
        self.assertEqual(self.errors(entities_file()), [])

    def test_a_packed_code_is_refused(self):
        document = entities_file()
        document["networks"][0]["mcc"] = "00101"
        self.assertTrue(any("does not match" in e for e in self.errors(document)))

    def test_only_the_regulator_gives_a_holder(self):
        document = entities_file()
        document["networks"][0]["on_regulator_list"] = False
        self.assertTrue(any("only the regulator" in e for e in self.errors(document)))

    def test_no_list_read_means_null(self):
        document = entities_file()
        document["regulators"] = []
        self.assertTrue(any("on_regulator_list is null" in e for e in self.errors(document)))

    def test_a_host_must_be_listed(self):
        document = entities_file()
        document["brands"][0]["runs_on"][0]["host"] = "zz.other"
        self.assertTrue(any("which the file does not list" in e for e in self.errors(document)))

    def test_dates_stay_in_order(self):
        document = entities_file()
        document["brands"][0]["runs_on"][0]["valid_to"] = "2023-01-01"
        self.assertTrue(any("ends before it starts" in e for e in self.errors(document)))

    def test_every_identity_entry_is_listed(self):
        identity = identity_file()
        brand = copy.deepcopy(identity["entries"][0])
        brand.update(key="zz.brand", name="Brand", kind="brand", host_only=True, selectors=[])
        identity["entries"].insert(0, brand)
        self.assertTrue(any("zz.brand is not a brand here" in e for e in self.errors(entities_file(), identity)))

    def test_the_table_copies_the_operator(self):
        identity = identity_file()
        document = entities_file()
        document["brands"][0]["operator_key"] = None
        self.assertTrue(any("the identity table gives zz.net" in e for e in self.errors(document, identity)))

    def test_phones_never_pull_it(self):
        with Tree(statements_file([statement()]), identity_file()) as tree:
            tree.write(vo.ENTITIES, entities_file())
            tree.write(vo.MANIFEST, {"files": [{"path": vo.ENTITIES}]})
            self.assertTrue(any("no carrier settings component reads" in e for e in tree.validate()[0]))


def offers_file():
    return {
        "schema_version": 1,
        "description": "test",
        "license": "CC0-1.0",
        "display_rule": "test",
        "counts": {"offers": 1, "lapsed": 0, "brand_features": 1},
        "offers": [{
            "id": "zz.net.option", "brand": "zz.net", "country": "ZZ", "type": "option", "name": "Option", "condition": None,
            "valid_from": "≤2026-10-28", "valid_to": None, "checked_at": "2026-10-28", "swept_at": "2026-10-28",
            "paraphrase": "The test network states that the option is free.",
            "features": [{"service": "mms", "state": "ended", "statement": "zz.net.mms"}],
            "sources": [{
                "url": "https://operator.example.test/option", "publisher": "Test network", "kind": "operator", "date": None,
                "read_on": "2026-10-28", "role": "admits", "passage_sha256": "sha256:" + "0" * 64,
            }],
        }],
        "brand_features": [{"brand": "zz.net", "service": "mms", "state": "ended", "statement": "zz.net.mms", "checked_at": "2026-10-28"}],
    }


class OffersTest(unittest.TestCase):
    def errors(self, document):
        with Tree(statements_file([statement()]), identity_file()) as tree:
            tree.write(vo.OFFERS, document)
            return tree.validate()[0]

    def test_a_valid_file(self):
        self.assertEqual(self.errors(offers_file()), [])

    def test_a_statement_must_exist(self):
        document = offers_file()
        document["offers"][0]["features"][0]["statement"] = "zz.net.other"
        self.assertTrue(any("does not list" in e for e in self.errors(document)))

    def test_a_state_must_fit_the_statement(self):
        document = offers_file()
        document["offers"][0]["features"][0]["state"] = "included"
        self.assertTrue(any("does not fit" in e for e in self.errors(document)))

    def test_a_lapsed_offer_reads_unknown(self):
        document = offers_file()
        document["offers"][0]["lapsed"] = {"reason": "not_confirmed_180_days", "since": "2026-10-01"}
        document["counts"]["lapsed"] = 1
        self.assertTrue(any("a lapsed offer reads unknown" in e for e in self.errors(document)))

    def test_a_brand_feature_repeats_its_statement(self):
        document = offers_file()
        document["brand_features"][0]["state"] = "depends_on_plan"
        self.assertTrue(any("as its statement does" in e for e in self.errors(document)))

    def test_an_offer_id_starts_with_its_brand(self):
        document = offers_file()
        document["offers"][0]["id"] = "zz.other.option"
        self.assertTrue(any("starts with its brand" in e for e in self.errors(document)))

    def test_phones_never_pull_it(self):
        with Tree(statements_file([statement()]), identity_file()) as tree:
            tree.write(vo.MANIFEST, {"files": [{"path": vo.OFFERS}]})
            self.assertTrue(any("no carrier settings component reads" in e for e in tree.validate()[0]))


class OverrideTest(unittest.TestCase):
    def test_a_profile_outside_every_statement(self):
        item = statement(mccmnc=["00102"])
        with Tree(statements_file([item]), identity_file()) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("no a value-setting MMS statement" in e or "covers its network codes" in e for e in errors), errors)

    def test_another_mmsc_is_not_covered(self):
        profile = copy.deepcopy(PROFILE)
        profile["android_apns"].append({"apn": "own", "types": ["mms"], "mmsc": "http://mms.mvno.example.test"})
        with Tree(statements_file([statement()]), identity_file(), profile=profile) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("covers its network codes" in e for e in errors), errors)

    def test_statement_use_without_the_file(self):
        with Tree(None, None) as tree:
            errors, _ = tree.validate()
            self.assertTrue(any("statements.json is missing" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
