#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diff_apns_conf


def xml(rows: list[str]) -> str:
    return '<?xml version="1.0" encoding="utf-8"?>\n<apns version="8">\n' + "\n".join(rows) + "\n</apns>\n"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        theirs_dir = Path(tmp) / "theirs"
        theirs_dir.mkdir()
        (theirs_dir / "DE.xml").write_text(
            xml(
                [
                    '<apn carrier="Shared" mcc="262" mnc="02" apn="web.example" type="default,supl" />',
                    '<apn carrier="Split" mcc="262" mnc="02" apn="mms.example" type="mms" />',
                    '<apn carrier="Missing" mcc="262" mnc="02" apn="old.example" type="default" />',
                ]
            ),
            encoding="utf-8",
        )
        (theirs_dir / "AT.xml").write_text(
            xml(['<apn carrier="Elsewhere" mcc="232" mnc="01" apn="a1.example" type="default" />']),
            encoding="utf-8",
        )
        ours = Path(tmp) / "ours.xml"
        ours.write_text(
            xml(
                [
                    '<apn carrier="Shared" mcc="262" mnc="02" apn="WEB.example" type="supl,default" />',
                    '<apn carrier="Split" mcc="262" mnc="02" apn="mms.example" type="mms,xcap" />',
                    '<apn carrier="Extra" mcc="262" mnc="02" apn="new.example" type="default" mvno_type="spn" mvno_match_data="Extra" />',
                ]
            ),
            encoding="utf-8",
        )
        report = diff_apns_conf.compare(
            diff_apns_conf.load_rows(theirs_dir), diff_apns_conf.load_rows(ours), set()
        )
        assert report["their_rows"] == 4 and report["our_rows"] == 3, report
        assert report["shared_rows"] == 1, "APN and types compare case- and order-insensitively"
        assert {item["apn"] for item in report["rows_only_ours"]} == {"mms.example", "new.example"}
        assert {item["apn"]: item["difference"] for item in report["rows_only_theirs"]} == {
            "mms.example": "types",
            "old.example": "apn",
            "a1.example": "network",
        }
        assert report["networks_only_theirs"] == ["23201"]
        limited = diff_apns_conf.compare(
            diff_apns_conf.load_rows(theirs_dir), diff_apns_conf.load_rows(ours), {"23201"}
        )
        assert limited["their_rows"] == 1 and limited["our_rows"] == 0
    print("apns-conf diff tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
