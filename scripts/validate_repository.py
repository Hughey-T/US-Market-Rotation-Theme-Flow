#!/usr/bin/env python3
"""Validate repository contracts without network access or current-time gates."""
from __future__ import annotations

import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.judgments import build_index, verify_index
from rotation.publication import load_current_generation
from rotation.validation import (
    ContractError,
    load_json,
    validate_latest_semantics,
    validate_public_latest,
    validate_judgment_semantics,
    validate_schema,
    validate_theme_master_semantics,
)


def validate_public_outputs(root: Path, latest_schema: dict) -> int:
    """Validate optional public outputs; absence is valid before first publication."""
    count = 0
    latest_path = root / "output" / "latest.json"
    if latest_path.exists():
        latest = load_json(latest_path)
        validate_schema(latest, latest_schema, "output/latest.json")
        validate_public_latest(latest, verify_source_hash=True)
        count += 1
    current = load_current_generation(root / "output")
    if current is not None:
        current_latest = current[3]
        validate_schema(current_latest, latest_schema, "output/current generation latest.json")
        validate_public_latest(current_latest, verify_source_hash=True)
        count += 1
    return count

def main() -> int:
    try:
        schemas = {
            "latest": load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"),
            "judgment": load_json(ROOT / "schemas" / "judgment_record.schema.json"),
            "master": load_json(ROOT / "schemas" / "theme_master.schema.json"),
            "generation_manifest": load_json(ROOT / "schemas" / "generation_manifest.schema.json"),
            "publication_pointer": load_json(ROOT / "schemas" / "publication_pointer.schema.json"),
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
        fixture_judgment = load_json(fixture_dir / "judgment_record.json")
        validate_schema(fixture_judgment, schemas["judgment"], "fixture judgment")
        validate_judgment_semantics(fixture_judgment, load_json(fixture_dir / "latest_normal.json"))
        fixture_master = load_json(fixture_dir / "theme_master.json")
        validate_schema(fixture_master, schemas["master"], "fixture master")
        validate_theme_master_semantics(fixture_master)
        validate_schema(load_json(ROOT / "docs" / "prediction_example.json"), schemas["prediction_legacy"], "legacy prediction example")
        validate_schema(load_json(ROOT / "docs" / "verification_example.json"), schemas["verification_legacy"], "legacy verification example")
        public_count = validate_public_outputs(ROOT, schemas["latest"])
        judgment_dir = ROOT / "output" / "judgments"
        index_path = judgment_dir / "index.json"
        def source_loader(record):
            path = ROOT / record["source_snapshot"]
            if not path.is_file():
                raise ContractError(f"judgment source latest is unavailable: {path}")
            source = load_json(path)
            validate_schema(source, schemas["latest"], str(path.relative_to(ROOT)))
            validate_public_latest(source, verify_source_hash=True)
            return source
        rebuilt = build_index(judgment_dir, schemas["judgment"], source_loader)
        if index_path.exists():
            verify_index(judgment_dir, load_json(index_path), schemas["judgment"], source_loader)
        current_generation = load_current_generation(ROOT / "output")
        if current_generation is not None:
            generation_index = {key: value for key, value in current_generation[5].items() if key != "publication"}
            if generation_index != rebuilt:
                raise ContractError("current generation judgment index does not match validated immutable records")
        instructions = (ROOT / "docs" / "custom_gpt_instructions_v1.1.md").read_text(encoding="utf-8")
        if len(instructions) > 8000:
            raise ContractError(f"Custom GPT instructions exceed 8,000 characters: {len(instructions)}")
        required_terms = ["schema_version=1.1", "methodology_version=1.1.0", "timing_status", "テーマ市場状態", "selected_for_deep_dive", "単一総合score"]
        missing = [term for term in required_terms if term not in instructions]
        if missing:
            raise ContractError(f"Custom GPT instructions missing contract terms: {missing}")
        print(f"validation passed: 5 current schemas, 7 latest fixtures, 1 judgment fixture, 1 master fixture, {public_count} public outputs, {len(warnings)} overlap warnings")
        return 0
    except (ContractError, OSError, ValueError) as error:
        print(f"validation failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
