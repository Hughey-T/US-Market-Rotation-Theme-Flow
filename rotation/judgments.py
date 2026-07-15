"""Immutable judgment indexing, projection, and withdrawal evaluation."""
from __future__ import annotations

import json
from pathlib import Path

from .provenance import file_sha256
from .validation import ContractError, load_json, validate_schema


def build_index(directory: Path, schema: dict) -> dict:
    entries, seen_ids = [], set()
    for path in sorted(directory.glob("*.json")):
        if path.name == "index.json":
            continue
        value = load_json(path)
        validate_schema(value, schema, str(path))
        judgment_id = value["judgment_id"]
        if judgment_id in seen_ids:
            raise ContractError(f"duplicate judgment_id: {judgment_id}")
        seen_ids.add(judgment_id)
        entries.append({"file": path.name, "sha256": file_sha256(path), "judgment_id": judgment_id, "data_date": value["data_date"], "content": value})
    entries.sort(key=lambda item: (item["data_date"], item["judgment_id"]))
    return {"index_version": "1.0", "records": entries}


def verify_index(directory: Path, index: dict, schema: dict) -> None:
    rebuilt = build_index(directory, schema)
    if rebuilt != index:
        raise ContractError("output/judgments/index.json does not match immutable judgment files")


def get_path(value, path: str):
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _compare(observed, operator, expected):
    if observed is None:
        return None
    return {"<": observed < expected, "<=": observed <= expected, ">": observed > expected, ">=": observed >= expected, "==": observed == expected, "!=": observed != expected}[operator]


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
