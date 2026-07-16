#!/usr/bin/env python3
"""Regression tests for generated Android output."""

from __future__ import annotations

from copy import deepcopy
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Callable

import generate_android_outputs
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
                    "revision_date": date.today().isoformat(),
                    "checked_at": date.today().isoformat(),
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
                "checked_at": date.today().isoformat(),
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
                "checked_at": date.today().isoformat(),
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
                "checked_at": date.today().isoformat(),
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
        today = date.today().isoformat()
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
                "model_source_provenance": "complete",
                "source_snapshots": [],
                "profiles": [
                    {
                        "profile_id": profile_id,
                        "observation_count": 1,
                        "sources": ["aosp", "lineageos"],
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
