#!/usr/bin/env python3
"""tools/f5_read.py (rule round 31, SM6): the emergency lines, each rule of
the deterministic read, the chain of reads and a consumer's walk along it,
and the chain on main. Networks 999-01 and 999-02 are synthetic."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import f5_read as f5

REPO = Path(__file__).resolve().parents[1]
DIGEST = "sha256:" + "0" * 64


def xml(*rows: str, digest: str = DIGEST) -> bytes:
    head = f'<?xml version="1.0" encoding="utf-8"?>\n<!--\n    data_digest: {digest}\n-->\n<apns version="8">\n'
    return (head + "".join(f"  <apn {row} />\n" for row in rows) + "</apns>\n").encode("utf-8")


INTERNET = 'carrier="Net" mcc="999" mnc="01" apn="internet" type="default,supl,mms" mmsc="http://mms.example.invalid" protocol="IPV4V6" roaming_protocol="IPV4V6"'
IMS = 'carrier="Net IMS" mcc="999" mnc="01" apn="ims" type="ims" protocol="IPV4V6" roaming_protocol="IPV4V6"'


def emergency(apn: str = "sos", protocol: str = "IPV4V6", roaming: str = "IPV4V6", mcc: str = "999", mnc: str = "01", extra: str = "") -> str:
    return f'carrier="Net SOS" mcc="{mcc}" mnc="{mnc}" apn="{apn}" type="emergency" protocol="{protocol}" roaming_protocol="{roaming}"{extra}'


class Ctx(f5.Context):
    """A rules context without a checkout: what a test states."""

    def __init__(self, stated=None, countries=None, lengths=None) -> None:
        super().__init__(None)
        self.stated.update(stated or {})
        for mcc, labels in (countries or {}).items():
            self.countries[mcc] = set(labels)
        for mcc, (length, count) in (lengths or {}).items():
            self.mnc_lengths[mcc] = {length}
            self.networks[mcc] = count
        self.all_labels = {label for labels in self.countries.values() for label in labels}


def read(base: bytes, head: bytes, context: f5.Context | None = None) -> dict:
    return f5.read_files(base, head, None, "1" * 40, context=context or Ctx(), read_at="2026-10-28T20:00:00Z")


class RulesTest(unittest.TestCase):
    def test_no_change_has_no_lines(self) -> None:
        base = xml(INTERNET, IMS)
        result = read(base, xml(INTERNET, IMS, digest="sha256:" + "1" * 64))
        self.assertEqual(result["verdict"], "no_lines")
        self.assertEqual(result["lines"], [])
        self.assertEqual(f5.apn_rows_sha256(base), f5.apn_rows_sha256(xml(INTERNET, IMS, digest="sha256:" + "1" * 64)))

    def test_a_row_equal_to_androids_default_proceeds(self) -> None:
        result = read(xml(INTERNET, IMS), xml(INTERNET, IMS, emergency()))
        self.assertEqual(result["verdict"], "proceed")
        self.assertEqual({f["rule"] for f in result["findings"]}, {"android_default"})
        self.assertTrue(result["lines"][0].startswith("emergency lead gained|999/01|"))

    def test_losing_a_carrier_row_to_androids_default_proceeds(self) -> None:
        result = read(xml(INTERNET, IMS, emergency("emergency.net", "IPV6", "IPV6")), xml(INTERNET, IMS))
        self.assertEqual(result["verdict"], "proceed")
        self.assertEqual(result["findings"][0]["rule"], "android_default")

    def test_a_carrier_row_proceeds_only_when_stated(self) -> None:
        base, head = xml(INTERNET, IMS), xml(INTERNET, IMS, emergency("sos", "IPV6", "IPV4V6"))
        self.assertEqual(read(base, head)["verdict"], "hold")
        self.assertEqual(read(base, head)["findings"][0]["rule"], "not_stated")
        stated = Ctx(stated={("999", "01", "", ""): {("sos", "IPV6", "IPV4V6")}})
        self.assertEqual(read(base, head, stated)["verdict"], "proceed")
        self.assertEqual(read(base, head, stated)["findings"][0]["rule"], "stated")

    def test_a_foreign_country_name_holds_even_when_stated(self) -> None:
        """The 302/37 class: CNT Ecuador's emergency row under a Canadian code."""
        row = emergency("emergency.volte.ims.cnt.net.ec", "IP", "IPV4V6", mcc="302", mnc="370")
        stated = Ctx(stated={("302", "370", "", ""): {("emergency.volte.ims.cnt.net.ec", "IP", "IPV4V6")}},
                     countries={"302": {"ca"}, "740": {"ec"}})
        internet = INTERNET.replace('mcc="999" mnc="01"', 'mcc="302" mnc="370"')
        result = read(xml(internet), xml(internet, row), stated)
        self.assertEqual(result["verdict"], "hold")
        self.assertEqual(result["findings"][0]["rule"], "foreign_name")

    def test_an_unreachable_network_code_proceeds(self) -> None:
        row = emergency("emergency.volte.ims.cnt.net.ec", "IP", "IPV4V6", mcc="302", mnc="37")
        internet = INTERNET.replace('mcc="999" mnc="01"', 'mcc="302" mnc="37"')
        context = Ctx(countries={"302": {"ca"}, "740": {"ec"}}, lengths={"302": (3, 12)})
        result = read(xml(internet, row), xml(internet), context)
        self.assertEqual(result["findings"][0]["rule"], "android_default")
        result = read(xml(internet), xml(internet, row), context)
        self.assertEqual(result["findings"][0]["rule"], "unreachable_scope")
        self.assertEqual(result["verdict"], "proceed")

    def test_a_network_type_gap_holds(self) -> None:
        lte_only = emergency(extra=' network_type_bitmask="13"')
        result = read(xml(INTERNET, IMS, emergency()), xml(INTERNET, IMS, lte_only))
        self.assertEqual(result["verdict"], "hold")
        self.assertIn("gap", {f["rule"] for f in result["findings"]})
        self.assertTrue(any("network-type gap" in line for line in result["lines"]))

    def test_a_new_mvno_scope_is_read_against_its_network(self) -> None:
        mvno = emergency("sos", "IPV6", "IPV6", extra=' mvno_type="spn" mvno_match_data="Brand"')
        result = read(xml(INTERNET, IMS, emergency()), xml(INTERNET, IMS, emergency(), mvno))
        self.assertEqual(result["verdict"], "hold")
        self.assertTrue(result["lines"][0].startswith(f"{f5.NEW_SCOPE}|999/01 SPN brand|"))
        # The same request as its network's row is no line at all.
        same = emergency(extra=' mvno_type="spn" mvno_match_data="Brand"')
        self.assertEqual(read(xml(INTERNET, IMS, emergency()), xml(INTERNET, IMS, emergency(), same))["verdict"], "no_lines")

    def test_the_lines_digest_is_the_pin_steps(self) -> None:
        result = read(xml(INTERNET, IMS), xml(INTERNET, IMS, emergency("sos", "IPV6", "IPV6")))
        text = "".join(line + "\n" for line in sorted(result["lines"]))
        import hashlib
        self.assertEqual(result["lines_digest"], hashlib.sha256(text.encode()).hexdigest()[:16])
        self.assertEqual(f5.read_problems(result, "r"), [])


class ChainTest(unittest.TestCase):
    def chain(self) -> tuple[dict, list[bytes]]:
        files = [xml(INTERNET), xml(INTERNET, IMS), xml(INTERNET, IMS, emergency()), xml(INTERNET, IMS, emergency("sos", "IPV6", "IPV6"))]
        document = None
        for base, head in zip(files, files[1:]):
            document = f5.append_read(document, read(base, head), "1" * 40, head)
        return document, files

    def test_a_chain_validates_and_walks(self) -> None:
        document, files = self.chain()
        self.assertEqual(f5.file_problems(document, files[-1]), [])
        self.assertEqual([r["verdict"] for r in document["reads"]], ["no_lines", "proceed", "hold"])
        rows = [f5.apn_rows_sha256(x) for x in files]
        self.assertEqual(f5.chain_path(document, rows[-1]), [])
        self.assertEqual(len(f5.chain_path(document, rows[0])), 3)
        self.assertIsNone(f5.chain_path(document, "f" * 64))
        self.assertEqual(f5.path_verdict(f5.chain_path(document, rows[0], rows[2])), ("take", []))
        decision, blocking = f5.path_verdict(f5.chain_path(document, rows[0]))
        self.assertEqual(decision, "refuse")
        self.assertTrue(blocking)
        # The narrow gate reads only an APN name or roaming protocol change on a matched network.
        self.assertEqual(f5.path_verdict(f5.chain_path(document, rows[0]), "narrow", {"262-02"})[0], "take")
        self.assertEqual(f5.path_verdict(f5.chain_path(document, rows[0]), "narrow", {"999-01"})[0], "refuse")
        self.assertEqual(f5.path_verdict(None)[0], "refuse")

    def test_broken_chains_are_refused(self) -> None:
        document, files = self.chain()
        self.assertTrue(f5.file_problems(document, xml(INTERNET)))
        broken = {**document, "reads": document["reads"][:1] + document["reads"][2:]}
        self.assertTrue(any("does not start where the chain stands" in p for p in f5.file_problems(broken, files[-1])))
        forged = json.loads(json.dumps(document))
        forged["reads"][2]["verdict"] = "proceed"
        self.assertTrue(any("does not follow" in p for p in f5.file_problems(forged, files[-1])))
        lines = json.loads(json.dumps(document))
        lines["reads"][1]["lines_digest"] = "0" * 16
        self.assertTrue(any("lines_digest" in p for p in f5.file_problems(lines, files[-1])))

    def test_an_agent_read_stands_in_only_for_its_lines(self) -> None:
        held = read(xml(INTERNET, IMS), xml(INTERNET, IMS, emergency("sos", "IPV6", "IPV6")))
        agent = {"schema": "x1s-ocd-f5-read.v1", "lines_digest": held["lines_digest"], "verdict": "proceed",
                 "reader": "independent F5 reader (Claude subagent)", "read_at": "2026-10-28T20:10:00Z", "notes": "read"}
        self.assertEqual(f5.agent_read_stands_in(held, agent, f5.BUILDER), [])
        self.assertTrue(f5.agent_read_stands_in(held, {**agent, "lines_digest": "0" * 16}, f5.BUILDER))
        self.assertTrue(f5.agent_read_stands_in(held, {**agent, "reader": f5.BUILDER}, f5.BUILDER))
        self.assertTrue(f5.agent_read_stands_in(held, {**agent, "verdict": "hold"}, f5.BUILDER))


@unittest.skipUnless((REPO / f5.FILE).is_file(), "needs this checkout's f5-reads.json")
class MainTest(unittest.TestCase):
    def test_the_chain_on_main(self) -> None:
        document = f5.load_file(REPO / f5.FILE)
        self.assertEqual(f5.file_problems(document, (REPO / f5.APN_FILE).read_bytes()), [])
        self.assertTrue(all(r["verdict"] in ("proceed", "no_lines") for r in document["reads"]))
        import ocd_dataset
        self.assertEqual(ocd_dataset.schema_check(REPO, document, "ocd-dataset-f5-reads.schema.json", f5.FILE), [])
        print(f"\nF5 reads on main: {len(document['reads'])} since {document['since']['commit'][:12]}: "
              + ", ".join(f"{r['verdict']} ({len(r['lines'])})" for r in document["reads"]))


if __name__ == "__main__":
    unittest.main()
