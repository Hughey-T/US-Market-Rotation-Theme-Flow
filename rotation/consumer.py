"""Deterministic, size-bounded Custom GPT consumer projection."""
from __future__ import annotations

import copy
from pathlib import Path

from .identity import validate_safe_id
from .provenance import canonical_bytes
from .validation import ContractError, load_json, validate_public_latest, validate_schema


CONSUMER_CONTRACT_VERSION = "1.0"
CONSUMER_CANONICAL_SIZE_LIMIT = 32 * 1024
CONSUMER_FILE_SIZE_LIMIT = 32 * 1024
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
CONSUMER_SCHEMA = load_json(SCHEMA_ROOT / "consumer_snapshot.schema.json")
LATEST_SCHEMA = load_json(SCHEMA_ROOT / "rotation_snapshot.schema.json")
CONSUMER_META_FIELDS = (
    "run_id", "source_commit", "source_snapshot", "source_sha256", "generated_at",
    "data_date", "valid_until", "hard_stop_after", "status", "failure_reason",
)


def source_generation_id(authoritative_latest: dict) -> str:
    source = authoritative_latest.get("meta", {}).get("source_snapshot", "")
    parts = Path(source).as_posix().split("/")
    if len(parts) != 4 or parts[:2] != ["output", "generations"] or parts[3] != "archive.json":
        raise ContractError("source_snapshot must identify one authoritative generation")
    return validate_safe_id(parts[2], "generation_id")  # type: ignore[return-value]


def build_consumer_snapshot(authoritative_latest: dict) -> dict:
    """Project one authoritative snapshot without recomputation or clock-dependent values."""
    meta = authoritative_latest.get("meta", {})
    run_id = validate_safe_id(meta.get("run_id"), "analysis_id")
    global_quality = meta.get("global_quality", {})
    return {
        "consumer_contract_version": CONSUMER_CONTRACT_VERSION,
        "source_identity": {
            "analysis_id": run_id,
            "generation_id": source_generation_id(authoritative_latest),
        },
        "meta": {
            **{field: copy.deepcopy(meta.get(field)) for field in CONSUMER_META_FIELDS},
            "global_quality": {
                "critical_missing": copy.deepcopy(global_quality.get("critical_missing", [])),
                "warnings": copy.deepcopy(global_quality.get("warnings", [])),
            },
        },
        "user_view": copy.deepcopy(authoritative_latest.get("user_view")),
    }


def validate_consumer_snapshot(
    consumer: dict,
    authoritative_latest: dict,
    *,
    pointer: dict | None = None,
    manifest: dict | None = None,
) -> None:
    """Validate the lightweight projection and bind it to its authoritative generation."""
    if consumer.get("consumer_contract_version") != CONSUMER_CONTRACT_VERSION:
        raise ContractError("unsupported consumer contract version")
    validate_schema(consumer, CONSUMER_SCHEMA, "consumer snapshot")
    meta = consumer["meta"]
    if meta.get("status") != "success":
        raise ContractError("consumer requires status=success")
    if meta.get("failure_reason") not in (None, ""):
        raise ContractError("successful consumer cannot contain failure_reason")
    if meta.get("global_quality", {}).get("critical_missing") != []:
        raise ContractError("consumer requires critical_missing=[]")

    expected = build_consumer_snapshot(authoritative_latest)
    identity = consumer["source_identity"]
    if identity.get("generation_id") != expected["source_identity"]["generation_id"]:
        raise ContractError("consumer source generation ID mismatch")
    if identity.get("analysis_id") != expected["source_identity"]["analysis_id"]:
        raise ContractError("consumer analysis ID mismatch")
    for field, label in (
        ("run_id", "run ID"), ("source_sha256", "source SHA-256"),
        ("source_commit", "source commit"), ("source_snapshot", "source snapshot"),
    ):
        if meta.get(field) != expected["meta"].get(field):
            raise ContractError(f"consumer {label} mismatch")
    if consumer.get("user_view") != authoritative_latest.get("user_view"):
        raise ContractError("consumer user_view differs from authoritative snapshot")

    if pointer is not None:
        for field in ("analysis_id", "generation_id"):
            if identity.get(field) != pointer.get(field):
                raise ContractError(f"consumer {field.replace('_', ' ')} does not match current pointer")
        if meta.get("run_id") != pointer.get("run_id"):
            raise ContractError("consumer run ID does not match current pointer")
    if manifest is not None:
        for field in ("analysis_id", "generation_id"):
            if identity.get(field) != manifest.get(field):
                raise ContractError(f"consumer {field.replace('_', ' ')} does not match generation manifest")
        for field, label in (("run_id", "run ID"), ("source_sha256", "source SHA-256"), ("source_commit", "source commit")):
            if meta.get(field) != manifest.get(field):
                raise ContractError(f"consumer {label} does not match generation manifest")

    if canonical_bytes(consumer) != canonical_bytes(expected):
        raise ContractError("consumer projection differs from deterministic authoritative projection")
    size = len(canonical_bytes(consumer))
    if size > CONSUMER_CANONICAL_SIZE_LIMIT:
        raise ContractError(
            f"consumer canonical JSON exceeds {CONSUMER_CANONICAL_SIZE_LIMIT} bytes: {size}"
        )


def validate_consumer_artifact(
    consumer: dict,
    authoritative_latest: dict,
    *,
    pointer: dict | None = None,
    manifest: dict | None = None,
) -> str:
    """Validate current projection or the read-only legacy full-snapshot export."""
    if "consumer_contract_version" in consumer:
        validate_consumer_snapshot(
            consumer, authoritative_latest, pointer=pointer, manifest=manifest,
        )
        return "projection"
    validate_schema(consumer, LATEST_SCHEMA, "legacy full-snapshot consumer")
    validate_public_latest(consumer, verify_source_hash=True)
    if canonical_bytes(consumer) != canonical_bytes(authoritative_latest):
        raise ContractError("legacy consumer export does not match authoritative current generation")
    return "legacy_full_snapshot"
