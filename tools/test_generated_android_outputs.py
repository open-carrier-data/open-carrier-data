#!/usr/bin/env python3
"""Regression tests for generated Android output."""

from __future__ import annotations

import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import generate_android_outputs
import validate_public_carrier_data


def write_profile(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_carrier_profile(carriers_dir: Path, value: dict) -> str:
    profile_id = validate_public_carrier_data.canonical_profile_id(value["match"])
    value = dict(value)
    value["profile_id"] = profile_id
    write_profile(
        carriers_dir / validate_public_carrier_data.public_path_for(profile_id),
        value,
    )
    return profile_id


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        carriers_dir = root / "carriers"
        generated_dir = root / "generated"

        base_id = write_carrier_profile(
            carriers_dir,
            {
                "schema_version": 1,
                "display_name": "Example",
                "match": {"mccmnc": ["26202"]},
                "capabilities": {"mms": "supported", "volte": "unknown"},
                "addons": {
                    "wifi_calling": {
                        "hide_menu_on_auth_failure": True,
                    },
                    "operator_display": {
                        "prefer_spn": True,
                    },
                },
                "android_apns": [
                    {
                        "name": "internet",
                        "apn": "internet.example",
                        "types": ["default", "supl"],
                        "protocol": "PPP",
                        "roaming_protocol": "NON-IP",
                        "bearer": 14,
                        "carrier_id": -1,
                        "network_type_bitmask": "14|20",
                        "lingering_network_type_bitmask": "20",
                        "infrastructure_bitmask": "cellular|satellite",
                        "mtu_v4": 1440,
                        "mtu_v6": 1420,
                        "apn_set_id": -1,
                        "skip_464xlat": -1,
                        "always_on": True,
                        "esim_bootstrap_provisioning": False,
                    }
                ],
            },
        )
        mvno_id = write_carrier_profile(
            carriers_dir,
            {
                "schema_version": 1,
                "display_name": "Example MVNO",
                "match": {"mccmnc": ["26202"], "spn": ["Example MVNO"]},
                "capabilities": {"mms": "supported", "volte": "supported"},
                "android_apns": [
                    {
                        "name": "mvno",
                        "apn": "mvno.example",
                        "types": ["*"],
                    }
                ],
            },
        )
        multi_id = write_carrier_profile(
            carriers_dir,
            {
                "schema_version": 1,
                "display_name": "Example Multi",
                "match": {
                    "mccmnc": ["26202", "26223"],
                    "gid1_prefixes": ["AB"],
                    "android_carrier_ids": [2536],
                },
                "capabilities": {"vowifi": "supported", "ims_conference": "supported"},
                "android_carrier_config": {
                    "carrier_default_wfc_ims_roaming_mode_int": 2,
                    "carrier_volte_available_bool": True,
                    "carrier_volte_override_wfc_provisioning_bool": False,
                    "imsvoice.conference_factory_uri_string": "sip:conf@example.com",
                    "support_ims_conference_call_bool": True,
                    "wfc_operator_error_codes_string_array": ["REG09|0"],
                    "wfc_data_spn_format_idx_int": 1,
                },
                "android_apns": [
                    {
                        "name": "ims",
                        "apn": "ims.example",
                        "types": ["ims", "rcs"],
                    }
                ],
            },
        )
        iccid_id = write_carrier_profile(
            carriers_dir,
            {
                "schema_version": 1,
                "display_name": "Example ICCID",
                "match": {"mccmnc": ["26224"], "iccid_prefixes": ["8981090"]},
                "capabilities": {"mms": "supported"},
                "android_apns": [
                    {
                        "name": "iccid",
                        "apn": "iccid.example",
                        "types": ["default"],
                    }
                ],
            },
        )
        gid2_id = write_carrier_profile(
            carriers_dir,
            {
                "schema_version": 1,
                "display_name": "Example GID2",
                "match": {"mccmnc": ["26225"], "gid2_prefixes": ["A1"]},
                "capabilities": {"mms": "supported"},
                "android_carrier_config": {"enabledMMS": True},
                "android_apns": [
                    {
                        "name": "gid2",
                        "apn": "gid2.example",
                        "types": ["default"],
                    }
                ],
            },
        )
        imsi_id = write_carrier_profile(
            carriers_dir,
            {
                "schema_version": 1,
                "display_name": "Example IMSI",
                "match": {"mccmnc": ["26226"], "imsi_prefix_patterns": ["262260x1"]},
                "capabilities": {"volte": "supported"},
                "android_carrier_config": {"carrier_volte_available_bool": True},
                "android_apns": [
                    {
                        "name": "imsi",
                        "apn": "imsi.example",
                        "types": ["default"],
                    }
                ],
            },
        )

        result = generate_android_outputs.main(
            ["generate_android_outputs.py", str(carriers_dir), str(generated_dir)]
        )
        assert_true(result == 0, "generator returned a non-zero status")
        write_profile(
            generated_dir / "index.json",
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "display_name": profile["display_name"],
                        "path": path.relative_to(root).as_posix(),
                        "profile_id": profile["profile_id"],
                    }
                    for path in sorted(carriers_dir.rglob("*.json"))
                    for profile in [load_json(path)]
                ],
            },
        )
        write_profile(
            generated_dir / "community" / "index.json",
            {
                "schema_version": 1,
                "description": "All valid non-expired community carrier-data claims.",
                "claims": [],
            },
        )
        write_profile(
            generated_dir / "candidate" / "index.json",
            {
                "schema_version": 1,
                "description": (
                    "Community claims with enough evidence to test as candidate "
                    "data. These are not stable defaults."
                ),
                "claims": [],
            },
        )
        validation = validate_public_carrier_data.main(
            ["validate_public_carrier_data.py", str(carriers_dir), str(generated_dir / "index.json")]
        )
        assert_true(validation == 0, "public validator returned a non-zero status")

        apn_rows = [
            dict(element.attrib)
            for element in ET.parse(generated_dir / "android/apns-conf.xml").getroot()
        ]
        assert_true(len(apn_rows) == 6, f"expected 6 APN rows, got {len(apn_rows)}")
        by_apn = {(row["mcc"], row["mnc"], row["apn"]): row for row in apn_rows}
        assert_true(
            "mvno_type" not in by_apn[("262", "02", "internet.example")],
            "plain MCC/MNC APN row should not be MVNO-constrained",
        )
        internet_row = by_apn[("262", "02", "internet.example")]
        for key, value in {
            "network_type_bitmask": "14|20",
            "protocol": "PPP",
            "roaming_protocol": "NON-IP",
            "bearer": "14",
            "carrier_id": "-1",
            "lingering_network_type_bitmask": "20",
            "infrastructure_bitmask": "cellular|satellite",
            "mtu_v4": "1440",
            "mtu_v6": "1420",
            "apn_set_id": "-1",
            "skip_464xlat": "-1",
            "always_on": "true",
            "esim_bootstrap_provisioning": "false",
        }.items():
            assert_true(internet_row[key] == value, f"APN row should preserve {key}")
        assert_true(
            by_apn[("262", "02", "mvno.example")]["mvno_type"] == "spn",
            "SPN profile should generate SPN-constrained APN row",
        )
        assert_true(
            by_apn[("262", "02", "mvno.example")]["mvno_match_data"] == "Example MVNO",
            "SPN APN row should preserve the SPN match value",
        )
        assert_true(
            by_apn[("262", "02", "mvno.example")]["type"] == "*",
            "APN rows should preserve wildcard APN type",
        )
        for key in [("262", "02", "ims.example"), ("262", "23", "ims.example")]:
            assert_true(
                by_apn[key]["mvno_type"] == "gid" and by_apn[key]["mvno_match_data"] == "AB",
                "GID profile should generate GID-constrained APN rows for every MCC/MNC",
            )
            assert_true(
                by_apn[key]["type"] == "ims,rcs",
                "APN rows should preserve newer standard APN types",
            )
        assert_true(
            by_apn[("262", "24", "iccid.example")]["mvno_type"] == "iccid",
            "ICCID profile should generate ICCID-constrained APN row",
        )
        assert_true(
            by_apn[("262", "24", "iccid.example")]["mvno_match_data"] == "8981090",
            "ICCID APN row should preserve the ICCID prefix",
        )
        assert_true(
            ("262", "25", "gid2.example") not in by_apn,
            "GID2-only profile should not generate broadened Android APN rows",
        )
        assert_true(
            by_apn[("262", "26", "imsi.example")]["mvno_type"] == "imsi",
            "IMSI-pattern profile should generate IMSI-constrained APN row",
        )
        assert_true(
            by_apn[("262", "26", "imsi.example")]["mvno_match_data"] == "262260x1",
            "IMSI APN row should preserve the x-pattern",
        )

        lookup = load_json(generated_dir / "android/lookup.json")
        assert_true(len(lookup["profiles"]) == 6, "lookup should contain all profiles")
        lookup_by_id = {item["profile_id"]: item for item in lookup["profiles"]}
        assert_true(
            lookup_by_id[multi_id]["android_apn_count"] == 1,
            "lookup should preserve APN counts",
        )
        assert_true(
            lookup_by_id[multi_id]["has_android_carrier_config"],
            "lookup should mark profiles with CarrierConfig overrides",
        )
        assert_true(
            lookup_by_id[multi_id]["match"]["android_carrier_ids"] == [2536],
            "lookup should preserve Android carrier ID match constraints",
        )
        assert_true(
            lookup_by_id[iccid_id]["match"]["iccid_prefixes"] == ["8981090"],
            "lookup should preserve ICCID prefix match constraints",
        )
        assert_true(
            lookup_by_id[gid2_id]["match"]["gid2_prefixes"] == ["A1"],
            "lookup should preserve GID2 prefix match constraints",
        )
        assert_true(
            lookup_by_id[imsi_id]["match"]["imsi_prefix_patterns"] == ["262260x1"],
            "lookup should preserve IMSI prefix pattern match constraints",
        )

        mccmnc_index = load_json(generated_dir / "android/mccmnc-index.json")
        assert_true(
            sorted(mccmnc_index["mccmnc"]) == ["26202", "26223", "26224", "26225", "26226"],
            "MCC/MNC index should expose expected SIM operator keys",
        )
        assert_true(
            [item["profile_id"] for item in mccmnc_index["mccmnc"]["26202"]]
            == sorted([base_id, multi_id, mvno_id]),
            "MCC/MNC index should list sorted candidate profiles",
        )
        assert_true(
            [item["profile_id"] for item in mccmnc_index["mccmnc"]["26223"]] == [multi_id],
            "MCC/MNC index should include multi-MCC/MNC profiles under every key",
        )
        assert_true(
            mccmnc_index["mccmnc"]["26223"][0]["match"]["android_carrier_ids"] == [2536],
            "MCC/MNC index should preserve Android carrier ID match constraints",
        )
        assert_true(
            mccmnc_index["mccmnc"]["26224"][0]["match"]["iccid_prefixes"] == ["8981090"],
            "MCC/MNC index should preserve ICCID match constraints",
        )
        assert_true(
            mccmnc_index["mccmnc"]["26225"][0]["match"]["gid2_prefixes"] == ["A1"],
            "MCC/MNC index should preserve GID2 match constraints",
        )
        assert_true(
            mccmnc_index["mccmnc"]["26226"][0]["match"]["imsi_prefix_patterns"] == ["262260x1"],
            "MCC/MNC index should preserve IMSI prefix pattern constraints",
        )

        carrier_id_index = load_json(generated_dir / "android/carrier-id-index.json")
        assert_true(
            sorted(carrier_id_index["android_carrier_ids"]) == ["2536"],
            "carrier ID index should expose expected Android carrier ID keys",
        )
        assert_true(
            [item["profile_id"] for item in carrier_id_index["android_carrier_ids"]["2536"]]
            == [multi_id],
            "carrier ID index should list sorted carrier-ID-matched profiles",
        )
        assert_true(
            carrier_id_index["android_carrier_ids"]["2536"][0]["match"]["mccmnc"]
            == ["26202", "26223"],
            "carrier ID index should preserve full profile match constraints",
        )

        carrier_config = load_json(generated_dir / "android/carrier-config-overrides.json")
        assert_true(
            sorted(item["profile_id"] for item in carrier_config["profiles"])
            == sorted([gid2_id, imsi_id, multi_id]),
            "CarrierConfig JSON export should preserve profiles with exact neutral matches",
        )
        carrier_config_by_id = {item["profile_id"]: item for item in carrier_config["profiles"]}
        assert_true(
            carrier_config_by_id[multi_id]["match"]["android_carrier_ids"] == [2536],
            "CarrierConfig export should preserve Android carrier ID match constraints",
        )
        assert_true(
            carrier_config_by_id[gid2_id]["match"]["gid2_prefixes"] == ["A1"],
            "CarrierConfig JSON export should preserve GID2 match constraints",
        )
        assert_true(
            carrier_config_by_id[imsi_id]["match"]["imsi_prefix_patterns"] == ["262260x1"],
            "CarrierConfig JSON export should preserve IMSI prefix pattern constraints",
        )
        exported_config = carrier_config_by_id[multi_id]["android_carrier_config"]
        assert_true(
            exported_config["carrier_default_wfc_ims_roaming_mode_int"] == 2,
            "CarrierConfig export should preserve WFC roaming mode",
        )
        assert_true(
            exported_config["carrier_volte_override_wfc_provisioning_bool"] is False,
            "CarrierConfig export should preserve VoLTE/WFC provisioning override",
        )
        assert_true(
            exported_config["wfc_data_spn_format_idx_int"] == 1,
            "CarrierConfig export should preserve WFC data SPN format",
        )

        config_xml = ET.parse(generated_dir / "android/carrier-config-list.xml").getroot()
        config_nodes = config_xml.findall("carrier_config")
        assert_true(
            len(config_nodes) == 3,
            "CarrierConfig XML should skip GID2/ICCID profiles it cannot represent exactly",
        )
        assert_true(
            sorted(node.attrib["mcc"] + node.attrib["mnc"] for node in config_nodes)
            == ["26202", "26223", "26226"],
            "CarrierConfig XML should preserve every MCC/MNC filter",
        )
        imsi_config = next(node for node in config_nodes if node.attrib["mcc"] + node.attrib["mnc"] == "26226")
        assert_true(
            imsi_config.attrib["imsi"] == "262260[0-9]1[0-9]*",
            "CarrierConfig XML should convert IMSI x-patterns to Java regex filters",
        )
        first_config = next(node for node in config_nodes if node.attrib.get("cid") == "2536")
        assert_true(
            first_config.attrib["cid"] == "2536",
            "CarrierConfig XML should preserve Android carrier ID filters",
        )
        assert_true(
            first_config.attrib["gid1"] == "AB",
            "CarrierConfig XML should preserve GID1 filters",
        )
        assert_true(
            first_config.attrib["name"] == "Example Multi",
            "CarrierConfig XML should include a readable carrier name filter",
        )
        config_children = {child.attrib["name"]: child for child in first_config}
        assert_true(
            config_children["carrier_volte_available_bool"].tag == "boolean"
            and config_children["carrier_volte_available_bool"].attrib["value"] == "true",
            "CarrierConfig XML should write boolean values",
        )
        assert_true(
            config_children["carrier_default_wfc_ims_roaming_mode_int"].tag == "int"
            and config_children["carrier_default_wfc_ims_roaming_mode_int"].attrib["value"] == "2",
            "CarrierConfig XML should write integer values",
        )
        assert_true(
            config_children["imsvoice.conference_factory_uri_string"].tag == "string"
            and config_children["imsvoice.conference_factory_uri_string"].text
            == "sip:conf@example.com",
            "CarrierConfig XML should write string values",
        )
        error_codes = config_children["wfc_operator_error_codes_string_array"]
        assert_true(
            error_codes.tag == "string-array"
            and error_codes.attrib["num"] == "1"
            and error_codes.find("item").attrib["value"] == "REG09|0",
            "CarrierConfig XML should write string-array values",
        )

    print("generated Android output tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
