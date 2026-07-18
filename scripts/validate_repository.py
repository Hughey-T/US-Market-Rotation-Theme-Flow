#!/usr/bin/env python3
"""Validate repository contracts without network access or current-time gates."""
from __future__ import annotations

import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.judgments import StableJsonSnapshot, build_index, verify_index
from rotation.consumer import (
    validate_consumer_detail,
    validate_consumer_snapshot,
    validate_legacy_full_consumer,
)
from rotation.consumer_v2 import (
    CONSUMER_V2_MANIFEST_SCHEMA,
    load_consumer_v2_file,
    validate_consumer_v2_payloads,
)
from rotation.publication import load_current_generation, validate_repository_output_inventory
from rotation.validation import (
    ContractError,
    load_json,
    validate_latest_semantics,
    validate_public_latest,
    validate_judgment_semantics,
    validate_schema,
    validate_theme_master_semantics,
)


def _load_consumer_v2_kind(
    root: Path,
    kind: str,
    inventory: list[dict],
) -> dict[int, list[dict]]:
    directory = root / kind

    if directory.is_symlink() or not directory.is_dir():
        raise ContractError(
            f"invalid consumer v2 {kind} directory: {directory}"
        )

    expected_phases = {
        f"phase-{phase}"
        for phase in range(1, 7)
    }
    phase_entries = {
        entry.name: entry
        for entry in directory.iterdir()
    }

    if set(phase_entries) != expected_phases:
        raise ContractError(
            f"consumer v2 {kind} phase inventory mismatch"
        )

    if [
        item.get("phase")
        for item in inventory
    ] != list(range(1, 7)):
        raise ContractError(
            f"consumer v2 {kind} manifest phases are invalid"
        )

    result: dict[int, list[dict]] = {}

    for item in inventory:
        phase = item["phase"]
        part_count = item["part_count"]
        phase_directory = (
            directory / f"phase-{phase}"
        )

        if (
            phase_directory.is_symlink()
            or not phase_directory.is_dir()
        ):
            raise ContractError(
                f"invalid consumer v2 {kind} phase directory: "
                f"{phase_directory}"
            )

        expected_parts = {
            f"part-{part}.json"
            for part in range(1, part_count + 1)
        }
        part_entries = {
            entry.name: entry
            for entry in phase_directory.iterdir()
        }

        if set(part_entries) != expected_parts:
            raise ContractError(
                f"consumer v2 {kind} phase {phase} "
                "part inventory mismatch"
            )

        result[phase] = []

        for part in range(1, part_count + 1):
            part_path = (
                phase_directory
                / f"part-{part}.json"
            )

            if (
                part_path.is_symlink()
                or not part_path.is_file()
            ):
                raise ContractError(
                    f"invalid consumer v2 part: {part_path}"
                )

            result[phase].append(
                load_consumer_v2_file(
                    part_path,
                    f"consumer v2 {kind} phase {phase} part {part}",
                )
            )

    return result


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
    legacy_path = root / "output" / "consumer" / "latest.json"
    if legacy_path.exists():
        if current is None:
            raise ContractError("consumer export exists without an authoritative current generation")
        validate_legacy_full_consumer(
            load_json(legacy_path), current[3], pointer=current[0], manifest=current[2],
        )
        if current[3].get("meta", {}).get("schema_version") == "1.2":
            projection_path = root / "output" / "consumer" / "v1" / "latest.json"
            projection = load_json(projection_path)
            validate_consumer_snapshot(
                projection, current[3], pointer=current[0], manifest=current[2],
            )
            for phase in range(1, 7):
                validate_consumer_detail(
                    load_json(root / "output" / "consumer" / "v1" / "details" / f"phase-{phase}.json"),
                    current[3], phase=phase,
                )

            v2_root = (
                root
                / "output"
                / "consumer"
                / "v2"
            )
            manifest_path = (
                v2_root / "manifest.json"
            )

            if (
                manifest_path.is_symlink()
                or not manifest_path.is_file()
            ):
                raise ContractError(
                    "consumer v2 manifest is missing or invalid"
                )

            manifest = load_consumer_v2_file(
                manifest_path,
                "output/consumer/v2/manifest.json",
            )
            validate_schema(
                manifest,
                CONSUMER_V2_MANIFEST_SCHEMA,
                "output/consumer/v2/manifest.json",
            )

            phase_chunks = _load_consumer_v2_kind(
                v2_root,
                "phases",
                manifest["phase_inventory"],
            )
            detail_chunks = _load_consumer_v2_kind(
                v2_root,
                "details",
                manifest["detail_inventory"],
            )

            validate_consumer_v2_payloads(
                manifest,
                phase_chunks,
                detail_chunks,
                current[3],
            )
        count += 1
    return count

def main() -> int:
    try:
        schemas = {
            "latest": load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"),
            "consumer": load_json(ROOT / "schemas" / "consumer_snapshot.schema.json"),
            "consumer_details": load_json(ROOT / "schemas" / "consumer_details.schema.json"),
            "consumer_v2_manifest": load_json(ROOT / "schemas" / "consumer_manifest_v2.schema.json"),
            "consumer_v2_chunk": load_json(ROOT / "schemas" / "consumer_chunk_v2.schema.json"),
            "judgment": load_json(ROOT / "schemas" / "judgment_record.schema.json"),
            "master": load_json(ROOT / "schemas" / "theme_master.schema.json"),
            "generation_manifest": load_json(ROOT / "schemas" / "generation_manifest.schema.json"),
            "publication_pointer": load_json(ROOT / "schemas" / "publication_pointer.schema.json"),
            "history_item": load_json(ROOT / "schemas" / "history_item.schema.json"),
            "judgment_index": load_json(ROOT / "schemas" / "judgment_index.schema.json"),
            "prediction_legacy": load_json(ROOT / "schemas" / "prediction_record.schema.json"),
            "verification_legacy": load_json(ROOT / "schemas" / "verification_record.schema.json"),
        }
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
        validate_repository_output_inventory(ROOT / "output", require_consumer=True)
        master = load_json(ROOT / "data" / "themes.json")
        validate_schema(master, schemas["master"], "data/themes.json")
        warnings = validate_theme_master_semantics(master)
        config_path = ROOT / "config" / "universe.json"
        if config_path.exists():
            config = load_json(config_path)
            fixed_ids = {theme["theme_id"] for theme in master["themes"]}
            dynamic_ids = set(config.get("dynamic_industries", {}))
            configured_ids = fixed_ids | dynamic_ids
            if set(config.get("structural_contexts", {})) != configured_ids:
                raise ContractError("structural contexts must cover exactly all fixed themes and configured dynamic industries")
            if set(config.get("research_lenses", {})) != configured_ids:
                raise ContractError("research lenses must cover exactly all fixed themes and configured dynamic industries")
            for item_id, context in config["structural_contexts"].items():
                if context.get("version") != config.get("structural_context_version") or context.get("status") not in {"supported", "uncertain", "unsupported", "not_assessed"}:
                    raise ContractError(f"invalid versioned structural context: {item_id}")
            for item_id, lenses in config["research_lenses"].items():
                if set(lenses) != {"representative", "breadth_check"}:
                    raise ContractError(f"research lenses require representative and breadth_check: {item_id}")
                for role, lens in lenses.items():
                    if not lens.get("key_check") or not lens.get("counter_evidence"):
                        raise ContractError(f"incomplete research lens: {item_id}/{role}")
            lens_text = str({
                "themes": config.get("research_lenses", {}),
                "tickers": config.get("company_research_overrides", {}),
                "roles": config.get("role_research_lenses", {}),
                "global": config.get("global_research_lens", {}),
            })
            forbidden_initial_terms = ("初動", "拡散", "失速", "悪化", "反転", "流入継続", "流出継続", "加速", "減速")
            leaked = [term for term in forbidden_initial_terms if term in lens_text]
            if leaked:
                raise ContractError(f"research lenses contain initial-observation trend claims: {leaked}")
        fixture_dir = ROOT / "tests" / "fixtures"
        for path in sorted(fixture_dir.glob("latest_*.json")):
            value = load_json(path)
            validate_schema(value, schemas["latest"], str(path.relative_to(ROOT)))
            validate_latest_semantics(value, verify_source_hash=True)
        sample_latest = load_json(ROOT / "docs" / "sample_latest.json")
        validate_schema(sample_latest, schemas["latest"], "docs/sample_latest.json")
        validate_latest_semantics(sample_latest, verify_source_hash=True)
        fixture_judgment = load_json(fixture_dir / "judgment_record.json")
        validate_schema(fixture_judgment, schemas["judgment"], "fixture judgment")
        validate_judgment_semantics(fixture_judgment, load_json(fixture_dir / "latest_normal.json"))
        sample_judgment = load_json(ROOT / "docs" / "judgment_example.json")
        validate_schema(sample_judgment, schemas["judgment"], "docs/judgment_example.json")
        validate_judgment_semantics(sample_judgment, sample_latest)
        fixture_master = load_json(fixture_dir / "theme_master.json")
        validate_schema(fixture_master, schemas["master"], "fixture master")
        validate_theme_master_semantics(fixture_master)
        display_cases = load_json(fixture_dir / "user_display_cases.json")
        case_ids = [case.get("id") for case in display_cases.get("cases", [])]
        if len(case_ids) != 8 or len(case_ids) != len(set(case_ids)):
            raise ContractError("display fixture registry must contain exactly 8 unique cases")
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
            index_snapshot = StableJsonSnapshot.read(
                index_path,
                relative_path="output/judgments/index.json",
                label="root judgment index",
            )
            verify_index(
                judgment_dir, index_snapshot.value, schemas["judgment"], source_loader,
            )
            index_snapshot.ensure_unchanged()
        current_generation = load_current_generation(ROOT / "output")
        if current_generation is not None:
            generation_index = {key: value for key, value in current_generation[5].items() if key != "publication"}
            if generation_index != rebuilt:
                raise ContractError("current generation judgment index does not match validated immutable records")
        instructions = (ROOT / "docs" / "custom_gpt_instructions_current.md").read_text(encoding="utf-8")
        if len(instructions) > 8000:
            raise ContractError(f"Custom GPT instructions exceed 8,000 characters: {len(instructions)}")
        required_terms = [
            "更新", "次", "詳細", "用語", "再評価", "user_view.phases",
            "consumer/v2/manifest.json", "consumer_contract_version=\"2.0\"",
            "phase_inventory", "detail_inventory", "part_count", "fragments",
            "source_identity.analysis_id", "source_identity.generation_id",
            "404の場合だけ", "critical_missing=[]", "presentation_version=\"1.2\"",
            "consumer_contract_version=\"1.0\"", "initial_observation",
            "資金流入・流出と断定しない", "不完全JSON", "前回キャッシュ",
            "details/phase-", "details_contract_version=\"1.0\"", "表示を停止",
        ]
        missing = [term for term in required_terms if term not in instructions]
        if missing:
            raise ContractError(f"Custom GPT instructions missing contract terms: {missing}")
        for old_name in ("custom_gpt_instructions_v1.1.md", "custom_gpt_instructions_v1.2.md", "custom_gpt_instructions_v2.md", "custom_gpt_instructions_v1.4.md"):
            old_text = (ROOT / "docs" / old_name).read_text(encoding="utf-8")
            if "Deprecated" not in old_text or "custom_gpt_instructions_current.md" not in old_text:
                raise ContractError(f"historical Custom GPT instructions are not clearly deprecated: {old_name}")
        print(f"validation passed: 13 schemas, 7 latest fixtures, 8 display fixtures, 1 sample latest, 1 judgment fixture, 1 sample judgment, 1 master fixture, {public_count} public outputs, {len(warnings)} overlap warnings")
        return 0
    except (ContractError, OSError, ValueError) as error:
        print(f"validation failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
