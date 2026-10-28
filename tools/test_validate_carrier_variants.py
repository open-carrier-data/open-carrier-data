#!/usr/bin/env python3
"""Tests for validate_carrier_variants.py, the device records check."""

from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

import validate_carrier_variants as check
import validate_public_carrier_data
from validate_public_carrier_data import ValidationError

DIGEST = "sha256:" + "a" * 64
PROFILE = "open.26202.8cebd7550c67"


def write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def variants_file() -> dict:
    return {
        "schema_version": 1,
        "description": "Configuration, not a test result.",
        "based_on_data_digest": DIGEST,
        "checks_through": "2026-07-14",
        "stale_after": "2027-01-10",
        "capabilities": ["video_calling", "volte", "vonr", "vowifi"],
        "profiles": {
            PROFILE: {
                "volte": [
                    {
                        "devices": ["android:09769a7b58e06b05037b"],
                        "newest_entry": "2024-12",
                        "source": "lineageos_device_overlays",
                        "stack": "lineageos",
                        "state": "off",
                    },
                    {
                        "devices": ["samsung:SM-G981B"],
                        "newest_entry": "2025-02",
                        "source": "samsung_omc",
                        "stack": "stock",
                        "state": "on",
                    },
                ],
                "vonr": [
                    {
                        "basis": "samsung_vonr_switch",
                        "devices": ["samsung:SM-G981B"],
                        "newest_entry": "2025-02",
                        "source": "samsung_omc",
                        "stack": "stock",
                        "state": "on",
                    }
                ],
            }
        },
    }


class ValidateCarrierVariantsTests(unittest.TestCase):
    def setUp(self) -> None:
        validate_public_carrier_data.TODAY_OVERRIDE = date(2026, 10, 17)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root / "generated/android/metadata.json", {"data_digest": DIGEST})
        write(
            self.root / "generated/index.json",
            {
                "checks_through": "2026-07-14",
                "stale_after": "2027-01-10",
                "profiles": [{"profile_id": PROFILE, "path": "carriers/open/26202.8cebd7550c67.json"}],
            },
        )
        write(
            self.root / "carriers/open/26202.8cebd7550c67.json",
            {"profile_id": PROFILE, "capabilities": {"volte": "conditional", "vonr": "unknown"}},
        )
        write(
            self.root / "generated/evidence-index.json",
            {
                "profiles": [
                    {
                        "profile_id": PROFILE,
                        "capability_sources": {
                            "volte": {"off": ["lineageos_device_overlays"], "on": ["lineageos_device_overlays", "samsung_omc"]},
                            "vonr": {"on": ["samsung_omc"]},
                        },
                        "capability_basis": {"vonr": {"basis": "samsung_vonr_switch"}},
                    }
                ]
            },
        )
        write(
            self.root / "generated/devices/android.json",
            {
                "devices": [
                    {"device_id": "android:09769a7b58e06b05037b", "brands": ["LGE"], "device_names": ["bullhead"], "models": []},
                    {"device_id": "android:5ecb137dfd5df943d5b0", "brands": ["Samsung"], "device_names": ["x1s"], "models": ["SM-G980F", "SM-G981B"]},
                ]
            },
        )

    def tearDown(self) -> None:
        validate_public_carrier_data.TODAY_OVERRIDE = None
        self.tmp.cleanup()

    def put(self, data: dict) -> None:
        path = self.root / check.VARIANTS_PATH
        path.write_bytes(check.canonical_bytes(data))

    def run_check(self, data: dict | None = None, require: bool = True) -> str:
        if data is not None:
            self.put(data)
        return check.validate(self.root, "fail", require)

    def assert_rejected(self, data: dict, text: str) -> None:
        with self.assertRaises(ValidationError) as caught:
            self.run_check(data)
        self.assertIn(text, str(caught.exception))

    def test_valid_file(self) -> None:
        self.assertIn("validated 3 device records", self.run_check(variants_file()))

    def device_backed(self) -> None:
        """Round 17's step 2: the profile's VoLTE is supported against the
        overlays' off, which the gate names."""
        path = self.root / "generated/evidence-index.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        evidence["profiles"][0]["capability_sources"]["volte"] = {
            "off": ["lineageos_device_overlays"],
            "on": ["samsung_omc"],
        }
        evidence["profiles"][0]["quality_gates"] = [
            {
                "kind": "quality_gate",
                "key": "single_family_off:volte",
                "observed_value_count": 1,
                "resolution": "omitted_from_stable",
                "section": "capabilities",
            }
        ]
        write(path, evidence)

    def test_a_supported_label_keeps_its_off_as_a_device_record(self) -> None:
        self.device_backed()
        self.assertIn("1 supported labels keep their off", self.run_check(variants_file()))

    def test_a_supported_label_without_its_off_record_is_rejected(self) -> None:
        self.device_backed()
        data = variants_file()
        data["profiles"][PROFILE]["volte"] = [
            record for record in data["profiles"][PROFILE]["volte"] if record["state"] != "off"
        ]
        self.assert_rejected(data, "has no off record from it")

    def test_a_supported_label_without_an_on_record_is_rejected(self) -> None:
        """Round 22: the device file must show both sides."""
        self.device_backed()
        data = variants_file()
        data["profiles"][PROFILE]["volte"] = [
            record for record in data["profiles"][PROFILE]["volte"] if record["state"] != "on"
        ]
        self.assert_rejected(data, "has no on record")

    def old_off(self) -> None:
        """Round 32's old-off clause: the profile's VoLTE is supported against
        an overlay off older than five years, which the gate names with its
        reason and month."""
        self.device_backed()
        path = self.root / "generated/evidence-index.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        evidence["profiles"][0]["quality_gates"][0].update(
            {"off_newest_entry": "2016-03", "reason": "off_older_than_five_years"}
        )
        write(path, evidence)

    def without_offs(self) -> dict:
        data = variants_file()
        data["profiles"][PROFILE]["volte"] = [
            record for record in data["profiles"][PROFILE]["volte"] if record["state"] != "off"
        ]
        return data

    def test_an_old_off_label_needs_an_on_record_and_no_off_record(self) -> None:
        self.old_off()
        result = self.run_check(self.without_offs())
        self.assertIn("1 supported labels have only offs older than five years", result)
        self.assertIn("0 supported labels keep their off", result)
        # A visible off is a current off the label would hide.
        self.assert_rejected(variants_file(), "has an off record from lineageos_device_overlays")
        data = self.without_offs()
        data["profiles"][PROFILE]["volte"] = []
        data["profiles"][PROFILE].pop("volte")
        self.assert_rejected(data, "older than five years, but the file has no on record")

    def test_an_old_off_label_needs_the_file(self) -> None:
        self.old_off()
        with self.assertRaises(ValidationError) as caught:
            check.validate(self.root, "fail", False)
        self.assertIn("1 rest on on records against an off older than five years", str(caught.exception))

    def test_a_supported_label_needs_the_file(self) -> None:
        self.device_backed()
        with self.assertRaises(ValidationError) as caught:
            check.validate(self.root, "fail", False)
        self.assertIn("keep their off as device records", str(caught.exception))

    def test_missing_file_passes_unless_required(self) -> None:
        self.assertIn("nothing to check", check.validate(self.root, "fail", False))
        with self.assertRaises(ValidationError):
            check.validate(self.root, "fail", True)

    def test_samsung_off_is_rejected(self) -> None:
        data = variants_file()
        data["profiles"][PROFILE]["volte"][1]["state"] = "off"
        data["profiles"][PROFILE]["volte"].sort(key=check.record_order)
        self.assert_rejected(data, "on only")

    def test_apple_and_ims_table_give_no_record(self) -> None:
        for source in ("apple_carrier_bundles", "samsung_ims", "samsung_carrier_config", "lineageos"):
            data = variants_file()
            data["profiles"][PROFILE]["volte"][0]["source"] = source
            self.assert_rejected(data, "gives no device record")

    def test_device_outside_the_catalog(self) -> None:
        data = variants_file()
        data["profiles"][PROFILE]["volte"][0]["devices"] = ["android:0000000000000000ffff"]
        self.assert_rejected(data, "not in generated/devices/android.json")
        data = variants_file()
        data["profiles"][PROFILE]["volte"][1]["devices"] = ["samsung:SM-A525"]
        self.assert_rejected(data, "not a Samsung model")

    def test_unpublished_profile(self) -> None:
        data = variants_file()
        data["profiles"]["open.26202.000000000000"] = data["profiles"].pop(PROFILE)
        self.assert_rejected(data, "not a published profile")

    def test_capability_outside_the_four(self) -> None:
        for capability in ("sms_over_ims", "mms", "carrier_volte_available_bool"):
            data = variants_file()
            data["profiles"][PROFILE][capability] = data["profiles"][PROFILE].pop("volte")
            self.assert_rejected(data, "not one of")

    def test_closed_field_list(self) -> None:
        for field, value in (
            ("needs_override", True),
            ("confidence", "high"),
            ("evidence", "strong"),
            ("supported", True),
            ("source_versions", {}),
        ):
            data = variants_file()
            data["profiles"][PROFILE]["volte"][0][field] = value
            self.assert_rejected(data, "record fields are invalid")
        for state in ("not_offered", "partial", "needs_override", "unknown", "supported"):
            data = variants_file()
            data["profiles"][PROFILE]["volte"][0]["state"] = state
            self.assert_rejected(data, "is not on, off or conditional")

    def test_source_must_be_in_capability_sources(self) -> None:
        data = variants_file()
        data["profiles"][PROFILE]["volte"][0]["source"] = "google_carriersettings"
        data["profiles"][PROFILE]["volte"][0]["stack"] = "stock"
        data["profiles"][PROFILE]["volte"][0]["devices"] = ["android:09769a7b58e06b05037b"]
        data["profiles"][PROFILE]["volte"].sort(key=check.record_order)
        self.assert_rejected(data, "does not list google_carriersettings as off")

    def test_conditional_needs_both_sides_listed(self) -> None:
        data = variants_file()
        data["profiles"][PROFILE]["volte"][0]["state"] = "conditional"
        self.run_check(data)
        data["profiles"][PROFILE]["vonr"][0].pop("basis")
        data["profiles"][PROFILE]["vonr"][0]["source"] = "lineageos_device_overlays"
        data["profiles"][PROFILE]["vonr"][0]["stack"] = "lineageos"
        data["profiles"][PROFILE]["vonr"][0]["state"] = "conditional"
        data["profiles"][PROFILE]["vonr"][0]["devices"] = ["android:09769a7b58e06b05037b"]
        self.assert_rejected(data, "does not list lineageos_device_overlays as conditional")

    def test_wrong_stack(self) -> None:
        data = variants_file()
        data["profiles"][PROFILE]["volte"][0]["stack"] = "stock"
        self.assert_rejected(data, "hold for stack lineageos")

    def test_one_value_per_device_and_stack(self) -> None:
        data = variants_file()
        data["profiles"][PROFILE]["volte"].insert(
            1,
            {
                "devices": ["android:09769a7b58e06b05037b"],
                "newest_entry": "2025-01",
                "source": "lineageos_device_overlays",
                "stack": "lineageos",
                "state": "on",
            },
        )
        self.assert_rejected(data, "has two records")

    def test_rule_7_floor(self) -> None:
        data = variants_file()
        data["profiles"][PROFILE]["volte"][0]["newest_entry"] = "2016-12"
        self.assert_rejected(data, "outside rule 7's five years")
        data["profiles"][PROFILE]["volte"][0]["newest_entry"] = "2027-01"
        self.assert_rejected(data, "future-dated")

    def test_digest_must_match_metadata(self) -> None:
        data = variants_file()
        data["based_on_data_digest"] = "sha256:" + "b" * 64
        self.assert_rejected(data, "data_digest")

    def test_freshness_window_must_match_the_index(self) -> None:
        data = variants_file()
        data["checks_through"] = "2026-07-15"
        self.assert_rejected(data, "must equal generated/index.json")

    def test_canonical_bytes_and_order(self) -> None:
        data = variants_file()
        (self.root / check.VARIANTS_PATH).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        with self.assertRaises(ValidationError):
            check.validate(self.root, "fail", True)
        data["profiles"][PROFILE]["volte"].reverse()
        self.assert_rejected(data, "order")
        data = variants_file()
        data["profiles"][PROFILE]["volte"][0]["devices"] = ["android:5ecb137dfd5df943d5b0", "android:09769a7b58e06b05037b"]
        self.assert_rejected(data, "sorted list")

    def test_a_record_agreeing_with_the_carrier_value_is_listed(self) -> None:
        """Every device value is listed (tie-break of 2026-10-17): an on record
        on a supported profile and an off record on an unsupported one pass."""
        write(
            self.root / "carriers/open/26202.8cebd7550c67.json",
            {"profile_id": PROFILE, "capabilities": {"volte": "supported", "vonr": "unknown"}},
        )
        data = variants_file()
        data["profiles"][PROFILE]["volte"] = [data["profiles"][PROFILE]["volte"][1]]
        self.assertIn("validated 2 device records", self.run_check(data))
        write(
            self.root / "carriers/open/26202.8cebd7550c67.json",
            {"profile_id": PROFILE, "capabilities": {"volte": "unsupported", "vonr": "unknown"}},
        )
        data = variants_file()
        data["profiles"][PROFILE]["volte"] = [data["profiles"][PROFILE]["volte"][0]]
        self.assertIn("validated 2 device records", self.run_check(data))

    def test_basis_only_where_the_evidence_index_names_it(self) -> None:
        data = variants_file()
        data["profiles"][PROFILE]["vonr"][0].pop("basis")
        self.assert_rejected(data, "basis must be present")
        data = variants_file()
        data["profiles"][PROFILE]["volte"][1]["basis"] = "samsung_vonr_switch"
        self.assert_rejected(data, "basis must be present")

    def test_stale_snapshot_fails_in_fail_mode(self) -> None:
        validate_public_carrier_data.TODAY_OVERRIDE = date(2027, 2, 1)
        self.put(variants_file())
        with self.assertRaises(ValidationError):
            check.validate(self.root, "fail", True)
        self.assertIn("validated", check.validate(self.root, "warn", True))

    def test_size_guard(self) -> None:
        data = copy.deepcopy(variants_file())
        data["description"] = "x" * (check.MAX_BYTES + 1)
        self.assert_rejected(data, "byte guard")


if __name__ == "__main__":
    unittest.main()
