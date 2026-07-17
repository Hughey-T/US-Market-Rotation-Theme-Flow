"""Pure compatibility model for the Custom GPT primary/fallback acquisition contract."""
from __future__ import annotations

import json
import datetime as dt

from .consumer import CONSUMER_SCHEMA, LATEST_SCHEMA, source_generation_id
from .validation import ContractError, validate_public_latest, validate_schema


def _decode(body: str, label: str) -> dict:
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, TypeError) as error:
        raise ContractError(f"{label} is not complete JSON") from error
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be one JSON object")
    return value


def _parse_timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_validity(meta: dict, now: dt.datetime | None) -> None:
    generated = _parse_timestamp(meta["generated_at"])
    valid_until = _parse_timestamp(meta["valid_until"])
    hard_stop = _parse_timestamp(meta["hard_stop_after"])
    if not generated < valid_until < hard_stop:
        raise ContractError("consumer validity window is invalid")
    if now is not None and now.astimezone(dt.timezone.utc) > hard_stop:
        raise ContractError("consumer is past hard_stop_after")


def _validate_primary(value: dict, now: dt.datetime | None) -> None:
    validate_schema(value, CONSUMER_SCHEMA, "primary lightweight consumer")
    meta = value["meta"]
    if meta["status"] != "success" or meta["failure_reason"] is not None:
        raise ContractError("primary consumer status is invalid")
    if meta["global_quality"]["critical_missing"] != []:
        raise ContractError("primary consumer has critical missing data")
    if meta["run_id"] != value["source_identity"]["analysis_id"]:
        raise ContractError("primary consumer analysis identity mismatch")
    if source_generation_id({"meta": meta}) != value["source_identity"]["generation_id"]:
        raise ContractError("primary consumer generation identity mismatch")
    user_view = value["user_view"]
    if user_view["presentation_version"] != "1.2" or len(user_view["phases"]) != 6:
        raise ContractError("primary consumer presentation contract mismatch")
    _validate_validity(meta, now)


def _validate_legacy(value: dict, now: dt.datetime | None) -> None:
    validate_schema(value, LATEST_SCHEMA, "legacy full consumer")
    validate_public_latest(value, verify_source_hash=True)
    user_view = value.get("user_view") or {}
    if user_view.get("presentation_version") != "1.2" or len(user_view.get("phases") or []) != 6:
        raise ContractError("legacy consumer presentation contract mismatch")
    _validate_validity(value["meta"], now)


def acquire_consumer(
    primary_status: int,
    primary_body: str,
    *,
    legacy_status: int | None = None,
    legacy_body: str | None = None,
    now: dt.datetime | None = None,
) -> tuple[str, dict]:
    """Return one fixed payload; fallback is permitted only for primary HTTP 404."""
    if primary_status == 200:
        value = _decode(primary_body, "primary consumer")
        _validate_primary(value, now)
        return "lightweight", value
    if primary_status != 404:
        raise ContractError(f"primary consumer HTTP status is {primary_status}; fallback is forbidden")
    if legacy_status != 200 or legacy_body is None:
        raise ContractError("primary consumer is unpublished and legacy consumer is unavailable")
    value = _decode(legacy_body, "legacy consumer")
    _validate_legacy(value, now)
    return "legacy_full_snapshot", value


def detail_matches_consumer(detail: dict, consumer: dict, phase: int) -> bool:
    """Check the six immutable identity fields before showing optional detail."""
    meta = consumer["meta"]
    identity = consumer.get("source_identity") or {
        "analysis_id": meta.get("run_id"),
        "generation_id": source_generation_id(consumer),
    }
    return (
        detail.get("phase") == phase
        and detail.get("source_identity") == identity
        and detail.get("meta") == {
            "run_id": meta.get("run_id"),
            "source_commit": meta.get("source_commit"),
            "source_sha256": meta.get("source_sha256"),
            "data_date": meta.get("data_date"),
            "status": meta.get("status"),
        }
    )
