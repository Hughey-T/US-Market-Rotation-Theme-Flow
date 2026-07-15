#!/usr/bin/env python3
"""Validate repository contracts without network access or current-time gates."""
from __future__ import annotations

import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.judgments import build_index, verify_index
from rotation.validation import (
    ContractError,
    load_json,
    validate_latest_semantics,
    validate_schema,
    validate_theme_master_semantics,
)

def main() -> int:
    try:
        schemas = {
            "latest": load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"),
            "judgment": load_json(ROOT / "schemas" / "judgment_record.schema.json"),
            "master": load_json(ROOT / "schemas" / "theme_master.schema.json"),
            "prediction_legacy": load_json(ROOT / "schemas" / "prediction_record.schema.json"),
            "verification_legacy": load_json(ROOT / "schemas" / "verification_record.schema.json"),
        }
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
        master = load_json(ROOT / "data" / "themes.json")
        validate_schema(master, schemas["master"], "data/themes.json")
        warnings = validate_theme_master_semantics(master)
        fixture_dir = ROOT / "tests" / "fixtures"
        for path in sorted(fixture_dir.glob("latest_*.json")):
            value = load_json(path)
            validate_schema(value, schemas["latest"], str(path.relative_to(ROOT)))
            validate_latest_semantics(value)
        validate_schema(load_json(fixture_dir / "judgment_record.json"), schemas["judgment"], "fixture judgment")
        fixture_master = load_json(fixture_dir / "theme_master.json")
        validate_schema(fixture_master, schemas["master"], "fixture master")
        validate_theme_master_semantics(fixture_master)
        validate_schema(load_json(ROOT / "docs" / "prediction_example.json"), schemas["prediction_legacy"], "legacy prediction example")
        validate_schema(load_json(ROOT / "docs" / "verification_example.json"), schemas["verification_legacy"], "legacy verification example")
        latest_path = ROOT / "output" / "latest.json"
        if latest_path.exists():
            latest = load_json(latest_path)
            validate_schema(latest, schemas["latest"], "output/latest.json")
            validate_latest_semantics(latest, verify_source_hash=True)
        judgment_dir = ROOT / "output" / "judgments"
        index_path = judgment_dir / "index.json"
        rebuilt = build_index(judgment_dir, schemas["judgment"])
        if index_path.exists():
            verify_index(judgment_dir, load_json(index_path), schemas["judgment"])
        instructions = (ROOT / "docs" / "custom_gpt_instructions_v1.1.md").read_text(encoding="utf-8")
        if len(instructions) > 8000:
            raise ContractError(f"Custom GPT instructions exceed 8,000 characters: {len(instructions)}")
        required_terms = ["schema_version=1.1", "methodology_version=1.1.0", "timing_status", "テーマ市場状態", "selected_for_deep_dive", "単一総合score"]
        missing = [term for term in required_terms if term not in instructions]
        if missing:
            raise ContractError(f"Custom GPT instructions missing contract terms: {missing}")
        print(f"validation passed: 3 current schemas, 7 latest fixtures, 1 judgment fixture, 1 master fixture, {len(warnings)} overlap warnings")
        return 0
    except (ContractError, OSError, ValueError) as error:
        print(f"validation failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
