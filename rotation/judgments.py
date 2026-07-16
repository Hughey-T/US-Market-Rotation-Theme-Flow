"""Immutable judgment indexing, projection, and withdrawal evaluation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .provenance import canonical_bytes
from .validation import ContractError, validate_judgment_semantics, validate_schema


class StableJsonChangedError(ContractError):
    """A stable JSON path changed between its initial and final raw reads."""

    def __init__(self, label: str, relative_path: str):
        super().__init__(f"{label} changed during validation: {relative_path}")
        self.relative_path = relative_path


@dataclass(frozen=True)
class StableJsonSnapshot:
    """One parsed JSON snapshot with a final raw-byte stability check."""

    path: Path
    relative_path: str
    label: str
    raw: bytes
    value: dict

    @classmethod
    def read(cls, path: Path, *, relative_path: str, label: str) -> "StableJsonSnapshot":
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ContractError(f"cannot read {label}: {relative_path}") from error
        try:
            value = json.loads(
                raw.decode("utf-8"),
                parse_constant=lambda item: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant: {item}")
                ),
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise ContractError(f"invalid {label} JSON: {relative_path}") from error
        if not isinstance(value, dict):
            raise ContractError(f"invalid {label} JSON object: {relative_path}")
        return cls(path=path, relative_path=relative_path, label=label, raw=raw, value=value)

    def ensure_unchanged(self) -> None:
        try:
            final_raw = self.path.read_bytes()
        except OSError as error:
            raise StableJsonChangedError(self.label, self.relative_path) from error
        if final_raw != self.raw:
            raise StableJsonChangedError(self.label, self.relative_path)


def _validated_record(path: Path, schema: dict, source_loader) -> tuple[dict, bytes]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"immutable judgment record is not a regular file: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid immutable judgment JSON: {path}") from error
    validate_schema(value, schema, str(path))
    if source_loader is None:
        raise ContractError(f"{path}: judgment source loader is required")
    validate_judgment_semantics(value, source_loader(value))
    if path.read_bytes() != raw:
        raise ContractError(f"immutable judgment record changed during validation: {path}")
    return value, raw


def build_index(directory: Path, schema: dict, source_loader=None) -> dict:
    entries, seen_ids = [], set()
    for path in sorted(directory.glob("*.json")):
        if path.name == "index.json":
            continue
        value, raw = _validated_record(path, schema, source_loader)
        judgment_id = value["judgment_id"]
        if judgment_id in seen_ids:
            raise ContractError(f"duplicate judgment_id: {judgment_id}")
        seen_ids.add(judgment_id)
        entries.append({
            "file": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "judgment_id": judgment_id, "data_date": value["data_date"], "content": value,
        })
    entries.sort(key=lambda item: (item["data_date"], item["judgment_id"]))
    return {"index_version": "1.0", "records": entries}


def validate_index_records(
    directory: Path, index: dict, schema: dict, source_loader=None,
    *, require_exact_inventory: bool = False,
) -> dict:
    """Validate index content and immutable records through one canonical contract."""
    records = index.get("records")
    if not isinstance(records, list):
        raise ContractError("judgment index records must be an array")
    expected_files = {entry.get("file") for entry in records if isinstance(entry, dict)}
    if require_exact_inventory:
        actual_files = {
            path.name for path in directory.glob("*.json")
            if path.name != "index.json"
        }
        if expected_files != actual_files:
            raise ContractError(
                "judgment index immutable inventory mismatch: "
                f"unknown={sorted(actual_files - expected_files)} "
                f"missing={sorted(expected_files - actual_files)}"
            )
    rebuilt_records = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for entry in records:
        if not isinstance(entry, dict):
            raise ContractError("judgment index record entry must be an object")
        filename = entry.get("file")
        judgment_id = entry.get("judgment_id")
        if filename in seen_files or judgment_id in seen_ids:
            raise ContractError("duplicate judgment index record reference")
        seen_files.add(filename)
        seen_ids.add(judgment_id)
        immutable, raw = _validated_record(directory / filename, schema, source_loader)
        content = entry.get("content")
        validate_schema(content, schema, f"judgment index {judgment_id}")
        if source_loader is None:
            raise ContractError(f"judgment index {judgment_id}: judgment source loader is required")
        validate_judgment_semantics(content, source_loader(content))
        if canonical_bytes(immutable) != canonical_bytes(content):
            raise ContractError(
                f"judgment index content does not match immutable record: {judgment_id}"
            )
        if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise ContractError(f"judgment index immutable SHA-256 mismatch: {judgment_id}")
        if judgment_id != immutable.get("judgment_id") or entry.get("data_date") != immutable.get("data_date"):
            raise ContractError(f"judgment index record identity mismatch: {judgment_id}")
        rebuilt_records.append({
            "file": filename, "sha256": hashlib.sha256(raw).hexdigest(),
            "judgment_id": immutable["judgment_id"], "data_date": immutable["data_date"],
            "content": immutable,
        })
    if records != sorted(records, key=lambda item: (item["data_date"], item["judgment_id"])):
        raise ContractError("judgment index record order is not deterministic")
    return {"index_version": "1.0", "records": rebuilt_records}


def verify_index(directory: Path, index: dict, schema: dict, source_loader=None) -> None:
    rebuilt = validate_index_records(
        directory, index, schema, source_loader, require_exact_inventory=True,
    )
    if rebuilt != index:
        raise ContractError("output/judgments/index.json does not match immutable judgment files")


def get_path(value, path: str):
    parts = path.split(".")
    current = value
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            break
        current = current[part]
    else:
        return current

    # Published history intentionally stores the five trend inputs directly
    # below each theme, while current snapshots group them under ``metrics``.
    # Withdrawal conditions use current-snapshot paths, so resolve only that
    # explicit shape difference when evaluating compact history records.
    if len(parts) == 4 and parts[0] == "themes" and parts[2] == "metrics":
        compact = value.get("themes", {}).get(parts[1], {}) if isinstance(value, dict) else {}
        if isinstance(compact, dict):
            return compact.get(parts[3])
    return None


def _compare(observed, operator, expected):
    if observed is None:
        return None
    compatible = (
        isinstance(observed, bool) and isinstance(expected, bool)
        or not isinstance(observed, bool) and not isinstance(expected, bool)
        and isinstance(observed, (int, float)) and isinstance(expected, (int, float))
        or isinstance(observed, str) and isinstance(expected, str)
    )
    if not compatible:
        return None
    if operator == "==":
        return observed == expected
    if operator == "!=":
        return observed != expected
    if isinstance(observed, bool) or isinstance(expected, bool) or not isinstance(observed, (int, float)) or not isinstance(expected, (int, float)):
        return None
    return {"<": observed < expected, "<=": observed <= expected, ">": observed > expected, ">=": observed >= expected}[operator]


def evaluate_withdrawal(condition: dict, current: dict, history: list[dict]) -> dict:
    required = condition["persistence_weeks"]
    observations = [current] + list(reversed(history))
    observed_weeks = 0
    for snapshot in observations:
        result = _compare(get_path(snapshot, condition["field_path"]), condition["operator"], condition["value"])
        if result is None:
            return {"condition_id": condition["condition_id"], "status": "unknown", "observed_weeks": observed_weeks}
        if not result:
            return {"condition_id": condition["condition_id"], "status": "not_triggered", "observed_weeks": observed_weeks}
        observed_weeks += 1
        if observed_weeks >= required:
            return {"condition_id": condition["condition_id"], "status": "triggered", "observed_weeks": observed_weeks}
    return {"condition_id": condition["condition_id"], "status": "unknown", "observed_weeks": observed_weeks}


def project_previous_judgments(index: dict, current: dict, history: list[dict], limit: int = 3) -> dict:
    records = index.get("records", [])[-limit:]
    projections = []
    for entry in records:
        judgment = entry["content"]
        for theme in judgment["theme_judgments"]:
            projections.append({
                "judgment_id": judgment["judgment_id"], "data_date": judgment["data_date"], "theme_id": theme["theme_id"],
                "phase": theme["phase"], "direction": theme["direction"], "research_priority": theme["research_priority"],
                "research_priority_rule": theme["research_priority_rule"], "timing_status": theme["timing_status"], "timing_rule": theme["timing_rule"],
                "selected_for_deep_dive": theme["selected_for_deep_dive"], "shortlist_rank": theme["shortlist_rank"],
                "shortlist_reason_codes": theme["shortlist_reason_codes"],
                "withdrawal_evaluations": [evaluate_withdrawal(condition, current, history) for condition in theme["withdrawal_conditions"]],
            })
    latest_date = records[-1]["data_date"] if records else None
    return {"source": "output/judgments/index.json", "available": bool(records), "latest_data_date": latest_date, "records": projections}
