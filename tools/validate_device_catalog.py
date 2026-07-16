#!/usr/bin/env python3
"""Validate the generated public device and carrier-artifact catalog."""

from __future__ import annotations

from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import sys
from typing import Any


HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DEVICE_ID_RE = re.compile(r"^(?:android|apple):[a-z0-9-]{3,80}$")
ANDROID_DEVICE_ID_RE = re.compile(r"^android:[a-z0-9-]{3,80}$")
APPLE_DEVICE_ID_RE = re.compile(r"^apple:[a-z0-9-]{3,80}$")
APPLE_ARTIFACT_ID_RE = re.compile(r"^apple:[0-9a-f]{24}$")
ANDROID_ARTIFACT_ID_RE = re.compile(r"^android:[0-9a-f]{24}$")
SOURCE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,63}$")
BASE_DEVICE_FIELDS = {
    "device_id",
    "platform",
    "identity_basis",
    "brands",
    "device_names",
    "models",
    "marketing_names",
    "family",
    "inventory_status",
    "inventory_sources",
    "carrier_observations",
    "carrier_artifact_catalog",
    "carrier_source_catalogs",
    "carrier_source_discovery",
    "carrier_data_coverage",
    "carrier_relevance",
}
DATA_COVERAGE_STATUSES = {
    "carrier_data_not_applicable",
    "exact_carrier_data_observed",
    "exact_source_extracted",
    "exact_source_verified",
    "exact_source_indexed",
    "family_source_verified",
    "family_source_indexed",
    "source_discovery_in_progress",
    "source_checked_no_artifact",
    "source_not_queryable",
    "platform_out_of_scope",
    "source_authentication_required",
    "source_transport_untrusted",
    "source_terms_restrict_extraction",
    "inventory_only",
}
ANDROID_SCOPE_KINDS = {"model", "device_id", "source_api_row"}
ANDROID_DISCOVERY_STATUSES = {
    "carrier_data_not_applicable",
    "discovery_in_progress",
    "no_artifact_found",
    "no_query_identifier",
    "artifact_indexed",
    "platform_out_of_scope",
    "source_extracted",
    "source_authentication_required",
    "source_transport_untrusted",
    "source_terms_restrict_extraction",
}
EXACT_ZERO_ARTIFACT_TERMINAL_STATUSES = {
    "source_authentication_required",
    "source_transport_untrusted",
}
AUTHENTICATION_TERMINAL_CONFLICT_FIELDS = {
    "carrier_observations",
    "carrier_artifact_catalog",
    "carrier_source_catalogs",
}
APPLE_NON_CELLULAR_FAMILIES = {"AppleTV", "AudioAccessory", "iPod"}
CARRIER_RELEVANCE_STATUSES = {
    "evidence_confirmed_cellular",
    "evidence_confirmed_non_cellular",
    "not_established",
}
CARRIER_RELEVANCE_EVIDENCE_KINDS = {
    "exact_carrier_observation",
    "extracted_carrier_configuration",
    "exact_product_type_carrier_bundle",
    "official_connectivity_specification",
    "official_connectivity_variant",
}
CARRIER_RELEVANCE_EVIDENCE_KINDS_BY_PLATFORM = {
    "android": {
        "exact_carrier_observation",
        "extracted_carrier_configuration",
        "official_connectivity_specification",
        "official_connectivity_variant",
    },
    "apple": {
        "exact_product_type_carrier_bundle",
        "official_connectivity_specification",
        "official_connectivity_variant",
    },
}
CELLULAR_ONLY_RELEVANCE_EVIDENCE_KINDS = {
    "exact_carrier_observation",
    "extracted_carrier_configuration",
    "exact_product_type_carrier_bundle",
}


class ValidationError(Exception):
    pass


def is_json_integer(value: Any) -> bool:
    """Return true only for JSON integers, never Python booleans."""

    return type(value) is int


def validate_nonnegative_count_tree(path: Path, label: str, value: Any) -> None:
    """Reject booleans, negative counts, and non-count leaves in nested summaries."""

    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ValidationError(f"{path}: {label} count keys are invalid")
            validate_nonnegative_count_tree(path, f"{label}.{key}", child)
        return
    if not is_json_integer(value) or value < 0:
        raise ValidationError(f"{path}: {label} must contain non-negative integer counts")


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: root must be an object")
    return value


def validate_date(path: Path, field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{path}: {field} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{path}: {field} must be an ISO date") from exc
    if parsed > date.today():
        raise ValidationError(f"{path}: {field} cannot be in the future")
    return value


def validate_source(path: Path, value: Any) -> dict[str, str]:
    expected = {"name", "url", "revision", "revision_date", "checked_at"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError(f"{path}: source object is invalid")
    if not isinstance(value["name"], str) or not SOURCE_NAME_RE.fullmatch(value["name"]):
        raise ValidationError(f"{path}: source name is invalid")
    if not isinstance(value["url"], str) or not value["url"].startswith("https://"):
        raise ValidationError(f"{path}: source URL must use HTTPS")
    if not isinstance(value["revision"], str) or not HASH_RE.fullmatch(value["revision"]):
        raise ValidationError(f"{path}: source revision is invalid")
    validate_date(path, "source.revision_date", value["revision_date"])
    validate_date(path, "source.checked_at", value["checked_at"])
    checked_at = date.fromisoformat(value["checked_at"])
    if (date.today() - checked_at).days > 180:
        raise ValidationError(f"{path}: source check is stale")
    return value


def validate_string_array(
    path: Path, label: str, value: Any, *, max_items: int = 10000
) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > max_items
        or any(not isinstance(item, str) or not item or len(item) > 500 for item in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError(f"{path}: {label} must be a unique string array")
    return value


def validate_observations(path: Path, device_id: str, value: Any) -> None:
    expected = {"matched_identifiers", "profile_count", "sources"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError(f"{path}: invalid carrier observations for {device_id}")
    matched = validate_string_array(
        path, "matched_identifiers", value["matched_identifiers"]
    )
    if matched != [device_id]:
        raise ValidationError(
            f"{path}: carrier observations are not bound to exact device ID {device_id}"
        )
    validate_string_array(path, "sources", value["sources"])
    if not is_json_integer(value["profile_count"]) or value["profile_count"] < 1:
        raise ValidationError(f"{path}: invalid profile count for {device_id}")


def validate_artifact_scope(path: Path, device_id: str, value: Any) -> None:
    expected = {
        "artifact_count",
        "match_kind",
        "scopes",
        "source",
        "verified_artifact_count",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError(f"{path}: invalid artifact catalog for {device_id}")
    if value["match_kind"] not in {"exact_product_type", "product_family"}:
        raise ValidationError(f"{path}: invalid artifact match kind for {device_id}")
    if value["source"] != "apple_carrier_bundles":
        raise ValidationError(f"{path}: invalid artifact source for {device_id}")
    validate_string_array(path, "artifact scopes", value["scopes"])
    if (
        not is_json_integer(value["artifact_count"])
        or value["artifact_count"] < 1
        or not is_json_integer(value["verified_artifact_count"])
        or not 0 <= value["verified_artifact_count"] <= value["artifact_count"]
    ):
        raise ValidationError(f"{path}: invalid artifact counts for {device_id}")


def validate_source_catalogs(path: Path, device_id: str, value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{path}: invalid source catalogs for {device_id}")
    previous_source = ""
    for item in value:
        expected = {
            "source",
            "match_kind",
            "matched_identifiers",
            "artifact_count",
            "indexed_artifact_count",
            "extracted_artifact_count",
        }
        if not isinstance(item, dict) or set(item) != expected:
            raise ValidationError(f"{path}: invalid source catalog for {device_id}")
        source = item["source"]
        if (
            not isinstance(source, str)
            or not SOURCE_NAME_RE.fullmatch(source)
            or source <= previous_source
        ):
            raise ValidationError(f"{path}: source catalogs are invalid or unsorted")
        if item["match_kind"] not in {"exact_device_id", "exact_model"}:
            raise ValidationError(f"{path}: invalid source match kind for {device_id}")
        matched_identifiers = validate_string_array(
            path, "matched identifiers", item["matched_identifiers"]
        )
        if item["match_kind"] == "exact_device_id" and matched_identifiers != [device_id]:
            raise ValidationError(
                f"{path}: exact-device source catalog is not bound to {device_id}"
            )
        counts = [
            item["artifact_count"],
            item["indexed_artifact_count"],
            item["extracted_artifact_count"],
        ]
        if any(not is_json_integer(count) or count < 0 for count in counts):
            raise ValidationError(f"{path}: invalid source artifact counts for {device_id}")
        if counts[0] < 1 or counts[1] + counts[2] != counts[0]:
            raise ValidationError(f"{path}: inconsistent source artifact counts for {device_id}")
        previous_source = source


def device_associated_sources(record: dict[str, Any]) -> set[str]:
    """Return sources explicitly joined to one exact device record."""

    sources = {
        state["source"]
        for state in record.get("inventory_sources") or []
        if isinstance(state, dict) and isinstance(state.get("source"), str)
    }
    observations = record.get("carrier_observations")
    if isinstance(observations, dict):
        sources.update(
            source
            for source in observations.get("sources") or []
            if isinstance(source, str)
        )
    artifact_catalog = record.get("carrier_artifact_catalog")
    if isinstance(artifact_catalog, dict) and isinstance(
        artifact_catalog.get("source"), str
    ):
        sources.add(artifact_catalog["source"])
    for field in ("carrier_source_catalogs", "carrier_source_discovery"):
        sources.update(
            item["source"]
            for item in record.get(field) or []
            if isinstance(item, dict) and isinstance(item.get("source"), str)
        )
    coverage = record.get("carrier_data_coverage")
    if isinstance(coverage, dict):
        sources.update(
            source
            for source in coverage.get("sources") or []
            if isinstance(source, str)
        )
    return sources


def validate_carrier_relevance(
    path: Path,
    device_id: str,
    record: dict[str, Any],
    declared_sources: set[str],
) -> None:
    """Validate explicit evidence without inferring relevance from labels or coverage."""

    platform = record.get("platform")
    platform_device_id_re = {
        "android": ANDROID_DEVICE_ID_RE,
        "apple": APPLE_DEVICE_ID_RE,
    }.get(platform)
    if (
        platform_device_id_re is None
        or not isinstance(device_id, str)
        or record.get("device_id") != device_id
        or not platform_device_id_re.fullmatch(device_id)
    ):
        raise ValidationError(
            f"{path}: carrier relevance device/platform binding is invalid"
        )
    value = record.get("carrier_relevance")
    if not isinstance(value, dict) or set(value) != {"status", "evidence"}:
        raise ValidationError(f"{path}: carrier relevance is missing for {device_id}")
    status = value["status"]
    if not isinstance(status, str) or status not in CARRIER_RELEVANCE_STATUSES:
        raise ValidationError(f"{path}: invalid carrier relevance status for {device_id}")
    evidence = value["evidence"]
    if not isinstance(evidence, list):
        raise ValidationError(f"{path}: carrier relevance evidence must be an array")
    if status == "not_established" and evidence:
        raise ValidationError(f"{path}: unestablished carrier relevance has evidence")
    if status != "not_established" and not evidence:
        raise ValidationError(f"{path}: confirmed carrier relevance lacks evidence")

    associated_sources = device_associated_sources(record)
    observations = record.get("carrier_observations") or {}
    observation_sources = (
        set(observations.get("sources") or [])
        if observations.get("matched_identifiers") == [device_id]
        else set()
    )
    extracted_sources = {
        item["source"]
        for item in record.get("carrier_source_catalogs") or []
        if is_json_integer(item.get("extracted_artifact_count"))
        and item["extracted_artifact_count"] > 0
        and item.get("match_kind") == "exact_device_id"
        and item.get("matched_identifiers") == [device_id]
    }
    artifact_catalog = record.get("carrier_artifact_catalog") or {}
    exact_bundle_sources = (
        {artifact_catalog.get("source")}
        if artifact_catalog.get("match_kind") == "exact_product_type"
        and isinstance(artifact_catalog.get("source"), str)
        else set()
    )
    previous_key: tuple[str, str] | None = None
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"kind", "source"}:
            raise ValidationError(f"{path}: invalid carrier relevance evidence for {device_id}")
        kind = item["kind"]
        source = item["source"]
        if (
            not isinstance(kind, str)
            or kind not in CARRIER_RELEVANCE_EVIDENCE_KINDS
            or kind not in CARRIER_RELEVANCE_EVIDENCE_KINDS_BY_PLATFORM[platform]
            or not isinstance(source, str)
            or not SOURCE_NAME_RE.fullmatch(source)
        ):
            raise ValidationError(f"{path}: invalid carrier relevance evidence for {device_id}")
        key = (kind, source)
        if previous_key is not None and key <= previous_key:
            raise ValidationError(
                f"{path}: carrier relevance evidence is duplicate or unsorted"
            )
        if source not in declared_sources or source not in associated_sources:
            raise ValidationError(
                f"{path}: carrier relevance source is not associated with {device_id}"
            )
        if kind == "exact_carrier_observation" and source not in observation_sources:
            raise ValidationError(
                f"{path}: relevance observation lacks exact observation evidence"
            )
        if kind == "extracted_carrier_configuration" and source not in extracted_sources:
            raise ValidationError(
                f"{path}: relevance extraction lacks extracted configuration evidence"
            )
        if kind == "exact_product_type_carrier_bundle" and source not in exact_bundle_sources:
            raise ValidationError(
                f"{path}: relevance bundle lacks exact product-type evidence"
            )
        previous_key = key

    if status == "evidence_confirmed_non_cellular":
        conflicting_kinds = {
            item["kind"] for item in evidence
        } & CELLULAR_ONLY_RELEVANCE_EVIDENCE_KINDS
        if conflicting_kinds:
            raise ValidationError(f"{path}: conflicting carrier relevance evidence")
        if observation_sources or extracted_sources or exact_bundle_sources:
            raise ValidationError(f"{path}: non-cellular relevance conflicts with carrier data")
        if (record.get("carrier_data_coverage") or {}).get("status") != (
            "carrier_data_not_applicable"
        ):
            raise ValidationError(
                f"{path}: non-cellular relevance requires not-applicable coverage"
            )
    if (
        status == "evidence_confirmed_cellular"
        and (record.get("carrier_data_coverage") or {}).get("status")
        == "carrier_data_not_applicable"
    ):
        raise ValidationError(f"{path}: cellular relevance conflicts with not-applicable coverage")


def validate_data_coverage(
    path: Path,
    device_id: str,
    record: dict[str, Any],
    *,
    schema_version: int = 1,
) -> None:
    value = record.get("carrier_data_coverage")
    if not isinstance(value, dict) or set(value) != {"status", "sources"}:
        raise ValidationError(f"{path}: carrier data coverage is missing for {device_id}")
    status = value["status"]
    if status not in DATA_COVERAGE_STATUSES:
        raise ValidationError(f"{path}: invalid carrier data coverage for {device_id}")
    sources = validate_string_array(path, "coverage sources", value["sources"])
    if status == "inventory_only" and sources:
        raise ValidationError(f"{path}: inventory-only device has carrier sources")
    if status not in {"inventory_only", "carrier_data_not_applicable"} and not sources:
        raise ValidationError(f"{path}: covered device has no carrier sources")
    if status == "source_authentication_required":
        conflict_fields = sorted(AUTHENTICATION_TERMINAL_CONFLICT_FIELDS & set(record))
        if conflict_fields:
            raise ValidationError(
                f"{path}: authentication-required coverage has carrier-bearing "
                f"device evidence: {conflict_fields[0]}"
            )
    if status == "carrier_data_not_applicable":
        if schema_version == 1:
            approved_apple = (
                record.get("platform") == "apple"
                and record.get("family") in APPLE_NON_CELLULAR_FAMILIES
                and not sources
            )
            evidenced_android = record.get("platform") == "android" and bool(sources)
        else:
            confirmed_non_cellular = (
                (record.get("carrier_relevance") or {}).get("status")
                == "evidence_confirmed_non_cellular"
            )
            approved_apple = (
                record.get("platform") == "apple"
                and confirmed_non_cellular
                and not sources
            )
            evidenced_android = (
                record.get("platform") == "android"
                and confirmed_non_cellular
                and bool(sources)
            )
        if not approved_apple and not evidenced_android:
            raise ValidationError(
                f"{path}: not-applicable coverage lacks approved exact evidence"
            )
    if status == "exact_carrier_data_observed" and "carrier_observations" not in record:
        raise ValidationError(f"{path}: observed coverage has no observations")
    if status == "exact_source_extracted" and not any(
        item["extracted_artifact_count"] > 0
        for item in record.get("carrier_source_catalogs") or []
    ):
        raise ValidationError(f"{path}: extracted coverage has no extracted artifact")
    if status in {"family_source_verified", "family_source_indexed"} and (
        record.get("carrier_artifact_catalog", {}).get("match_kind") != "product_family"
    ):
        raise ValidationError(f"{path}: family coverage has no family artifact")
    discovery_statuses: Counter[str] = Counter()
    for item in record.get("carrier_source_discovery") or []:
        discovery_statuses.update(item["status_counts"])
    if status == "source_discovery_in_progress" and not discovery_statuses[
        "discovery_in_progress"
    ]:
        raise ValidationError(f"{path}: in-progress coverage has no active discovery")
    if status == "source_checked_no_artifact" and (
        not discovery_statuses["no_artifact_found"]
        or discovery_statuses["discovery_in_progress"]
    ):
        raise ValidationError(f"{path}: no-artifact coverage is inconsistent")
    if status == "source_not_queryable" and set(discovery_statuses) != {
        "no_query_identifier"
    }:
        raise ValidationError(f"{path}: not-queryable coverage is inconsistent")
    for terminal_status in (
        "carrier_data_not_applicable",
        "platform_out_of_scope",
        "source_authentication_required",
        "source_transport_untrusted",
        "source_terms_restrict_extraction",
    ):
        if status == terminal_status and record.get("platform") == "android":
            terminal_sources = sorted(
                item["source"]
                for item in record.get("carrier_source_discovery") or []
                if terminal_status in item["status_counts"]
            )
            if set(discovery_statuses) != {terminal_status} or sources != terminal_sources:
                raise ValidationError(
                    f"{path}: {terminal_status} coverage lacks exact terminal evidence"
                )
    if (
        status
        in {
            "platform_out_of_scope",
            "source_authentication_required",
            "source_transport_untrusted",
            "source_terms_restrict_extraction",
        }
        and record.get("platform") != "android"
    ):
        raise ValidationError(f"{path}: {status} is only valid for Android inventory")


def validate_source_discovery(path: Path, device_id: str, value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{path}: invalid source discovery for {device_id}")
    previous_source = ""
    for item in value:
        expected = {"source", "matched_identifiers", "scope_count", "status_counts"}
        if not isinstance(item, dict) or set(item) != expected:
            raise ValidationError(f"{path}: invalid source discovery record for {device_id}")
        source = item["source"]
        if (
            not isinstance(source, str)
            or not SOURCE_NAME_RE.fullmatch(source)
            or source <= previous_source
        ):
            raise ValidationError(f"{path}: source discovery is invalid or unsorted")
        matched = validate_string_array(
            path, "source discovery identifiers", item["matched_identifiers"]
        )
        if matched != [device_id]:
            raise ValidationError(
                f"{path}: source discovery is not bound to exact device ID {device_id}"
            )
        counts = item["status_counts"]
        if (
            not isinstance(counts, dict)
            or not counts
            or not set(counts) <= ANDROID_DISCOVERY_STATUSES
            or any(not is_json_integer(count) or count < 1 for count in counts.values())
        ):
            raise ValidationError(f"{path}: source discovery counts are invalid")
        if (
            "source_authentication_required" in counts
            and not ANDROID_DEVICE_ID_RE.fullmatch(device_id)
        ):
            raise ValidationError(
                f"{path}: authentication-required discovery is Android-only"
            )
        if (
            not is_json_integer(item["scope_count"])
            or item["scope_count"] != sum(counts.values())
        ):
            raise ValidationError(f"{path}: source discovery scope count is inconsistent")
        previous_source = source


def validate_inventory(
    path: Path, platform: str
) -> tuple[int, list[dict[str, str]], list[dict[str, Any]]]:
    value = load_object(path)
    expected = {"schema_version", "inventory_id", "platform", "description", "sources", "devices"}
    if (
        set(value) != expected
        or not is_json_integer(value.get("schema_version"))
        or value.get("schema_version") not in {1, 2}
    ):
        raise ValidationError(f"{path}: inventory keys are invalid")
    schema_version = value["schema_version"]
    if value.get("platform") != platform:
        raise ValidationError(f"{path}: expected {platform} platform")
    if not isinstance(value.get("inventory_id"), str) or not value["inventory_id"]:
        raise ValidationError(f"{path}: inventory ID is invalid")
    if not isinstance(value.get("description"), str) or not value["description"]:
        raise ValidationError(f"{path}: description is invalid")
    raw_sources = value.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValidationError(f"{path}: sources must be a non-empty array")
    sources = [validate_source(path, source) for source in raw_sources]
    source_names = [source["name"] for source in sources]
    if source_names != sorted(source_names) or len(source_names) != len(set(source_names)):
        raise ValidationError(f"{path}: sources must be unique and sorted")
    devices = value.get("devices")
    if not isinstance(devices, list):
        raise ValidationError(f"{path}: devices must be an array")
    seen: set[str] = set()
    previous_id = ""
    for record in devices:
        if not isinstance(record, dict) or not set(record) <= BASE_DEVICE_FIELDS:
            raise ValidationError(f"{path}: device record fields are invalid")
        if schema_version == 1 and "carrier_relevance" in record:
            raise ValidationError(f"{path}: v1 device record has v2 carrier relevance")
        if schema_version == 2 and "carrier_relevance" not in record:
            raise ValidationError(f"{path}: v2 device record lacks carrier relevance")
        device_id = record.get("device_id")
        if (
            not isinstance(device_id, str)
            or not DEVICE_ID_RE.fullmatch(device_id)
            or device_id in seen
            or device_id <= previous_id
        ):
            raise ValidationError(f"{path}: duplicate, invalid, or unsorted device ID")
        if record.get("platform") != platform:
            raise ValidationError(f"{path}: platform mismatch for {device_id}")
        platform_device_id_re = (
            ANDROID_DEVICE_ID_RE if platform == "android" else APPLE_DEVICE_ID_RE
        )
        if not platform_device_id_re.fullmatch(device_id):
            raise ValidationError(f"{path}: device ID prefix does not match {platform} platform")
        if record.get("inventory_status") not in {"present", "historical"}:
            raise ValidationError(f"{path}: invalid inventory status for {device_id}")
        if not isinstance(record.get("identity_basis"), str) or not record["identity_basis"]:
            raise ValidationError(f"{path}: identity basis is invalid for {device_id}")
        for field in ("brands", "device_names", "models", "marketing_names"):
            validate_string_array(path, f"{device_id}.{field}", record.get(field))
        states = record.get("inventory_sources")
        if not isinstance(states, list) or not states:
            raise ValidationError(f"{path}: inventory sources are missing for {device_id}")
        state_names: list[str] = []
        for state in states:
            expected_state = {
                "source",
                "status",
                "first_seen_revision",
                "last_changed_revision",
            }
            if not isinstance(state, dict) or set(state) != expected_state:
                raise ValidationError(f"{path}: invalid source state for {device_id}")
            if state["source"] not in source_names:
                raise ValidationError(f"{path}: unknown source state for {device_id}")
            if state["status"] not in {"present", "historical"}:
                raise ValidationError(f"{path}: invalid source status for {device_id}")
            for field in ("first_seen_revision", "last_changed_revision"):
                if not isinstance(state[field], str) or not HASH_RE.fullmatch(state[field]):
                    raise ValidationError(f"{path}: invalid source revision for {device_id}")
            state_names.append(state["source"])
        if state_names != sorted(state_names) or len(state_names) != len(set(state_names)):
            raise ValidationError(f"{path}: source states are not unique and sorted")
        expected_status = (
            "present" if any(state["status"] == "present" for state in states) else "historical"
        )
        if record["inventory_status"] != expected_status:
            raise ValidationError(f"{path}: combined status is invalid for {device_id}")
        if "family" in record and (
            not isinstance(record["family"], str) or not record["family"]
        ):
            raise ValidationError(f"{path}: invalid family for {device_id}")
        if "carrier_observations" in record:
            validate_observations(path, device_id, record["carrier_observations"])
        if "carrier_artifact_catalog" in record:
            validate_artifact_scope(path, device_id, record["carrier_artifact_catalog"])
        if "carrier_source_catalogs" in record:
            validate_source_catalogs(path, device_id, record["carrier_source_catalogs"])
        if "carrier_source_discovery" in record:
            validate_source_discovery(path, device_id, record["carrier_source_discovery"])
        if schema_version == 2:
            validate_carrier_relevance(path, device_id, record, set(source_names))
        validate_data_coverage(
            path, device_id, record, schema_version=schema_version
        )
        seen.add(device_id)
        previous_id = device_id
    return schema_version, sources, devices


def validate_artifacts(path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    value = load_object(path)
    expected = {"schema_version", "registry_id", "description", "source", "artifacts"}
    if (
        set(value) != expected
        or not is_json_integer(value.get("schema_version"))
        or value.get("schema_version") != 1
    ):
        raise ValidationError(f"{path}: artifact registry keys are invalid")
    if not isinstance(value.get("registry_id"), str) or not value["registry_id"]:
        raise ValidationError(f"{path}: registry ID is invalid")
    if not isinstance(value.get("description"), str) or not value["description"]:
        raise ValidationError(f"{path}: description is invalid")
    source = validate_source(path, value.get("source"))
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValidationError(f"{path}: artifacts must be an array")
    expected_record = {
        "artifact_id",
        "source",
        "carrier_bundle_ids",
        "categories",
        "product_scopes",
        "os_versions",
        "build_versions",
        "bundle_versions",
        "verification",
    }
    seen: set[str] = set()
    previous_id = ""
    for record in artifacts:
        if not isinstance(record, dict) or set(record) != expected_record:
            raise ValidationError(f"{path}: artifact record fields are invalid")
        artifact_id = record.get("artifact_id")
        if (
            not isinstance(artifact_id, str)
            or not APPLE_ARTIFACT_ID_RE.fullmatch(artifact_id)
            or artifact_id in seen
            or artifact_id <= previous_id
        ):
            raise ValidationError(f"{path}: duplicate, invalid, or unsorted artifact ID")
        if record.get("source") != source["name"]:
            raise ValidationError(f"{path}: artifact source mismatch")
        for field in (
            "carrier_bundle_ids",
            "categories",
            "product_scopes",
            "os_versions",
            "build_versions",
            "bundle_versions",
        ):
            validate_string_array(path, f"{artifact_id}.{field}", record.get(field))
        if record.get("verification") not in {"indexed", "verified"}:
            raise ValidationError(f"{path}: failed or invalid artifact is public")
        seen.add(artifact_id)
        previous_id = artifact_id
    return source, artifacts


def validate_android_artifacts(
    path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    value = load_object(path)
    expected = {
        "schema_version",
        "registry_id",
        "description",
        "sources",
        "scope_coverage",
        "artifacts",
    }
    if (
        set(value) != expected
        or not is_json_integer(value.get("schema_version"))
        or value.get("schema_version") != 1
    ):
        raise ValidationError(f"{path}: Android artifact registry keys are invalid")
    if value.get("registry_id") != "android_carrier_source_artifacts":
        raise ValidationError(f"{path}: Android artifact registry ID is invalid")
    if not isinstance(value.get("description"), str) or not value["description"]:
        raise ValidationError(f"{path}: Android artifact description is invalid")
    raw_sources = value.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValidationError(f"{path}: Android artifact sources are missing")
    sources = [validate_source(path, item) for item in raw_sources]
    source_names = [item["name"] for item in sources]
    if source_names != sorted(source_names) or len(source_names) != len(set(source_names)):
        raise ValidationError(f"{path}: Android artifact sources are invalid or unsorted")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValidationError(f"{path}: Android artifacts must be an array")
    expected_record = {
        "artifact_id",
        "source",
        "device_scopes",
        "device_ids",
        "regions",
        "build_versions",
        "verification",
        "checked_at",
    }
    seen: set[str] = set()
    previous_id = ""
    for record in artifacts:
        if not isinstance(record, dict) or set(record) != expected_record:
            raise ValidationError(f"{path}: Android artifact record fields are invalid")
        artifact_id = record.get("artifact_id")
        if (
            not isinstance(artifact_id, str)
            or not ANDROID_ARTIFACT_ID_RE.fullmatch(artifact_id)
            or artifact_id in seen
            or artifact_id <= previous_id
        ):
            raise ValidationError(f"{path}: Android artifact ID is invalid or unsorted")
        if record.get("source") not in source_names:
            raise ValidationError(f"{path}: Android artifact source is unknown")
        for field in ("device_scopes", "regions", "build_versions"):
            values = validate_string_array(path, f"{artifact_id}.{field}", record.get(field))
            if not values:
                raise ValidationError(f"{path}: Android artifact {field} is empty")
        device_ids = validate_string_array(
            path, f"{artifact_id}.device_ids", record.get("device_ids")
        )
        if not device_ids or any(
            not ANDROID_DEVICE_ID_RE.fullmatch(item) for item in device_ids
        ):
            raise ValidationError(f"{path}: Android artifact device IDs are invalid")
        if record.get("verification") not in {"indexed", "extracted"}:
            raise ValidationError(f"{path}: Android artifact verification is invalid")
        checked_at = validate_date(path, f"{artifact_id}.checked_at", record.get("checked_at"))
        source = next(item for item in sources if item["name"] == record["source"])
        if checked_at > source["checked_at"]:
            raise ValidationError(f"{path}: Android artifact is newer than its source check")
        seen.add(artifact_id)
        previous_id = artifact_id
    scope_coverage = value.get("scope_coverage")
    if not isinstance(scope_coverage, list):
        raise ValidationError(f"{path}: Android scope coverage must be an array")
    expected_coverage = {
        "source",
        "device_scope",
        "scope_kind",
        "device_ids",
        "discovery_status",
        "region_seed_count",
        "probed_region_count",
        "available_region_count",
        "extracted_artifact_count",
    }
    previous_key = ("", "")
    seen_coverage: set[tuple[str, str]] = set()
    for record in scope_coverage:
        if not isinstance(record, dict) or set(record) != expected_coverage:
            raise ValidationError(f"{path}: Android scope coverage fields are invalid")
        key = (record.get("source"), record.get("device_scope"))
        if (
            not all(isinstance(item, str) and item for item in key)
            or key[0] not in source_names
            or key in seen_coverage
            or key <= previous_key
            or record.get("scope_kind") not in ANDROID_SCOPE_KINDS
            or record.get("discovery_status") not in ANDROID_DISCOVERY_STATUSES
        ):
            raise ValidationError(f"{path}: Android scope coverage is invalid or unsorted")
        counts = [
            record.get("region_seed_count"),
            record.get("probed_region_count"),
            record.get("available_region_count"),
            record.get("extracted_artifact_count"),
        ]
        if any(not is_json_integer(count) or count < 0 for count in counts):
            raise ValidationError(f"{path}: Android scope coverage counts are invalid")
        if counts[1] > counts[0] or counts[2] > counts[1]:
            raise ValidationError(f"{path}: Android scope coverage counts are inconsistent")
        device_ids = validate_string_array(
            path,
            f"{record['source']}.{record['device_scope']}.device_ids",
            record.get("device_ids"),
        )
        if not device_ids or any(
            not ANDROID_DEVICE_ID_RE.fullmatch(item) for item in device_ids
        ):
            raise ValidationError(f"{path}: Android scope coverage device IDs are invalid")
        if record["scope_kind"] == "device_id" and not ANDROID_DEVICE_ID_RE.fullmatch(
            record["device_scope"]
        ):
            raise ValidationError(f"{path}: Android device-ID scope is invalid")
        if record["scope_kind"] == "device_id" and device_ids != [record["device_scope"]]:
            raise ValidationError(f"{path}: Android device-ID scope does not identify itself")
        if (
            record["discovery_status"] == "no_query_identifier"
            and record["scope_kind"] != "device_id"
        ):
            raise ValidationError(f"{path}: no-query scope kind is inconsistent")
        if record["discovery_status"] == "artifact_indexed" and counts[2] < 1:
            raise ValidationError(f"{path}: indexed scope has no available artifact")
        if record["discovery_status"] == "source_extracted" and counts[3] < 1:
            raise ValidationError(f"{path}: extracted scope has no extracted artifact")
        if record["discovery_status"] in EXACT_ZERO_ARTIFACT_TERMINAL_STATUSES and (
            record["scope_kind"] != "device_id" or counts != [0, 0, 0, 0]
        ):
            raise ValidationError(
                f"{path}: {record['discovery_status']} scope must be exact and "
                "artifact-free"
            )
        seen_coverage.add(key)
        previous_key = key
    exact_terminal_keys = {
        (record["source"], record["device_scope"])
        for record in scope_coverage
        if record["discovery_status"] in EXACT_ZERO_ARTIFACT_TERMINAL_STATUSES
    }
    artifact_keys = {
        (record["source"], device_id)
        for record in artifacts
        for device_id in record["device_ids"]
    }
    conflicting_artifacts = sorted(exact_terminal_keys & artifact_keys)
    if conflicting_artifacts:
        source, device_id = conflicting_artifacts[0]
        raise ValidationError(
            f"{path}: exact artifact-free terminal scope has artifact evidence for "
            f"{source}/{device_id}"
        )
    positive_scope_keys = {
        (record["source"], device_id)
        for record in scope_coverage
        if record["discovery_status"] in {"artifact_indexed", "source_extracted"}
        or any(
            record[field] > 0
            for field in (
                "region_seed_count",
                "probed_region_count",
                "available_region_count",
                "extracted_artifact_count",
            )
        )
        for device_id in record["device_ids"]
    }
    conflicting_scopes = sorted(exact_terminal_keys & positive_scope_keys)
    if conflicting_scopes:
        source, device_id = conflicting_scopes[0]
        raise ValidationError(
            f"{path}: exact artifact-free terminal scope has positive scope evidence for "
            f"{source}/{device_id}"
        )
    return sources, artifacts, scope_coverage


def validate_android_exact_terminal_links(
    path: Path,
    android_devices: list[dict[str, Any]],
    android_scope_coverage: list[dict[str, Any]],
    terminal_status: str,
) -> None:
    """Join one exact artifact-free terminal to its public device summaries."""

    if terminal_status not in EXACT_ZERO_ARTIFACT_TERMINAL_STATUSES:
        raise ValidationError(f"{path}: unknown exact Android terminal status")

    devices_by_id = {record["device_id"]: record for record in android_devices}
    expected: Counter[tuple[str, str]] = Counter()
    for scope in android_scope_coverage:
        if scope["discovery_status"] != terminal_status:
            continue
        device_id = scope["device_scope"]
        if device_id not in devices_by_id:
            raise ValidationError(
                f"{path}: {terminal_status} scope references unknown device {device_id}"
            )
        expected[(scope["source"], device_id)] += 1

    actual: Counter[tuple[str, str]] = Counter()
    for device_id, record in devices_by_id.items():
        for discovery in record.get("carrier_source_discovery") or []:
            count = discovery["status_counts"].get(terminal_status, 0)
            if count:
                if (
                    (record.get("carrier_data_coverage") or {}).get("status")
                    != terminal_status
                ):
                    raise ValidationError(
                        f"{path}: {terminal_status} discovery has mismatched device "
                        f"coverage for {device_id}"
                    )
                actual[(discovery["source"], device_id)] += count
        catalog_sources = {
            item["source"] for item in record.get("carrier_source_catalogs") or []
        }
        conflicting_catalogs = sorted(
            source
            for source in catalog_sources
            if (source, device_id) in expected
        )
        if conflicting_catalogs:
            raise ValidationError(
                f"{path}: {terminal_status} scope has device artifact catalog evidence "
                f"for {conflicting_catalogs[0]}/{device_id}"
            )

    if actual != expected:
        missing_summaries = sorted((expected - actual).elements())
        orphan_summaries = sorted((actual - expected).elements())
        if missing_summaries:
            source, device_id = missing_summaries[0]
            raise ValidationError(
                f"{path}: {terminal_status} scope lacks device summary for "
                f"{source}/{device_id}"
            )
        source, device_id = orphan_summaries[0]
        raise ValidationError(
            f"{path}: {terminal_status} device summary lacks exact scope for "
            f"{source}/{device_id}"
        )


def validate_android_transport_links(
    path: Path,
    android_devices: list[dict[str, Any]],
    android_scope_coverage: list[dict[str, Any]],
) -> None:
    """Join every transport-terminal scope to its exact public device summary."""

    validate_android_exact_terminal_links(
        path,
        android_devices,
        android_scope_coverage,
        "source_transport_untrusted",
    )


def validate_android_authentication_links(
    path: Path,
    android_devices: list[dict[str, Any]],
    android_artifacts: list[dict[str, Any]],
    android_scope_coverage: list[dict[str, Any]],
) -> None:
    """Enforce device-global precedence for every authentication terminal."""

    validate_android_exact_terminal_links(
        path,
        android_devices,
        android_scope_coverage,
        "source_authentication_required",
    )
    authentication_device_ids = {
        record["device_id"]
        for record in android_devices
        if (record.get("carrier_data_coverage") or {}).get("status")
        == "source_authentication_required"
    }
    for record in android_devices:
        if record["device_id"] not in authentication_device_ids:
            continue
        conflict_fields = sorted(AUTHENTICATION_TERMINAL_CONFLICT_FIELDS & set(record))
        if conflict_fields:
            raise ValidationError(
                f"{path}: authentication-required device has carrier-bearing evidence: "
                f"{record['device_id']}/{conflict_fields[0]}"
            )

    scope_device_ids = {
        (scope.get("source"), scope.get("device_scope")): set(
            scope.get("device_ids") or []
        )
        for scope in android_scope_coverage
    }
    for artifact in android_artifacts:
        matched_device_ids = set(artifact.get("device_ids") or []) | set(
            artifact.get("device_scopes") or []
        )
        for device_scope in artifact.get("device_scopes") or []:
            matched_device_ids.update(
                scope_device_ids.get((artifact.get("source"), device_scope), set())
            )
        conflicting_device_ids = sorted(
            authentication_device_ids & matched_device_ids
        )
        if conflicting_device_ids:
            raise ValidationError(
                f"{path}: authentication-required device has registry artifact "
                f"evidence: {conflicting_device_ids[0]}"
            )

    positive_statuses = {"artifact_indexed", "source_extracted"}
    count_fields = (
        "region_seed_count",
        "probed_region_count",
        "available_region_count",
        "extracted_artifact_count",
    )
    for scope in android_scope_coverage:
        positive = scope.get("discovery_status") in positive_statuses or any(
            is_json_integer(scope.get(field)) and scope[field] > 0
            for field in count_fields
        )
        if not positive:
            continue
        matched_device_ids = set(scope.get("device_ids") or [])
        if scope.get("device_scope") in authentication_device_ids:
            matched_device_ids.add(scope["device_scope"])
        conflicting_device_ids = sorted(
            authentication_device_ids & matched_device_ids
        )
        if conflicting_device_ids:
            raise ValidationError(
                f"{path}: authentication-required device has positive registry "
                f"scope evidence: {conflicting_device_ids[0]}"
            )


def validate_index(
    path: Path,
    android_sources: list[dict[str, str]],
    android_devices: list[dict[str, Any]],
    apple_sources: list[dict[str, str]],
    apple_devices: list[dict[str, Any]],
    apple_artifact_source: dict[str, str],
    artifacts: list[dict[str, Any]],
    android_artifact_sources: list[dict[str, str]],
    android_artifacts: list[dict[str, Any]],
    *,
    inventory_schema_versions: tuple[int, int] | None = None,
) -> None:
    value = load_object(path)
    expected = {
        "schema_version",
        "description",
        "generated_from_checks_through",
        "sources",
        "platforms",
        "artifact_registries",
    }
    if (
        set(value) != expected
        or not is_json_integer(value.get("schema_version"))
        or value.get("schema_version") not in {1, 2}
    ):
        raise ValidationError(f"{path}: catalog index keys are invalid")
    schema_version = value["schema_version"]
    if schema_version == 2 and inventory_schema_versions is None:
        raise ValidationError(f"{path}: v2 index requires inventory schema versions")
    if inventory_schema_versions is not None and inventory_schema_versions != (
        schema_version,
        schema_version,
    ):
        raise ValidationError(f"{path}: inventory and index schema versions do not match")
    validate_date(path, "generated_from_checks_through", value["generated_from_checks_through"])
    expected_sources = sorted(
        {
            source["name"]: source
            for source in (
                android_sources
                + apple_sources
                + [apple_artifact_source]
                + android_artifact_sources
            )
        }.values(),
        key=lambda source: source["name"],
    )
    if value.get("sources") != expected_sources:
        raise ValidationError(f"{path}: source summaries do not match inventories")
    if value["generated_from_checks_through"] != max(
        source["checked_at"] for source in expected_sources
    ):
        raise ValidationError(f"{path}: generated check date is inconsistent")
    platforms = value.get("platforms")
    if not isinstance(platforms, dict) or set(platforms) != {"android", "apple"}:
        raise ValidationError(f"{path}: platform summaries are invalid")
    validate_nonnegative_count_tree(path, "platforms", platforms)
    android_observed = sum("carrier_observations" in item for item in android_devices)
    apple_observed = sum("carrier_observations" in item for item in apple_devices)
    apple_exact = sum(
        item.get("carrier_artifact_catalog", {}).get("match_kind") == "exact_product_type"
        for item in apple_devices
    )
    apple_family = sum(
        item.get("carrier_artifact_catalog", {}).get("match_kind") == "product_family"
        for item in apple_devices
    )
    android_artifact_matches = sum("carrier_source_catalogs" in item for item in android_devices)
    android_discovery_matches = sum(
        "carrier_source_discovery" in item for item in android_devices
    )

    def coverage_counts(devices: list[dict[str, Any]]) -> dict[str, int]:
        return dict(
            sorted(Counter(item["carrier_data_coverage"]["status"] for item in devices).items())
        )

    def brand_counts(devices: list[dict[str, Any]]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for device in devices:
            if device["inventory_status"] != "present":
                continue
            brands = device.get("brands") or []
            counts[brands[0] if brands else "(not provided by source)"] += 1
        return dict(sorted(counts.items(), key=lambda item: (item[0].casefold(), item[0])))

    def coverage_counts_by_brand(devices: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        counts: dict[str, Counter[str]] = {}
        for device in devices:
            brands = device.get("brands") or []
            brand = brands[0] if brands else "(not provided by source)"
            counts.setdefault(brand, Counter())[device["carrier_data_coverage"]["status"]] += 1
        return {
            brand: dict(sorted(statuses.items()))
            for brand, statuses in sorted(counts.items(), key=lambda item: item[0].casefold())
        }

    def relevance_counts(devices: list[dict[str, Any]]) -> dict[str, int]:
        counts = Counter(
            item["carrier_relevance"]["status"] for item in devices
        )
        return {
            status: counts[status]
            for status in sorted(CARRIER_RELEVANCE_STATUSES)
        }

    def relevance_by_coverage(
        devices: list[dict[str, Any]],
    ) -> dict[str, dict[str, int]]:
        counts: dict[str, Counter[str]] = {
            coverage_status: Counter() for coverage_status in DATA_COVERAGE_STATUSES
        }
        for item in devices:
            counts[item["carrier_data_coverage"]["status"]][
                item["carrier_relevance"]["status"]
            ] += 1
        return {
            coverage_status: {
                relevance_status: counts[coverage_status][relevance_status]
                for relevance_status in sorted(CARRIER_RELEVANCE_STATUSES)
            }
            for coverage_status in sorted(DATA_COVERAGE_STATUSES)
        }

    expected_platforms = {
        "android": {
            "carrier_observation_match_count": android_observed,
            "carrier_artifact_match_count": android_artifact_matches,
            "carrier_source_discovery_match_count": android_discovery_matches,
            "carrier_data_coverage_counts": coverage_counts(android_devices),
            "carrier_data_coverage_counts_by_brand": coverage_counts_by_brand(android_devices),
            "device_count": len(android_devices),
            "historical_device_count": sum(
                item["inventory_status"] == "historical" for item in android_devices
            ),
            "present_device_count": sum(
                item["inventory_status"] == "present" for item in android_devices
            ),
            "present_device_count_by_brand": brand_counts(android_devices),
        },
        "apple": {
            "carrier_observation_match_count": apple_observed,
            "carrier_data_coverage_counts": coverage_counts(apple_devices),
            "carrier_data_coverage_counts_by_brand": coverage_counts_by_brand(apple_devices),
            "device_count": len(apple_devices),
            "exact_artifact_scope_match_count": apple_exact,
            "family_artifact_scope_match_count": apple_family,
            "historical_device_count": sum(
                item["inventory_status"] == "historical" for item in apple_devices
            ),
            "present_device_count": sum(
                item["inventory_status"] == "present" for item in apple_devices
            ),
            "present_device_count_by_brand": brand_counts(apple_devices),
        },
    }
    if schema_version == 2:
        expected_platforms["android"].update(
            {
                "carrier_relevance_counts": relevance_counts(android_devices),
                "carrier_relevance_by_coverage": relevance_by_coverage(android_devices),
            }
        )
        expected_platforms["apple"].update(
            {
                "carrier_relevance_counts": relevance_counts(apple_devices),
                "carrier_relevance_by_coverage": relevance_by_coverage(apple_devices),
            }
        )
    if platforms != expected_platforms:
        raise ValidationError(f"{path}: platform counts do not match records")
    statuses = Counter(item["verification"] for item in artifacts)
    android_statuses = Counter(item["verification"] for item in android_artifacts)
    registries = value.get("artifact_registries")
    if not isinstance(registries, dict):
        raise ValidationError(f"{path}: artifact registries must be an object")
    validate_nonnegative_count_tree(path, "artifact_registries", registries)
    apple_registry = registries.get("apple_carrier_bundles")
    if not isinstance(apple_registry, dict):
        raise ValidationError(f"{path}: Apple artifact registry summary is missing")
    quarantined_count = apple_registry.get("quarantined_count")
    if not is_json_integer(quarantined_count) or quarantined_count < 0:
        raise ValidationError(f"{path}: quarantined artifact count is invalid")
    android_registry = registries.get("android_carrier_source_artifacts")
    if not isinstance(android_registry, dict):
        raise ValidationError(f"{path}: Android artifact registry summary is missing")
    android_quarantined_count = android_registry.get("quarantined_count")
    if not is_json_integer(android_quarantined_count) or android_quarantined_count < 0:
        raise ValidationError(f"{path}: Android quarantined artifact count is invalid")
    expected_registries = {
        "apple_carrier_bundles": {
            "artifact_count": len(artifacts),
            "indexed_count": statuses["indexed"],
            "verified_count": statuses["verified"],
            "failed_count": 0,
            "quarantined_count": quarantined_count,
        },
        "android_carrier_source_artifacts": {
            "artifact_count": len(android_artifacts),
            "indexed_count": android_statuses["indexed"],
            "extracted_count": android_statuses["extracted"],
            "failed_count": 0,
            "quarantined_count": android_quarantined_count,
        },
    }
    if registries != expected_registries:
        raise ValidationError(f"{path}: artifact counts do not match records")


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("generated/devices")
    android_version, android_sources, android_devices = validate_inventory(
        root / "android.json", "android"
    )
    apple_version, apple_sources, apple_devices = validate_inventory(
        root / "apple.json", "apple"
    )
    artifact_source, artifacts = validate_artifacts(root / "apple-carrier-artifacts.json")
    android_artifact_sources, android_artifacts, android_scope_coverage = validate_android_artifacts(
        root / "android-carrier-artifacts.json"
    )
    validate_android_transport_links(root, android_devices, android_scope_coverage)
    validate_android_authentication_links(
        root,
        android_devices,
        android_artifacts,
        android_scope_coverage,
    )
    if artifact_source not in apple_sources:
        raise ValidationError("Apple device and artifact sources do not match")
    validate_index(
        root / "index.json",
        android_sources,
        android_devices,
        apple_sources,
        apple_devices,
        artifact_source,
        artifacts,
        android_artifact_sources,
        android_artifacts,
        inventory_schema_versions=(android_version, apple_version),
    )
    print(
        f"validated {len(android_devices)} Android devices, {len(apple_devices)} Apple "
        f"products, and {len(android_artifacts) + len(artifacts)} carrier artifacts"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
