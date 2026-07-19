#!/usr/bin/env python3
"""Adversarial tests for the schema-version-2 carrier-relevance contract."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
from typing import Callable

import validate_device_catalog as catalog


PATH = Path("synthetic-carrier-relevance.json")
ANDROID_ID = "android:" + "a" * 20
APPLE_ID = "apple:" + "a" * 20


def assert_rejected(action: Callable[[], object], message: str) -> None:
    try:
        action()
    except catalog.ValidationError:
        return
    raise AssertionError(message)


def source(name: str) -> dict[str, str]:
    today = date.today().isoformat()
    return {
        "name": name,
        "url": f"https://example.com/{name}",
        "revision": "0" * 64,
        "revision_date": today,
        "checked_at": today,
    }


def device(platform: str, device_id: str, source_name: str) -> dict:
    return {
        "device_id": device_id,
        "platform": platform,
        "identity_basis": "synthetic_exact_identity",
        "brands": ["Synthetic"],
        "device_names": ["synthetic-device"],
        "models": ["Synthetic-1"],
        "marketing_names": ["Synthetic Device"],
        "inventory_status": "present",
        "inventory_sources": [
            {
                "source": source_name,
                "status": "present",
                "first_seen_revision": "0" * 64,
                "last_changed_revision": "0" * 64,
            }
        ],
        "carrier_data_coverage": {"status": "inventory_only", "sources": []},
        "carrier_relevance": {"status": "not_established", "evidence": []},
    }


def inventory(
    platform: str,
    records: list[dict],
    sources: list[dict[str, str]],
    *,
    schema_version: int = 2,
) -> dict:
    return {
        "schema_version": schema_version,
        "inventory_id": f"synthetic_{platform}_inventory",
        "platform": platform,
        "description": "Synthetic carrier-relevance inventory.",
        "sources": sorted(sources, key=lambda item: item["name"]),
        "devices": records,
    }


def validate_inventory(tmp: Path, value: dict, platform: str) -> tuple:
    path = tmp / f"{platform}.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return catalog.validate_inventory(path, platform)


def zero_relevance_counts() -> dict[str, int]:
    return {status: 0 for status in sorted(catalog.CARRIER_RELEVANCE_STATUSES)}


def relevance_summaries(records: list[dict]) -> tuple[dict, dict]:
    counts = zero_relevance_counts()
    matrix = {
        coverage: zero_relevance_counts()
        for coverage in sorted(catalog.DATA_COVERAGE_STATUSES)
    }
    for record in records:
        relevance = record["carrier_relevance"]["status"]
        coverage = record["carrier_data_coverage"]["status"]
        counts[relevance] += 1
        matrix[coverage][relevance] += 1
    return counts, matrix


def platform_summary(records: list[dict], *, android: bool) -> dict:
    coverage_counts: dict[str, int] = {}
    coverage_by_brand: dict[str, dict[str, int]] = {}
    brand_counts: dict[str, int] = {}
    for record in records:
        status = record["carrier_data_coverage"]["status"]
        brand = (record.get("brands") or ["(not provided by source)"])[0]
        coverage_counts[status] = coverage_counts.get(status, 0) + 1
        brand_statuses = coverage_by_brand.setdefault(brand, {})
        brand_statuses[status] = brand_statuses.get(status, 0) + 1
        if record["inventory_status"] == "present":
            brand_counts[brand] = brand_counts.get(brand, 0) + 1
    relevance_counts, relevance_matrix = relevance_summaries(records)
    summary = {
        "carrier_observation_match_count": sum(
            "carrier_observations" in record for record in records
        ),
        "carrier_data_coverage_counts": dict(sorted(coverage_counts.items())),
        "carrier_data_coverage_counts_by_brand": {
            brand: dict(sorted(statuses.items()))
            for brand, statuses in sorted(
                coverage_by_brand.items(), key=lambda item: item[0].casefold()
            )
        },
        "carrier_relevance_counts": relevance_counts,
        "carrier_relevance_by_coverage": relevance_matrix,
        "device_count": len(records),
        "historical_device_count": sum(
            record["inventory_status"] == "historical" for record in records
        ),
        "present_device_count": sum(
            record["inventory_status"] == "present" for record in records
        ),
        "present_device_count_by_brand": dict(
            sorted(brand_counts.items(), key=lambda item: (item[0].casefold(), item[0]))
        ),
    }
    if android:
        summary.update(
            {
                "carrier_artifact_match_count": sum(
                    "carrier_source_catalogs" in record for record in records
                ),
                "carrier_source_discovery_match_count": sum(
                    "carrier_source_discovery" in record for record in records
                ),
            }
        )
    else:
        summary.update(
            {
                "exact_artifact_scope_match_count": sum(
                    record.get("carrier_artifact_catalog", {}).get("match_kind")
                    == "exact_product_type"
                    for record in records
                ),
                "family_artifact_scope_match_count": sum(
                    record.get("carrier_artifact_catalog", {}).get("match_kind")
                    == "product_family"
                    for record in records
                ),
            }
        )
    return summary


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    inventory_schema = json.loads(
        (repository / "schemas/device-inventory.schema.json").read_text(encoding="utf-8")
    )
    index_schema = json.loads(
        (repository / "schemas/device-catalog-index.schema.json").read_text(
            encoding="utf-8"
        )
    )
    relevance_schema = inventory_schema["$defs"]["device"]["properties"][
        "carrier_relevance"
    ]
    assert set(relevance_schema["properties"]["status"]["enum"]) == (
        catalog.CARRIER_RELEVANCE_STATUSES
    )
    assert set(
        inventory_schema["$defs"]["carrier_relevance_evidence"]["properties"][
            "kind"
        ]["enum"]
    ) == catalog.CARRIER_RELEVANCE_EVIDENCE_KINDS
    device_rules = inventory_schema["$defs"]["device"]["allOf"]
    platform_rules = {
        rule["if"]["properties"]["platform"]["const"]: rule
        for rule in device_rules
        if "platform" in rule.get("if", {}).get("properties", {})
    }
    for platform, expected_kinds in (
        catalog.CARRIER_RELEVANCE_EVIDENCE_KINDS_BY_PLATFORM.items()
    ):
        schema_kinds = set(
            platform_rules[platform]["then"]["properties"]["carrier_relevance"]
            ["properties"]["evidence"]["items"]["properties"]["kind"]["enum"]
        )
        assert schema_kinds == expected_kinds
    assert set().union(
        *catalog.CARRIER_RELEVANCE_EVIDENCE_KINDS_BY_PLATFORM.values()
    ) == catalog.CARRIER_RELEVANCE_EVIDENCE_KINDS

    evidence_backing_rules = {}
    for rule in device_rules:
        contains = (
            rule.get("if", {})
            .get("properties", {})
            .get("carrier_relevance", {})
            .get("properties", {})
            .get("evidence", {})
            .get("contains", {})
        )
        kind = contains.get("properties", {}).get("kind", {}).get("const")
        if kind:
            evidence_backing_rules[kind] = rule["then"]
    observation_backing = evidence_backing_rules["exact_carrier_observation"]
    assert observation_backing["properties"]["platform"] == {"const": "android"}
    assert observation_backing["properties"]["carrier_observations"]["properties"][
        "matched_identifiers"
    ]["items"]["pattern"].startswith("^android:")
    extraction_backing = evidence_backing_rules["extracted_carrier_configuration"]
    extraction_catalog = extraction_backing["properties"]["carrier_source_catalogs"]
    assert extraction_backing["properties"]["platform"] == {"const": "android"}
    assert extraction_catalog["items"]["properties"]["match_kind"] == {
        "const": "exact_device_id"
    }
    assert extraction_catalog["items"]["properties"]["matched_identifiers"][
        "items"
    ]["pattern"].startswith("^android:")
    bundle_backing = evidence_backing_rules["exact_product_type_carrier_bundle"]
    assert bundle_backing["properties"]["platform"] == {"const": "apple"}
    assert bundle_backing["properties"]["carrier_artifact_catalog"]["properties"][
        "match_kind"
    ] == {"const": "exact_product_type"}
    assert set(index_schema["$defs"]["relevance_counts"]["required"]) == (
        catalog.CARRIER_RELEVANCE_STATUSES
    )
    assert set(index_schema["$defs"]["relevance_by_coverage"]["required"]) == (
        catalog.DATA_COVERAGE_STATUSES
    )

    inventory_source = source("inventory_source")
    other_source = source("other_source")
    bundle_source = source("apple_carrier_bundles")
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        base = device("android", ANDROID_ID, "inventory_source")
        version, _, records = validate_inventory(
            tmp, inventory("android", [base], [inventory_source]), "android"
        )
        assert version == 2 and records == [base]

        missing_relevance = deepcopy(base)
        del missing_relevance["carrier_relevance"]
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("android", [missing_relevance], [inventory_source]),
                "android",
            ),
            "v2 inventory accepted a device without carrier relevance",
        )

        for invalid_status in (0, 1, False, True, "unknown"):
            invalid = deepcopy(base)
            invalid["carrier_relevance"]["status"] = invalid_status
            assert_rejected(
                lambda value=invalid: validate_inventory(
                    tmp, inventory("android", [value], [inventory_source]), "android"
                ),
                f"carrier relevance accepted invalid status {invalid_status!r}",
            )

        for invalid_evidence in (0, 1, False, True, {}):
            invalid = deepcopy(base)
            invalid["carrier_relevance"]["evidence"] = invalid_evidence
            assert_rejected(
                lambda value=invalid: validate_inventory(
                    tmp, inventory("android", [value], [inventory_source]), "android"
                ),
                f"carrier relevance accepted invalid evidence {invalid_evidence!r}",
            )

        confirmed_without_evidence = deepcopy(base)
        confirmed_without_evidence["carrier_relevance"]["status"] = (
            "evidence_confirmed_cellular"
        )
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("android", [confirmed_without_evidence], [inventory_source]),
                "android",
            ),
            "confirmed relevance accepted empty evidence",
        )

        official = {
            "kind": "official_connectivity_specification",
            "source": "inventory_source",
        }
        established = deepcopy(base)
        established["carrier_relevance"] = {
            "status": "evidence_confirmed_cellular",
            "evidence": [official],
        }
        validate_inventory(
            tmp, inventory("android", [established], [inventory_source]), "android"
        )
        for unbacked_kind in (
            "exact_carrier_observation",
            "extracted_carrier_configuration",
            "exact_product_type_carrier_bundle",
        ):
            unbacked = deepcopy(established)
            unbacked["carrier_relevance"]["evidence"] = [
                {"kind": unbacked_kind, "source": "inventory_source"}
            ]
            assert_rejected(
                lambda value=unbacked: validate_inventory(
                    tmp, inventory("android", [value], [inventory_source]), "android"
                ),
                f"carrier relevance accepted unbacked {unbacked_kind}",
            )
        unestablished_with_evidence = deepcopy(established)
        unestablished_with_evidence["carrier_relevance"]["status"] = "not_established"
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("android", [unestablished_with_evidence], [inventory_source]),
                "android",
            ),
            "not-established relevance accepted evidence",
        )

        for field in ("kind", "source"):
            for invalid_value in (0, 1, False, True):
                invalid = deepcopy(established)
                invalid["carrier_relevance"]["evidence"][0][field] = invalid_value
                assert_rejected(
                    lambda value=invalid: validate_inventory(
                        tmp,
                        inventory("android", [value], [inventory_source]),
                        "android",
                    ),
                    f"relevance evidence accepted {field}={invalid_value!r}",
                )
        unknown_kind = deepcopy(established)
        unknown_kind["carrier_relevance"]["evidence"][0]["kind"] = "unknown"
        assert_rejected(
            lambda: validate_inventory(
                tmp, inventory("android", [unknown_kind], [inventory_source]), "android"
            ),
            "carrier relevance accepted an unknown evidence kind",
        )

        unrelated = deepcopy(established)
        unrelated["carrier_relevance"]["evidence"][0]["source"] = "other_source"
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory(
                    "android", [unrelated], [inventory_source, other_source]
                ),
                "android",
            ),
            "carrier relevance accepted a declared but device-unassociated source",
        )

        two_evidence = [
            official,
            {
                "kind": "official_connectivity_variant",
                "source": "inventory_source",
            },
        ]
        duplicate = deepcopy(established)
        duplicate["carrier_relevance"]["evidence"] = [official, official]
        unsorted = deepcopy(established)
        unsorted["carrier_relevance"]["evidence"] = list(reversed(two_evidence))
        for invalid, label in ((duplicate, "duplicate"), (unsorted, "unsorted")):
            assert_rejected(
                lambda value=invalid: validate_inventory(
                    tmp, inventory("android", [value], [inventory_source]), "android"
                ),
                f"carrier relevance accepted {label} evidence",
            )
        both_official_kinds = deepcopy(established)
        both_official_kinds["carrier_relevance"]["evidence"] = two_evidence
        validate_inventory(
            tmp,
            inventory("android", [both_official_kinds], [inventory_source]),
            "android",
        )

        authentication_terminal = deepcopy(base)
        authentication_terminal["inventory_sources"].append(
            {
                "source": "other_source",
                "status": "present",
                "first_seen_revision": "0" * 64,
                "last_changed_revision": "0" * 64,
            }
        )
        authentication_terminal["carrier_source_discovery"] = [
            {
                "source": "inventory_source",
                "matched_identifiers": [ANDROID_ID],
                "scope_count": 1,
                "status_counts": {"source_authentication_required": 1},
            }
        ]
        authentication_terminal["carrier_data_coverage"] = {
            "status": "source_authentication_required",
            "sources": ["inventory_source"],
        }
        authentication_terminal["carrier_relevance"] = {
            "status": "evidence_confirmed_cellular",
            "evidence": [
                {
                    "kind": "official_connectivity_specification",
                    "source": "other_source",
                }
            ],
        }
        validate_inventory(
            tmp,
            inventory(
                "android",
                [authentication_terminal],
                [inventory_source, other_source],
            ),
            "android",
        )

        for observation_source in ("inventory_source", "other_source"):
            authentication_observed = deepcopy(authentication_terminal)
            authentication_observed["carrier_observations"] = {
                "matched_identifiers": [ANDROID_ID],
                "profile_count": 1,
                "sources": [observation_source],
            }
            authentication_observed["carrier_relevance"] = {
                "status": "evidence_confirmed_cellular",
                "evidence": [
                    {
                        "kind": "exact_carrier_observation",
                        "source": observation_source,
                    }
                ],
            }
            assert_rejected(
                lambda value=authentication_observed: validate_inventory(
                    tmp,
                    inventory(
                        "android",
                        [value],
                        [inventory_source, other_source],
                    ),
                    "android",
                ),
                "schema-v2 authentication terminal accepted exact observation "
                f"evidence from {observation_source}",
            )

        for catalog_source in ("inventory_source", "other_source"):
            authentication_cataloged = deepcopy(authentication_terminal)
            authentication_cataloged["carrier_source_catalogs"] = [
                {
                    "source": catalog_source,
                    "match_kind": "exact_device_id",
                    "matched_identifiers": [ANDROID_ID],
                    "artifact_count": 1,
                    "indexed_artifact_count": 1,
                    "extracted_artifact_count": 0,
                }
            ]
            assert_rejected(
                lambda value=authentication_cataloged: validate_inventory(
                    tmp,
                    inventory(
                        "android",
                        [value],
                        [inventory_source, other_source],
                    ),
                    "android",
                ),
                "schema-v2 authentication terminal accepted source-catalog "
                f"evidence from {catalog_source}",
            )

        for authentication_source in (
            "inventory_source",
            "apple_carrier_bundles",
        ):
            authentication_artifact = device(
                "android", ANDROID_ID, authentication_source
            )
            authentication_artifact["carrier_source_discovery"] = [
                {
                    "source": authentication_source,
                    "matched_identifiers": [ANDROID_ID],
                    "scope_count": 1,
                    "status_counts": {"source_authentication_required": 1},
                }
            ]
            authentication_artifact["carrier_data_coverage"] = {
                "status": "source_authentication_required",
                "sources": [authentication_source],
            }
            authentication_artifact["carrier_relevance"] = {
                "status": "evidence_confirmed_cellular",
                "evidence": [
                    {
                        "kind": "official_connectivity_specification",
                        "source": authentication_source,
                    }
                ],
            }
            authentication_artifact["carrier_artifact_catalog"] = {
                "artifact_count": 1,
                "match_kind": "exact_product_type",
                "scopes": ["Synthetic1,1"],
                "source": "apple_carrier_bundles",
                "verified_artifact_count": 1,
            }
            declared_sources = [bundle_source]
            if authentication_source != "apple_carrier_bundles":
                declared_sources.append(inventory_source)
            assert_rejected(
                lambda value=authentication_artifact, sources=declared_sources: validate_inventory(
                    tmp,
                    inventory("android", [value], sources),
                    "android",
                ),
                "schema-v2 authentication terminal accepted an Apple artifact "
                f"catalog with authentication source {authentication_source}",
            )

        observed = deepcopy(base)
        observed["carrier_observations"] = {
            "matched_identifiers": [ANDROID_ID],
            "profile_count": 1,
            "sources": ["inventory_source"],
        }
        observed["carrier_data_coverage"] = {
            "status": "exact_carrier_data_observed",
            "sources": ["inventory_source"],
        }
        observed["carrier_relevance"] = {
            "status": "evidence_confirmed_cellular",
            "evidence": [
                {
                    "kind": "exact_carrier_observation",
                    "source": "inventory_source",
                }
            ],
        }
        validate_inventory(
            tmp, inventory("android", [observed], [inventory_source]), "android"
        )
        for wrong_observation_id, label in (
            ("android:" + "b" * 20, "wrong device"),
            (APPLE_ID, "wrong platform"),
        ):
            wrong_observation = deepcopy(observed)
            wrong_observation["carrier_observations"]["matched_identifiers"] = [
                wrong_observation_id
            ]
            assert_rejected(
                lambda value=wrong_observation: validate_inventory(
                    tmp, inventory("android", [value], [inventory_source]), "android"
                ),
                f"observation relevance accepted a {label} identifier",
            )
        conflicting_observed = deepcopy(observed)
        conflicting_observed["carrier_relevance"]["status"] = (
            "evidence_confirmed_non_cellular"
        )
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("android", [conflicting_observed], [inventory_source]),
                "android",
            ),
            "non-cellular classification accepted conflicting cellular evidence",
        )

        extracted = deepcopy(base)
        extracted["carrier_source_catalogs"] = [
            {
                "source": "inventory_source",
                "match_kind": "exact_device_id",
                "matched_identifiers": [ANDROID_ID],
                "artifact_count": 1,
                "indexed_artifact_count": 0,
                "extracted_artifact_count": 1,
            }
        ]
        extracted["carrier_data_coverage"] = {
            "status": "exact_source_extracted",
            "sources": ["inventory_source"],
        }
        extracted["carrier_relevance"] = {
            "status": "evidence_confirmed_cellular",
            "evidence": [
                {
                    "kind": "extracted_carrier_configuration",
                    "source": "inventory_source",
                }
            ],
        }
        validate_inventory(
            tmp, inventory("android", [extracted], [inventory_source]), "android"
        )
        for wrong_catalog_id, label in (
            ("android:" + "b" * 20, "wrong device"),
            (APPLE_ID, "wrong platform"),
        ):
            wrong_catalog = deepcopy(extracted)
            wrong_catalog["carrier_source_catalogs"][0]["matched_identifiers"] = [
                wrong_catalog_id
            ]
            assert_rejected(
                lambda value=wrong_catalog: validate_inventory(
                    tmp, inventory("android", [value], [inventory_source]), "android"
                ),
                f"extracted relevance accepted a {label} catalog identifier",
            )
        model_bound_catalog = deepcopy(extracted)
        model_bound_catalog["carrier_source_catalogs"][0]["match_kind"] = "exact_model"
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("android", [model_bound_catalog], [inventory_source]),
                "android",
            ),
            "extracted relevance accepted a model-bound source catalog",
        )

        exact_bundle = device("apple", APPLE_ID, "apple_carrier_bundles")
        exact_bundle["carrier_artifact_catalog"] = {
            "artifact_count": 1,
            "match_kind": "exact_product_type",
            "scopes": ["Synthetic1,1"],
            "source": "apple_carrier_bundles",
            "verified_artifact_count": 1,
        }
        exact_bundle["carrier_data_coverage"] = {
            "status": "exact_source_verified",
            "sources": ["apple_carrier_bundles"],
        }
        exact_bundle["carrier_relevance"] = {
            "status": "evidence_confirmed_cellular",
            "evidence": [
                {
                    "kind": "exact_product_type_carrier_bundle",
                    "source": "apple_carrier_bundles",
                }
            ],
        }
        validate_inventory(
            tmp, inventory("apple", [exact_bundle], [bundle_source]), "apple"
        )

        android_bundle = device("android", ANDROID_ID, "apple_carrier_bundles")
        android_bundle["carrier_artifact_catalog"] = deepcopy(
            exact_bundle["carrier_artifact_catalog"]
        )
        android_bundle["carrier_data_coverage"] = deepcopy(
            exact_bundle["carrier_data_coverage"]
        )
        android_bundle["carrier_relevance"] = deepcopy(
            exact_bundle["carrier_relevance"]
        )
        assert_rejected(
            lambda: validate_inventory(
                tmp, inventory("android", [android_bundle], [bundle_source]), "android"
            ),
            "Android relevance accepted Apple exact-bundle evidence",
        )

        apple_extracted = device("apple", APPLE_ID, "inventory_source")
        apple_extracted["carrier_source_catalogs"] = deepcopy(
            extracted["carrier_source_catalogs"]
        )
        apple_extracted["carrier_source_catalogs"][0]["matched_identifiers"] = [
            APPLE_ID
        ]
        apple_extracted["carrier_data_coverage"] = deepcopy(
            extracted["carrier_data_coverage"]
        )
        apple_extracted["carrier_relevance"] = deepcopy(
            extracted["carrier_relevance"]
        )
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("apple", [apple_extracted], [inventory_source]),
                "apple",
            ),
            "Apple relevance accepted Android extraction evidence",
        )

        apple_observed = device("apple", APPLE_ID, "inventory_source")
        apple_observed["carrier_observations"] = deepcopy(
            observed["carrier_observations"]
        )
        apple_observed["carrier_observations"]["matched_identifiers"] = [APPLE_ID]
        apple_observed["carrier_data_coverage"] = deepcopy(
            observed["carrier_data_coverage"]
        )
        apple_observed["carrier_relevance"] = deepcopy(observed["carrier_relevance"])
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("apple", [apple_observed], [inventory_source]),
                "apple",
            ),
            "Apple relevance accepted Android observation evidence",
        )

        out_of_scope = deepcopy(base)
        out_of_scope["carrier_source_discovery"] = [
            {
                "source": "inventory_source",
                "matched_identifiers": [ANDROID_ID],
                "scope_count": 1,
                "status_counts": {"platform_out_of_scope": 1},
            }
        ]
        out_of_scope["carrier_data_coverage"] = {
            "status": "platform_out_of_scope",
            "sources": ["inventory_source"],
        }
        validate_inventory(
            tmp, inventory("android", [out_of_scope], [inventory_source]), "android"
        )
        assert out_of_scope["carrier_relevance"]["status"] == "not_established"

        android_not_applicable = deepcopy(base)
        android_not_applicable["carrier_source_discovery"] = [
            {
                "source": "inventory_source",
                "matched_identifiers": [ANDROID_ID],
                "scope_count": 1,
                "status_counts": {"carrier_data_not_applicable": 1},
            }
        ]
        android_not_applicable["carrier_data_coverage"] = {
            "status": "carrier_data_not_applicable",
            "sources": ["inventory_source"],
        }
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory(
                    "android", [android_not_applicable], [inventory_source]
                ),
                "android",
            ),
            "v2 Android not-applicable coverage passed without non-cellular evidence",
        )
        explicit_android_non_cellular = deepcopy(android_not_applicable)
        explicit_android_non_cellular["carrier_relevance"] = {
            "status": "evidence_confirmed_non_cellular",
            "evidence": [official],
        }
        validate_inventory(
            tmp,
            inventory(
                "android", [explicit_android_non_cellular], [inventory_source]
            ),
            "android",
        )

        non_cellular_without_not_applicable = deepcopy(base)
        non_cellular_without_not_applicable["carrier_relevance"] = {
            "status": "evidence_confirmed_non_cellular",
            "evidence": [official],
        }
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory(
                    "android",
                    [non_cellular_without_not_applicable],
                    [inventory_source],
                ),
                "android",
            ),
            "v2 non-cellular relevance passed without not-applicable coverage",
        )

        for family, marketing_name in (("AppleTV", "Apple TV"), ("iPod", "iPod touch")):
            apple = device("apple", APPLE_ID, "inventory_source")
            apple["family"] = family
            apple["marketing_names"] = [marketing_name]
            validate_inventory(
                tmp, inventory("apple", [apple], [inventory_source]), "apple"
            )
            inferred = deepcopy(apple)
            inferred["carrier_data_coverage"] = {
                "status": "carrier_data_not_applicable",
                "sources": [],
            }
            assert_rejected(
                lambda value=inferred: validate_inventory(
                    tmp, inventory("apple", [value], [inventory_source]), "apple"
                ),
                f"v2 inferred non-cellular relevance from {family}",
            )
            explicit = deepcopy(inferred)
            explicit["carrier_relevance"] = {
                "status": "evidence_confirmed_non_cellular",
                "evidence": [official],
            }
            validate_inventory(
                tmp, inventory("apple", [explicit], [inventory_source]), "apple"
            )

        wrong_android_id = deepcopy(established)
        wrong_android_id["device_id"] = APPLE_ID
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("android", [wrong_android_id], [inventory_source]),
                "android",
            ),
            "v2 Android inventory accepted an Apple ID",
        )
        wrong_apple_id = device("apple", ANDROID_ID, "inventory_source")
        wrong_apple_id["carrier_relevance"] = {
            "status": "evidence_confirmed_cellular",
            "evidence": [official],
        }
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory("apple", [wrong_apple_id], [inventory_source]),
                "apple",
            ),
            "v2 Apple inventory accepted an Android ID",
        )

        legacy_apple = device("apple", APPLE_ID, "inventory_source")
        del legacy_apple["carrier_relevance"]
        legacy_apple["family"] = "AppleTV"
        legacy_apple["carrier_data_coverage"] = {
            "status": "carrier_data_not_applicable",
            "sources": [],
        }
        legacy_version, _, _ = validate_inventory(
            tmp,
            inventory(
                "apple", [legacy_apple], [inventory_source], schema_version=1
            ),
            "apple",
        )
        assert legacy_version == 1
        legacy_with_v2_field = deepcopy(legacy_apple)
        legacy_with_v2_field["carrier_relevance"] = {
            "status": "not_established",
            "evidence": [],
        }
        assert_rejected(
            lambda: validate_inventory(
                tmp,
                inventory(
                    "apple",
                    [legacy_with_v2_field],
                    [inventory_source],
                    schema_version=1,
                ),
                "apple",
            ),
            "v1 inventory accepted a v2 carrier-relevance field",
        )

        index_android = deepcopy(out_of_scope)
        index_apple = device("apple", APPLE_ID, "other_source")
        index_sources = [inventory_source, other_source]
        index = {
            "schema_version": 2,
            "description": "Synthetic v2 carrier-relevance index.",
            "generated_from_checks_through": date.today().isoformat(),
            "sources": index_sources,
            "platforms": {
                "android": platform_summary([index_android], android=True),
                "apple": platform_summary([index_apple], android=False),
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
        index_path = tmp / "index.json"

        def validate_index(value: dict) -> None:
            index_path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            catalog.validate_index(
                index_path,
                [inventory_source],
                [index_android],
                [other_source],
                [index_apple],
                other_source,
                [],
                [inventory_source],
                [],
                inventory_schema_versions=(2, 2),
            )

        validate_index(index)
        matrix_drift = deepcopy(index)
        matrix_drift["platforms"]["android"]["carrier_relevance_by_coverage"][
            "platform_out_of_scope"
        ]["not_established"] += 1
        assert_rejected(
            lambda: validate_index(matrix_drift),
            "v2 index accepted relevance-by-coverage matrix drift",
        )
        total_drift = deepcopy(index)
        total_drift["platforms"]["apple"]["carrier_relevance_counts"][
            "not_established"
        ] += 1
        assert_rejected(
            lambda: validate_index(total_drift),
            "v2 index accepted carrier-relevance total drift",
        )
        missing_zero_cell = deepcopy(index)
        del missing_zero_cell["platforms"]["apple"][
            "carrier_relevance_by_coverage"
        ]["inventory_only"]["evidence_confirmed_cellular"]
        assert_rejected(
            lambda: validate_index(missing_zero_cell),
            "v2 index accepted an incomplete relevance matrix",
        )
        for invalid_count in (False, True, 0.0, 1.0):
            invalid = deepcopy(index)
            invalid["platforms"]["android"]["carrier_relevance_counts"][
                "not_established"
            ] = invalid_count
            assert_rejected(
                lambda value=invalid: validate_index(value),
                f"v2 relevance index accepted non-integer count {invalid_count!r}",
            )
        validate_index(index)
        assert_rejected(
            lambda: catalog.validate_index(
                index_path,
                [inventory_source],
                [index_android],
                [other_source],
                [index_apple],
                other_source,
                [],
                [inventory_source],
                [],
                inventory_schema_versions=(1, 2),
            ),
            "v2 index accepted mixed inventory schema versions",
        )

    print("carrier relevance contract tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
