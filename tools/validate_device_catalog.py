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
ARTIFACT_ID_RE = re.compile(r"^apple:[0-9a-f]{24}$")
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
}


class ValidationError(Exception):
    pass


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
    validate_string_array(path, "matched_identifiers", value["matched_identifiers"])
    validate_string_array(path, "sources", value["sources"])
    if not isinstance(value["profile_count"], int) or value["profile_count"] < 1:
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
        not isinstance(value["artifact_count"], int)
        or value["artifact_count"] < 1
        or not isinstance(value["verified_artifact_count"], int)
        or not 0 <= value["verified_artifact_count"] <= value["artifact_count"]
    ):
        raise ValidationError(f"{path}: invalid artifact counts for {device_id}")


def validate_inventory(
    path: Path, platform: str
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    value = load_object(path)
    expected = {"schema_version", "inventory_id", "platform", "description", "sources", "devices"}
    if set(value) != expected or value.get("schema_version") != 1:
        raise ValidationError(f"{path}: inventory keys are invalid")
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
        seen.add(device_id)
        previous_id = device_id
    return sources, devices


def validate_artifacts(path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    value = load_object(path)
    expected = {"schema_version", "registry_id", "description", "source", "artifacts"}
    if set(value) != expected or value.get("schema_version") != 1:
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
            or not ARTIFACT_ID_RE.fullmatch(artifact_id)
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


def validate_index(
    path: Path,
    android_sources: list[dict[str, str]],
    android_devices: list[dict[str, Any]],
    apple_sources: list[dict[str, str]],
    apple_devices: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
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
    if set(value) != expected or value.get("schema_version") != 1:
        raise ValidationError(f"{path}: catalog index keys are invalid")
    validate_date(path, "generated_from_checks_through", value["generated_from_checks_through"])
    expected_sources = sorted(
        {
            source["name"]: source
            for source in android_sources + apple_sources
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

    def brand_counts(devices: list[dict[str, Any]]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for device in devices:
            if device["inventory_status"] != "present":
                continue
            brands = device.get("brands") or []
            counts[brands[0] if brands else "(not provided by source)"] += 1
        return dict(sorted(counts.items(), key=lambda item: (item[0].casefold(), item[0])))

    expected_platforms = {
        "android": {
            "carrier_observation_match_count": android_observed,
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
    if platforms != expected_platforms:
        raise ValidationError(f"{path}: platform counts do not match records")
    statuses = Counter(item["verification"] for item in artifacts)
    registries = value.get("artifact_registries")
    if not isinstance(registries, dict):
        raise ValidationError(f"{path}: artifact registries must be an object")
    apple_registry = registries.get("apple_carrier_bundles")
    if not isinstance(apple_registry, dict):
        raise ValidationError(f"{path}: Apple artifact registry summary is missing")
    quarantined_count = apple_registry.get("quarantined_count")
    if not isinstance(quarantined_count, int) or quarantined_count < 0:
        raise ValidationError(f"{path}: quarantined artifact count is invalid")
    expected_registries = {
        "apple_carrier_bundles": {
            "artifact_count": len(artifacts),
            "indexed_count": statuses["indexed"],
            "verified_count": statuses["verified"],
            "failed_count": 0,
            "quarantined_count": quarantined_count,
        }
    }
    if registries != expected_registries:
        raise ValidationError(f"{path}: artifact counts do not match records")


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("generated/devices")
    android_sources, android_devices = validate_inventory(root / "android.json", "android")
    apple_sources, apple_devices = validate_inventory(root / "apple.json", "apple")
    artifact_source, artifacts = validate_artifacts(root / "apple-carrier-artifacts.json")
    if artifact_source not in apple_sources:
        raise ValidationError("Apple device and artifact sources do not match")
    validate_index(
        root / "index.json",
        android_sources,
        android_devices,
        apple_sources,
        apple_devices,
        artifacts,
    )
    print(
        f"validated {len(android_devices)} Android devices, {len(apple_devices)} Apple "
        f"products, and {len(artifacts)} carrier artifacts"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
