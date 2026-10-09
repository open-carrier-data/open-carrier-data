#!/usr/bin/env python3
"""Regression tests for generated Android output."""

from __future__ import annotations

import contextlib
from copy import deepcopy
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Callable

import generate_android_outputs
import lineageos_apns
import validate_device_catalog
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


def assert_validation_error(action: Callable[[], object], message: str) -> None:
    try:
        action()
    except validate_device_catalog.ValidationError:
        return
    raise AssertionError(message)


def check_freshness_rules(carriers_dir: Path, generated_dir: Path) -> None:
    evidence_path = generated_dir / "evidence-index.json"
    index_path = generated_dir / "index.json"
    metadata_path = generated_dir / "android" / "metadata.json"
    freshness_keys = {"checks_through", "stale_after"}
    base_evidence = load_json(evidence_path)
    base_evidence["source_snapshots"] = [
        {
            "schema_version": 2,
            "source_name": "lineageos",
            "upstream_url": "https://example.com/lineageos",
            "revision": "0" * 40,
            "revision_date": "2026-07-01",
            "checked_at": "2026-07-13",
            "license_expression": "Apache-2.0",
        }
    ]
    base_evidence["profiles"][0]["reviewed_range"] = {
        "oldest": "2026-07-20",
        "newest": "2026-07-21",
    }
    base_index = load_json(index_path)
    real_public_today = validate_public_carrier_data.utc_today
    real_device_today = validate_device_catalog.utc_today

    def set_today(value: str) -> None:
        validate_public_carrier_data.utc_today = lambda: date.fromisoformat(value)
        validate_device_catalog.utc_today = lambda: date.fromisoformat(value)

    def write_evidence(**overrides: object) -> None:
        evidence = deepcopy(base_evidence)
        evidence.update(overrides)
        write_profile(evidence_path, evidence)

    def regenerate() -> dict:
        result = generate_android_outputs.main(
            ["generate_android_outputs.py", str(carriers_dir), str(generated_dir)]
        )
        assert_true(result == 0, "generator returned a non-zero status")
        return load_json(metadata_path)

    def validate(*extra: str) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = validate_public_carrier_data.main(
                ["validate_public_carrier_data.py", str(carriers_dir), str(index_path), *extra]
            )
        assert_true(result == 0, "public validator returned a non-zero status")
        return stderr.getvalue()

    def assert_rejected(message: str, *extra: str, reason: str) -> None:
        try:
            validate(*extra)
        except validate_public_carrier_data.ValidationError as exc:
            assert_true(reason in str(exc), f"{message}: unexpected error {exc}")
            return
        raise AssertionError(message)

    try:
        assert_true(
            not freshness_keys & set(load_json(metadata_path)),
            "metadata carried a freshness window without evidence dates",
        )
        write_evidence()
        metadata = regenerate()
        assert_true(
            metadata["checks_through"] == "2026-07-13"
            and metadata["stale_after"] == "2027-01-09",
            "generator did not compute the freshness window from the evidence index",
        )
        set_today("2026-09-23")
        assert_true(validate() == "", "fresh snapshot produced a warning")
        assert_true(validate("--freshness", "fail") == "", "fresh snapshot failed in fail mode")
        set_today("2027-01-09")
        assert_true(validate("--freshness", "fail") == "", "snapshot failed on stale_after itself")
        set_today("2027-01-10")
        assert_true(
            validate()
            == "warning: snapshot is past stale_after 2027-01-09 (checks_through 2026-07-13)\n",
            "warn mode did not print the stale warning",
        )
        assert_rejected(
            "fail mode accepted a stale snapshot", "--freshness", "fail", reason="past stale_after"
        )

        write_evidence(checks_through="2026-07-10", stale_after="2027-01-06")
        metadata = regenerate()
        assert_true(
            metadata["checks_through"] == "2026-07-10"
            and metadata["stale_after"] == "2027-01-06",
            "generator did not copy the published freshness window",
        )
        set_today("2026-09-23")
        assert_true(validate() == "", "published window produced a warning")
        set_today("2027-01-07")
        assert_true(
            validate()
            == "warning: snapshot is past stale_after 2027-01-06 (checks_through 2026-07-10)\n",
            "published window did not drive the warning",
        )
        assert_rejected(
            "fail mode ignored the published window",
            "--freshness",
            "fail",
            reason="past stale_after 2027-01-06",
        )

        set_today("2026-09-23")
        write_evidence(checks_through="2026-07-10", stale_after="2027-07-20")
        assert_rejected("stale_after more than 366 days out was accepted", reason="1 to 366 days")
        write_evidence(checks_through="2026-07-10", stale_after="2026-07-10")
        assert_rejected("stale_after equal to checks_through was accepted", reason="1 to 366 days")
        write_evidence(checks_through="2026-07-10")
        assert_rejected("checks_through without stale_after was accepted", reason="published together")
        write_evidence(checks_through="2026-09-24", stale_after="2027-03-23")
        assert_rejected("future-dated checks_through was accepted", reason="future-dated")
        write_evidence(checks_through="2026-07-14", stale_after="2027-01-10")
        assert_rejected(
            "snapshot checked before checks_through was accepted",
            reason="checked_at is before checks_through",
        )
        write_evidence(checks_through="2026-07-13", stale_after="2027-01-09")
        stale_evidence = deepcopy(base_evidence)
        stale_evidence["profiles"][0]["reviewed_range"]["oldest"] = "2026-07-12"
        stale_evidence.update(checks_through="2026-07-13", stale_after="2027-01-09")
        write_profile(evidence_path, stale_evidence)
        assert_rejected(
            "reviewed_range before checks_through was accepted",
            reason="reviewed_range is before checks_through",
        )

        write_evidence(checks_through="2026-07-10", stale_after="2027-01-06")
        write_profile(
            index_path,
            {**base_index, "checks_through": "2026-07-11", "stale_after": "2027-01-07"},
        )
        assert_rejected(
            "index and evidence freshness windows disagreed but passed",
            reason="does not match the stable index",
        )
        write_profile(
            index_path,
            {**base_index, "checks_through": "2026-07-10", "stale_after": "2027-01-06"},
        )
        assert_true(validate() == "", "matching index freshness window was rejected")
        write_profile(index_path, {**base_index, "stale_after": "2027-01-06"})
        assert_rejected(
            "index stale_after without checks_through was accepted", reason="published together"
        )
        write_profile(index_path, base_index)

        write_profile(metadata_path, {**metadata, "stale_after": "2027-01-05"})
        assert_rejected(
            "metadata freshness window disagreed with the evidence index",
            reason="does not match the evidence index",
        )
        write_profile(metadata_path, {**metadata, "stale_after": "2027-01-06"})
        assert_true(validate() == "", "matching metadata freshness window was rejected")

        # The early alarm for a stopped pipeline: the newest source check (the
        # snapshot was checked on 2026-07-13) or the last publish more than 21
        # days ago, long before stale_after.
        assert_true(
            validate_public_carrier_data.LIVENESS_MAX_AGE_DAYS == 21,
            "the liveness limit is one named constant of 21 days",
        )
        set_today("2026-08-03")
        assert_true(
            validate("--liveness", "fail") == "", "a source checked 21 days ago passed as alive"
        )
        set_today("2026-08-04")
        assert_true(validate() == "", "liveness must be off unless asked for")
        assert_true(
            validate("--liveness", "warn")
            == "warning: the pipeline looks stopped: source lineageos was last checked on "
            "2026-07-13, 22 days ago (more than 21 days)\n",
            "warn mode did not print the liveness warning",
        )
        assert_rejected(
            "a source check 22 days old passed in fail mode",
            "--liveness",
            "fail",
            reason="source lineageos was last checked on 2026-07-13",
        )
        set_today("2026-08-03")
        assert_rejected(
            "a last publish 22 days old passed in fail mode",
            "--liveness",
            "fail",
            "--last-publish",
            "2026-07-12",
            reason="the last data publish was on 2026-07-12, 22 days ago",
        )
        assert_true(
            validate("--liveness", "fail", "--last-publish", "2026-07-13") == "",
            "a publish 21 days ago passed as alive",
        )

        # Liveness is per lane: a daily Samsung lane that stops shows after 10
        # days, even while a weekly lane's newer check would keep the newest
        # check across all lanes fresh.
        assert_true(
            validate_public_carrier_data.LANE_LIVENESS_MAX_AGE_DAYS
            == {"samsung_carrier_config": 10, "samsung_ims": 10, "samsung_omc": 10},
            "the Samsung lanes have a 10-day liveness limit",
        )
        samsung_snapshot = {
            **base_evidence["source_snapshots"][0],
            "source_name": "samsung_omc",
            "upstream_url": "https://example.com/samsung",
            "revision_date": "2026-07-14",
            "checked_at": "2026-07-14",
        }
        window = {"checks_through": "2026-07-10", "stale_after": "2027-01-06"}
        write_evidence(
            source_snapshots=[*base_evidence["source_snapshots"], samsung_snapshot], **window
        )
        set_today("2026-07-24")
        assert_true(
            validate("--liveness", "fail") == "", "a Samsung check 10 days old failed"
        )
        set_today("2026-07-25")
        assert_rejected(
            "a Samsung check 11 days old passed while a weekly lane was fresh",
            "--liveness",
            "fail",
            reason="source samsung_omc was last checked on 2026-07-14, 11 days ago "
            "(more than 10 days)",
        )
        write_evidence(**window)

        # A tracked Samsung build in its grace: the values keep publishing,
        # the liveness check warns, and fails like a stopped Samsung lane once
        # the last confirmation is more than 10 days old.
        grace_item = {
            "sources": ["samsung_carrier_config", "samsung_ims"],
            "model": "SM-S942B",
            "region": "EUX",
            "build": "S942BXXS4BZIG",
            "superseded_by": "S942BXXS5BZJ1",
            "confirmed_at": "2026-07-20",
            "grace_until": "2026-08-19",
        }
        write_evidence(vendor_build_grace=[grace_item], **window)
        set_today("2026-07-25")
        assert_true(validate() == "", "the grace warned with liveness off")
        grace_warning = (
            "warning: samsung_carrier_config, samsung_ims values of SM-S942B EUX build "
            "S942BXXS4BZIG (superseded by S942BXXS5BZJ1) publish under the vendor build "
            "grace: last confirmed current on 2026-07-20, 5 days ago; they drop on "
            "2026-08-19 unless the lane rebuilds them from the current build\n"
        )
        assert_true(
            validate("--liveness", "warn") == grace_warning, "the grace did not warn in warn mode"
        )
        assert_true(
            validate("--liveness", "fail") == grace_warning,
            "the grace failed, or did not warn, within the Samsung lane limit",
        )
        set_today("2026-07-31")
        assert_rejected(
            "a grace 11 days after the last confirmation passed in fail mode",
            "--liveness",
            "fail",
            reason="last confirmed current on 2026-07-20, 11 days ago; they drop on "
            "2026-08-19 unless the lane rebuilds them from the current build (more than 10 days)",
        )
        set_today("2026-07-25")
        for bad, reason in (
            ({"grace_until": "2026-08-20"}, "grace_until must be 1 to 30 days"),
            ({"confirmed_at": "2026-07-09"}, "confirmed_at is before checks_through"),
            ({"confirmed_at": "2026-07-26"}, "confirmed_at is future-dated"),
            ({"build_id": "x"}, "has invalid keys"),
            ({"sources": ["samsung_ims", "samsung_carrier_config"]}, "sources must be"),
        ):
            write_evidence(vendor_build_grace=[{**grace_item, **bad}], **window)
            assert_rejected(f"an invalid grace item {bad} was accepted", reason=reason)
        write_evidence(vendor_build_grace=[], **window)
        assert_rejected("an empty grace list was accepted", reason="vendor_build_grace is empty")
        write_evidence(**window)

        set_today("2027-01-19")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            validate_device_catalog.check_freshness("2026-07-23", "fail")
        assert_true(stderr.getvalue() == "", "device catalog warned on stale_after itself")
        set_today("2027-01-20")
        with contextlib.redirect_stderr(stderr):
            validate_device_catalog.check_freshness("2026-07-23", "warn")
        assert_true(
            stderr.getvalue()
            == "warning: snapshot is past stale_after 2027-01-19 (checks_through 2026-07-23)\n",
            "device catalog warn mode did not print the stale warning",
        )
        assert_validation_error(
            lambda: validate_device_catalog.check_freshness("2026-07-23", "fail"),
            "device catalog fail mode accepted a stale snapshot",
        )
    finally:
        validate_public_carrier_data.utc_today = real_public_today
        validate_device_catalog.utc_today = real_device_today


def check_entry_dates(carriers_dir: Path, evidence_path: Path, profile_ids: set[str]) -> None:
    """newest_entry and capability_newest_entries are optional YYYY-MM dates;
    a capability date needs a published capability and cannot be newer than
    the profile's newest_entry."""
    capabilities = {
        profile["profile_id"]: profile["capabilities"]
        for path in carriers_dir.rglob("*.json")
        for profile in [load_json(path)]
    }
    dated_id = next(
        profile_id
        for profile_id, values in sorted(capabilities.items())
        if values.get("mms") == "supported"
    )
    old_shape = evidence_path.read_text(encoding="utf-8")

    config_keys: dict[str, set[str]] = {}

    def validate(value: dict) -> None:
        write_profile(evidence_path, value)
        validate_public_carrier_data.validate_evidence_index(
            evidence_path, profile_ids, None, capabilities, config_keys or None
        )

    def dated(**fields: object) -> dict:
        value = json.loads(old_shape)
        for profile in value["profiles"]:
            if profile["profile_id"] == dated_id:
                profile.update(fields)
        return value

    def expect_failure(value: dict, message: str) -> None:
        try:
            validate(value)
        except validate_public_carrier_data.ValidationError:
            return
        raise AssertionError(message)

    try:
        validate(json.loads(old_shape))
        validate(dated(newest_entry="2025-08"))
        validate(dated(newest_entry="2025-08", capability_newest_entries={"mms": "2019-03"}))
        validate(dated(capability_newest_entries={"mms": "2019-03"}))
        for bad_month in ("2025-8", "2025-08-01", "2025-13", "2025-00", 202508):
            expect_failure(
                dated(newest_entry=bad_month),
                f"newest_entry accepted {bad_month!r}",
            )
            expect_failure(
                dated(capability_newest_entries={"mms": bad_month}),
                f"a capability entry date accepted {bad_month!r}",
            )
        expect_failure(dated(newest_entry="2999-01"), "a future newest_entry passed")
        expect_failure(
            dated(capability_newest_entries={}), "an empty capability date map passed"
        )
        expect_failure(
            dated(capability_newest_entries={"telepathy": "2019-03"}),
            "a date for an unknown capability name passed",
        )
        expect_failure(
            dated(capability_newest_entries={"vonr": "2019-03"}),
            "a date for a capability no source gives a value passed",
        )
        expect_failure(
            dated(newest_entry="2019-02", capability_newest_entries={"mms": "2019-03"}),
            "a capability date newer than the profile's newest_entry passed",
        )

        def gate(key: str, section: str = "capabilities") -> dict:
            return {
                "kind": "quality_gate",
                "section": section,
                "key": key,
                "observed_value_count": 1,
                "resolution": "omitted_from_stable",
            }

        validate(dated(quality_gates=[gate("stale_single_source_entry:vonr")]))
        validate(dated(quality_gates=[gate("uncorroborated_generic_apn", "android_apns")]))
        expect_failure(
            dated(quality_gates=[gate("stale_single_source_entry:mms")]),
            "a stale gate for a capability the profile still publishes passed",
        )
        expect_failure(
            dated(quality_gates=[gate("stale_single_source_entry:telepathy")]),
            "a stale gate for an unknown capability name passed",
        )
        expect_failure(
            dated(quality_gates=[gate("stale_single_source_entry:vonr", "android_apns")]),
            "a stale gate outside the capabilities section passed",
        )
        # The evidence version of the five-year rule withholds VoLTE, VoWiFi,
        # MMS and Wi-Fi calling while roaming under two gates of its own,
        # checked like the age gate.
        for name in ("frozen_source_only", "unseen_scope"):
            validate(dated(quality_gates=[gate(f"{name}:vonr")]))
            expect_failure(
                dated(quality_gates=[gate(f"{name}:mms")]),
                f"a {name} gate for a capability the profile still publishes passed",
            )
            expect_failure(
                dated(quality_gates=[gate(f"{name}:telepathy")]),
                f"a {name} gate for an unknown capability name passed",
            )
            expect_failure(
                dated(quality_gates=[gate(f"{name}:vonr", "android_carrier_config")]),
                f"a {name} gate outside the capabilities section passed",
            )

        # A withheld label takes its switch with it (rule decisions of
        # 2026-10-06, change 6): no withholding gate sits next to the
        # capability's gating key. A single-family off is not such a gate.
        for name in ("stale_single_source_entry", "frozen_source_only", "unseen_scope"):
            config_keys[dated_id] = {"carrier_vt_available_bool", "maxMessageSize"}
            expect_failure(
                dated(quality_gates=[gate(f"{name}:video_calling")]),
                f"a {name} gate next to its capability's switch passed",
            )
            config_keys[dated_id] = {"maxMessageSize"}
            validate(dated(quality_gates=[gate(f"{name}:video_calling")]))
        config_keys[dated_id] = {"support_conference_call_bool"}
        expect_failure(
            dated(quality_gates=[gate("stale_single_source_entry:ims_conference")]),
            "a withheld ims_conference label next to support_conference_call_bool passed",
        )
        config_keys[dated_id] = {"carrier_vt_available_bool"}
        validate(dated(quality_gates=[gate("single_family_off:video_calling")]))
        config_keys.clear()

        # A withheld capability keeps its date (report item #5), and flags
        # mark old single-source values without withholding anything.
        base = json.loads(old_shape)
        sources = next(
            profile["sources"] for profile in base["profiles"] if profile["profile_id"] == dated_id
        )
        capability_sources = {
            **next(
                profile.get("capability_sources", {})
                for profile in base["profiles"]
                if profile["profile_id"] == dated_id
            ),
            "video_calling": {"on": sources[:1]},
        }
        withheld = dict(
            capability_sources=capability_sources,
            quality_gates=[gate("stale_single_source_entry:video_calling")],
            capability_newest_entries={"mms": "2019-03", "video_calling": "2018-05"},
        )
        validate(dated(**withheld))
        expect_failure(
            dated(**{**withheld, "capability_newest_entries": {"vonr": "2019-03"}}),
            "a date for a capability no source gives passed",
        )

        def flag(section: str, key: str, name: str) -> dict:
            return {"section": section, "key": key, "flag": name}

        flags = [
            flag("capabilities", "mms", "old_single_source"),
            flag("capabilities", "video_calling", "old_single_source"),
        ]
        validate(dated(**withheld, flags=flags))
        for bad, message in (
            ([], "an empty flag list passed"),
            (list(reversed(flags)), "unsorted flags passed"),
            ([flag("capabilities", "vonr", "old_single_source")], "an undated old_single_source flag passed"),
            ([flag("capabilities", "mms", "stale")], "an unknown flag passed"),
            ([flag("android_carrier_config", "mms", "old_single_source")], "a flag in the wrong section passed"),
            (
                [flag("android_carrier_config", "carrier_vt_available_bool", "capability_label_withheld")],
                "the retired capability_label_withheld flag passed",
            ),
            ([{**flags[0], "gate": "stale_single_source_entry"}], "a flag with an unknown key passed"),
        ):
            expect_failure(dated(**withheld, flags=bad), message)
    finally:
        evidence_path.write_text(old_shape, encoding="utf-8")


def check_capability_sources(
    carriers_dir: Path, evidence_path: Path, profile_ids: set[str]
) -> None:
    """capability_sources lists, per capability, the profile sources that turn
    it on, turn it off, or call it conditional. It agrees with the published
    value, covers every published capability, replaces the capability entries
    of fact_sources, and an unknown with sources names the gate behind it."""
    profiles = {
        profile["profile_id"]: profile
        for path in carriers_dir.rglob("*.json")
        for profile in [load_json(path)]
    }
    capabilities = {profile_id: profile["capabilities"] for profile_id, profile in profiles.items()}
    config_keys = {
        profile_id: set(profile.get("android_carrier_config") or {})
        for profile_id, profile in profiles.items()
    }
    target = next(
        profile_id
        for profile_id, values in sorted(capabilities.items())
        if values.get("mms") == "supported" and values.get("vonr", "unknown") == "unknown"
    )
    published = {key: value for key, value in capabilities[target].items() if value != "unknown"}
    kinds_for = {
        "supported": {"on": ["aosp"]},
        "unsupported": {"off": ["aosp", "lineageos"]},
        "conditional": {"off": ["lineageos"], "on": ["aosp"]},
    }
    new_sources = {key: kinds_for[value] for key, value in published.items()}
    old_shape = evidence_path.read_text(encoding="utf-8")

    def shaped(sources: object, gates: list | None = None, facts: list | None = None) -> dict:
        value = json.loads(old_shape)
        for profile in value["profiles"]:
            if profile["profile_id"] == target:
                profile["fact_sources"] = facts or []
                profile["capability_sources"] = sources
                if gates:
                    profile["quality_gates"] = gates
        return value

    def validate(value: dict) -> None:
        write_profile(evidence_path, value)
        validate_public_carrier_data.validate_evidence_index(
            evidence_path, profile_ids, None, capabilities, config_keys
        )

    def expect_failure(value: dict, message: str) -> None:
        try:
            validate(value)
        except validate_public_carrier_data.ValidationError:
            return
        raise AssertionError(message)

    def gate(key: str, section: str = "capabilities") -> dict:
        return {
            "kind": "quality_gate",
            "section": section,
            "key": key,
            "observed_value_count": 1,
            "resolution": "omitted_from_stable",
        }

    def without_sources(facts: list) -> dict:
        value = json.loads(old_shape)
        for profile in value["profiles"]:
            if profile["profile_id"] == target:
                profile.pop("capability_sources", None)
                profile["fact_sources"] = facts
        return value

    try:
        validate(json.loads(old_shape))
        validate(shaped(new_sources))
        expect_failure(
            without_sources([{"section": "capabilities", "key": "mms", "sources": ["aosp"]}]),
            "the old shape, capabilities in fact_sources, passed",
        )
        expect_failure(
            without_sources([]), "a profile that publishes capabilities without sources passed"
        )
        withheld = {**new_sources, "vonr": {"off": ["lineageos"]}}
        validate(shaped(withheld, [gate("single_family_off:vonr")]))
        validate(shaped(withheld, [gate("stale_single_source_entry:vonr")]))
        validate(shaped(withheld, [gate("frozen_source_only:vonr")]))
        validate(shaped(withheld, [gate("unseen_scope:vonr")]))
        expect_failure(
            shaped(withheld), "an unknown capability with sources but no gate passed"
        )
        expect_failure(
            shaped({key: value for key, value in new_sources.items() if key != "mms"}),
            "capability_sources without a published capability passed",
        )
        expect_failure(
            shaped({**new_sources, "mms": {"off": ["lineageos"], "on": ["aosp"]}}),
            "a supported capability with an off source passed",
        )
        expect_failure(
            shaped({**new_sources, "mms": {"on": ["samsung_omc"]}}),
            "a source the profile does not name passed",
        )
        expect_failure(
            shaped({**new_sources, "mms": {"on": ["lineageos", "aosp"]}}),
            "an unsorted source list passed",
        )
        expect_failure(
            shaped({**new_sources, "mms": {"yes": ["aosp"]}}), "an unknown source kind passed"
        )
        expect_failure(
            shaped({**new_sources, "telepathy": {"on": ["aosp"]}}),
            "an unknown capability name passed",
        )
        expect_failure(shaped({}), "an empty capability_sources passed")
        expect_failure(
            shaped(
                new_sources,
                facts=[{"section": "capabilities", "key": "mms", "sources": ["aosp"]}],
            ),
            "capability entries in both fact_sources and capability_sources passed",
        )
        expect_failure(
            shaped(new_sources, [gate("single_family_off:mms")]),
            "a single-family gate on a published capability passed",
        )
        validate(
            shaped(
                new_sources,
                [gate("single_family_off:carrier_volte_available_bool", "android_carrier_config")],
            )
        )
        expect_failure(
            shaped(new_sources, [gate("single_family_off:rtt_supported_bool", "android_carrier_config")]),
            "a single-family gate on a key that gates no capability passed",
        )
        expect_failure(
            shaped(new_sources, [gate("single_family_off:vonr", "android_apns")]),
            "a single-family gate outside capabilities and CarrierConfig passed",
        )
    finally:
        evidence_path.write_text(old_shape, encoding="utf-8")


def check_source_versions(evidence_path: Path, profile_ids: set[str]) -> None:
    """source_versions is optional. Each item names a profile source once, in
    order, with sorted lists of build IDs, full Git commits, or Apple bundle
    and iOS versions, and nothing else."""
    old_shape = evidence_path.read_text(encoding="utf-8")
    first_id = sorted(profile_ids)[0]

    def versioned(items: object) -> dict:
        value = json.loads(old_shape)
        for profile in value["profiles"]:
            if profile["profile_id"] == first_id:
                profile["source_versions"] = items
        return value

    def validate(value: dict) -> None:
        write_profile(evidence_path, value)
        validate_public_carrier_data.validate_evidence_index(evidence_path, profile_ids)

    def expect_failure(items: object, message: str) -> None:
        try:
            validate(versioned(items))
        except validate_public_carrier_data.ValidationError:
            return
        raise AssertionError(message)

    commit = "b446f3306fb55d46e6799f3ae76dbb1f40b22193"
    try:
        validate(json.loads(old_shape))
        validate(
            versioned(
                [
                    {"source": "aosp", "builds": ["CP3A.260905.009", "G981BXXSNHYB1"]},
                    {
                        "source": "lineageos",
                        "commits": [commit],
                        "bundle_versions": ["31.1", "8.1.1"],
                        "ios_versions": ["11.2", "26.0.1"],
                    },
                ]
            )
        )
        expect_failure([], "an empty source_versions list passed")
        expect_failure({"source": "aosp"}, "a source_versions object instead of a list passed")
        expect_failure([{"source": "aosp"}], "an item without identifiers passed")
        expect_failure(
            [{"source": "samsung_omc", "builds": ["G981BXXSNHYB1"]}],
            "an item for a source the profile does not name passed",
        )
        expect_failure(
            [{"source": "lineageos", "commits": [commit]}, {"source": "aosp", "builds": ["A1"]}],
            "unsorted source_versions items passed",
        )
        expect_failure(
            [{"source": "aosp", "builds": ["A1"]}, {"source": "aosp", "commits": [commit]}],
            "a source named twice passed",
        )
        expect_failure(
            [{"source": "aosp", "urls": ["https://example.com/firmware.zip"]}],
            "an unknown identifier kind passed",
        )
        expect_failure([{"source": "aosp", "builds": []}], "an empty identifier list passed")
        expect_failure(
            [{"source": "aosp", "builds": ["B2", "A1"]}], "an unsorted identifier list passed"
        )
        expect_failure(
            [{"source": "aosp", "builds": ["A1", "A1"]}], "a repeated identifier passed"
        )
        for kind, bad in (
            ("builds", "work/raw/firmware.zip"),
            ("builds", "SM-G981B/BTU G981BXXSNHYB1"),
            ("builds", 12),
            ("commits", commit[:12]),
            ("commits", "git-" + commit),
            ("commits", commit.upper()),
            ("bundle_versions", "31.1-beta"),
            ("ios_versions", "iOS 17.1"),
            ("ios_versions", "21A329"),
        ):
            expect_failure(
                [{"source": "aosp", kind: [bad]}], f"{kind} accepted {bad!r}"
            )
    finally:
        evidence_path.write_text(old_shape, encoding="utf-8")


def check_capability_basis(evidence_path: Path, profile_ids: set[str]) -> None:
    """capability_basis is optional. Samsung OMC's vonr names the Samsung VoNR
    switch offer with its sales codes and models: the models by name up to
    24, otherwise their count and SHA-256. The source must turn the capability
    on, and the sales codes and models must be in the observed scope."""
    old_shape = evidence_path.read_text(encoding="utf-8")
    target = sorted(profile_ids)[0]
    models = [f"SM-S9{index:02d}U" for index in range(30)]

    def based(basis: object, scope_models: list[str] | None = None, on: list[str] | None = None) -> dict:
        value = json.loads(old_shape)
        for profile in value["profiles"]:
            if profile["profile_id"] == target:
                profile["sources"] = sorted(set(profile["sources"]) | {"samsung_omc"})
                profile["fact_sources"] = []
                profile.pop("observed_model_source_groups", None)
                profile.pop("source_versions", None)
                profile["observed_scope"] = {
                    "models": scope_models if scope_models is not None else models,
                    "sales_codes": ["TMB", "XAG"],
                }
                profile["capability_sources"] = {"vonr": {"on": on or ["samsung_omc"]}}
                profile["capability_basis"] = basis
        return value

    def validate(value: dict) -> None:
        write_profile(evidence_path, value)
        validate_public_carrier_data.validate_evidence_index(evidence_path, profile_ids)

    def expect_failure(value: dict, message: str) -> None:
        try:
            validate(value)
        except validate_public_carrier_data.ValidationError:
            return
        raise AssertionError(message)

    listed = {
        "basis": "samsung_vonr_switch",
        "source": "samsung_omc",
        "sales_codes": ["TMB"],
        "model_count": 2,
        "models": models[:2],
    }
    digest = hashlib.sha256("\n".join(models).encode("utf-8")).hexdigest()
    hashed = {
        "basis": "samsung_vonr_switch",
        "source": "samsung_omc",
        "sales_codes": ["TMB", "XAG"],
        "model_count": 30,
        "models_sha256": digest,
    }
    try:
        validate(json.loads(old_shape))
        validate(based({"vonr": listed}))
        validate(based({"vonr": hashed}))
        expect_failure(based({}), "an empty capability_basis passed")
        expect_failure(based({"volte": listed}), "the VoNR switch as a VoLTE basis passed")
        expect_failure(based({"telepathy": listed}), "an unknown capability passed")
        expect_failure(
            based({"vonr": {**listed, "basis": "samsung_default_on"}}), "an unknown basis passed"
        )
        expect_failure(
            based({"vonr": {**listed, "source": "aosp"}}), "the switch from another source passed"
        )
        expect_failure(
            based({"vonr": listed}, on=["aosp"]),
            "a basis whose source does not turn the capability on passed",
        )
        expect_failure(
            based({"vonr": {**listed, "sales_codes": ["KTC"]}}),
            "a sales code outside the observed scope passed",
        )
        expect_failure(
            based({"vonr": {**listed, "sales_codes": []}}), "an empty sales code list passed"
        )
        expect_failure(
            based({"vonr": {**listed, "sales_codes": ["XAG", "TMB"]}}),
            "an unsorted sales code list passed",
        )
        expect_failure(
            based({"vonr": {**listed, "model_count": 3}}), "a model count that disagrees passed"
        )
        expect_failure(
            based({"vonr": {**listed, "models": ["SM-X000"], "model_count": 1}}),
            "a model outside the observed scope passed",
        )
        expect_failure(
            based({"vonr": {**listed, "models": models[1::-1]}}), "an unsorted model list passed"
        )
        expect_failure(
            based({"vonr": {**listed, "models": models[:25], "model_count": 25}}),
            "more than 24 listed models passed",
        )
        expect_failure(
            based({"vonr": {**hashed, "model_count": 24}}),
            "a digest for a list short enough to name passed",
        )
        expect_failure(
            based({"vonr": {**hashed, "model_count": 31}}),
            "more models than the profile observed passed",
        )
        expect_failure(
            based({"vonr": {**hashed, "models_sha256": digest.upper()}}),
            "a malformed digest passed",
        )
        expect_failure(
            based({"vonr": {**listed, "models_sha256": digest}}),
            "both a model list and a digest passed",
        )
        expect_failure(
            based({"vonr": {key: value for key, value in listed.items() if key != "model_count"}}),
            "a basis without a model count passed",
        )
        expect_failure(
            based({"vonr": {**listed, "default_on": True}}), "an unknown basis field passed"
        )
    finally:
        evidence_path.write_text(old_shape, encoding="utf-8")


def check_apn_variant_sources_and_removal_gates(
    evidence_path: Path, profile_ids: set[str]
) -> None:
    """An APN variant conflict may name, per variant, the sources that gave
    it, and a lineageos_apn_removed gate names one full LineageOS commit in
    the APN section."""
    old_shape = evidence_path.read_text(encoding="utf-8")
    first_id = sorted(profile_ids)[0]
    key_a = "sha256:" + "a" * 16
    key_b = "sha256:" + "b" * 16
    commit = "3169b43c" + "0" * 32

    def conflict(**extra: object) -> dict:
        return {
            "kind": "conflict",
            "section": "android_apns",
            "key": "type:default:selector:" + "c" * 16,
            "observed_value_count": 2,
            "resolution": "published_variants",
            **extra,
        }

    def gate(key: str, section: str = "android_apns", resolution: str = "omitted_from_stable") -> dict:
        return {
            "kind": "quality_gate",
            "section": section,
            "key": key,
            "observed_value_count": 3,
            "resolution": resolution,
        }

    def shaped(conflicts: list | None = None, gates: list | None = None) -> dict:
        value = json.loads(old_shape)
        for profile in value["profiles"]:
            if profile["profile_id"] == first_id:
                if conflicts is not None:
                    profile["conflicts"] = conflicts
                if gates is not None:
                    profile["quality_gates"] = gates
        return value

    def validate(value: dict) -> None:
        write_profile(evidence_path, value)
        validate_public_carrier_data.validate_evidence_index(evidence_path, profile_ids)

    def expect_failure(value: dict, message: str) -> None:
        try:
            validate(value)
        except validate_public_carrier_data.ValidationError:
            return
        raise AssertionError(message)

    variants = [
        {"key": key_a, "sources": ["aosp", "lineageos"]},
        {"key": key_b, "sources": ["lineageos"]},
    ]
    try:
        validate(shaped([conflict()]))
        validate(shaped([conflict(variant_sources=variants)]))
        expect_failure(
            shaped([conflict(variant_sources=variants[:1])]),
            "variant_sources that miss a variant passed",
        )
        expect_failure(
            shaped([conflict(variant_sources=list(reversed(variants)))]),
            "unsorted variant_sources passed",
        )
        expect_failure(
            shaped([conflict(variant_sources=[variants[0], {"key": key_b, "sources": ["samsung_omc"]}])]),
            "a variant source the profile does not name passed",
        )
        expect_failure(
            shaped([conflict(variant_sources=[variants[0], {"key": "internet.example", "sources": ["aosp"]}])]),
            "a variant keyed by anything but an APN fact key passed",
        )
        expect_failure(
            shaped([conflict(variant_sources=[variants[0], {"key": key_b, "sources": []}])]),
            "a variant without sources passed",
        )
        expect_failure(
            shaped(
                [
                    {
                        **conflict(variant_sources=variants),
                        "section": "android_carrier_config",
                        "resolution": "omitted_from_stable",
                    }
                ]
            ),
            "variant_sources outside an APN variant conflict passed",
        )
        # A conflict Google's current file settled against its frozen Pixel
        # copies: only a capability or CarrierConfig conflict.
        superseded = {
            "kind": "conflict",
            "section": "capabilities",
            "key": "vowifi",
            "observed_value_count": 2,
            "resolution": "superseded_device_file",
        }
        validate(shaped([superseded]))
        validate(
            shaped(
                [
                    {
                        **superseded,
                        "section": "android_carrier_config",
                        "key": "carrier_wfc_ims_available_bool",
                    }
                ]
            )
        )
        expect_failure(
            shaped([{**superseded, "section": "android_apns"}]),
            "a superseded_device_file conflict in the APN section passed",
        )
        expect_failure(
            shaped([{**superseded, "section": "addons"}]),
            "a superseded_device_file conflict in the add-ons passed",
        )
        expect_failure(
            shaped(gates=[{**superseded, "kind": "quality_gate"}]),
            "a superseded_device_file quality gate passed",
        )
        expect_failure(
            shaped([{**superseded, "superseded_sources": ["google_pixel_vendor_carriersettings"]}]),
            "a superseded_device_file conflict with an extra key passed",
        )
        expect_failure(
            shaped([{**superseded, "resolution": "superseded_by_current_version"}]),
            "an unknown resolution passed",
        )
        validate(shaped(gates=[gate("lineageos_apn_removed:" + commit)]))
        validate(
            shaped(
                gates=[
                    gate("lineageos_apn_removed:" + commit),
                    gate("lineageos_apn_removed:" + "e003409d" + "1" * 32),
                ]
            )
        )
        expect_failure(
            shaped(gates=[gate("lineageos_apn_removed:" + commit[:12])]),
            "a removal gate with an abbreviated commit passed",
        )
        expect_failure(
            shaped(gates=[gate("lineageos_apn_removed:" + commit, section="capabilities")]),
            "a removal gate outside the APN section passed",
        )
        expect_failure(
            shaped(gates=[gate("lineageos_apn_removed:" + commit, resolution="conditional")]),
            "a removal gate that is not an omission passed",
        )
        expect_failure(
            shaped(gates=[gate("lineageos_apn_removed:" + commit), gate("lineageos_apn_removed:" + commit)]),
            "a removal commit named twice passed",
        )

        # Why each removing commit dropped its rows, and the profiles a gate
        # left with no fact at all.
        other = "d6b9e1c0" + "2" * 32
        withdrawn = {
            "profile_id": "open.722071.0123456789ab",
            "sources": ["sony_open_devices_aosp"],
            "quality_gates": [gate("lineageos_apn_removed:" + other)],
        }
        commits = [
            {"commit": commit, "removed_on": "2026-07-20", "reasons": ["extra_code", "vendor_rom_absent"], "gerrit_change": 486920},
            {"commit": other, "removed_on": "2026-03-27", "reasons": ["extra_code"]},
        ]

        def with_removals(withdrawn_profiles: list | None, removal_commits: list | None) -> dict:
            value = shaped(gates=[gate("lineageos_apn_removed:" + commit)])
            if withdrawn_profiles is not None:
                value["withdrawn_profiles"] = withdrawn_profiles
            if removal_commits is not None:
                value["apn_removal_commits"] = removal_commits
            return value

        validate(with_removals([withdrawn], commits))
        validate(with_removals(None, commits[:1]))
        validate(with_removals([withdrawn], None))
        for bad_withdrawn, bad_commits, message in (
            ([withdrawn], commits[:1], "a withdrawn profile's removal commit missing from the table passed"),
            (None, commits, "a removal commit no gate names passed"),
            (None, [{**commits[0], "reasons": ["shut_down"]}], "an unknown removal reason passed"),
            (None, [{**commits[0], "reasons": ["vendor_rom_absent", "extra_code"]}], "unsorted reasons passed"),
            (None, [{**commits[0], "reasons": []}], "a commit without a reason passed"),
            (None, [{**commits[0], "gerrit_change": "486920"}], "a Gerrit change given as text passed"),
            (None, [{**commits[0], "url": "https://review.lineageos.org/486920"}], "an unknown commit key passed"),
            ([withdrawn], list(reversed(commits)), "unsorted removal commits passed"),
            ([{**withdrawn, "profile_id": first_id}], commits, "a withdrawn profile that is published passed"),
            ([{**withdrawn, "quality_gates": []}], commits[:1], "a withdrawn profile without a gate passed"),
            (
                [{**withdrawn, "quality_gates": [gate("lineageos_apn_removed:" + other, resolution="conditional")]}],
                commits,
                "a withdrawn profile whose gate is no omission passed",
            ),
            ([withdrawn, withdrawn], commits, "a withdrawn profile listed twice passed"),
            ([{**withdrawn, "display_name": "Movistar"}], commits, "an unknown withdrawn key passed"),
        ):
            expect_failure(with_removals(bad_withdrawn, bad_commits), message)
    finally:
        evidence_path.write_text(old_shape, encoding="utf-8")


def check_evidence_format(carriers_dir: Path, generated_dir: Path) -> None:
    """The evidence index carries no constant markers, no redistribution class,
    and only fact_sources entries narrower than the profile's sources."""
    evidence_path = generated_dir / "evidence-index.json"
    original = evidence_path.read_text(encoding="utf-8")
    profile_ids = {
        item["profile_id"] for item in load_json(generated_dir / "index.json")["profiles"]
    }
    snapshot = {
        "schema_version": 2,
        "source_name": "samsung_omc",
        "upstream_url": "https://example.com/samsung",
        "revision": "a" * 64,
        "revision_date": "2026-07-20",
        "checked_at": "2026-07-21",
        "license_expression": "NOASSERTION",
    }

    def expect_failure(mutate: Callable[[dict], None], message: str) -> None:
        bad = load_json(evidence_path)
        mutate(bad)
        write_profile(evidence_path, bad)
        try:
            validate_public_carrier_data.validate_evidence_index(evidence_path, profile_ids)
        except validate_public_carrier_data.ValidationError:
            pass
        else:
            raise AssertionError(message)
        finally:
            evidence_path.write_text(good_text, encoding="utf-8")

    try:
        good = load_json(evidence_path)
        good["source_snapshots"] = [snapshot]
        write_profile(evidence_path, good)
        good_text = evidence_path.read_text(encoding="utf-8")
        validate_public_carrier_data.validate_evidence_index(evidence_path, profile_ids)
        expect_failure(
            lambda value: value.__setitem__("model_source_provenance", "complete"),
            "the constant model_source_provenance marker must be rejected",
        )
        expect_failure(
            lambda value: value["source_snapshots"][0].__setitem__("redistribution", "permitted"),
            "the dropped redistribution class must be rejected",
        )

        def redundant(value: dict) -> None:
            profile = value["profiles"][0]
            profile["fact_sources"] = [
                {
                    "section": "android_carrier_config",
                    "key": "carrier_volte_available_bool",
                    "sources": list(profile["sources"]),
                }
            ]

        expect_failure(redundant, "a fact entry equal to the profile sources must be rejected")

        def display_name_entry(value: dict) -> None:
            profile = value["profiles"][0]
            profile["fact_sources"] = [
                {"section": "profile", "key": "display_name", "sources": profile["sources"][:1]}
            ]

        expect_failure(display_name_entry, "display-name provenance entries must be rejected")

        # old_build_sources: the Samsung sources that give an APN fact only
        # from builds over three years old. Such an entry may repeat the
        # profile's sources.
        def old_build(entry: dict) -> Callable[[dict], None]:
            def mutate(value: dict) -> None:
                profile = value["profiles"][0]
                profile["sources"] = ["lineageos", "samsung_omc"]
                profile["fact_sources"] = [entry]
            return mutate

        base_entry = {
            "section": "android_apns",
            "key": "sha256:0123456789abcdef",
            "sources": ["lineageos", "samsung_omc"],
            "old_build_sources": ["samsung_omc"],
        }
        accepted = load_json(evidence_path)
        old_build(base_entry)(accepted)
        write_profile(evidence_path, accepted)
        validate_public_carrier_data.validate_evidence_index(evidence_path, profile_ids)
        evidence_path.write_text(good_text, encoding="utf-8")
        for entry, message in (
            ({**base_entry, "old_build_sources": ["lineageos"]}, "a non-vendor old build source passed"),
            ({**base_entry, "old_build_sources": []}, "an empty old_build_sources passed"),
            ({**base_entry, "sources": ["lineageos"]}, "an old build source the fact does not name passed"),
            ({**base_entry, "section": "android_carrier_config", "key": "enabledMMS"}, "old_build_sources outside APN facts passed"),
            ({**base_entry, "old_build_sources": "samsung_omc"}, "a string old_build_sources passed"),
        ):
            expect_failure(old_build(entry), message)
        # shared_file_sources: Google gives an APN fact only from its shared
        # carrier file, unconfirmed. Such an entry may repeat the profile's
        # sources.
        def shared_file(entry: dict) -> Callable[[dict], None]:
            def mutate(value: dict) -> None:
                profile = value["profiles"][0]
                profile["sources"] = ["google_carriersettings", "lineageos"]
                profile["fact_sources"] = [entry]
            return mutate

        shared_entry = {
            "section": "android_apns",
            "key": "sha256:0123456789abcdef",
            "sources": ["google_carriersettings", "lineageos"],
            "shared_file_sources": ["google_carriersettings"],
        }
        accepted = load_json(evidence_path)
        shared_file(shared_entry)(accepted)
        write_profile(evidence_path, accepted)
        validate_public_carrier_data.validate_evidence_index(evidence_path, profile_ids)
        evidence_path.write_text(good_text, encoding="utf-8")
        for entry, message in (
            ({**shared_entry, "shared_file_sources": ["lineageos"]}, "a shared file of another source passed"),
            ({**shared_entry, "shared_file_sources": []}, "an empty shared_file_sources passed"),
            ({**shared_entry, "shared_file_sources": "google_carriersettings"}, "a string shared_file_sources passed"),
            ({**shared_entry, "sources": ["lineageos"]}, "a shared-file source the fact does not name passed"),
            ({**shared_entry, "section": "android_carrier_config", "key": "enabledMMS"}, "shared_file_sources outside APN facts passed"),
        ):
            expect_failure(shared_file(entry), message)
        check_entry_dates(carriers_dir, evidence_path, profile_ids)
        check_capability_sources(carriers_dir, evidence_path, profile_ids)
        check_source_versions(evidence_path, profile_ids)
        check_capability_basis(evidence_path, profile_ids)
        check_apn_variant_sources_and_removal_gates(evidence_path, profile_ids)
    finally:
        evidence_path.write_text(original, encoding="utf-8")

    rcs_profile = {
        "schema_version": 1,
        "display_name": "Unused namespace",
        "match": {"mccmnc": ["00195"]},
        "capabilities": {},
        "addons": {"rcs": {"chat_enabled": True}},
    }
    rcs_profile["profile_id"] = validate_public_carrier_data.canonical_profile_id(
        rcs_profile["match"]
    )
    try:
        validate_public_carrier_data.validate_profile_object(
            carriers_dir / "rcs.json", rcs_profile
        )
    except validate_public_carrier_data.ValidationError:
        pass
    else:
        raise AssertionError("an add-on namespace no source uses must be rejected")


def check_subscriber_prefix_rules(root: Path) -> None:
    """Full IMSI or ICCID values never pass, in match or in APN MVNO data."""
    accepted = {
        ("imsi", "26201"),
        ("imsi", "262260x1"),
        ("imsi", "2620112345"),
        ("imsi", "26201xxxxxxxxxx"),
        ("imsi", "310260XXXXX"),
        ("iccid", "89490"),
        ("iccid", "8949012345678"),
    }
    rejected = {
        ("imsi", "262011234567890"),
        ("imsi", "26201123456"),
        ("imsi", "2620xxxxxx"),
        ("imsi", "xxxxxxx"),
        ("imsi", "26201-1"),
        ("iccid", "8949"),
        ("iccid", "8949012345678901234"),
        ("iccid", "89490x"),
    }
    schema = load_json(
        Path(__file__).resolve().parents[1] / "schemas/carrier-profile.schema.json"
    )
    schema_patterns = {
        rule["if"]["properties"]["mvno_type"]["const"]: re.compile(
            rule["then"]["properties"]["mvno_match_data"]["pattern"]
        )
        for rule in schema["properties"]["android_apns"]["items"]["allOf"]
    }
    assert_true(
        set(schema_patterns) == validate_public_carrier_data.SUBSCRIBER_PREFIX_KINDS,
        "schema must pin APN MVNO data for every subscriber prefix kind",
    )
    for kind, value in accepted | rejected:
        expected = (kind, value) in accepted
        assert_true(
            validate_public_carrier_data.subscriber_prefix_ok(kind, value) is expected,
            f"subscriber_prefix_ok({kind!r}, {value!r}) should be {expected}",
        )
        assert_true(
            (schema_patterns[kind].search(value) is not None) is expected,
            f"schema pattern for {kind} disagrees with the validator on {value!r}",
        )

    def profile_with_mvno(mvno_type: str, mvno_match_data: str) -> dict:
        profile = {
            "schema_version": 1,
            "display_name": "Subscriber prefix",
            "match": {"mccmnc": ["00197"]},
            "capabilities": {},
            "android_apns": [
                {
                    "name": "mvno",
                    "apn": "mvno.example",
                    "types": ["default"],
                    "mvno_type": mvno_type,
                    "mvno_match_data": mvno_match_data,
                }
            ],
        }
        profile["profile_id"] = validate_public_carrier_data.canonical_profile_id(
            profile["match"]
        )
        return profile

    for mvno_type, value in (("imsi", "262260x1"), ("imsi", "26201xxxxxxxxxx"), ("iccid", "8949012")):
        validate_public_carrier_data.validate_profile_object(
            root / "mvno-prefix.json", profile_with_mvno(mvno_type, value)
        )
    for mvno_type, value in (("imsi", "262011234567890"), ("iccid", "8949012345678901234")):
        try:
            validate_public_carrier_data.validate_profile_object(
                root / "mvno-full-identity.json", profile_with_mvno(mvno_type, value)
            )
        except validate_public_carrier_data.ValidationError as exc:
            assert_true(
                "mvno_match_data is not an" in str(exc),
                f"wrong error for a full {mvno_type} in mvno_match_data: {exc}",
            )
        else:
            raise AssertionError(f"a full {mvno_type} in mvno_match_data should fail")

    for key, value in (
        ("imsi_prefix_patterns", "262011234567890"),
        ("imsi_prefix_patterns", "2620xxxxxx"),
        ("iccid_prefixes", "8949012345678901234"),
    ):
        profile = {
            "schema_version": 1,
            "display_name": "Subscriber prefix",
            "match": {"mccmnc": ["00196"], key: [value]},
            "capabilities": {},
        }
        profile["profile_id"] = validate_public_carrier_data.canonical_profile_id(
            profile["match"]
        )
        try:
            validate_public_carrier_data.validate_profile_object(
                root / "match-full-identity.json", profile
            )
        except validate_public_carrier_data.ValidationError:
            pass
        else:
            raise AssertionError(f"match.{key} {value!r} should fail")


def check_provenance_and_lookup(carriers_dir: Path, generated_dir: Path) -> None:
    """apns-conf.xml and carrier-config-list.xml start with a provenance
    comment: licence, the digest of their inputs, and the freshness window,
    the same as metadata.json. The digest is deterministic and moves with any
    input. lookup.json repeats each profile's newest_entry month from the
    evidence index, and the validator checks both."""
    evidence_path = generated_dir / "evidence-index.json"
    metadata_path = generated_dir / "android" / "metadata.json"
    apns_path = generated_dir / "android" / "apns-conf.xml"
    config_path = generated_dir / "android" / "carrier-config-list.xml"
    lookup_path = generated_dir / "android" / "lookup.json"
    index_path = generated_dir / "index.json"
    original_evidence = evidence_path.read_text(encoding="utf-8")
    evidence = json.loads(original_evidence)
    dated_id = evidence["profiles"][0]["profile_id"]
    evidence["profiles"][0]["newest_entry"] = "2019-03"
    evidence["checks_through"] = "2026-07-10"
    evidence["stale_after"] = "2027-01-06"
    index = load_json(index_path)
    original_index = index_path.read_text(encoding="utf-8")

    def regenerate() -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            result = generate_android_outputs.main(
                ["generate_android_outputs.py", str(carriers_dir), str(generated_dir)]
            )
        assert_true(result == 0, "generator returned a non-zero status")

    def validate() -> None:
        validate_public_carrier_data.main(
            ["validate_public_carrier_data.py", str(carriers_dir), str(index_path)]
        )

    def expect_failure(message: str, reason: str) -> None:
        try:
            validate()
        except validate_public_carrier_data.ValidationError as exc:
            assert_true(reason in str(exc), f"{message}: unexpected error {exc}")
            return
        raise AssertionError(message)

    real_today = validate_public_carrier_data.utc_today
    validate_public_carrier_data.utc_today = lambda: date(2026, 10, 4)
    try:
        write_profile(evidence_path, evidence)
        write_profile(index_path, {**index, "checks_through": "2026-07-10", "stale_after": "2027-01-06"})
        regenerate()
        metadata = load_json(metadata_path)
        digest = metadata["data_digest"]
        assert_true(
            re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None,
            f"metadata names the data digest: {digest}",
        )
        for path, what in ((apns_path, "Android APN list"), (config_path, "Android CarrierConfig list")):
            lines = path.read_text(encoding="utf-8").split("\n")
            assert_true(
                lines[:3] == ['<?xml version="1.0" encoding="utf-8"?>', "<!--", lines[2]]
                and lines[2].startswith(f"    {what}")
                and "    SPDX-License-Identifier: CC0-1.0" in lines
                and f"    data_digest: {digest}" in lines
                and "    checks_through: 2026-07-10" in lines
                and "    stale_after: 2027-01-06" in lines,
                f"{path.name} starts with the provenance comment: {lines[:12]}",
            )
        root = ET.parse(apns_path).getroot()
        assert_true(root.tag == "apns" and root.attrib == {"version": "8"}, "the comment leaves the APN root alone")
        lookup = {item["profile_id"]: item for item in load_json(lookup_path)["profiles"]}
        assert_true(lookup[dated_id]["newest_entry"] == "2019-03", "lookup copies newest_entry")
        assert_true(
            all("newest_entry" not in item for key, item in lookup.items() if key != dated_id),
            "lookup has no newest_entry where the evidence index has none",
        )
        validate()

        before = apns_path.read_bytes()
        regenerate()
        assert_true(apns_path.read_bytes() == before, "the generated files are deterministic")
        profile_file = sorted(carriers_dir.rglob("*.json"))[0]
        original_profile = profile_file.read_text(encoding="utf-8")
        profile_file.write_text(original_profile.replace("}", "}", 1) + "\n", encoding="utf-8")
        regenerate()
        assert_true(
            load_json(metadata_path)["data_digest"] != digest,
            "a changed profile file changes the data digest",
        )
        profile_file.write_text(original_profile, encoding="utf-8")
        regenerate()
        assert_true(load_json(metadata_path)["data_digest"] == digest, "the digest comes back")

        apns_text = apns_path.read_text(encoding="utf-8")
        apns_path.write_text(apns_text.replace(digest, "sha256:" + "0" * 64), encoding="utf-8")
        expect_failure("a header digest that differs from metadata passed", "provenance comment")
        apns_path.write_text(apns_text.replace("    stale_after: 2027-01-06\n", ""), encoding="utf-8")
        expect_failure("a header without stale_after passed", "provenance comment")
        apns_path.write_text(apns_text.replace("SPDX-License-Identifier: CC0-1.0", "SPDX-License-Identifier: MIT"), encoding="utf-8")
        expect_failure("a header with another licence passed", "CC0-1.0")
        apns_path.write_text(apns_text, encoding="utf-8")

        lookup_text = lookup_path.read_text(encoding="utf-8")
        lookup_path.write_text(lookup_text.replace('"newest_entry": "2019-03"', '"newest_entry": "2020-03"'), encoding="utf-8")
        expect_failure("a lookup newest_entry that differs from the evidence index passed", "newest_entry")
        lookup_path.write_text(lookup_text.replace('"newest_entry": "2019-03"', '"newest_entry": "2019-3"'), encoding="utf-8")
        expect_failure("a malformed lookup newest_entry passed", "newest_entry")
        lookup_path.write_text(lookup_text, encoding="utf-8")
        validate()

        metadata_text = metadata_path.read_text(encoding="utf-8")
        metadata = json.loads(metadata_text)
        assert_true(
            metadata["omissions"]["ia_types_left_out_not_vendor_current"] == 0,
            "metadata counts the rows that lost their attach type",
        )
        metadata["omissions"]["ia_types_left_out_not_vendor_current"] = -1
        write_profile(metadata_path, metadata)
        expect_failure("a negative count of rows without their attach type passed", "attach type")
        del metadata["omissions"]["ia_types_left_out_not_vendor_current"]
        write_profile(metadata_path, metadata)
        expect_failure("metadata without the attach type count passed", "omission fields")
        metadata_path.write_text(metadata_text, encoding="utf-8")
        validate()
    finally:
        validate_public_carrier_data.utc_today = real_today
        evidence_path.write_text(original_evidence, encoding="utf-8")
        index_path.write_text(original_index, encoding="utf-8")
        regenerate()


def check_no_country_export() -> None:
    """The generator writes one APN file, apns-conf.xml, and nothing under
    generated/android/apns/; the validator refuses a per-country file there.
    The per-country export was removed on 2026-10-04: nothing read it, it
    repeated every row, and LineageOS's format.py re-sorts such files."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        carriers_dir = root / "carriers"
        generated_dir = root / "generated"
        write_carrier_profile(
            carriers_dir / "open",
            {
                "schema_version": 1,
                "display_name": "Example",
                "match": {"mccmnc": ["26202"]},
                "capabilities": {},
                "android_apns": [{"name": "Web", "apn": "web.example", "types": ["default"]}],
            },
        )
        result = generate_android_outputs.main(
            ["generate_android_outputs.py", str(carriers_dir), str(generated_dir)]
        )
        assert_true(result == 0, "generator returned a non-zero status")
        assert_true(
            not (generated_dir / "android" / "apns").exists(),
            "the generator must not write per-country APN files",
        )
        assert_true(
            not hasattr(generate_android_outputs, "write_country_apns")
            and not hasattr(lineageos_apns, "country_files"),
            "the per-country export code is gone",
        )
        for name in ("index.json", "evidence-index.json"):
            (generated_dir / name).write_text("{}\n", encoding="utf-8")
        validate_public_carrier_data.validate_generated_files(generated_dir)
        stray = generated_dir / "android" / "apns" / "DE.xml"
        stray.parent.mkdir(parents=True)
        stray.write_text('<?xml version="1.0" encoding="utf-8"?>\n<apns version="8">\n</apns>\n', encoding="utf-8")
        try:
            validate_public_carrier_data.validate_generated_files(generated_dir)
        except validate_public_carrier_data.ValidationError as exc:
            assert_true("android/apns/DE.xml" in str(exc), f"unexpected error {exc}")
        else:
            raise AssertionError("a per-country APN file in generated/android/apns/ must be rejected")


def check_lineageos_schema_rules() -> None:
    """fits_lineageos_schema agrees with xmllint and LineageOS's apns-conf.xsd."""
    # Expected outcomes from xmllint --schema with LineageOS's apns-conf.xsd.
    uri_cases = {
        "http://mms.example/servlets/mms": True,
        "mms.example": True,
        "10.81.6.11": True,
        "mmsc.example:8002": True,
        "http://[::1]:80/": True,
        "http://user:pass@host:80/": True,
        "http://h/%e4": True,
        "a b": True,
        "208.254.124.11:8514": False,
        "10.0.0.1:80/mms": False,
        "a_b:c": False,
        "%zz": False,
        "%4": False,
        "http://a#b#c": False,
        "http://host:port": False,
        "http://h:/x": False,
        "http://h:80:90/": False,
        "http://[::1]:x": False,
        "x://a@b@c": False,
    }
    for value, accepted in uri_cases.items():
        assert_true(
            lineageos_apns.schema_uri_ok(value) == accepted,
            f"anyURI check of {value!r} must be {accepted}",
        )
    base = {"mcc": "262", "mnc": "01", "apn": "web", "type": "default"}
    for extra, accepted in (
        ({"authtype": 3}, True),
        ({"authtype": -1}, False),
        ({"authtype": "x"}, False),
        ({"skip_464xlat": -1}, False),
        ({"bearer_bitmask": "14|20"}, True),
        ({"network_type_bitmask": "1,2"}, False),
        ({"infrastructure_bitmask": "cellular|satellite"}, True),
        ({"infrastructure_bitmask": "1"}, False),
        ({"proxy": "10.0.0.1:80"}, False),
    ):
        assert_true(
            lineageos_apns.fits_lineageos_schema({**base, **extra}) == accepted,
            f"LineageOS schema check of {extra} must be {accepted}",
        )


def check_apn_value_rules(root: Path) -> None:
    """The validator refuses values a phone cannot use: control characters or
    padding in strings, an MMSC without a scheme, and an mms row whose APN has
    no MMSC in the profile."""

    def profile(*apns: dict, spn: str = "Example", display_name: str = "Example") -> dict:
        value = {
            "schema_version": 1,
            "display_name": display_name,
            "match": {"mccmnc": ["26202"], "spn": [spn]},
            "capabilities": {},
            "android_apns": list(apns),
        }
        value["profile_id"] = validate_public_carrier_data.canonical_profile_id(value["match"])
        return value

    def row(apn: str = "internet", types: tuple[str, ...] = ("default",), **extra: object) -> dict:
        return {"name": "Internet", "apn": apn, "types": sorted(types), **extra}

    def accepted(value: dict) -> None:
        validate_public_carrier_data.validate_profile_object(root / "value.json", value)

    def rejected(value: dict, message: str) -> None:
        try:
            accepted(value)
        except validate_public_carrier_data.ValidationError:
            return
        raise AssertionError(message)

    accepted(profile(row(), row("mms", ("mms",), mmsc="http://10.0.0.1:8002/mms")))
    accepted(
        profile(
            row("internet", ("default", "mms"), protocol="IPV4V6"),
            row("internet", ("mms",), mmsc="https://mms.example"),
        )
    )
    rejected(profile(row(), spn="C Spire\r"), "a carriage return in an SPN")
    rejected(profile(row(), display_name=" Example"), "a padded display name")
    rejected(profile(row(mvno_type="spn", mvno_match_data="C Spire\r")), "a carriage return in mvno_match_data")
    rejected(profile(row("internet\t")), "a tab in an APN")
    for mmsc in ("208.254.124.11:8514", "mms.iliad.it", "http:/mms.example", "http:// 10.0.0.1", "null"):
        rejected(profile(row("mms", ("mms",), mmsc=mmsc)), f"the MMSC {mmsc!r}")
    rejected(profile(row("internet", ("default", "mms"))), "an mms row without an MMSC")
    rejected(profile(row("internet", ("*",))), "a wildcard row serves mms and needs an MMSC")
    rejected(
        profile(
            row("internet", ("default", "mms")),
            row("internet", ("mms",), mmsc="http://mms.example", mvno_type="spn", mvno_match_data="Other"),
        ),
        "the MMSC must come from a row of the same MVNO selector",
    )


def check_apn_ranking() -> None:
    """Android tries a scope's rows in file order, so each scope is ordered by
    the evidence behind its rows, rows Android treats as one are collapsed,
    rows LineageOS's schema rejects are left out, and control characters
    survive the XML round trip."""

    def apn(value: str, types: tuple[str, ...] = ("default",), **extra: object) -> dict:
        return {"name": str(extra.pop("name", value)), "apn": value, "types": sorted(types), **extra}

    def profile(profile_id: str, match: dict, *rows: dict) -> dict:
        return {
            "profile_id": profile_id,
            "display_name": profile_id,
            "match": match,
            "android_apns": list(rows),
        }

    def evidence_index(*entries: tuple[dict, list[tuple[str, ...]]]) -> dict:
        """Each entry is a profile and the sources behind each of its rows,
        written the way the sanitizer writes them: fact_sources only for facts
        that rest on fewer sources than the profile."""
        records = []
        for item, row_sources in entries:
            everything = sorted({source for sources in row_sources for source in sources})
            facts = [
                {
                    "section": "android_apns",
                    "key": generate_android_outputs.apn_fact_key(row, apn_type),
                    "sources": sorted(sources),
                }
                for row, sources in zip(item["android_apns"], row_sources, strict=True)
                for apn_type in row["types"]
                if sorted(sources) != everything
            ]
            records.append(
                {"profile_id": item["profile_id"], "sources": everything, "fact_sources": facts}
            )
        return {"profiles": records}

    fact = {"name": "label", "apn": "internet", "types": ["default", "mms"], "mmsc": "http://m"}
    expected_key = "sha256:" + hashlib.sha256(
        b'{"apn":"internet","mmsc":"http://m","types":["mms"]}'
    ).hexdigest()[:16]
    assert_true(
        generate_android_outputs.apn_fact_key(fact, "mms") == expected_key,
        "an APN fact key is the evidence index key: the row without its label, one type",
    )

    roshan = profile(
        "open.41220.a",
        {"mccmnc": ["41220"]},
        apn("default", ("default", "supl")),
        apn("internet", ("default", "supl"), user="gprs"),
    )
    telekom = profile(
        "open.26201.a",
        {"mccmnc": ["26201"]},
        apn("internet.t-d1.de", ("default", "supl")),
        apn("internet.v6.telekom", ("default", "supl"), protocol="IPV4V6"),
        apn("internet.v6.telekom", ("default", "supl"), protocol="IP"),
    )
    orange = profile(
        "open.20801.a",
        {"mccmnc": ["20801"]},
        apn("aaa.example"),
        apn("zzz.example"),
    )
    lead = profile(
        "open.23410.a",
        {"mccmnc": ["23410"]},
        apn("ims", ("ims",)),
        apn("mms.example", ("mms",), mmsc="http://mms.example"),
        apn("web.example", ("default", "mms"), mmsc="http://mms.example"),
    )
    twins = profile(
        "open.24001.a",
        {"mccmnc": ["24001"]},
        apn("net.example", ("default",), name="First"),
        apn("net.example", ("default", "supl"), name="Second", carrier_enabled=True, protocol="IP"),
        apn("net.example", ("default",), protocol="IPV6"),
    )
    host = profile(
        "open.26202.a",
        {"mccmnc": ["26202"]},
        apn("lidl.example", mvno_type="spn", mvno_match_data="LIDL"),
    )
    mvno = profile("open.26202.b", {"mccmnc": ["26202"], "spn": ["lidl"]}, apn("web.example"))
    schema = profile(
        "open.310100.a",
        {"mccmnc": ["310100"]},
        apn("plateau", ("mms",), mmsc="208.254.124.11:8514"),
        apn("open.example", authtype=-1),
    )
    control = profile(
        "open.20404.a",
        {"mccmnc": ["20404"]},
        apn("cspire.example", mvno_type="spn", mvno_match_data="C Spire\r"),
    )
    profiles = [roshan, telekom, orange, lead, twins, host, mvno, schema, control]
    google = "google_carriersettings"
    pixel = "google_pixel_vendor_carriersettings"
    index = evidence_index(
        (roshan, [(google, pixel, "fairphone_official_source"), ("lineageos", "apple_carrier_bundles")]),
        (
            telekom,
            [
                ("lineageos", "sony_open_devices_aosp", "fairphone_official_source",
                 "mobile_broadband_provider_info"),
                ("lineageos", google, "samsung_omc"),
                ("samsung_omc",),
            ],
        ),
        (orange, [("mobile_broadband_provider_info", "aosp"), ("apple_carrier_bundles", "mobile_broadband_provider_info")]),
        (lead, [("apple_carrier_bundles", google, "samsung_omc", "lineageos"), ("apple_carrier_bundles",), ("lineageos",)]),
        (twins, [("lineageos",), ("apple_carrier_bundles",), ("mobile_broadband_provider_info",)]),
        (host, [("lineageos",)]),
        (mvno, [("apple_carrier_bundles", google, "samsung_omc")]),
        (schema, [("lineageos",), ("lineageos",)]),
        (control, [(google,)]),
    )
    with tempfile.TemporaryDirectory() as tmp:
        evidence_path = Path(tmp) / "evidence-index.json"
        evidence_path.write_text(json.dumps(index), encoding="utf-8")
        evidence = generate_android_outputs.load_apn_evidence(evidence_path)
        assert_true(
            generate_android_outputs.load_apn_evidence(Path(tmp) / "missing.json") is None,
            "a missing evidence index gives no evidence",
        )
        rows = generate_android_outputs.apn_xml_rows(profiles, evidence)

        def scope_apns(mccmnc: str, **selector: str) -> list[tuple[str, str]]:
            return [
                (record["apn"], record.get("protocol", ""))
                for record in rows.records
                if record.get("mcc", "") + record.get("mnc", "") == mccmnc
                and all(
                    str(record.get(key, "")).casefold() == value.casefold()
                    for key, value in selector.items()
                )
            ]

        assert_true(
            scope_apns("41220")[0][0] == "internet",
            "a real APN comes before the placeholder 'default' at equal backing",
        )
        assert_true(
            scope_apns("26201")
            == [("internet.v6.telekom", "IPV4V6"), ("internet.v6.telekom", "IP"), ("internet.t-d1.de", "")],
            "the APN more source families back comes first, the LineageOS, Sony and "
            "Fairphone copies of one list count once, and within one APN the row "
            f"more families back leads: {scope_apns('26201')}",
        )
        assert_true(
            scope_apns("20801")[0][0] == "zzz.example",
            "at equal family counts an APN a primary APN source gives comes first",
        )
        assert_true(
            [value for value, _ in scope_apns("23410")] == ["web.example", "mms.example", "ims"],
            "rows that serve the internet lead, then MMS rows, then IMS rows",
        )
        net_rows = [record for record in rows.records if record["apn"] == "net.example"]
        assert_true(
            len(net_rows) == 2
            and net_rows[0]["type"] == "default,supl"
            and net_rows[0]["carrier"] == "First"
            and net_rows[1]["protocol"] == "IPV6",
            "rows differing only in label, a covered type set, or an explicit "
            f"Android default collapse; another protocol stays a variant: {net_rows}",
        )
        assert_true(
            [value for value, _ in scope_apns("26202", mvno_type="spn", mvno_match_data="lidl")]
            == ["web.example", "lidl.example"],
            "rows from two profiles that one SIM sees are ranked together",
        )
        assert_true(
            rows.schema_rejected == 1
            and "plateau" not in {record["apn"] for record in rows.records},
            "a row LineageOS's apns-conf.xsd rejects is left out of every APN file",
        )
        open_row = next(record for record in rows.records if record["apn"] == "open.example")
        assert_true(
            "authtype" not in open_row,
            "authtype -1 is TelephonyProvider's default and is left out of the row",
        )

        android_dir = Path(tmp) / "android"
        generate_android_outputs.write_apns(android_dir / "apns-conf.xml", profiles, 8, evidence)
        text = (android_dir / "apns-conf.xml").read_text(encoding="utf-8")
        assert_true("C Spire&#13;" in text, "a carriage return is written as a character reference")
        parsed = {
            element.attrib["apn"]: element.attrib
            for element in ET.parse(android_dir / "apns-conf.xml").getroot()
        }
        assert_true(
            parsed["cspire.example"]["mvno_match_data"] == "C Spire\r",
            "an XML parser reads back the exact value",
        )
        assert_true(
            all("_support" not in attributes for attributes in parsed.values()),
            "the ranking evidence is never written",
        )
        if shutil.which("xmllint"):
            xsd = Path(__file__).resolve().parent / "lineageos" / "apns-conf.xsd"
            result = subprocess.run(
                ["xmllint", "--noout", "--schema", str(xsd), str(android_dir / "apns-conf.xml")],
                capture_output=True,
                text=True,
                check=False,
            )
            assert_true(result.returncode == 0, f"LineageOS's schema accepts the output: {result.stderr}")

        try:
            generate_android_outputs.attr("apn", "bad\x01value")
        except ValueError:
            pass
        else:
            raise AssertionError("a control character XML cannot carry must fail")

        plain = generate_android_outputs.apn_xml_records(profiles)
        plain_scope = [record["apn"] for record in plain if record.get("mcc") == "412"]
        assert_true(
            plain_scope == ["internet", "default"],
            "without evidence the placeholder still comes last",
        )
        assert_true(
            [record["apn"] for record in plain if record.get("mnc") == "01" and record.get("mcc") == "262"][0]
            == "internet.t-d1.de",
            "without evidence rows keep the fallback order, by APN",
        )


def check_current_vendor_attach() -> None:
    """A value a current vendor (Google CarrierSettings, Samsung) gives comes
    first in its lead type, and apns-conf.xml takes the attach type off a row
    whose APN no current vendor gives, when a current vendor gives the
    network's attach or internet APN. No row is removed."""

    def apn(value: str, types: tuple[str, ...] = ("default",), **extra: object) -> dict:
        return {"name": str(extra.pop("name", value)), "apn": value, "types": list(types), **extra}

    def profile(profile_id: str, mccmnc: str, *rows: dict) -> dict:
        return {
            "profile_id": profile_id,
            "display_name": profile_id,
            "match": {"mccmnc": [mccmnc]},
            "android_apns": list(rows),
        }

    google = "google_carriersettings"
    # 26203: Fairphone's frozen E-Plus row is the only one typed "ia"; Google's
    # current file gives "internet".
    eplus = profile(
        "open.26203.a",
        "26203",
        apn("internet.eplus.de", ("default", "ia", "supl"), user="eplus", password="internet"),
        apn("internet", ("default",)),
    )
    # 310410: old copies agree on "broadband"; Google's current file says
    # "nxtgenphone". More families give the old value.
    att = profile(
        "open.310410.a",
        "310410",
        apn("broadband", ("default", "mms"), mmsc="http://mmsc.example"),
        apn("nxtgenphone", ("default", "mms"), mmsc="http://mmsc.example", protocol="IPV4V6"),
    )
    # 311480: an IMS row typed "ims,ia" keeps "ia" when a current vendor gives
    # that APN for "ims".
    verizon = profile(
        "open.311480.a",
        "311480",
        apn("vzwinternet", ("default",)),
        apn("vzwims", ("ia", "ims")),
        apn("vzwims", ("ims",), protocol="IPV6"),
    )
    # 23415: a row whose only type is "ia" keeps it.
    attach_only = profile(
        "open.23415.a",
        "23415",
        apn("internet.example", ("default",)),
        apn("attach.example", ("ia",)),
    )
    # 20408: no current vendor gives anything here, so nothing changes.
    untouched = profile(
        "open.20408.a",
        "20408",
        apn("old.example", ("default", "ia", "supl")),
        apn("web.example", ("default",)),
    )
    profiles = [eplus, att, verizon, attach_only, untouched]
    row_sources = {
        "open.26203.a": [("fairphone_official_source",), (google,)],
        "open.310410.a": [
            ("lineageos", "apple_carrier_bundles", "mobile_broadband_provider_info"),
            (google,),
        ],
        "open.311480.a": [(google,), ("lineageos",), (google,)],
        "open.23415.a": [("samsung_omc",), ("lineageos",)],
        "open.20408.a": [("lineageos",), ("apple_carrier_bundles",)],
    }
    # 24007 (Tele2 Sweden, SPN Tele2comviq): a Samsung build from 2017 gives
    # "4g.tele2.se", a current Samsung build "internet.tele2.se". The evidence
    # index names samsung_omc in the old fact's old_build_sources, so only the
    # current build's value counts as a current vendor's.
    tele2 = profile(
        "open.24007.a",
        "24007",
        apn("4g.tele2.se", ("default", "ia")),
        apn("internet.tele2.se", ("default",)),
    )
    # 73003 (Claro Chile): one value, two variants. A current Samsung build
    # gives IPV4V6; an old build and two old copies give IP. The current
    # build's variant leads although more families back the other.
    claro = profile(
        "open.73003.a",
        "73003",
        apn("bam.clarochile.cl", ("default",), protocol="IP"),
        apn("bam.clarochile.cl", ("default",), protocol="IPV4V6"),
    )
    profiles += [tele2, claro]
    row_sources["open.24007.a"] = [("samsung_omc", "lineageos", "apple_carrier_bundles"), ("samsung_omc",)]
    row_sources["open.73003.a"] = [("samsung_omc", "lineageos", "apple_carrier_bundles"), ("samsung_omc",)]
    old_builds = {
        "open.24007.a": {0: ["samsung_omc"]},
        "open.73003.a": {0: ["samsung_omc"]},
    }
    records = []
    for item in profiles:
        sources = row_sources[item["profile_id"]]
        everything = sorted({source for group in sources for source in group})
        facts = []
        for row_index, (row, group) in enumerate(zip(item["android_apns"], sources, strict=True)):
            old = old_builds.get(item["profile_id"], {}).get(row_index)
            for apn_type in row["types"]:
                if sorted(group) == everything and not old:
                    continue
                fact = {
                    "section": "android_apns",
                    "key": generate_android_outputs.apn_fact_key(row, apn_type),
                    "sources": sorted(group),
                }
                if old:
                    fact["old_build_sources"] = old
                facts.append(fact)
        records.append({"profile_id": item["profile_id"], "sources": everything, "fact_sources": facts})
    with tempfile.TemporaryDirectory() as tmp:
        evidence_path = Path(tmp) / "evidence-index.json"
        evidence_path.write_text(json.dumps({"profiles": records}), encoding="utf-8")
        evidence = generate_android_outputs.load_apn_evidence(evidence_path)
        rows = generate_android_outputs.apn_xml_rows(profiles, evidence)
        plain = generate_android_outputs.apn_xml_rows(profiles)

        def scope(mccmnc: str, result: object = rows) -> list[tuple[str, str]]:
            return [
                (record["apn"], record["type"])
                for record in result.records
                if record.get("mcc", "") + record.get("mnc", "") == mccmnc
            ]

        assert_true(
            scope("26203") == [("internet", "default"), ("internet.eplus.de", "default,supl")],
            "the current vendor's APN comes first and the frozen E-Plus row stays "
            f"without the attach type: {scope('26203')}",
        )
        assert_true(
            [value for value, _ in scope("310410")] == ["nxtgenphone", "broadband"],
            "a value a current vendor gives beats one more old copies give: "
            f"{scope('310410')}",
        )
        assert_true(
            ("vzwims", "ia,ims") in scope("311480"),
            f"an IMS attach row keeps ia when a current vendor gives its APN: {scope('311480')}",
        )
        assert_true(
            ("attach.example", "ia") in scope("23415"),
            f"a row whose only type is ia keeps it: {scope('23415')}",
        )
        assert_true(
            scope("20408") == scope("20408", plain)
            and ("old.example", "default,ia,supl") in scope("20408"),
            f"a scope no current vendor covers is unchanged: {scope('20408')}",
        )
        assert_true(
            scope("24007") == [("internet.tele2.se", "default"), ("4g.tele2.se", "default")],
            "a value only an old Samsung build gives is not a current vendor's: it ranks "
            f"after the current build's value and loses ia: {scope('24007')}",
        )
        claro_rows = [
            record.get("protocol")
            for record in rows.records
            if record.get("mcc", "") + record.get("mnc", "") == "73003"
        ]
        assert_true(
            claro_rows == ["IPV4V6", "IP"],
            f"among the variants of one value the current build's comes first: {claro_rows}",
        )
        assert_true(
            len(rows.records) == len(plain.records) and rows.ia_left_out == 2,
            f"no row is removed and two rows lose ia: {len(rows.records)}, {rows.ia_left_out}",
        )
        assert_true(
            plain.ia_left_out == 0,
            "without evidence no row loses its attach type",
        )
        eplus_row = next(record for record in rows.records if record["apn"] == "internet.eplus.de")
        assert_true(eplus_row.get("_ia_left_out") is True, "the changed row is marked for --explain")

        android_dir = Path(tmp) / "android"
        generate_android_outputs.write_apns(android_dir / "apns-conf.xml", profiles, 8, evidence)
        written = ET.parse(android_dir / "apns-conf.xml").getroot()
        assert_true(
            all(
                not any(key.startswith("_") for key in element.attrib)
                for element in written
            ),
            "the attach mark is never written",
        )


def check_shared_file_and_malformed_values() -> None:
    """A Google value from its shared "others" file that no maintained
    per-carrier source confirms (shared_file_sources) is not a current
    vendor's, and a malformed APN value ranks with the placeholders."""

    def apn(value: str, types: tuple[str, ...] = ("default",), **extra: object) -> dict:
        return {"name": str(extra.pop("name", value)), "apn": value, "types": list(types), **extra}

    def profile(profile_id: str, mccmnc: str, *rows: dict) -> dict:
        return {
            "profile_id": profile_id,
            "display_name": profile_id,
            "match": {"mccmnc": [mccmnc]},
            "android_apns": list(rows),
        }

    google = "google_carriersettings"
    # 64004 (Vodacom Tanzania), plain scope: Google's shared file gives "Wap"
    # with a WAP proxy; the open lists give "internet". Samsung's current
    # builds give "internet" only under SPN Vodacom, another scope.
    vodacom = profile(
        "open.64004.a",
        "64004",
        apn("Wap", ("default", "ia", "supl"), proxy="10.154.0.8", port=9401),
        apn("internet", ("default", "ia", "supl")),
    )
    # 41401 (MPT): the shared file gives "mptnet", and Samsung confirms it
    # under an SPN, so the sanitizer does not name the fact: it stays current.
    mpt = profile(
        "open.41401.a",
        "41401",
        apn("mptnet", ("default",)),
        apn("mpt.old", ("default",)),
    )
    # 62006 (Airtel Ghana), MMS: Google's shared file gives "airtelmms.com",
    # a Google per-carrier file the malformed "mms/airtel mms", and the open
    # lists "mms".
    airtel = profile(
        "open.62006.a",
        "62006",
        apn("airtelmms.com", ("mms",)),
        apn("mms/airtel mms", ("mms",)),
        apn("mms", ("mms",)),
    )
    # 20408: no shared-file fact; nothing changes.
    untouched = profile(
        "open.20408.a",
        "20408",
        apn("web.example", ("default",)),
        apn("old.example", ("default",)),
    )
    profiles = [vodacom, mpt, airtel, untouched]
    row_sources = {
        "open.64004.a": [(google,), ("lineageos", "mobile_broadband_provider_info")],
        "open.41401.a": [(google,), ("lineageos", "mobile_broadband_provider_info")],
        "open.62006.a": [(google,), (google,), ("lineageos", "mobile_broadband_provider_info")],
        "open.20408.a": [(google,), ("lineageos", "mobile_broadband_provider_info")],
    }
    shared_rows = {"open.64004.a": {0}, "open.62006.a": {0}}

    def evidence_for(with_shared: bool) -> dict:
        records = []
        for item in profiles:
            sources = row_sources[item["profile_id"]]
            everything = sorted({source for group in sources for source in group})
            facts = []
            for row_index, (row, group) in enumerate(zip(item["android_apns"], sources, strict=True)):
                shared = with_shared and row_index in shared_rows.get(item["profile_id"], set())
                for apn_type in row["types"]:
                    if sorted(group) == everything and not shared:
                        continue
                    fact = {
                        "section": "android_apns",
                        "key": generate_android_outputs.apn_fact_key(row, apn_type),
                        "sources": sorted(group),
                    }
                    if shared:
                        fact["shared_file_sources"] = [google]
                    facts.append(fact)
            records.append({"profile_id": item["profile_id"], "sources": everything, "fact_sources": sorted(facts, key=lambda fact: fact["key"])})
        return {"profiles": records}

    with tempfile.TemporaryDirectory() as tmp:
        results = {}
        for name, with_shared in (("shared", True), ("plain", False)):
            evidence_path = Path(tmp) / f"evidence-{name}.json"
            evidence_path.write_text(json.dumps(evidence_for(with_shared)), encoding="utf-8")
            results[name] = generate_android_outputs.apn_xml_rows(
                profiles, generate_android_outputs.load_apn_evidence(evidence_path)
            )
        rows, before = results["shared"], results["plain"]

        def scope(mccmnc: str, result: object = rows) -> list[tuple[str, str]]:
            return [
                (record["apn"], record["type"])
                for record in result.records
                if record.get("mcc", "") + record.get("mnc", "") == mccmnc
            ]

        assert_true(
            [value for value, _ in scope("64004", before)] == ["Wap", "internet"],
            f"without the shared-file mark Google's Wap row leads: {scope('64004', before)}",
        )
        first_ia = next(value for value, types in scope("64004") if "ia" in types.split(","))
        assert_true(
            [value for value, _ in scope("64004")] == ["internet", "Wap"] and first_ia == "internet",
            "an unconfirmed shared-file value is not a current vendor's: the WAP-proxy "
            f"row no longer leads or attaches: {scope('64004')}",
        )
        assert_true(
            [value for value, _ in scope("41401")] == ["mptnet", "mpt.old"],
            f"a shared-file value a maintained source confirms stays current: {scope('41401')}",
        )
        airtel_order = [value for value, _ in scope("62006")]
        assert_true(
            airtel_order.index("mms") < airtel_order.index("mms/airtel mms")
            and airtel_order[-1] == "mms/airtel mms",
            f"a malformed APN value never comes before a valid one: {airtel_order}",
        )
        assert_true(
            scope("20408") == scope("20408", before),
            f"a scope with no shared-file fact is unchanged: {scope('20408')}",
        )
        assert_true(
            len(rows.records) == len(before.records),
            "the shared-file rule removes no row",
        )
        wap = next(record for record in rows.records if record["apn"] == "Wap")
        assert_true(
            wap.get("_shared") == {"default": frozenset({google}), "ia": frozenset({google}), "supl": frozenset({google})},
            f"the row carries its shared-file sources for --explain: {wap.get('_shared')}",
        )
        wap_rank = generate_android_outputs.scope_row_ranks(
            [record for record in rows.records if record.get("mnc") == "04" and record.get("mcc") == "640"]
        )
        assert_true(
            any(rank.value_shared == {google} and not rank.value_current for rank in wap_rank),
            f"the rank names the unconfirmed shared-file source: {wap_rank}",
        )
        android_dir = Path(tmp) / "android"
        evidence = generate_android_outputs.load_apn_evidence(Path(tmp) / "evidence-shared.json")
        generate_android_outputs.write_apns(android_dir / "apns-conf.xml", profiles, 8, evidence)
        written = ET.parse(android_dir / "apns-conf.xml").getroot()
        assert_true(
            all(not any(key.startswith("_") for key in element.attrib) for element in written),
            "the shared-file mark is never written",
        )

    for value, expected in (
        ("default", True),
        ("DEFAULT", True),
        ("internet", False),
        ("ims.sos", False),
        ("internet_1", False),
        ("web-gprs.example", False),
        ("mms/airtel mms", True),
        ("http://mms.pepephone.com", True),
        ("Orange MMS", True),
        ("#777", True),
        ("", True),
    ):
        assert_true(
            generate_android_outputs.placeholder_apn(value) is expected,
            f"placeholder_apn({value!r}) should be {expected}",
        )


def check_proxy_free_first() -> None:
    """Among the rows that lead with "default", a row without an HTTP proxy
    comes before a row with one, right after the current-vendor key. An MMS
    proxy never counts, rows that lead with another type never move, and no
    row is removed or retyped."""

    def apn(value: str, types: tuple[str, ...] = ("default",), **extra: object) -> dict:
        return {"name": str(extra.pop("name", value)), "apn": value, "types": list(types), **extra}

    def profile(profile_id: str, mccmnc: str, *rows: dict) -> dict:
        return {
            "profile_id": profile_id,
            "display_name": profile_id,
            "match": {"mccmnc": [mccmnc]},
            "android_apns": list(rows),
        }

    google = "google_carriersettings"
    pixel = "google_pixel_vendor_carriersettings"
    mbpi = "mobile_broadband_provider_info"
    # 62006 (Airtel Ghana): Google's shared file, its frozen Pixel copy and
    # Fairphone give "wap" with a WAP proxy, and it is the only row with
    # "ia"; Apple and MBPI give "internet". No current vendor gives either.
    airtel = profile(
        "open.62006.a",
        "62006",
        apn("wap", ("default", "ia", "supl"), proxy="10.93.85.88", port=9201),
        apn("internet", ("default", "supl")),
    )
    # 61002 (Orange Mali): Google's per-carrier file gives only "wap", with a
    # proxy; old copies give "internet".
    orange = profile(
        "open.61002.a",
        "61002",
        apn("wap", ("default", "supl"), proxy="10.109.4.35", port=8080, user="wap", password="wap"),
        apn("internet", ("default", "supl")),
    )
    # 40439 (BSNL): Google gives both, "bsnllive" with a WAP proxy, which
    # sorts first by name, and "bsnlnet".
    bsnl = profile(
        "open.40439.a",
        "40439",
        apn("bsnllive", ("default", "ia", "supl"), proxy="10.220.67.131", port=8080),
        apn("bsnlnet", ("default", "ia", "supl")),
    )
    # 60503: two variants of one value; more families give the proxied one.
    variants = profile(
        "open.60503.a",
        "60503",
        apn("internet.example", ("default", "supl"), proxy="10.3.2.99", port=8080),
        apn("internet.example", ("default", "supl"), name="bare"),
    )
    # 20408: MMS rows with a proxy or an MMS proxy keep their place, and so
    # does an internet row that carries only an MMS proxy.
    mms = profile(
        "open.20408.a",
        "20408",
        apn("web.example", ("default", "mms"), mmsc="http://mms.example", mmsproxy="10.0.0.1", mmsport=8080),
        apn("web2.example", ("default",)),
        apn("mms.example", ("mms",), mmsc="http://mms.example", proxy="10.0.0.2", port=8080),
        apn("mms2.example", ("mms",), mmsc="http://mms2.example"),
    )
    # 21910: every internet row carries a proxy; the families decide, as
    # before.
    all_proxied = profile(
        "open.21910.a",
        "21910",
        apn("wap.b", ("default",), proxy="10.0.0.3", port=8080),
        apn("wap.a", ("default",), proxy="10.0.0.4", port=8080),
    )
    profiles = [airtel, orange, bsnl, variants, mms, all_proxied]
    row_sources = {
        "open.62006.a": [(google, pixel, "fairphone_official_source"), ("apple_carrier_bundles", mbpi)],
        "open.61002.a": [(google, pixel, "lineageos"), ("lineageos", "apple_carrier_bundles", mbpi)],
        "open.40439.a": [(google, pixel), (google, pixel)],
        "open.60503.a": [("lineageos", mbpi), ("apple_carrier_bundles",)],
        "open.20408.a": [("lineageos", mbpi), ("apple_carrier_bundles",), ("lineageos", mbpi), ("apple_carrier_bundles",)],
        "open.21910.a": [("lineageos", mbpi), ("apple_carrier_bundles",)],
    }
    shared_rows = {"open.62006.a": {0}}
    records = []
    for item in profiles:
        sources = row_sources[item["profile_id"]]
        everything = sorted({source for group in sources for source in group})
        facts = []
        for row_index, (row, group) in enumerate(zip(item["android_apns"], sources, strict=True)):
            for apn_type in row["types"]:
                fact = {
                    "section": "android_apns",
                    "key": generate_android_outputs.apn_fact_key(row, apn_type),
                    "sources": sorted(group),
                }
                if row_index in shared_rows.get(item["profile_id"], set()):
                    fact["shared_file_sources"] = [google]
                facts.append(fact)
        records.append({"profile_id": item["profile_id"], "sources": everything, "fact_sources": sorted(facts, key=lambda fact: fact["key"])})

    with tempfile.TemporaryDirectory() as tmp:
        evidence_path = Path(tmp) / "evidence.json"
        evidence_path.write_text(json.dumps({"profiles": records}), encoding="utf-8")
        rows = generate_android_outputs.apn_xml_rows(
            profiles, generate_android_outputs.load_apn_evidence(evidence_path)
        )

        def scope(mccmnc: str) -> list[tuple[str, str, str]]:
            return [
                (record["apn"], record["type"], str(record.get("proxy", "")))
                for record in rows.records
                if record.get("mcc", "") + record.get("mnc", "") == mccmnc
            ]

        def first(mccmnc: str, apn_type: str) -> tuple[str, str, str]:
            return next(row for row in scope(mccmnc) if apn_type in row[1].split(","))

        assert_true(
            [row[0] for row in scope("62006")] == ["internet", "wap"],
            f"a proxy-free internet row comes before the shared file's WAP row: {scope('62006')}",
        )
        assert_true(
            first("62006", "ia")[0] == "wap",
            f"the attach row stays the only row with ia: {scope('62006')}",
        )
        assert_true(
            [row[0] for row in scope("61002")] == ["wap", "internet"],
            f"a current vendor's only internet value still leads with its proxy: {scope('61002')}",
        )
        assert_true(
            [row[0] for row in scope("40439")] == ["bsnlnet", "bsnllive"]
            and first("40439", "ia")[0] == "bsnlnet",
            f"of two current values the proxy-free one leads and attaches: {scope('40439')}",
        )
        assert_true(
            [row[2] for row in scope("60503")] == ["", "10.3.2.99"],
            f"the proxy-free variant of one value comes first: {scope('60503')}",
        )
        assert_true(
            [row[0] for row in scope("20408")] == ["web.example", "web2.example", "mms.example", "mms2.example"],
            f"an MMS proxy never counts and MMS rows never move: {scope('20408')}",
        )
        assert_true(
            [row[0] for row in scope("21910")] == ["wap.b", "wap.a"],
            f"a scope with no proxy-free internet row keeps its order: {scope('21910')}",
        )
        written = sorted((record["apn"], record["type"], str(record.get("proxy", ""))) for record in rows.records)
        given = sorted(
            (row["apn"], ",".join(sorted(row["types"])), str(row.get("proxy", "")))
            for item in profiles
            for row in item["android_apns"]
        )
        assert_true(
            written == given,
            f"no row is removed and no type set changes: {written} != {given}",
        )
        ranks = generate_android_outputs.scope_row_ranks(
            [record for record in rows.records if record.get("mcc") == "204"]
        )
        assert_true(
            [rank.proxied for rank in ranks] == [False, False, False, False],
            f"neither an MMS proxy nor a proxy on an MMS row makes a row proxied: {ranks}",
        )


def check_malformed_values_stay() -> None:
    """A malformed APN value is kept and ranks with the placeholders: a scope
    whose only MMS row or only internet row has one still writes it, and a
    malformed default row never comes before a valid one, however many
    sources give it (rule decisions of 2026-10-06, round 4, change 13)."""

    def profile(profile_id: str, mccmnc: str, *rows: dict) -> dict:
        return {
            "profile_id": profile_id,
            "display_name": profile_id,
            "match": {"mccmnc": [mccmnc]},
            "android_apns": list(rows),
        }

    profiles = [
        # 21404 SPN Pepephone shape: the only MMS row has a URL for an APN.
        profile(
            "open.21404.a",
            "21404",
            {"name": "Internet", "apn": "gprsmov.pepephone.com", "types": ["default"]},
            {"name": "MMS", "apn": "http://mms.pepephone.com", "types": ["mms"], "mmsc": "http://mms.pepephone.com/servlets/mms"},
        ),
        # 62125 shape: the only internet row is the CDMA dial string.
        profile(
            "open.62125.a",
            "62125",
            {"name": "Visafone", "apn": "#777", "types": ["default", "supl"]},
        ),
        # A malformed internet value more families give than the valid one.
        profile(
            "open.20408.a",
            "20408",
            {"name": "Web", "apn": "web example", "types": ["default"]},
            {"name": "Web", "apn": "web.example", "types": ["default"]},
        ),
    ]
    evidence = {
        "profiles": [
            {"profile_id": "open.21404.a", "sources": ["lineageos"], "fact_sources": []},
            {"profile_id": "open.62125.a", "sources": ["lineageos", "sony_open_devices_aosp"], "fact_sources": []},
            {
                "profile_id": "open.20408.a",
                "sources": ["apple_carrier_bundles", "lineageos", "mobile_broadband_provider_info"],
                "fact_sources": sorted(
                    [
                        {
                            "section": "android_apns",
                            "key": generate_android_outputs.apn_fact_key(profiles[2]["android_apns"][0], "default"),
                            "sources": ["apple_carrier_bundles", "lineageos", "mobile_broadband_provider_info"],
                        },
                        {
                            "section": "android_apns",
                            "key": generate_android_outputs.apn_fact_key(profiles[2]["android_apns"][1], "default"),
                            "sources": ["lineageos"],
                        },
                    ],
                    key=lambda fact: fact["key"],
                ),
            },
        ]
    }
    with tempfile.TemporaryDirectory() as tmp:
        evidence_path = Path(tmp) / "evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        apns_path = Path(tmp) / "apns-conf.xml"
        count = generate_android_outputs.write_apns(
            apns_path, profiles, 8, generate_android_outputs.load_apn_evidence(evidence_path)
        )
        written = [dict(element.attrib) for element in ET.parse(apns_path).getroot()]

    def scope(mccmnc: str) -> list[tuple[str, str]]:
        return [(row["apn"], row["type"]) for row in written if row["mcc"] + row["mnc"] == mccmnc]

    assert_true(count == 5, f"no malformed row is dropped: {written}")
    assert_true(
        ("http://mms.pepephone.com", "mms") in scope("21404"),
        f"a scope whose only MMS row is malformed still writes it: {scope('21404')}",
    )
    assert_true(
        scope("62125") == [("#777", "default,supl")],
        f"a scope whose only internet row is malformed still writes it: {scope('62125')}",
    )
    assert_true(
        [apn for apn, _ in scope("20408")] == ["web.example", "web example"],
        f"a malformed internet row never comes before a valid one: {scope('20408')}",
    )


def check_best_row_last() -> None:
    """Rows TelephonyProvider stores as one (equal on its unique fields) are
    written together at the best-ranked row's place, the best row last and
    the others before it in reverse rank order, so the stored row takes the
    best row's values and only what it leaves unset from the others. No row
    is removed, no value changes, and rows that differ in a unique field are
    not grouped (rule decisions of 2026-10-06, round 5, change 17)."""

    google = "google_carriersettings"
    samsung = "samsung_omc"

    def apn(value: str, types: tuple[str, ...] = ("default",), **extra: object) -> dict:
        return {"name": str(extra.pop("name", value)), "apn": value, "types": list(types), **extra}

    scopes: dict[str, list[tuple[dict, tuple[str, ...]]]] = {
        # RACC shape: Samsung's bare row is the best; LineageOS's row with
        # CLIENTERACC/RACC is lower.
        "21406": [
            (apn("internet.racc.es", ("default", "supl")), (samsung,)),
            (apn("internet.racc.es", user="CLIENTERACC", password="RACC", authtype=1), ("lineageos",)),
        ],
        # 20825 shape: the best row has the user "lmfr", a lower one the typo
        # "Imfr".
        "20825": [
            (apn("data.lycamobile.fr", user="lmfr", password="plus", authtype=1), (google, "lineageos")),
            (apn("data.lycamobile.fr", user="Imfr", password="plus", authtype=1), ("mobile_broadband_provider_info",)),
        ],
        # 722340 shape: best datos/datos with PAP, lower gprs/adgj without.
        "722340": [
            (apn("datos.personal.example", user="datos", password="datos", authtype=1), (google,)),
            (apn("datos.personal.example", user="gprs", password="adgj", authtype=0), ("lineageos", "sony_open_devices_aosp")),
        ],
        # LRA shape: VZWINTERNET in an eHRPD (bearer 13) and an LTE (bearer 14)
        # row.
        "311490": [
            (apn("VZWINTERNET", bearer_bitmask="13"), ("lineageos",)),
            (apn("VZWINTERNET", bearer_bitmask="14", user_visible=False), ("lineageos", "sony_open_devices_aosp")),
        ],
        # Rows that differ in proxy, protocol, carrier id, user_editable or
        # APN letter case are other rows to Android and are not grouped.
        "23415": [
            (apn("web.example", user="a", password="a"), (google, "lineageos")),
            (apn("web.example", proxy="10.0.0.1", port=8080, user="b", password="b"), ("lineageos",)),
            (apn("web.example", protocol="IPV4V6", user="c", password="c"), ("lineageos",)),
            (apn("web.example", carrier_id=1234, user="d", password="d"), ("lineageos",)),
            (apn("web.example", user_editable=False, user="e", password="e"), ("lineageos",)),
            (apn("Web.example", user="f", password="f"), ("lineageos",)),
        ],
        # A group sits at its best row's place and the other rows keep their
        # order: x.example (best) and y.example tie on the value, the lower
        # x.example row ranks after y.example.
        "26202": [
            (apn("x.example"), (google, "lineageos")),
            (apn("x.example", user="u", password="p"), ("sony_open_devices_aosp",)),
            (apn("y.example"), (google, "lineageos")),
            (apn("z.example"), ("mobile_broadband_provider_info",)),
        ],
    }
    profiles = []
    records = []
    for mccmnc, rows in scopes.items():
        profile_id = f"open.{mccmnc}.a"
        profiles.append(
            {
                "profile_id": profile_id,
                "display_name": profile_id,
                "match": {"mccmnc": [mccmnc]},
                "android_apns": [row for row, _ in rows],
            }
        )
        facts = [
            {
                "section": "android_apns",
                "key": generate_android_outputs.apn_fact_key(row, apn_type),
                "sources": sorted(sources),
            }
            for row, sources in rows
            for apn_type in row["types"]
        ]
        records.append(
            {
                "profile_id": profile_id,
                "sources": sorted({source for _, sources in rows for source in sources}),
                "fact_sources": sorted(facts, key=lambda fact: fact["key"]),
            }
        )

    with tempfile.TemporaryDirectory() as tmp:
        evidence_path = Path(tmp) / "evidence.json"
        evidence_path.write_text(json.dumps({"profiles": records}), encoding="utf-8")
        evidence = generate_android_outputs.load_apn_evidence(evidence_path)
        rows = generate_android_outputs.apn_xml_rows(profiles, evidence)
        apns_path = Path(tmp) / "apns-conf.xml"
        count = generate_android_outputs.write_apns(apns_path, profiles, 8, evidence)
        written = [dict(element.attrib) for element in ET.parse(apns_path).getroot()]

    def provider_store(file_rows: list[dict]) -> list[dict]:
        """TelephonyProvider's load: a row equal to an earlier one on the
        unique fields merges into it at its place, types united, bitmasks
        OR-ed (none when either has none), written attributes overwriting."""
        stored: dict[tuple[str, ...], dict] = {}
        for row in file_rows:
            key = generate_android_outputs.android_unique_key(row)
            old = stored.get(key)
            if old is None:
                stored[key] = dict(row)
                continue
            types = old["type"].split(",")
            types += [apn_type for apn_type in row["type"].split(",") if apn_type not in types]
            masks = [item.get("bearer_bitmask") for item in (old, row)]
            merged = {**old, **row, "type": ",".join(types)}
            if all(masks):
                merged["bearer_bitmask"] = "|".join(
                    sorted({part for mask in masks for part in str(mask).split("|")}, key=int)
                )
            else:
                merged.pop("bearer_bitmask", None)
            stored[key] = merged
        return list(stored.values())

    def scope(mccmnc: str) -> list[dict]:
        return [row for row in written if row["mcc"] + row["mnc"] == mccmnc]

    def stored(mccmnc: str) -> list[dict]:
        return provider_store(scope(mccmnc))

    racc = scope("21406")
    assert_true(
        [row.get("user", "") for row in racc] == ["CLIENTERACC", ""],
        f"the lower row with the credentials comes first and the best bare row last: {racc}",
    )
    [racc_stored] = stored("21406")
    assert_true(
        (racc_stored.get("user"), racc_stored.get("password"), racc_stored["type"])
        == ("CLIENTERACC", "RACC", "default,supl"),
        f"the stored row keeps the credentials the best row leaves unset: {racc_stored}",
    )
    [lyca] = stored("20825")
    assert_true(lyca["user"] == "lmfr", f"the best row's user is stored, not the typo: {lyca}")
    [personal] = stored("722340")
    assert_true(
        (personal["user"], personal["password"], personal["authtype"]) == ("datos", "datos", "1"),
        f"the stored row is the best row's PAP datos: {personal}",
    )
    lra = scope("311490")
    [lra_stored] = stored("311490")
    assert_true(
        len(lra) == 2 and set(lra_stored["bearer_bitmask"].split("|")) == {"13", "14"},
        f"both VZWINTERNET rows are written and the stored bitmask covers LTE: {lra} {lra_stored}",
    )
    apart = scope("23415")
    assert_true(
        sorted(row["user"] for row in apart) == ["a", "b", "c", "d", "e", "f"]
        and len({generate_android_outputs.android_unique_key(row) for row in apart}) == 6
        and len(stored("23415")) == 6,
        f"rows that differ in a unique field stay apart: {apart}",
    )
    order = [(row["apn"], row.get("user", "")) for row in scope("26202")]
    assert_true(
        order == [("x.example", "u"), ("x.example", ""), ("y.example", ""), ("z.example", "")],
        f"a group sits at its best row's place and other rows keep their order: {order}",
    )
    marked = sorted(
        (record.get("mcc", "") + record.get("mnc", ""), record["apn"], str(record.get("user", "")))
        for record in rows.records
        if record.get("_stored_with_best_row")
    )
    assert_true(
        marked
        == [
            ("20825", "data.lycamobile.fr", "Imfr"),
            ("21406", "internet.racc.es", "CLIENTERACC"),
            ("26202", "x.example", "u"),
            ("311490", "VZWINTERNET", ""),
            ("722340", "datos.personal.example", "gprs"),
        ],
        f"rows written before their group's best row are marked: {marked}",
    )
    given = sorted(
        json.dumps(
            {
                key: str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in {**row, "type": ",".join(row["types"])}.items()
                if key not in {"name", "types"}
            },
            sort_keys=True,
        )
        for items in scopes.values()
        for row, _ in items
    )
    got = sorted(
        json.dumps({key: value for key, value in row.items() if key not in {"carrier", "mcc", "mnc"}}, sort_keys=True)
        for row in written
    )
    assert_true(count == len(given) and got == given, f"the rows and their values do not change: {got} != {given}")


def check_vendor_mms_first() -> None:
    """MMS goes to a current vendor's MMS row that serves a mobile network
    (rule decisions of 2026-10-06, round 6, change 18). A vendor MMS row is a
    row a current vendor backs for "mms", with a real APN and an MMSC, that
    serves a 3GPP data network type; it counts for the types it serves. The
    first internet row loses "mms" when no current vendor backs it for MMS
    and the vendor MMS rows together serve every such type it serves; then
    the best vendor MMS row moves just before the first row that still
    serves "mms" when that row is no vendor MMS row. No row is removed, and
    no type other than one "mms" changes."""

    google = "google_carriersettings"
    samsung = "samsung_omc"

    def apn(value: str, types: tuple[str, ...] = ("default",), **extra: object) -> dict:
        return {"name": str(extra.pop("name", value)), "apn": value, "types": list(types), **extra}

    # Each row: (row, sources for every type) or (row, {type: sources}).
    scopes: dict[str, list[tuple[dict, object]]] = {
        # 65507 shape: a LineageOS and Sony "internet" row typed "*" with an
        # MMSC; Google gives only "mms". The "*" row loses "mms", so Google's
        # row is the first MMS row.
        "65507": [
            (apn("internet", ("*",), mmsc="http://mms.old.example"), ("lineageos", "sony_open_devices_aosp")),
            (apn("mms", ("mms",), mmsc="http://mms.vodacom.example"), (google,)),
        ],
        # 50501 shape: "telstra.wap" leads; LineageOS's "mdata.net.au"
        # (default, mms) sits above Samsung's "telstra.mms", a vendor row
        # without a bitmask, which moves just before it.
        "50501": [
            (apn("telstra.wap", ("default", "ia", "supl")), (samsung, google)),
            (apn("mdata.net.au", ("default", "mms"), mmsc="http://mmsc.old.example"), ("lineageos",)),
            (apn("telstra.mms", ("mms",), mmsc="http://mmsc.telstra.example", mmsproxy="10.1.1.180", mmsport=80), (samsung,)),
        ],
        # 63902 shape: the first internet row "safaricom" serves "mms" with
        # an MMSC no vendor gives; Google backs it only for "default".
        "63902": [
            (apn("safaricom", ("default", "mms"), mmsc="http://old.safaricom.example"), {"default": (google,), "mms": ("lineageos",)}),
            (apn("safaricom", ("mms",), mmsc="http://mms.gprs.safaricom.example"), (google,)),
        ],
        # 234/30 shape: only the first internet row loses "mms"; a lower
        # default and mms row no vendor backs keeps it, and "eezone" moves
        # ahead of it.
        "23430": [
            (apn("everywhere", ("default", "mms"), mmsc="http://mms.ee.example"), {"default": (google,), "mms": ("lineageos",)}),
            (apn("general.t-mobile.uk", ("default", "mms"), mmsc="http://mmsc.t-mobile.example"), ("lineageos", "mobile_broadband_provider_info")),
            (apn("eezone", ("mms",), mmsc="http://mms/", mmsproxy="149.254.201.135", mmsport=8080), (google,)),
        ],
        # A first internet row a current vendor backs for "mms" keeps it,
        # and nothing moves.
        "21401": [
            (apn("web.example", ("default", "mms"), mmsc="http://mms.web.example"), (google,)),
            (apn("mms.example", ("mms",), mmsc="http://mms.other.example"), (samsung,)),
        ],
        # 73404 shape: no current vendor MMS row, nothing changes.
        "73404": [
            (apn("internet.example", ("default", "mms"), mmsc="http://mms.a.example"), ("lineageos",)),
            (apn("mms.example", ("mms",), mmsc="http://mms.b.example"), ("apple_carrier_bundles",)),
        ],
        # Bell shape: the only vendor MMS row is Wi-Fi only (bearer 18), so
        # it never counts and nothing changes.
        "30263": [
            (apn("pda.bell.ca", ("default", "mms"), mmsc="http://mms.bell.example"), ("lineageos",)),
            (apn("apps.bell.ca", ("mms",), mmsc="http://mms.bell.example", bearer_bitmask="18"), (google,)),
        ],
        # The same with network_type_bitmask 18.
        "30264": [
            (apn("pda.bell.ca", ("default", "mms"), mmsc="http://mms.bell.example"), ("lineageos",)),
            (apn("apps.bell.ca", ("mms",), mmsc="http://mms.bell.example", network_type_bitmask="18"), (google,)),
        ],
        # A vendor MMS row for LTE and NR only (bearer 14|20) next to an
        # internet row without a bitmask: the internet row keeps "mms",
        # because no vendor MMS row serves UMTS, HSPA or EDGE.
        "26210": [
            (apn("web.lte.example", ("default", "mms"), mmsc="http://mms.old.example"), ("lineageos",)),
            (apn("mms.lte.example", ("mms",), mmsc="http://mms.lte.example", bearer_bitmask="14|20"), (google,)),
        ],
        # CDMA-only and eHRPD-only vendor MMS rows do not count.
        "31000": [
            (apn("web.cdma.example", ("default", "mms"), mmsc="http://mms.old.example"), ("lineageos",)),
            (apn("mms.cdma.example", ("mms",), mmsc="http://mms.cdma.example", bearer_bitmask="4|5|6|7|8|12"), (google,)),
        ],
        "31001": [
            (apn("web.ehrpd.example", ("default", "mms"), mmsc="http://mms.old.example"), ("lineageos",)),
            (apn("mms.ehrpd.example", ("mms",), mmsc="http://mms.ehrpd.example", bearer_bitmask="13"), (google,)),
        ],
        # Verizon shape: VZWINTERNET leads; Google's CDMA-only "internet"
        # row (default, mms) is the first MMS row and is no vendor MMS row,
        # so VZWAPP moves just before it, ahead of T-Mobile's row.
        "310590": [
            (apn("VZWINTERNET", ("default", "supl")), (google, samsung, "lineageos")),
            (apn("internet", ("default", "mms"), mmsc="http://mms.vtext.example/servlets/mms", bearer_bitmask="4|5|6|7|8|12"), (google,)),
            (apn("fast.t-mobile.com", ("default", "mms"), mmsc="http://mms.msg.eng.t-mobile.example/mms/wapenc"), ("google_pixel_vendor_carriersettings", "fairphone_official_source")),
            (apn("VZWAPP", ("mms", "cbs"), mmsc="http://mms.vtext.example/servlets/mms"), (google,)),
        ],
        # A moved row with a TelephonyProvider twin that serves "default"
        # stays behind the first internet row.
        "23410": [
            (apn("web.example", ("default", "supl")), (google, "lineageos")),
            (apn("old.mms.example", ("default", "mms"), mmsc="http://mms.old.example"), ("lineageos", "mobile_broadband_provider_info")),
            (apn("mms.example", ("mms",), mmsc="http://mms.example"), (google,)),
            (apn("mms.example", ("default",), mmsc="http://mms.example", user="wap", password="wap"), ("apple_carrier_bundles",)),
        ],
    }

    def sources_for(sources: object, apn_type: str) -> tuple[str, ...]:
        return sources[apn_type] if isinstance(sources, dict) else sources  # type: ignore[index,return-value]

    profiles = []
    records = []
    for mccmnc, rows in scopes.items():
        profile_id = validate_public_carrier_data.canonical_profile_id({"mccmnc": [mccmnc]})
        profiles.append(
            {
                "profile_id": profile_id,
                "display_name": profile_id,
                "match": {"mccmnc": [mccmnc]},
                "android_apns": [row for row, _ in rows],
            }
        )
        facts = [
            {
                "section": "android_apns",
                "key": generate_android_outputs.apn_fact_key(row, apn_type),
                "sources": sorted(sources_for(sources, apn_type)),
            }
            for row, sources in rows
            for apn_type in row["types"]
        ]
        records.append(
            {
                "profile_id": profile_id,
                "sources": sorted({source for fact in facts for source in fact["sources"]}),
                "fact_sources": sorted(facts, key=lambda fact: fact["key"]),
            }
        )

    with tempfile.TemporaryDirectory() as tmp:
        evidence_path = Path(tmp) / "evidence.json"
        evidence_path.write_text(json.dumps({"profiles": records}), encoding="utf-8")
        evidence = generate_android_outputs.load_apn_evidence(evidence_path)
        rows = generate_android_outputs.apn_xml_rows(deepcopy(profiles), evidence)
        generated = Path(tmp) / "generated"
        carriers = Path(tmp) / "carriers"
        for item in profiles:
            write_carrier_profile(carriers, {**item, "capabilities": {}})
        shutil.copy(evidence_path, Path(tmp) / "evidence-index.json")
        with contextlib.redirect_stdout(io.StringIO()):
            generate_android_outputs.main(
                [
                    "generate_android_outputs.py",
                    str(carriers),
                    str(generated),
                    "--evidence-index",
                    str(Path(tmp) / "evidence-index.json"),
                ]
            )
        metadata = load_json(generated / "android" / "metadata.json")

    def scope(mccmnc: str) -> list[tuple[str, list[str]]]:
        return [
            (record["apn"], generate_android_outputs.apn_row_types(record["type"]))
            for record in rows.records
            if record.get("mcc", "") + record.get("mnc", "") == mccmnc
        ]

    def first(mccmnc: str, apn_type: str) -> str:
        return next(value for value, types in scope(mccmnc) if apn_type in types)

    def given(mccmnc: str) -> list[tuple[str, list[str]]]:
        return [
            (row["apn"], generate_android_outputs.apn_row_types(row["types"]))
            for row, _ in scopes[mccmnc]
        ]

    def unchanged(mccmnc: str) -> bool:
        return sorted(scope(mccmnc)) == sorted(given(mccmnc))

    retyped = {
        (record.get("mcc", "") + record.get("mnc", ""), record["apn"])
        for record in rows.records
        if record.get("_mms_left_out")
    }
    moved = {
        (record.get("mcc", "") + record.get("mnc", ""), record["apn"])
        for record in rows.records
        if record.get("_vendor_mms_ahead")
    }
    kept = {
        (record.get("mcc", "") + record.get("mnc", ""), record["apn"])
        for record in rows.records
        if record.get("_mms_kept_no_vendor_coverage")
    }
    internet_65507 = dict(scope("65507"))["internet"]
    assert_true(
        "mms" not in internet_65507 and "default" in internet_65507 and first("65507", "mms") == "mms",
        f"65507: the '*' row loses only mms and Google's row is the first MMS row: {scope('65507')}",
    )
    assert_true(
        first("50501", "mms") == "telstra.mms"
        and first("50501", "default") == "telstra.wap"
        and first("50501", "ia") == "telstra.wap"
        and unchanged("50501"),
        f"50501: telstra.mms moves ahead, internet and attach rows stay: {scope('50501')}",
    )
    assert_true(
        scope("63902") == [("safaricom", ["default"]), ("safaricom", ["mms"])]
        and next(r for r in rows.records if r.get("mcc", "") + r.get("mnc", "") == "63902" and r["type"] == "mms")["mmsc"]
        == "http://mms.gprs.safaricom.example",
        f"63902: the first internet row loses mms, Google's MMS row comes first: {scope('63902')}",
    )
    assert_true(
        scope("23430")
        == [
            ("everywhere", ["default"]),
            ("eezone", ["mms"]),
            ("general.t-mobile.uk", ["default", "mms"]),
        ],
        f"234/30: only the first internet row loses mms, eezone moves ahead: {scope('23430')}",
    )
    for mccmnc in ("21401", "73404", "30263", "30264", "26210", "31000", "31001"):
        assert_true(
            scope(mccmnc) == given(mccmnc),
            f"{mccmnc}: nothing changes: {scope(mccmnc)} != {given(mccmnc)}",
        )
    assert_true(
        [value for value, _ in scope("310590")] == ["VZWINTERNET", "VZWAPP", "internet", "fast.t-mobile.com"]
        and unchanged("310590"),
        f"Verizon: VZWAPP moves just before Google's CDMA-only internet row: {scope('310590')}",
    )
    assert_true(
        first("23410", "default") == "web.example" and first("23410", "mms") == "mms.example",
        f"a moved row's twin that serves default stays behind the first internet row: {scope('23410')}",
    )
    assert_true(
        retyped == {("65507", "internet"), ("63902", "safaricom"), ("23430", "everywhere")}
        and rows.mms_left_out == 3
        and metadata["omissions"]["mms_types_left_out_not_vendor_backed"] == 3,
        f"three first internet rows lose mms and are counted: {retyped}, {rows.mms_left_out}",
    )
    assert_true(
        moved == {("50501", "telstra.mms"), ("23430", "eezone"), ("310590", "VZWAPP"), ("23410", "mms.example")},
        f"the moved vendor rows are marked for --explain: {moved}, {scope('23410')}",
    )
    assert_true(
        kept == {("26210", "web.lte.example")},
        f"only the LTE-only vendor row leaves an internet row with mms for want of coverage: {kept}",
    )
    without_mms = sorted(
        (record.get("mcc", "") + record.get("mnc", ""), record["apn"], tuple(t for t in generate_android_outputs.apn_row_types(record["type"]) if t != "mms"))
        for record in rows.records
    )
    given_without_mms = sorted(
        (mccmnc, row["apn"], tuple(t for t in generate_android_outputs.apn_row_types(row["types"]) if t != "mms"))
        for mccmnc, items in scopes.items()
        for row, _ in items
    )
    assert_true(
        len(rows.records) == sum(len(items) for items in scopes.values()) and without_mms == given_without_mms,
        f"no row is removed and no type other than mms changes: {without_mms} != {given_without_mms}",
    )
    assert_true(
        generate_android_outputs.apn_row_network_types({"bearer_bitmask": "18"}) == frozenset()
        and generate_android_outputs.apn_row_network_types({"network_type_bitmask": "18"}) == frozenset()
        and generate_android_outputs.apn_row_network_types({"bearer_bitmask": "14|20"}) == frozenset({13, 20})
        and generate_android_outputs.apn_row_network_types({}) == generate_android_outputs.MMS_NETWORK_TYPES
        and generate_android_outputs.apn_row_network_types({"bearer_bitmask": "13"}) == frozenset(),
        "network types: Wi-Fi and eHRPD serve none, LTE and NR stay, no bitmask serves all",
    )


def check_leave_out_absorbed_mms() -> None:
    """apns-conf.xml leaves out a stored row that serves only "mms", whose
    MMS setting no vendor MMS row gives, whose network types the vendor MMS
    rows serve, and that ApnSetting.similar ties to an earlier stored row
    (auth types resolved): DataProfileManager would merge it there (rule
    decisions of 2026-10-06, round 6, change 19). The rows of one stored row
    go together, the other rows keep their order, and profile JSON keeps
    every row."""

    google = "google_carriersettings"

    def apn(value: str, types: tuple[str, ...] = ("default",), **extra: object) -> dict:
        return {"name": str(extra.pop("name", value)), "apn": value, "types": list(types), **extra}

    scopes: dict[str, list[tuple[dict, tuple[str, ...]]]] = {
        # 238/02 shape: a lower default row, a stale MMS-only row with its
        # APN (two file rows Android stores as one), and a vendor MMS row with
        # another APN. The stale row merges into the lower default row.
        "23802": [
            (apn("internet", ("default", "ia", "supl")), (google, "lineageos")),
            (apn("telia", ("default",)), ("lineageos",)),
            (apn("telia", ("mms",), mmsc="http://mms.old.example"), ("lineageos", "mobile_broadband_provider_info")),
            (apn("telia", ("mms",), mmsc="http://mms.old.example", mtu=1500), ("sony_open_devices_aosp",)),
            (apn("mms.telia.example", ("mms",), mmsc="http://mms.telia.example"), (google,)),
        ],
        # 530/05 shape: a vendor internet row and a vendor MMS row with the
        # same APN, and a stale MMS row of that APN with another MMSC.
        "53005": [
            (apn("internet", ("default", "supl")), (google,)),
            (apn("internet", ("mms",), mmsc="http://mms.spark.example"), (google,)),
            (apn("internet", ("mms",), mmsc="http://mms.old.example"), ("lineageos",)),
        ],
        # Talkmobile shape: an MMS-only row with a username and no auth type
        # (3) next to a default row with neither (0). Not similar: it stays.
        "23415": [
            (apn("payg.talkmobile.co.uk", ("default",)), ("lineageos",)),
            (apn("payg.talkmobile.co.uk", ("mms",), mmsc="http://mms.old.example", user="wap", password="wap"), ("lineageos",)),
            (apn("mms.example", ("mms",), mmsc="http://mms.example"), (google,)),
        ],
        # 208/01 Orange shape: the earlier row serves dun. It stays.
        "20801": [
            (apn("orange", ("default", "dun")), (google,)),
            (apn("orange", ("mms",), mmsc="http://mms.old.example"), ("lineageos",)),
            (apn("orange.mms", ("mms",), mmsc="http://mms.orange.example"), (google,)),
        ],
        # 466/89 shape: the MMS row's setting equals a vendor's. It stays.
        "46689": [
            (apn("internet", ("default",)), ("lineageos",)),
            (apn("internet", ("mms",), mmsc="http://mms.example"), ("lineageos",)),
            (apn("internet", ("mms",), mmsc="http://mms.example", protocol="IPV4V6"), (google,)),
        ],
        # Bell shape: the only vendor MMS row is Wi-Fi only. It stays.
        "30263": [
            (apn("pda.bell.ca", ("default",)), ("lineageos",)),
            (apn("pda.bell.ca", ("mms",), mmsc="http://mms.old.example"), ("lineageos",)),
            (apn("apps.bell.ca", ("mms",), mmsc="http://mms.bell.example", bearer_bitmask="18"), (google,)),
        ],
        # A same-APN row with another protocol is not similar. It stays.
        "26201": [
            (apn("web", ("default",), protocol="IPV4V6"), (google,)),
            (apn("web", ("mms",), mmsc="http://mms.old.example"), ("lineageos",)),
            (apn("mms", ("mms",), mmsc="http://mms.example"), (google,)),
        ],
        # The vendor MMS row serves LTE only; the stale row serves every
        # network type. It stays.
        "26202": [
            (apn("web", ("default",)), (google,)),
            (apn("web", ("mms",), mmsc="http://mms.old.example"), ("lineageos",)),
            (apn("mms", ("mms",), mmsc="http://mms.example", bearer_bitmask="14"), (google,)),
        ],
        # 73404 shape: no vendor MMS row, nothing changes.
        "73404": [
            (apn("internet", ("default",)), ("lineageos",)),
            (apn("internet", ("mms",), mmsc="http://mms.old.example"), ("apple_carrier_bundles",)),
        ],
    }
    profiles = []
    records = []
    for mccmnc, rows in scopes.items():
        profile_id = f"open.{mccmnc}.a"
        profiles.append(
            {
                "profile_id": profile_id,
                "display_name": profile_id,
                "match": {"mccmnc": [mccmnc]},
                "android_apns": [row for row, _ in rows],
            }
        )
        facts = [
            {
                "section": "android_apns",
                "key": generate_android_outputs.apn_fact_key(row, apn_type),
                "sources": sorted(sources),
            }
            for row, sources in rows
            for apn_type in row["types"]
        ]
        records.append(
            {
                "profile_id": profile_id,
                "sources": sorted({source for _, sources in rows for source in sources}),
                "fact_sources": sorted(facts, key=lambda fact: fact["key"]),
            }
        )

    with tempfile.TemporaryDirectory() as tmp:
        evidence_path = Path(tmp) / "evidence.json"
        evidence_path.write_text(json.dumps({"profiles": records}), encoding="utf-8")
        evidence = generate_android_outputs.load_apn_evidence(evidence_path)
        rows = generate_android_outputs.apn_xml_rows(deepcopy(profiles), evidence)

    def scope(mccmnc: str) -> list[tuple[str, str, str]]:
        return [
            (record["apn"], record["type"], str(record.get("mmsc", "")))
            for record in rows.records
            if record.get("mcc", "") + record.get("mnc", "") == mccmnc
        ]

    def given(mccmnc: str) -> list[tuple[str, str, str]]:
        return sorted(
            (row["apn"], ",".join(row["types"]), str(row.get("mmsc", ""))) for row, _ in scopes[mccmnc]
        )

    left = sorted(
        (record.get("mcc", "") + record.get("mnc", ""), record["apn"], str(record.get("mmsc", "")), str(record.get("mtu", "")))
        for record in rows.mms_absorbed_left_out
    )
    assert_true(
        left
        == [
            ("23802", "telia", "http://mms.old.example", ""),
            ("23802", "telia", "http://mms.old.example", "1500"),
            ("53005", "internet", "http://mms.old.example", ""),
        ],
        f"the stale MMS-only rows Android absorbs are left out, both file rows of a stored row: {left}",
    )
    assert_true(
        all(record.get("_absorbed_mms_left_out") for record in rows.mms_absorbed_left_out),
        "left-out rows are marked for --explain",
    )
    assert_true(
        sorted(scope("23802"))
        == sorted(
            [
                ("internet", "default,ia,supl", ""),
                ("telia", "default", ""),
                ("mms.telia.example", "mms", "http://mms.telia.example"),
            ]
        )
        and sorted(scope("53005"))
        == sorted([("internet", "default,supl", ""), ("internet", "mms", "http://mms.spark.example")]),
        f"the rest of 238/02 and 530/05 stays: {scope('23802')}, {scope('53005')}",
    )
    for mccmnc in ("23415", "20801", "46689", "30263", "26201", "26202", "73404"):
        assert_true(
            sorted(scope(mccmnc)) == given(mccmnc),
            f"{mccmnc}: every row stays: {scope(mccmnc)} != {given(mccmnc)}",
        )
    # Without the rule every row is written; with it, the same rows in the
    # same order, minus the left-out ones.
    rule = generate_android_outputs.leave_out_absorbed_mms
    try:
        generate_android_outputs.leave_out_absorbed_mms = lambda written: (written, [])
        with tempfile.TemporaryDirectory() as tmp:
            evidence_path = Path(tmp) / "evidence.json"
            evidence_path.write_text(json.dumps({"profiles": records}), encoding="utf-8")
            plain = generate_android_outputs.apn_xml_rows(
                deepcopy(profiles), generate_android_outputs.load_apn_evidence(evidence_path)
            )
    finally:
        generate_android_outputs.leave_out_absorbed_mms = rule
    line = generate_android_outputs.apn_row_line
    left_lines = {line(record) for record in rows.mms_absorbed_left_out}
    assert_true(
        [line(record) for record in rows.records]
        == [line(record) for record in plain.records if line(record) not in left_lines]
        and len(plain.records) == sum(len(items) for items in scopes.values()),
        "only the absorbed rows are left out and the other rows keep their order",
    )
    stored = generate_android_outputs.android_stored_rows(
        [record for record in rows.records if record.get("mcc", "") + record.get("mnc", "") == "23415"]
    )
    assert_true(
        [generate_android_outputs.android_auth_type(row) for row, _ in stored if row["apn"] == "payg.talkmobile.co.uk"]
        == [0, 3],
        "auth types resolve as ApnSetting does: 0 without a user, 3 with one",
    )
    assert_true(
        generate_android_outputs.android_auth_type({"authtype": 0, "user": "u"}) == 0
        and generate_android_outputs.android_auth_type({"authtype": "1"}) == 1,
        "an explicit auth type stays",
    )


def main() -> int:
    exact_device_id = "android:" + "a" * 20
    artifact_schema = load_json(
        Path(__file__).resolve().parents[1]
        / "schemas/android-carrier-artifact-registry.schema.json"
    )
    schema_scope_kinds = set(
        artifact_schema["properties"]["scope_coverage"]["items"]["properties"][
            "scope_kind"
        ]["enum"]
    )
    assert_true(
        schema_scope_kinds == validate_device_catalog.ANDROID_SCOPE_KINDS,
        "Android artifact schema and validator scope kinds must match",
    )
    schema_discovery_statuses = set(
        artifact_schema["properties"]["scope_coverage"]["items"]["properties"][
            "discovery_status"
        ]["enum"]
    )
    assert_true(
        schema_discovery_statuses
        == validate_device_catalog.ANDROID_DISCOVERY_STATUSES,
        "Android artifact schema and validator discovery statuses must match",
    )
    android_device_id_pattern = artifact_schema["$defs"]["device_ids"]["items"][
        "pattern"
    ]
    assert_true(
        android_device_id_pattern.startswith("^android:"),
        "Android artifact schema must reject Apple device IDs",
    )
    scope_schema = artifact_schema["properties"]["scope_coverage"]["items"]
    transport_rule = next(
        rule
        for rule in scope_schema["allOf"]
        if rule["if"]["properties"]["discovery_status"].get("const")
        == "source_transport_untrusted"
    )
    transport_properties = transport_rule["then"]["properties"]
    assert_true(
        transport_properties["scope_kind"] == {"const": "device_id"},
        "Transport-untrusted schema must require exact device scope",
    )
    for count_field in (
        "region_seed_count",
        "probed_region_count",
        "available_region_count",
        "extracted_artifact_count",
    ):
        assert_true(
            transport_properties[count_field] == {"const": 0},
            f"Transport-untrusted schema must force {count_field} to zero",
        )
    authentication_rule = next(
        rule
        for rule in scope_schema["allOf"]
        if rule["if"]["properties"]["discovery_status"].get("const")
        == "source_authentication_required"
    )
    authentication_properties = authentication_rule["then"]["properties"]
    assert_true(
        authentication_properties["scope_kind"] == {"const": "device_id"},
        "Authentication-required schema must require exact device scope",
    )
    for count_field in (
        "region_seed_count",
        "probed_region_count",
        "available_region_count",
        "extracted_artifact_count",
    ):
        assert_true(
            authentication_properties[count_field] == {"const": 0},
            f"Authentication-required schema must force {count_field} to zero",
        )
    inventory_schema = load_json(
        Path(__file__).resolve().parents[1] / "schemas/device-inventory.schema.json"
    )
    device_properties = inventory_schema["$defs"]["device"]["properties"]
    schema_coverage_statuses = set(
        device_properties["carrier_data_coverage"]["properties"]["status"]["enum"]
    )
    assert_true(
        schema_coverage_statuses == validate_device_catalog.DATA_COVERAGE_STATUSES,
        "Device schema and validator coverage statuses must match",
    )
    schema_status_count_keys = set(
        device_properties["carrier_source_discovery"]["items"]["properties"][
            "status_counts"
        ]["properties"]
    )
    assert_true(
        schema_status_count_keys == validate_device_catalog.ANDROID_DISCOVERY_STATUSES,
        "Device schema and validator discovery count statuses must match",
    )
    authentication_platform_rule = next(
        rule
        for rule in inventory_schema["$defs"]["device"]["allOf"]
        if rule.get("if", {})
        .get("properties", {})
        .get("carrier_data_coverage", {})
        .get("properties", {})
        .get("status", {})
        .get("const")
        == "source_authentication_required"
    )
    assert_true(
        authentication_platform_rule["then"]["properties"]["platform"]
        == {"const": "android"},
        "Authentication-required device coverage must be Android-only",
    )
    assert_true(
        authentication_platform_rule["then"].get("required")
        == ["carrier_source_discovery"]
        and authentication_platform_rule["then"]["properties"][
            "carrier_source_discovery"
        ]["contains"]["properties"]["status_counts"]["required"]
        == ["source_authentication_required"],
        "Authentication-required coverage must require matching discovery evidence",
    )
    authentication_forbidden_fields = {
        rule["required"][0]
        for rule in authentication_platform_rule["then"]["not"]["anyOf"]
    }
    assert_true(
        authentication_forbidden_fields
        == validate_device_catalog.AUTHENTICATION_TERMINAL_CONFLICT_FIELDS,
        "Authentication schema and validator carrier-bearing fields must match",
    )
    authentication_discovery_rule = next(
        rule
        for rule in inventory_schema["$defs"]["device"]["allOf"]
        if rule.get("if", {})
        .get("properties", {})
        .get("carrier_source_discovery", {})
        .get("contains", {})
        .get("properties", {})
        .get("status_counts", {})
        .get("required")
        == ["source_authentication_required"]
    )
    assert_true(
        authentication_discovery_rule["then"]["properties"][
            "carrier_data_coverage"
        ]["properties"]["status"]
        == {"const": "source_authentication_required"},
        "Authentication discovery evidence must require matching device coverage",
    )
    discovery_identifiers = device_properties["carrier_source_discovery"]["items"][
        "properties"
    ]["matched_identifiers"]
    assert_true(
        discovery_identifiers.get("maxItems") == 1
        and discovery_identifiers["items"]["pattern"].startswith("^(android|apple):"),
        "Device schema must require one exact platform device identifier",
    )
    observation = {
        "matched_identifiers": [exact_device_id],
        "profile_count": 1,
        "sources": ["synthetic_source"],
    }
    validate_device_catalog.validate_observations(
        Path("synthetic-device-catalog.json"), exact_device_id, observation
    )
    try:
        validate_device_catalog.validate_observations(
            Path("synthetic-device-catalog.json"),
            exact_device_id,
            {**observation, "matched_identifiers": ["ambiguous_alias"]},
        )
    except validate_device_catalog.ValidationError:
        pass
    else:
        raise AssertionError("bare alias bypassed exact device observation validation")

    for terminal_status in (
        "carrier_data_not_applicable",
        "platform_out_of_scope",
        "source_authentication_required",
        "source_transport_untrusted",
        "source_terms_restrict_extraction",
    ):
        discovery = [
            {
                "source": "synthetic_source",
                "matched_identifiers": [exact_device_id],
                "scope_count": 1,
                "status_counts": {terminal_status: 1},
            }
        ]
        record = {
            "device_id": exact_device_id,
            "platform": "android",
            "carrier_source_discovery": discovery,
            "carrier_data_coverage": {
                "status": terminal_status,
                "sources": ["synthetic_source"],
            },
        }
        validate_device_catalog.validate_source_discovery(
            Path("synthetic-device-catalog.json"), exact_device_id, discovery
        )
        validate_device_catalog.validate_data_coverage(
            Path("synthetic-device-catalog.json"), exact_device_id, record
        )

    exact_transport_discovery = [
        {
            "source": "synthetic_source",
            "matched_identifiers": [exact_device_id],
            "scope_count": 1,
            "status_counts": {"source_transport_untrusted": 1},
        }
    ]
    alias_discovery = deepcopy(exact_transport_discovery)
    alias_discovery[0]["matched_identifiers"] = ["SM-NOT-AN-EXACT-DEVICE-ID"]
    assert_validation_error(
        lambda: validate_device_catalog.validate_source_discovery(
            Path("synthetic-device-catalog.json"), exact_device_id, alias_discovery
        ),
        "source discovery accepted a non-device alias",
    )
    boolean_scope_count = deepcopy(exact_transport_discovery)
    boolean_scope_count[0]["scope_count"] = True
    assert_validation_error(
        lambda: validate_device_catalog.validate_source_discovery(
            Path("synthetic-device-catalog.json"), exact_device_id, boolean_scope_count
        ),
        "source discovery accepted a boolean scope count",
    )
    boolean_status_count = deepcopy(exact_transport_discovery)
    boolean_status_count[0]["status_counts"]["source_transport_untrusted"] = True
    assert_validation_error(
        lambda: validate_device_catalog.validate_source_discovery(
            Path("synthetic-device-catalog.json"), exact_device_id, boolean_status_count
        ),
        "source discovery accepted a boolean status count",
    )
    assert_validation_error(
        lambda: validate_device_catalog.validate_observations(
            Path("synthetic-device-catalog.json"),
            exact_device_id,
            {**observation, "profile_count": True},
        ),
        "carrier observations accepted a boolean profile count",
    )
    artifact_scope = {
        "artifact_count": 1,
        "match_kind": "exact_product_type",
        "scopes": [exact_device_id],
        "source": "apple_carrier_bundles",
        "verified_artifact_count": 1,
    }
    for count_field in ("artifact_count", "verified_artifact_count"):
        boolean_artifact_scope = deepcopy(artifact_scope)
        boolean_artifact_scope[count_field] = True
        assert_validation_error(
            lambda value=boolean_artifact_scope: validate_device_catalog.validate_artifact_scope(
                Path("synthetic-device-catalog.json"), exact_device_id, value
            ),
            f"artifact catalog accepted boolean {count_field}",
        )

    with tempfile.TemporaryDirectory() as raw_tmp:
        registry_path = Path(raw_tmp) / "android-carrier-artifacts.json"
        terminal_statuses = (
            "carrier_data_not_applicable",
            "platform_out_of_scope",
            "source_authentication_required",
            "source_transport_untrusted",
            "source_terms_restrict_extraction",
        )
        registry = {
            "schema_version": 1,
            "registry_id": "android_carrier_source_artifacts",
            "description": "Synthetic exact terminal coverage.",
            "sources": [
                {
                    "name": "synthetic_source",
                    "url": "https://example.com/source",
                    "revision": "0" * 64,
                    "revision_date": validate_public_carrier_data.utc_today().isoformat(),
                    "checked_at": validate_public_carrier_data.utc_today().isoformat(),
                }
            ],
            "scope_coverage": [
                *[
                    {
                        "source": "synthetic_source",
                        "device_scope": "android:" + marker * 20,
                        "scope_kind": "device_id",
                        "device_ids": ["android:" + marker * 20],
                        "discovery_status": status,
                        "region_seed_count": 0,
                        "probed_region_count": 0,
                        "available_region_count": 0,
                        "extracted_artifact_count": 0,
                    }
                    for marker, status in zip("abcde", terminal_statuses, strict=True)
                ],
                {
                    "source": "synthetic_source",
                    "device_scope": "api_device_id:101",
                    "scope_kind": "source_api_row",
                    "device_ids": [exact_device_id],
                    "discovery_status": "artifact_indexed",
                    "region_seed_count": 1,
                    "probed_region_count": 1,
                    "available_region_count": 1,
                    "extracted_artifact_count": 0,
                },
            ],
            "artifacts": [],
        }
        registry_path.write_text(
            json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_device_catalog.validate_android_artifacts(registry_path)

        transport_scope = next(
            item
            for item in registry["scope_coverage"]
            if item["discovery_status"] == "source_transport_untrusted"
        )
        transport_registry = deepcopy(registry)
        transport_registry["scope_coverage"] = [deepcopy(transport_scope)]
        invalid_path = Path(raw_tmp) / "invalid-transport.json"

        def assert_registry_rejected(value: dict, message: str) -> None:
            invalid_path.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            assert_validation_error(
                lambda: validate_device_catalog.validate_android_artifacts(invalid_path),
                message,
            )

        for count_field in (
            "region_seed_count",
            "probed_region_count",
            "available_region_count",
            "extracted_artifact_count",
        ):
            invalid_transport = deepcopy(transport_registry)
            invalid_transport["scope_coverage"][0][count_field] = 1
            assert_registry_rejected(
                invalid_transport,
                f"transport-untrusted scope accepted nonzero {count_field}",
            )
            boolean_transport = deepcopy(transport_registry)
            boolean_transport["scope_coverage"][0][count_field] = False
            assert_registry_rejected(
                boolean_transport,
                f"transport-untrusted scope accepted boolean {count_field}",
            )

        for scope_kind in ("model", "source_api_row"):
            invalid_transport = deepcopy(transport_registry)
            invalid_transport["scope_coverage"][0]["scope_kind"] = scope_kind
            invalid_transport["scope_coverage"][0]["device_scope"] = "synthetic-scope"
            assert_registry_rejected(
                invalid_transport,
                f"transport-untrusted scope accepted {scope_kind} scope",
            )

        apple_transport = deepcopy(transport_registry)
        apple_device_id = "apple:" + "a" * 20
        apple_transport["scope_coverage"][0]["device_scope"] = apple_device_id
        apple_transport["scope_coverage"][0]["device_ids"] = [apple_device_id]
        assert_registry_rejected(
            apple_transport,
            "Android transport-untrusted scope accepted an Apple device ID",
        )

        artifact_transport = deepcopy(transport_registry)
        transport_device_id = artifact_transport["scope_coverage"][0]["device_scope"]
        artifact_transport["artifacts"] = [
            {
                "artifact_id": "android:" + "1" * 24,
                "source": "synthetic_source",
                "device_scopes": [transport_device_id],
                "device_ids": [transport_device_id],
                "regions": ["global"],
                "build_versions": ["1"],
                "verification": "indexed",
                "checked_at": validate_public_carrier_data.utc_today().isoformat(),
            }
        ]
        assert_registry_rejected(
            artifact_transport,
            "transport-untrusted scope accepted same-source/device artifact evidence",
        )

        positive_scope_transport = deepcopy(transport_registry)
        positive_scope_transport["scope_coverage"].append(
            {
                "source": "synthetic_source",
                "device_scope": "api_device_id:transport-conflict",
                "scope_kind": "source_api_row",
                "device_ids": [transport_device_id],
                "discovery_status": "artifact_indexed",
                "region_seed_count": 1,
                "probed_region_count": 1,
                "available_region_count": 1,
                "extracted_artifact_count": 0,
            }
        )
        positive_scope_transport["scope_coverage"].sort(
            key=lambda item: (item["source"], item["device_scope"])
        )
        assert_registry_rejected(
            positive_scope_transport,
            "transport-untrusted scope accepted same-source/device positive scope evidence",
        )

        authentication_scope = next(
            item
            for item in registry["scope_coverage"]
            if item["discovery_status"] == "source_authentication_required"
        )
        authentication_registry = deepcopy(registry)
        authentication_registry["scope_coverage"] = [deepcopy(authentication_scope)]
        for count_field in (
            "region_seed_count",
            "probed_region_count",
            "available_region_count",
            "extracted_artifact_count",
        ):
            nonzero_authentication = deepcopy(authentication_registry)
            nonzero_authentication["scope_coverage"][0][count_field] = 1
            assert_registry_rejected(
                nonzero_authentication,
                f"authentication-required scope accepted nonzero {count_field}",
            )
            boolean_authentication = deepcopy(authentication_registry)
            boolean_authentication["scope_coverage"][0][count_field] = False
            assert_registry_rejected(
                boolean_authentication,
                f"authentication-required scope accepted boolean {count_field}",
            )

        loose_authentication = deepcopy(authentication_registry)
        loose_authentication["scope_coverage"][0]["scope_kind"] = "model"
        loose_authentication["scope_coverage"][0]["device_scope"] = "synthetic-model"
        assert_registry_rejected(
            loose_authentication,
            "authentication-required terminal accepted a non-device scope",
        )

        apple_authentication = deepcopy(authentication_registry)
        apple_device_id = "apple:" + "b" * 20
        apple_authentication["scope_coverage"][0]["device_scope"] = apple_device_id
        apple_authentication["scope_coverage"][0]["device_ids"] = [apple_device_id]
        assert_registry_rejected(
            apple_authentication,
            "Android authentication-required scope accepted an Apple device ID",
        )

        artifact_authentication = deepcopy(authentication_registry)
        authentication_device_id = artifact_authentication["scope_coverage"][0][
            "device_scope"
        ]
        artifact_authentication["artifacts"] = [
            {
                "artifact_id": "android:" + "2" * 24,
                "source": "synthetic_source",
                "device_scopes": [authentication_device_id],
                "device_ids": [authentication_device_id],
                "regions": ["global"],
                "build_versions": ["1"],
                "verification": "indexed",
                "checked_at": validate_public_carrier_data.utc_today().isoformat(),
            }
        ]
        assert_registry_rejected(
            artifact_authentication,
            "authentication-required scope accepted artifact evidence",
        )

        positive_scope_authentication = deepcopy(authentication_registry)
        positive_scope_authentication["scope_coverage"].append(
            {
                "source": "synthetic_source",
                "device_scope": "api_device_id:authentication-conflict",
                "scope_kind": "source_api_row",
                "device_ids": [authentication_device_id],
                "discovery_status": "artifact_indexed",
                "region_seed_count": 1,
                "probed_region_count": 1,
                "available_region_count": 1,
                "extracted_artifact_count": 0,
            }
        )
        positive_scope_authentication["scope_coverage"].sort(
            key=lambda item: (item["source"], item["device_scope"])
        )
        assert_registry_rejected(
            positive_scope_authentication,
            "authentication-required scope accepted positive scope evidence",
        )

        boolean_schema = deepcopy(transport_registry)
        boolean_schema["schema_version"] = True
        assert_registry_rejected(
            boolean_schema,
            "Android artifact registry accepted a boolean schema version",
        )

    transport_scope = {
        "source": "synthetic_source",
        "device_scope": exact_device_id,
        "scope_kind": "device_id",
        "device_ids": [exact_device_id],
        "discovery_status": "source_transport_untrusted",
        "region_seed_count": 0,
        "probed_region_count": 0,
        "available_region_count": 0,
        "extracted_artifact_count": 0,
    }
    transport_device = {
        "device_id": exact_device_id,
        "platform": "android",
        "carrier_source_discovery": deepcopy(exact_transport_discovery),
        "carrier_data_coverage": {
            "status": "source_transport_untrusted",
            "sources": ["synthetic_source"],
        },
    }
    validate_device_catalog.validate_android_transport_links(
        Path("synthetic-device-catalog"), [transport_device], [transport_scope]
    )
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_transport_links(
            Path("synthetic-device-catalog"), [transport_device], []
        ),
        "transport-untrusted device summary passed without an exact registry scope",
    )
    scope_without_summary_device = {
        "device_id": exact_device_id,
        "platform": "android",
        "carrier_data_coverage": {"status": "inventory_only", "sources": []},
    }
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_transport_links(
            Path("synthetic-device-catalog"),
            [scope_without_summary_device],
            [transport_scope],
        ),
        "transport-untrusted registry scope passed without a device summary",
    )
    unknown_scope = deepcopy(transport_scope)
    unknown_scope["device_scope"] = "android:" + "b" * 20
    unknown_scope["device_ids"] = [unknown_scope["device_scope"]]
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_transport_links(
            Path("synthetic-device-catalog"), [transport_device], [unknown_scope]
        ),
        "transport-untrusted scope accepted an unknown Android device ID",
    )
    catalog_conflict_device = deepcopy(transport_device)
    catalog_conflict_device["carrier_source_catalogs"] = [
        {
            "source": "synthetic_source",
            "match_kind": "exact_device_id",
            "matched_identifiers": [exact_device_id],
            "artifact_count": 1,
            "indexed_artifact_count": 1,
            "extracted_artifact_count": 0,
        }
    ]
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_transport_links(
            Path("synthetic-device-catalog"),
            [catalog_conflict_device],
            [transport_scope],
        ),
        "transport-untrusted scope accepted same-source/device catalog evidence",
    )
    for count_field in (
        "artifact_count",
        "indexed_artifact_count",
        "extracted_artifact_count",
    ):
        boolean_catalog = deepcopy(catalog_conflict_device["carrier_source_catalogs"])
        boolean_catalog[0][count_field] = True
        assert_validation_error(
            lambda value=boolean_catalog: validate_device_catalog.validate_source_catalogs(
                Path("synthetic-device-catalog.json"), exact_device_id, value
            ),
            f"source catalog accepted boolean {count_field}",
        )

    exact_authentication_discovery = [
        {
            "source": "synthetic_source",
            "matched_identifiers": [exact_device_id],
            "scope_count": 1,
            "status_counts": {"source_authentication_required": 1},
        }
    ]
    authentication_scope = {
        **transport_scope,
        "discovery_status": "source_authentication_required",
    }
    authentication_device = {
        "device_id": exact_device_id,
        "platform": "android",
        "carrier_source_discovery": deepcopy(exact_authentication_discovery),
        "carrier_data_coverage": {
            "status": "source_authentication_required",
            "sources": ["synthetic_source"],
        },
    }
    validate_device_catalog.validate_source_discovery(
        Path("synthetic-device-catalog.json"),
        exact_device_id,
        exact_authentication_discovery,
    )
    validate_device_catalog.validate_data_coverage(
        Path("synthetic-device-catalog.json"),
        exact_device_id,
        authentication_device,
    )
    validate_device_catalog.validate_android_authentication_links(
        Path("synthetic-device-catalog"),
        [authentication_device],
        [],
        [authentication_scope],
    )
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_authentication_links(
            Path("synthetic-device-catalog"), [authentication_device], [], []
        ),
        "authentication-required summary passed without an exact registry scope",
    )
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_authentication_links(
            Path("synthetic-device-catalog"),
            [scope_without_summary_device],
            [],
            [authentication_scope],
        ),
        "authentication-required scope passed without a matching device summary",
    )
    wrong_source_authentication = deepcopy(authentication_scope)
    wrong_source_authentication["source"] = "other_source"
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_authentication_links(
            Path("synthetic-device-catalog"),
            [authentication_device],
            [],
            [wrong_source_authentication],
        ),
        "authentication-required scope accepted a mismatched source",
    )
    counted_twice_authentication = deepcopy(authentication_device)
    counted_twice_authentication["carrier_source_discovery"][0]["scope_count"] = 2
    counted_twice_authentication["carrier_source_discovery"][0]["status_counts"][
        "source_authentication_required"
    ] = 2
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_authentication_links(
            Path("synthetic-device-catalog"),
            [counted_twice_authentication],
            [],
            [authentication_scope],
        ),
        "authentication-required summary accepted a non-singleton scope count",
    )
    authentication_catalog_conflict = deepcopy(authentication_device)
    authentication_catalog_conflict["carrier_source_catalogs"] = deepcopy(
        catalog_conflict_device["carrier_source_catalogs"]
    )
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_authentication_links(
            Path("synthetic-device-catalog"),
            [authentication_catalog_conflict],
            [],
            [authentication_scope],
        ),
        "authentication-required scope accepted source catalog evidence",
    )

    for evidence_source in ("synthetic_source", "other_source"):
        observation_conflict = deepcopy(authentication_device)
        observation_conflict["carrier_observations"] = {
            "matched_identifiers": [exact_device_id],
            "profile_count": 1,
            "sources": [evidence_source],
        }
        validate_device_catalog.validate_observations(
            Path("synthetic-device-catalog.json"),
            exact_device_id,
            observation_conflict["carrier_observations"],
        )
        assert_validation_error(
            lambda value=observation_conflict: validate_device_catalog.validate_data_coverage(
                Path("synthetic-device-catalog.json"), exact_device_id, value
            ),
            f"authentication terminal accepted {evidence_source} observations",
        )

        source_catalog_conflict = deepcopy(authentication_device)
        source_catalog_conflict["carrier_source_catalogs"] = [
            {
                "source": evidence_source,
                "match_kind": "exact_device_id",
                "matched_identifiers": [exact_device_id],
                "artifact_count": 1,
                "indexed_artifact_count": 1,
                "extracted_artifact_count": 0,
            }
        ]
        validate_device_catalog.validate_source_catalogs(
            Path("synthetic-device-catalog.json"),
            exact_device_id,
            source_catalog_conflict["carrier_source_catalogs"],
        )
        assert_validation_error(
            lambda value=source_catalog_conflict: validate_device_catalog.validate_data_coverage(
                Path("synthetic-device-catalog.json"), exact_device_id, value
            ),
            f"authentication terminal accepted {evidence_source} source catalog",
        )

    apple_artifact_scope = {
        "artifact_count": 1,
        "match_kind": "exact_product_type",
        "scopes": [exact_device_id],
        "source": "apple_carrier_bundles",
        "verified_artifact_count": 0,
    }
    validate_device_catalog.validate_artifact_scope(
        Path("synthetic-device-catalog.json"),
        exact_device_id,
        apple_artifact_scope,
    )
    for authentication_source in ("synthetic_source", "apple_carrier_bundles"):
        artifact_catalog_conflict = deepcopy(authentication_device)
        artifact_catalog_conflict["carrier_source_discovery"][0]["source"] = (
            authentication_source
        )
        artifact_catalog_conflict["carrier_data_coverage"]["sources"] = [
            authentication_source
        ]
        artifact_catalog_conflict["carrier_artifact_catalog"] = deepcopy(
            apple_artifact_scope
        )
        assert_validation_error(
            lambda value=artifact_catalog_conflict: validate_device_catalog.validate_data_coverage(
                Path("synthetic-device-catalog.json"), exact_device_id, value
            ),
            "authentication terminal accepted Apple artifact catalog with "
            f"authentication source {authentication_source}",
        )

    other_android_device_id = "android:" + "d" * 20
    for artifact_source in ("synthetic_source", "other_source"):
        for match_kind in (
            "device_ids",
            "device_scopes",
            "mapped_device_scope",
        ):
            mapped_scope = {
                "source": artifact_source,
                "device_scope": "model-a",
                "scope_kind": "model",
                "device_ids": [exact_device_id],
                "discovery_status": "no_artifact_found",
                "region_seed_count": 0,
                "probed_region_count": 0,
                "available_region_count": 0,
                "extracted_artifact_count": 0,
            }
            registry_artifact = {
                "artifact_id": "android:" + "3" * 24,
                "source": artifact_source,
                "device_scopes": [
                    exact_device_id if match_kind == "device_scopes" else "model-a"
                ],
                "device_ids": [
                    exact_device_id
                    if match_kind == "device_ids"
                    else other_android_device_id
                ],
                "regions": ["global"],
                "build_versions": ["1"],
                "verification": "indexed",
                "checked_at": validate_public_carrier_data.utc_today().isoformat(),
            }
            assert_validation_error(
                lambda value=registry_artifact: validate_device_catalog.validate_android_authentication_links(
                    Path("synthetic-device-catalog"),
                    [authentication_device],
                    [value],
                    [authentication_scope]
                    + ([mapped_scope] if match_kind == "mapped_device_scope" else []),
                ),
                f"authentication terminal accepted {artifact_source} registry artifact "
                f"matched through {match_kind}",
            )

    positive_scope_variants = (
        ("artifact_indexed", (1, 1, 1, 0)),
        ("source_extracted", (1, 1, 1, 1)),
        ("no_artifact_found", (1, 0, 0, 0)),
        ("no_artifact_found", (1, 1, 0, 0)),
        ("no_artifact_found", (1, 1, 1, 0)),
        ("no_artifact_found", (0, 0, 0, 1)),
    )
    for scope_source in ("synthetic_source", "other_source"):
        for variant_index, (status, counts) in enumerate(positive_scope_variants):
            positive_scope = {
                "source": scope_source,
                "device_scope": f"api_device_id:auth-global-{variant_index}",
                "scope_kind": "source_api_row",
                "device_ids": [exact_device_id],
                "discovery_status": status,
                "region_seed_count": counts[0],
                "probed_region_count": counts[1],
                "available_region_count": counts[2],
                "extracted_artifact_count": counts[3],
            }
            assert_validation_error(
                lambda value=positive_scope: validate_device_catalog.validate_android_authentication_links(
                    Path("synthetic-device-catalog"),
                    [authentication_device],
                    [],
                    [authentication_scope, value],
                ),
                f"authentication terminal accepted {scope_source} positive scope "
                f"variant {variant_index}",
            )

    mixed_authentication = deepcopy(authentication_device)
    mixed_authentication["carrier_source_discovery"][0]["scope_count"] = 2
    mixed_authentication["carrier_source_discovery"][0]["status_counts"][
        "source_terms_restrict_extraction"
    ] = 1
    assert_validation_error(
        lambda: validate_device_catalog.validate_data_coverage(
            Path("synthetic-device-catalog.json"),
            exact_device_id,
            mixed_authentication,
        ),
        "authentication-required coverage accepted mixed discovery statuses",
    )
    mismatched_authentication_sources = deepcopy(authentication_device)
    mismatched_authentication_sources["carrier_data_coverage"]["sources"] = [
        "other_source"
    ]
    assert_validation_error(
        lambda: validate_device_catalog.validate_data_coverage(
            Path("synthetic-device-catalog.json"),
            exact_device_id,
            mismatched_authentication_sources,
        ),
        "authentication-required coverage accepted mismatched sources",
    )
    boolean_authentication_count = deepcopy(exact_authentication_discovery)
    boolean_authentication_count[0]["status_counts"][
        "source_authentication_required"
    ] = True
    assert_validation_error(
        lambda: validate_device_catalog.validate_source_discovery(
            Path("synthetic-device-catalog.json"),
            exact_device_id,
            boolean_authentication_count,
        ),
        "authentication-required discovery accepted a boolean count",
    )
    dangling_authentication = deepcopy(authentication_device)
    dangling_authentication["carrier_data_coverage"] = {
        "status": "inventory_only",
        "sources": [],
    }
    assert_validation_error(
        lambda: validate_device_catalog.validate_android_authentication_links(
            Path("synthetic-device-catalog"),
            [dangling_authentication],
            [],
            [authentication_scope],
        ),
        "authentication discovery passed with non-authentication device coverage",
    )
    apple_authentication_id = "apple:" + "c" * 20
    apple_authentication_discovery = deepcopy(exact_authentication_discovery)
    apple_authentication_discovery[0]["matched_identifiers"] = [
        apple_authentication_id
    ]
    assert_validation_error(
        lambda: validate_device_catalog.validate_source_discovery(
            Path("synthetic-device-catalog.json"),
            apple_authentication_id,
            apple_authentication_discovery,
        ),
        "Apple source discovery accepted authentication-required evidence",
    )

    apple_device_id = "apple:" + "a" * 20
    apple_transport_discovery = deepcopy(exact_transport_discovery)
    apple_transport_discovery[0]["matched_identifiers"] = [apple_device_id]
    assert_validation_error(
        lambda: validate_device_catalog.validate_data_coverage(
            Path("synthetic-device-catalog.json"),
            apple_device_id,
            {
                "device_id": apple_device_id,
                "platform": "apple",
                "carrier_source_discovery": apple_transport_discovery,
                "carrier_data_coverage": {
                    "status": "source_transport_untrusted",
                    "sources": ["synthetic_source"],
                },
            },
        ),
        "Apple inventory accepted source_transport_untrusted coverage",
    )
    apple_authentication_discovery = deepcopy(exact_authentication_discovery)
    apple_authentication_discovery[0]["matched_identifiers"] = [apple_device_id]
    assert_validation_error(
        lambda: validate_device_catalog.validate_data_coverage(
            Path("synthetic-device-catalog.json"),
            apple_device_id,
            {
                "device_id": apple_device_id,
                "platform": "apple",
                "carrier_source_discovery": apple_authentication_discovery,
                "carrier_data_coverage": {
                    "status": "source_authentication_required",
                    "sources": ["synthetic_source"],
                },
            },
        ),
        "Apple inventory accepted source_authentication_required coverage",
    )

    with tempfile.TemporaryDirectory() as raw_tmp:
        temporary_root = Path(raw_tmp)
        today = validate_public_carrier_data.utc_today().isoformat()
        synthetic_source = {
            "name": "synthetic_source",
            "url": "https://example.com/source",
            "revision": "0" * 64,
            "revision_date": today,
            "checked_at": today,
        }
        inventory = {
            "schema_version": 1,
            "inventory_id": "synthetic_inventory",
            "platform": "android",
            "description": "Synthetic inventory.",
            "sources": [synthetic_source],
            "devices": [
                {
                    "device_id": apple_device_id,
                    "platform": "android",
                    "identity_basis": "synthetic",
                    "brands": [],
                    "device_names": [],
                    "models": [],
                    "marketing_names": [],
                    "inventory_status": "present",
                    "inventory_sources": [
                        {
                            "source": "synthetic_source",
                            "status": "present",
                            "first_seen_revision": "0" * 64,
                            "last_changed_revision": "0" * 64,
                        }
                    ],
                    "carrier_data_coverage": {
                        "status": "inventory_only",
                        "sources": [],
                    },
                }
            ],
        }
        inventory_path = temporary_root / "inventory.json"
        inventory_path.write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        assert_validation_error(
            lambda: validate_device_catalog.validate_inventory(inventory_path, "android"),
            "Android inventory accepted an Apple-prefixed device ID",
        )
        boolean_inventory = deepcopy(inventory)
        boolean_inventory["schema_version"] = True
        boolean_inventory["devices"][0]["device_id"] = exact_device_id
        inventory_path.write_text(
            json.dumps(boolean_inventory, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        assert_validation_error(
            lambda: validate_device_catalog.validate_inventory(inventory_path, "android"),
            "device inventory accepted a boolean schema version",
        )

        android_source = {**synthetic_source, "name": "synthetic_android"}
        apple_source = {**synthetic_source, "name": "synthetic_apple"}
        index_android_devices = [
            {
                "inventory_status": "present",
                "brands": ["Synthetic"],
                "carrier_source_discovery": deepcopy(exact_transport_discovery),
                "carrier_data_coverage": {
                    "status": "source_transport_untrusted",
                    "sources": ["synthetic_source"],
                },
            }
        ]
        index = {
            "schema_version": 1,
            "description": "Synthetic index.",
            "generated_from_checks_through": today,
            "sources": sorted(
                [android_source, apple_source], key=lambda item: item["name"]
            ),
            "platforms": {
                "android": {
                    "carrier_observation_match_count": 0,
                    "carrier_artifact_match_count": 0,
                    "carrier_source_discovery_match_count": 1,
                    "carrier_data_coverage_counts": {
                        "source_transport_untrusted": 1
                    },
                    "carrier_data_coverage_counts_by_brand": {
                        "Synthetic": {"source_transport_untrusted": 1}
                    },
                    "device_count": 1,
                    "historical_device_count": 0,
                    "present_device_count": 1,
                    "present_device_count_by_brand": {"Synthetic": 1},
                },
                "apple": {
                    "carrier_observation_match_count": 0,
                    "carrier_data_coverage_counts": {},
                    "carrier_data_coverage_counts_by_brand": {},
                    "device_count": 0,
                    "exact_artifact_scope_match_count": 0,
                    "family_artifact_scope_match_count": 0,
                    "historical_device_count": 0,
                    "present_device_count": 0,
                    "present_device_count_by_brand": {},
                },
            },
            "artifact_registries": {
                "apple_carrier_bundles": {
                    "artifact_count": 0,
                    "indexed_count": 0,
                    "verified_count": 0,
                    "failed_count": 0,
                    "quarantined_count": 0,
                },
                "android_carrier_source_artifacts": {
                    "artifact_count": 0,
                    "indexed_count": 0,
                    "extracted_count": 0,
                    "failed_count": 0,
                    "quarantined_count": 0,
                },
            },
        }
        index_path = temporary_root / "index.json"

        def validate_synthetic_index(
            value: dict, android_devices: list[dict] | None = None
        ) -> None:
            index_path.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            validate_device_catalog.validate_index(
                index_path,
                [android_source],
                android_devices if android_devices is not None else index_android_devices,
                [apple_source],
                [],
                apple_source,
                [],
                [android_source],
                [],
            )

        validate_synthetic_index(index)
        authentication_index_devices = deepcopy(index_android_devices)
        authentication_index_devices[0]["carrier_source_discovery"][0][
            "status_counts"
        ] = {"source_authentication_required": 1}
        authentication_index_devices[0]["carrier_data_coverage"]["status"] = (
            "source_authentication_required"
        )
        authentication_index = deepcopy(index)
        authentication_index["platforms"]["android"][
            "carrier_data_coverage_counts"
        ] = {"source_authentication_required": 1}
        authentication_index["platforms"]["android"][
            "carrier_data_coverage_counts_by_brand"
        ] = {"Synthetic": {"source_authentication_required": 1}}
        validate_synthetic_index(authentication_index, authentication_index_devices)
        boolean_coverage_index = deepcopy(index)
        boolean_coverage_index["platforms"]["android"]["carrier_data_coverage_counts"][
            "source_transport_untrusted"
        ] = True
        assert_validation_error(
            lambda: validate_synthetic_index(boolean_coverage_index),
            "device index accepted a boolean transport coverage count",
        )
        boolean_brand_coverage_index = deepcopy(index)
        boolean_brand_coverage_index["platforms"]["android"][
            "carrier_data_coverage_counts_by_brand"
        ]["Synthetic"]["source_transport_untrusted"] = True
        assert_validation_error(
            lambda: validate_synthetic_index(boolean_brand_coverage_index),
            "device index accepted a nested boolean transport coverage count",
        )
        boolean_registry_index = deepcopy(index)
        boolean_registry_index["artifact_registries"][
            "android_carrier_source_artifacts"
        ]["quarantined_count"] = False
        assert_validation_error(
            lambda: validate_synthetic_index(boolean_registry_index),
            "device index accepted a boolean artifact-registry count",
        )
        boolean_schema_index = deepcopy(index)
        boolean_schema_index["schema_version"] = True
        assert_validation_error(
            lambda: validate_synthetic_index(boolean_schema_index),
            "device index accepted a boolean schema version",
        )

    try:
        validate_device_catalog.validate_data_coverage(
            Path("synthetic-device-catalog.json"),
            exact_device_id,
            {
                "device_id": exact_device_id,
                "platform": "android",
                "carrier_data_coverage": {
                    "status": "carrier_data_not_applicable",
                    "sources": ["synthetic_source"],
                },
            },
        )
    except validate_device_catalog.ValidationError:
        pass
    else:
        raise AssertionError("Android not-applicable claim passed without exact evidence")

    schema = load_json(
        Path(__file__).resolve().parents[1] / "schemas/carrier-profile.schema.json"
    )
    schema_config_keys = set(
        schema["properties"]["android_carrier_config"]["propertyNames"]["enum"]
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
                        "mmsc": "http://mms.mvno.example",
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
        published = {
            profile["profile_id"]: {
                key: value
                for key, value in profile["capabilities"].items()
                if value != "unknown"
            }
            for path in carriers_dir.rglob("*.json")
            for profile in [load_json(path)]
        }
        profile_ids = sorted(published)
        sources_for = {
            "supported": {"on": ["lineageos"]},
            "unsupported": {"off": ["aosp", "lineageos"]},
            "conditional": {"off": ["aosp"], "on": ["lineageos"]},
        }
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
                        "sources": ["aosp", "lineageos"],
                        "fact_sources": [],
                        **(
                            {
                                "capability_sources": {
                                    key: sources_for[value]
                                    for key, value in published[profile_id].items()
                                }
                            }
                            if published[profile_id]
                            else {}
                        ),
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
        check_freshness_rules(carriers_dir, generated_dir)
        check_evidence_format(carriers_dir, generated_dir)
        check_provenance_and_lookup(carriers_dir, generated_dir)

        apn_root = ET.parse(generated_dir / "android/apns-conf.xml").getroot()
        assert_true(apn_root.attrib["version"] == "8", "APN XML should target version 8")
        apn_rows = [
            dict(element.attrib)
            for element in apn_root
        ]
        assert_true(len(apn_rows) == 7, f"expected 7 APN rows, got {len(apn_rows)}")
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
            "always_on": "true",
            "esim_bootstrap_provisioning": "false",
        }.items():
            assert_true(internet_row[key] == value, f"APN row should preserve {key}")
        assert_true(
            "skip_464xlat" not in internet_row,
            "skip_464xlat -1 is TelephonyProvider's default, which LineageOS's "
            "schema does not accept as a value, so the row leaves it out",
        )
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
        for mnc in ("02", "23"):
            ims_row = by_apn[("262", mnc, "ims.example")]
            assert_true(
                ims_row["mvno_type"] == "gid"
                and ims_row["mvno_match_data"] == "AB"
                and ims_row["carrier_id"] == "2536",
                "carrier-ID plus GID profiles emit network rows with both selectors",
            )
        carrier_id_row = by_apn[("262", "27", "cid.example")]
        assert_true(
            carrier_id_row["carrier_id"] == "4000",
            "carrier-ID profiles keep mcc and mnc and add carrier_id, as AOSP does",
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

        for name in ("mccmnc-index.json", "carrier-id-index.json", "carrier-config-overrides.json"):
            assert_true(
                not (generated_dir / "android" / name).exists(),
                f"{name} is no longer published: only the validator read it",
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
            metadata["target"]
            == {
                "apn_database_version": 8,
                "carrier_config_gid_matching": "omitted",
                "carrier_config_iccid_matching": "omitted",
            },
            "metadata must say that GID and ICCID profiles are left out of the CarrierConfig XML",
        )
        assert_true(
            not any(
                key in node.attrib
                for node in config_nodes
                for key in ("gid1", "gid2", "iccid")
            ),
            "the CarrierConfig XML carries no GID or ICCID filter",
        )
        assert_true(
            metadata["omissions"]["carrier_config_profiles_with_unrepresentable_match"] == 2,
            "metadata should count CarrierConfig profiles omitted to avoid broadening matches",
        )
        assert_true(
            metadata["omissions"]["apn_profile_ids_with_unrepresentable_match"]
            == [gid2_id],
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

        def unassigned_profile(codes: list[str]) -> dict:
            value = {
                "schema_version": 1,
                "display_name": "Example",
                "match": {"mccmnc": codes},
                "capabilities": {},
                "android_apns": [{"name": "Example", "apn": "internet.example", "types": ["default"]}],
            }
            value["profile_id"] = validate_public_carrier_data.canonical_profile_id(value["match"])
            return value

        # Sony's "Virgin Mobile US" on 200053, NRJ on 20901 and Samsung IMS's
        # "MOBILY SA" on 96654: no SIM carries these MCCs.
        for codes in (["200053"], ["20901"], ["96654"], ["000000"], ["25851", "96656"]):
            try:
                validate_public_carrier_data.validate_profile_object(
                    root / "unassigned.json", unassigned_profile(codes)
                )
            except validate_public_carrier_data.ValidationError as exc:
                assert_true("ITU-T E.212" in str(exc), f"wrong unassigned MCC error: {exc}")
            else:
                raise AssertionError(f"a profile on unassigned MCCs only passed: {codes}")
        # The shared code 901, private networks (999), the test MCC 001 and a
        # profile with one assigned code pass this check.
        for codes in (["90137"], ["99999"], ["00101"], ["26202", "96654"]):
            validate_public_carrier_data.validate_profile_object(
                root / "assigned.json", unassigned_profile(sorted(codes))
            )
        assert_true(
            len(validate_public_carrier_data.ASSIGNED_MCCS) == 242
            and {"001", "901", "902", "991", "999"} <= validate_public_carrier_data.ASSIGNED_MCCS
            and not {"000", "200", "209", "233", "254", "258", "966"}
            & validate_public_carrier_data.ASSIGNED_MCCS,
            "the validator's MCC list is the ITU list plus 001 and 999",
        )

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

        check_subscriber_prefix_rules(root)

    print("generated Android output tests passed")
    with tempfile.TemporaryDirectory() as tmp:
        apns_path = Path(tmp) / "apns-conf.xml"
        twins = [
            {
                "match": {"mccmnc": ["00101"]},
                "android_apns": [
                    {"name": name, "apn": "internet", "types": ["default"], "protocol": "IP"}
                ],
                "display_name": name,
            }
            for name in ("First label", "Second label")
        ]
        count = generate_android_outputs.write_apns(apns_path, twins, 8)
        assert_true(
            count == 1 and 'carrier="First label"' in apns_path.read_text(encoding="utf-8"),
            "Rows identical except their label must collapse to the first",
        )
    check_no_country_export()
    print("no per-country export tests passed")
    check_lineageos_schema_rules()
    print("LineageOS schema rule tests passed")
    check_apn_ranking()
    print("APN ranking tests passed")
    check_current_vendor_attach()
    print("current vendor and attach type tests passed")
    check_shared_file_and_malformed_values()
    print("shared-file and malformed APN value tests passed")
    check_proxy_free_first()
    print("proxy-free internet row tests passed")
    check_malformed_values_stay()
    print("malformed APN value tests passed")
    check_best_row_last()
    print("best row last tests passed")
    check_vendor_mms_first()
    print("vendor MMS row tests passed")
    check_leave_out_absorbed_mms()
    print("absorbed MMS row tests passed")
    with tempfile.TemporaryDirectory() as tmp:
        check_apn_value_rules(Path(tmp))
    print("APN value rule tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
