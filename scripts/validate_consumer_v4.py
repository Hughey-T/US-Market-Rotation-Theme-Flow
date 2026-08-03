#!/usr/bin/env python3
"""Validate consumer v4 schemas, fixture transport, and optional publication."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.consumer_v4 import export_consumer_v4, load_and_validate_consumer_v4
from rotation.validation import ContractError, load_json


def validate_v4_schemas() -> int:
    root = ROOT / "schemas" / "v4"
    paths = sorted(root.glob("*.schema.json"))
    if len(paths) < 18:
        raise ContractError(f"consumer v4 schema inventory is incomplete: {len(paths)}")
    for path in paths:
        schema = load_json(path)
        Draft202012Validator.check_schema(schema)
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ContractError(f"consumer v4 schema must be a closed object: {path.name}")
    return len(paths)


def main() -> int:
    try:
        count = validate_v4_schemas()
        fixture = load_json(ROOT / "tests" / "fixtures" / "latest_normal.json")
        with tempfile.TemporaryDirectory(prefix="consumer-v4-validate-") as directory:
            root = Path(directory) / "v4"
            export_consumer_v4(fixture, root)
            load_and_validate_consumer_v4(root)
        published = ROOT / "output" / "consumer" / "v4"
        if published.exists():
            load_and_validate_consumer_v4(published)
        instructions = (ROOT / "docs" / "custom_gpt_instructions_current.md").read_text(encoding="utf-8")
        if len(instructions) > 8000:
            raise ContractError(f"Custom GPT instructions exceed 8,000 characters: {len(instructions)}")
        required = (
            "正本指示 2.0.1", "consumer/v4/manifest.json", "全10 Phase",
            "blind-handoff", "reconciliation-handoff", "session_local",
            "runtime_available=false", "mechanical rank", "independent AI rank",
            "integrated rank", "exact 404", "1 tool callにつき1 URL",
            "fixed_hidden", "Phase7", "pass／fail／not_evaluable",
            "RELATIVE_BELOW_THRESHOLD", "selection_eligible=true",
            "exploratory_only", "Phase10はPhase9より短く",
        )
        missing = [term for term in required if term not in instructions]
        if missing:
            raise ContractError(f"Custom GPT instructions missing v4 terms: {missing}")
        if "Phase1〜8で`【機械判定】`を使わない" not in instructions:
            raise ContractError("Custom GPT instructions do not reserve machine-decision labeling for Phase 9")
        print(f"consumer v4 validation passed: {count} closed schemas")
        return 0
    except (ContractError, OSError, ValueError) as error:
        print(f"consumer v4 validation failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
