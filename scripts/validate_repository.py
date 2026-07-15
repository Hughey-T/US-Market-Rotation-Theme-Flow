#!/usr/bin/env python3
"""Dependency-free validation for configs and generated records."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PHASES = {"初動", "拡散", "過熱", "流出", "判定不能"}
ALLOWED_LEVELS = {"直接証拠", "間接証拠", "価格のみ", "証拠不足"}
ALLOWED_DIRECTIONS = {"流入示唆", "流出示唆", "上昇", "下落", "不明"}
ALLOWED_ACTIONS = {"DDへ", "条件付き監視", "待機", "流出中", "判定不能"}
ALLOWED_ROLES = {"core", "beneficiary", "peripheral"}


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def valid_date(value) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_prediction(path: Path, value: dict, errors: list[str]) -> None:
    prefix = str(path.relative_to(ROOT))
    require(value.get("prediction_schema_version") == "1.0", f"{prefix}: prediction_schema_version must be 1.0", errors)
    require(valid_date(value.get("data_date")), f"{prefix}: invalid data_date", errors)
    require(isinstance(value.get("run_id"), str) and len(value["run_id"]) >= 10, f"{prefix}: invalid run_id", errors)
    require(isinstance(value.get("predictions"), list), f"{prefix}: predictions must be an array", errors)
    for i, prediction in enumerate(value.get("predictions", [])):
        item = f"{prefix}: predictions[{i}]"
        require(prediction.get("phase") in ALLOWED_PHASES, f"{item}: invalid phase", errors)
        evidence = prediction.get("flow_evidence", {})
        require(evidence.get("level") in ALLOWED_LEVELS, f"{item}: invalid evidence level", errors)
        require(evidence.get("direction") in ALLOWED_DIRECTIONS, f"{item}: invalid evidence direction", errors)
        require(prediction.get("action") in ALLOWED_ACTIONS, f"{item}: invalid action", errors)
        require(isinstance(prediction.get("withdrawal_conditions"), list) and prediction["withdrawal_conditions"],
                f"{item}: withdrawal_conditions required", errors)
        require(len(prediction.get("dd_candidates", [])) <= 5, f"{item}: at most 5 dd_candidates", errors)
        for candidate in prediction.get("dd_candidates", []):
            require(candidate.get("role") in ALLOWED_ROLES, f"{item}: invalid candidate role", errors)


def validate_verification(path: Path, value: dict, errors: list[str]) -> None:
    prefix = str(path.relative_to(ROOT))
    require(value.get("verification_schema_version") == "1.0", f"{prefix}: verification_schema_version must be 1.0", errors)
    require(valid_date(value.get("prediction_data_date")), f"{prefix}: invalid prediction_data_date", errors)
    require(valid_date(value.get("verification_date")), f"{prefix}: invalid verification_date", errors)
    require(value.get("horizon_weeks") in {4, 13, 26, 52}, f"{prefix}: invalid horizon_weeks", errors)
    require(isinstance(value.get("outcomes"), list), f"{prefix}: outcomes must be an array", errors)


def main() -> int:
    errors = []
    universe = load(ROOT / "config" / "universe.json")
    themes = load(ROOT / "data" / "themes.json")
    require("SPY" in universe.get("regime_assets", {}), "config: SPY missing from regime_assets", errors)
    for theme_id, theme in themes.get("themes", {}).items():
        require(len(theme.get("members", {})) >= 6, f"theme {theme_id}: fewer than 6 members", errors)
        require(set(theme.get("members", {}).values()) <= ALLOWED_ROLES, f"theme {theme_id}: invalid role", errors)

    latest_path = ROOT / "output" / "latest.json"
    if latest_path.exists():
        latest = load(latest_path)
        meta = latest.get("meta", {})
        require(meta.get("schema_version") == "1.0", "output/latest.json: schema_version must be 1.0", errors)
        require(meta.get("status") == "success", "output/latest.json: status must be success", errors)
        require(valid_date(meta.get("data_date")), "output/latest.json: invalid data_date", errors)
        require(len(latest.get("history_weekly", [])) <= 12, "output/latest.json: history exceeds 12", errors)
        require(len(latest.get("previous_predictions", [])) <= 3, "output/latest.json: predictions exceed 3", errors)
        for theme_id, theme in latest.get("themes", {}).items():
            require(theme.get("phase_assessment", {}).get("phase") in ALLOWED_PHASES,
                    f"output/latest.json: {theme_id} invalid phase", errors)

    for path in sorted((ROOT / "output" / "predictions").glob("*.json")):
        validate_prediction(path, load(path), errors)
    for path in sorted((ROOT / "output" / "verifications").glob("*.json")):
        validate_verification(path, load(path), errors)
    prediction_example = ROOT / "docs" / "prediction_example.json"
    verification_example = ROOT / "docs" / "verification_example.json"
    validate_prediction(prediction_example, load(prediction_example), errors)
    validate_verification(verification_example, load(verification_example), errors)

    if errors:
        print("validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
