#!/usr/bin/env python3
"""Regression tests for generated Android output."""

from __future__ import annotations

import json
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import generate_android_outputs
import validate_public_carrier_data
from carrier_config_types import expected_config_type


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
    schema = load_json(
        Path(__file__).resolve().parents[1] / "schemas/carrier-profile.schema.json"
    )
    schema_config_keys = set(
        schema["properties"]["android_carrier_config"]["propertyNames"]["enum"]
    )
    assert_true(
        schema_config_keys == validate_public_carrier_data.ALLOWED_CONFIG_KEYS,
        "CarrierConfig schema and validator key whitelists must match",
    )
    config_schema = schema["properties"]["android_carrier_config"]
    schema_type_names = {
        "boolean": "bool",
        "integer": "int",
        "string": "string",
        "array": "string_array",
    }
    for key in schema_config_keys:
        declared = config_schema["properties"].get(key)
        if declared is None:
            declared = next(
                value
                for pattern, value in config_schema["patternProperties"].items()
                if re.search(pattern, key)
            )
        assert_true(
            schema_type_names[declared["type"]] == expected_config_type(key),
            f"CarrierConfig schema has the wrong value type for {key}",
        )

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
        carrier_id_only = write_carrier_profile(
            carriers_dir,
            {
                "schema_version": 1,
                "display_name": "Example Carrier ID",
                "match": {
                    "mccmnc": ["26227"],
                    "android_carrier_ids": [4000],
                },
                "capabilities": {"mms": "supported"},
                "android_apns": [
                    {
                        "name": "carrier id",
                        "apn": "cid.example",
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
        profile_ids = sorted(
            load_json(path)["profile_id"] for path in carriers_dir.rglob("*.json")
        )
        write_profile(
            generated_dir / "evidence-index.json",
            {
                "schema_version": 1,
                "description": "Safe source and scope summaries for neutral carrier profiles.",
                "source_snapshots": [],
                "profiles": [
                    {
                        "profile_id": profile_id,
                        "observation_count": 1,
                        "sources": ["lineageos"],
                        "fact_sources": [
                            {
                                "section": "match",
                                "key": "match",
                                "sources": ["lineageos"],
                            },
                            {
                                "section": "profile",
                                "key": "display_name",
                                "sources": ["lineageos"],
                            },
                        ],
                        "verified_observation_count": 0,
                        "observed_scope": {
                            "models": ["SM-TEST"],
                            "firmware_regions": ["TST"],
                            "firmware_builds": ["TESTXX1"],
                        },
                        "observed_model_source_groups": [
                            {"models": ["SM-TEST"], "sources": ["lineageos"]}
                        ],
                    }
                    for profile_id in profile_ids
                ],
            },
        )
        validation = validate_public_carrier_data.main(
            ["validate_public_carrier_data.py", str(carriers_dir), str(generated_dir / "index.json")]
        )
        assert_true(validation == 0, "public validator returned a non-zero status")

        apn_root = ET.parse(generated_dir / "android/apns-conf.xml").getroot()
        assert_true(apn_root.attrib["version"] == "8", "APN XML should target version 8")
        apn_rows = [
            dict(element.attrib)
            for element in apn_root
        ]
        assert_true(len(apn_rows) == 5, f"expected 5 APN rows, got {len(apn_rows)}")
        by_apn = {
            (row["mcc"], row["mnc"], row["apn"]): row
            for row in apn_rows
            if "mcc" in row and "mnc" in row
        }
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
        assert_true(
            not any(row["apn"] == "ims.example" for row in apn_rows),
            "carrier-ID plus GID applicability must not be broadened into APN rows",
        )
        carrier_id_row = next(row for row in apn_rows if row["apn"] == "cid.example")
        assert_true(
            carrier_id_row["carrier_id"] == "4000"
            and "mcc" not in carrier_id_row
            and "mnc" not in carrier_id_row,
            "carrier-ID-only APNs must not become generic MCC/MNC APNs",
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
        assert_true(len(lookup["profiles"]) == 7, "lookup should contain all profiles")
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
            lookup_by_id[base_id]["specificity"] == 0
            and lookup_by_id[carrier_id_only]["specificity"] == 1,
            "lookup should expose deterministic match specificity",
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
            sorted(mccmnc_index["mccmnc"])
            == ["26202", "26223", "26224", "26225", "26226", "26227"],
            "MCC/MNC index should expose expected SIM operator keys",
        )
        assert_true(
            [item["profile_id"] for item in mccmnc_index["mccmnc"]["26202"]]
            == [base_id, mvno_id, multi_id],
            "MCC/MNC index should list generic profiles before more specific matches",
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
            sorted(carrier_id_index["android_carrier_ids"]) == ["2536", "4000"],
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
        assert_true(len(config_nodes) == 1, "CarrierConfig XML should omit prefix-only matches")
        assert_true(
            sorted(node.attrib["mcc"] + node.attrib["mnc"] for node in config_nodes)
            == ["26226"],
            "CarrierConfig XML should keep only exactly representable matches",
        )
        imsi_config = next(node for node in config_nodes if node.attrib["mcc"] + node.attrib["mnc"] == "26226")
        assert_true(
            imsi_config.attrib["imsi"] == "262260[0-9]1[0-9]*",
            "CarrierConfig XML should convert IMSI x-patterns to Java regex filters",
        )
        assert_true(
            "gid1" not in imsi_config.attrib,
            "CarrierConfig XML must not turn a GID prefix into an exact GID",
        )
        config_children = {child.attrib["name"]: child for child in imsi_config}
        assert_true(
            config_children["carrier_volte_available_bool"].tag == "boolean"
            and config_children["carrier_volte_available_bool"].attrib["value"] == "true",
            "CarrierConfig XML should write boolean values",
        )
        metadata = load_json(generated_dir / "android/metadata.json")
        assert_true(
            metadata["target"]["apn_database_version"] == 8,
            "metadata should identify the APN target version",
        )
        assert_true(
            metadata["target"]["carrier_config_gid_matching"] == "exact_only",
            "metadata should identify exact CarrierConfig GID semantics",
        )
        assert_true(
            metadata["omissions"]["carrier_config_profiles_with_unrepresentable_match"] == 2,
            "metadata should count CarrierConfig profiles omitted to avoid broadening matches",
        )
        assert_true(
            metadata["omissions"]["apn_profile_ids_with_unrepresentable_match"]
            == sorted([gid2_id, multi_id]),
            "metadata should identify every APN profile omitted to preserve match semantics",
        )
        assert_true(
            metadata["omissions"][
                "carrier_config_profile_ids_with_unrepresentable_match"
            ]
            == sorted([gid2_id, multi_id]),
            "metadata should identify every omitted CarrierConfig profile",
        )

        invalid_type_profile = {
            "schema_version": 1,
            "display_name": "Invalid type",
            "match": {"mccmnc": ["00199"]},
            "capabilities": {},
            "android_carrier_config": {"carrier_volte_available_bool": "yes"},
        }
        invalid_type_profile["profile_id"] = (
            validate_public_carrier_data.canonical_profile_id(
                invalid_type_profile["match"]
            )
        )
        try:
            validate_public_carrier_data.validate_profile_object(
                root / "invalid-type.json",
                invalid_type_profile,
            )
        except validate_public_carrier_data.ValidationError as exc:
            assert_true("must be bool" in str(exc), "wrong CarrierConfig type error")
        else:
            raise AssertionError("string-valued boolean CarrierConfig should fail")

        duplicate_types_profile = {
            "schema_version": 1,
            "display_name": "Duplicate APN types",
            "match": {"mccmnc": ["00198"]},
            "capabilities": {},
            "android_apns": [
                {
                    "name": "internet",
                    "apn": "internet.example",
                    "types": ["default", "default"],
                }
            ],
        }
        duplicate_types_profile["profile_id"] = (
            validate_public_carrier_data.canonical_profile_id(
                duplicate_types_profile["match"]
            )
        )
        try:
            validate_public_carrier_data.validate_profile_object(
                root / "duplicate-types.json",
                duplicate_types_profile,
            )
        except validate_public_carrier_data.ValidationError as exc:
            assert_true("sorted and unique" in str(exc), "wrong APN type error")
        else:
            raise AssertionError("duplicate APN types should fail")

    print("generated Android output tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
