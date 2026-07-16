"""Publication contract 1.0: validated generations and one atomic current pointer."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable

from . import INSTRUCTION_VERSION, PUBLICATION_CONTRACT_VERSION
from .identity import safe_generation_path, validate_safe_id
from .provenance import atomic_write_json, canonical_bytes, file_sha256, stable_hash
from .publication_lock import owned_lock
from .validation import (
    ContractError, load_json, validate_judgment_semantics, validate_public_latest,
    validate_schema,
)


GENERATION_VERSION = "1.0"
POINTER_VERSION = "1.0"
GENERATION_FILES = ("archive.json", "history.json", "judgment-index.json", "latest.json")
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
LATEST_SCHEMA = load_json(SCHEMA_ROOT / "rotation_snapshot.schema.json")
HISTORY_SCHEMA = load_json(SCHEMA_ROOT / "history_item.schema.json")
INDEX_SCHEMA = load_json(SCHEMA_ROOT / "judgment_index.schema.json")
JUDGMENT_SCHEMA = load_json(SCHEMA_ROOT / "judgment_record.schema.json")
MANIFEST_SCHEMA = load_json(SCHEMA_ROOT / "generation_manifest.schema.json")
POINTER_SCHEMA = load_json(SCHEMA_ROOT / "publication_pointer.schema.json")


def _generation_id(snapshot: dict) -> str:
    source = snapshot.get("meta", {}).get("source_snapshot", "")
    parts = Path(source).as_posix().split("/")
    if len(parts) != 4 or parts[:2] != ["output", "generations"] or parts[3] != "archive.json":
        raise ContractError("source_snapshot must be output/generations/<generation_id>/archive.json")
    return validate_safe_id(parts[2], "generation_id")  # type: ignore[return-value]


def _expected_history(latest: dict) -> dict:
    return {
        "data_date": latest["meta"]["data_date"],
        "schema_version": latest["meta"]["schema_version"],
        "methodology_version": latest["meta"]["methodology_version"],
        "theme_master_version": latest["meta"]["universe_definition"]["theme_master_version"],
        "themes": {theme_id: {
            "equal_weight_rel_spy_4w": theme["metrics"]["equal_weight_rel_spy_4w"],
            "advance_count_4w": theme["metrics"]["advance_count_4w"],
            "above_50dma_count": theme["metrics"]["above_50dma_count"],
            "pct_above_50dma": theme["metrics"]["pct_above_50dma"],
            "volume_ratio_20d_60d": theme["metrics"]["volume_ratio_20d_60d"],
        } for theme_id, theme in latest["themes"].items()},
    }


def generation_manifest(snapshot: dict, history: dict, index: dict, previous_generation_id: str | None) -> dict:
    analysis_id = validate_safe_id(snapshot["meta"]["run_id"], "analysis_id")
    generation_id = _generation_id(snapshot)
    validate_safe_id(previous_generation_id, "previous_generation_id", nullable=True)
    return {
        "publication_contract_version": PUBLICATION_CONTRACT_VERSION,
        "generation_version": GENERATION_VERSION,
        "analysis_id": analysis_id, "generation_id": generation_id, "run_id": analysis_id,
        "data_date": snapshot["meta"]["data_date"], "generated_at": snapshot["meta"]["generated_at"],
        "source_commit": snapshot["meta"]["source_commit"], "source_sha256": snapshot["meta"]["source_sha256"],
        "previous_generation_id": previous_generation_id,
        "files": {name: stable_hash(snapshot if name in {"archive.json", "latest.json"} else history if name == "history.json" else index) for name in GENERATION_FILES},
    }


def current_pointer(manifest: dict) -> dict:
    generation_id = validate_safe_id(manifest["generation_id"], "generation_id")
    return {
        "publication_contract_version": PUBLICATION_CONTRACT_VERSION,
        "pointer_version": POINTER_VERSION,
        "analysis_id": manifest["analysis_id"], "generation_id": generation_id,
        "run_id": manifest["run_id"], "data_date": manifest["data_date"],
        "generation": f"generations/{generation_id}",
        "previous_generation_id": manifest["previous_generation_id"],
        "manifest_sha256": stable_hash(manifest),
    }


def _output_for(directory: Path) -> Path:
    return directory.parents[1] if directory.parent.name == "generations" else directory.parent


def validate_generation(directory: Path) -> tuple[dict, dict, dict, dict]:
    missing = [name for name in (*GENERATION_FILES, "manifest.json") if not (directory / name).is_file()]
    if missing:
        raise ContractError(f"generation is incomplete: {missing}")
    manifest = load_json(directory / "manifest.json")
    latest = load_json(directory / "latest.json")
    archive = load_json(directory / "archive.json")
    history = load_json(directory / "history.json")
    index = load_json(directory / "judgment-index.json")
    validate_schema(manifest, MANIFEST_SCHEMA, str(directory / "manifest.json"))
    validate_schema(latest, LATEST_SCHEMA, str(directory / "latest.json"))
    validate_schema(archive, LATEST_SCHEMA, str(directory / "archive.json"))  # archive uses the latest contract
    validate_schema(history, HISTORY_SCHEMA, str(directory / "history.json"))
    validate_schema(index, INDEX_SCHEMA, str(directory / "judgment-index.json"))
    validate_public_latest(latest, verify_source_hash=True)
    validate_public_latest(archive, verify_source_hash=True)
    if canonical_bytes(latest) != canonical_bytes(archive):
        raise ContractError("generation latest/archive mismatch")
    meta = latest["meta"]
    generation_id = _generation_id(latest)
    for label, value in (("analysis_id", manifest.get("analysis_id")), ("generation_id", manifest.get("generation_id")),
                         ("run_id", manifest.get("run_id")), ("previous_generation_id", manifest.get("previous_generation_id"))):
        validate_safe_id(value, label, nullable=label == "previous_generation_id")
    if directory.parent.name == "generations" and directory.name != generation_id:
        raise ContractError("generation directory identity mismatch")
    expected = {
        "analysis_id": meta["run_id"], "generation_id": generation_id, "run_id": meta["run_id"],
        "data_date": meta["data_date"], "generated_at": meta["generated_at"],
        "source_commit": meta["source_commit"], "source_sha256": meta["source_sha256"],
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise ContractError(f"generation manifest {field} mismatch")
    if history != _expected_history(latest):
        raise ContractError("generation history semantic mismatch")
    publication = index["publication"]
    index_expected = {"analysis_id": meta["run_id"], "generation_id": generation_id, "run_id": meta["run_id"],
                      "data_date": meta["data_date"], "source_sha256": meta["source_sha256"],
                      "instruction_version": INSTRUCTION_VERSION}
    if publication != index_expected:
        raise ContractError("generation judgment index publication identity mismatch")
    output = _output_for(directory)
    seen = set()
    for entry in index["records"]:
        validate_schema(entry["content"], JUDGMENT_SCHEMA, f"judgment index {entry['judgment_id']}")
        if entry["judgment_id"] in seen or entry["judgment_id"] != entry["content"].get("judgment_id") or entry["data_date"] != entry["content"].get("data_date"):
            raise ContractError("judgment index record identity mismatch")
        seen.add(entry["judgment_id"])
        immutable = output / "judgments" / entry["file"]
        if not immutable.is_file() or file_sha256(immutable) != entry["sha256"]:
            raise ContractError("judgment index immutable file mismatch")
        source = output.parent / entry["content"]["source_snapshot"]
        validate_judgment_semantics(entry["content"], load_json(source) if source.is_file() else None)
    if index["records"] != sorted(index["records"], key=lambda item: (item["data_date"], item["judgment_id"])):
        raise ContractError("judgment index record order is not deterministic")
    hashes = {name: stable_hash({"archive.json": archive, "history.json": history, "judgment-index.json": index, "latest.json": latest}[name]) for name in GENERATION_FILES}
    if manifest["files"] != hashes:
        raise ContractError("generation file hash mismatch")
    return manifest, latest, history, index


def validate_pointer_candidate(output: Path, pointer: dict) -> tuple[dict, dict, dict, dict]:
    validate_schema(pointer, POINTER_SCHEMA, "publication pointer candidate")
    generation_id = validate_safe_id(pointer["generation_id"], "generation_id")
    validate_safe_id(pointer["analysis_id"], "analysis_id")
    validate_safe_id(pointer["run_id"], "run_id")
    validate_safe_id(pointer["previous_generation_id"], "previous_generation_id", nullable=True)
    if pointer["generation"] != f"generations/{generation_id}":
        raise ContractError("publication pointer generation path mismatch")
    directory = safe_generation_path(output, generation_id)
    if not directory.is_dir():
        raise ContractError("publication pointer generation does not exist")
    manifest, latest, history, index = validate_generation(directory)
    comparisons = ("analysis_id", "generation_id", "run_id", "data_date", "previous_generation_id")
    if any(pointer[field] != manifest[field] for field in comparisons) or pointer["manifest_sha256"] != stable_hash(manifest):
        raise ContractError("publication pointer and generation manifest mismatch")
    previous = pointer["previous_generation_id"]
    if previous == generation_id:
        raise ContractError("publication pointer cannot reference itself as previous generation")
    if previous is not None:
        previous_directory = safe_generation_path(output, previous)
        if not previous_directory.is_dir():
            raise ContractError("publication pointer previous generation does not exist")
        validate_generation(previous_directory)
    return manifest, latest, history, index


def load_current_generation(output: Path) -> tuple[dict, Path, dict, dict, dict, dict] | None:
    pointer_path = output / "current.json"
    if not pointer_path.is_file():
        return None
    pointer = load_json(pointer_path)
    manifest, latest, history, index = validate_pointer_candidate(output, pointer)
    return pointer, safe_generation_path(output, pointer["generation_id"]), manifest, latest, history, index


def committed_history(output: Path, limit: int = 12) -> list[dict]:
    current = load_current_generation(output)
    if current is None:
        return []
    values, seen = [], set()
    directory, manifest = current[1], current[2]
    while manifest and len(values) < limit:
        generation_id = manifest["generation_id"]
        if generation_id in seen:
            raise ContractError("generation history chain contains a cycle")
        seen.add(generation_id)
        manifest, _, history, _ = validate_generation(directory)
        values.append(history)
        previous = manifest["previous_generation_id"]
        if previous is None:
            break
        directory = safe_generation_path(output, previous)
        manifest, _, _, _ = validate_generation(directory)
    by_date = {value["data_date"]: value for value in reversed(values)}
    return [by_date[key] for key in sorted(by_date)][-limit:]


def _valid_orphans(output: Path, analysis_id: str, current_generation_id: str | None) -> list[tuple[dict, Path]]:
    candidates = []
    generations = output / "generations"
    if not generations.is_dir():
        return candidates
    for path in sorted(generations.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.name == current_generation_id:
            continue
        try:
            manifest, *_ = validate_generation(path)
        except (ContractError, OSError, ValueError):
            continue
        if manifest["analysis_id"] == analysis_id and manifest["previous_generation_id"] == current_generation_id:
            candidates.append((manifest, path))
    return sorted(candidates, key=lambda item: (item[0]["generated_at"], item[0]["generation_id"]))


def publish_generation(output: Path, snapshot: dict, history: dict, index: dict,
                       failure_injector: Callable[[str], None] | None = None) -> dict:
    """Stage, fully validate, rename, then prevalidate and atomically switch current."""
    validate_schema(snapshot, LATEST_SCHEMA, "publication latest")
    validate_public_latest(snapshot, verify_source_hash=True)
    analysis_id = validate_safe_id(snapshot["meta"]["run_id"], "analysis_id")
    generation_id = _generation_id(snapshot)
    target = safe_generation_path(output, generation_id)
    inject = failure_injector or (lambda _step: None)
    with owned_lock(output / ".publish.lock", analysis_id):
        current = load_current_generation(output)
        current_generation_id = current[2]["generation_id"] if current else None
        if current and current[2]["analysis_id"] == analysis_id:
            return current[0]
        if current and snapshot["meta"]["data_date"] < current[2]["data_date"]:
            raise ContractError("publication data_date cannot move backwards; use explicit rollback")
        orphans = _valid_orphans(output, analysis_id, current_generation_id)
        if orphans:
            manifest, _ = orphans[0]
            pointer = current_pointer(manifest)
            validate_pointer_candidate(output, pointer)
            inject("current_pointer_switch")
            atomic_write_json(output / "current.json", pointer)
            return pointer
        previous_generation_id = current_generation_id
        index = {**index, "publication": {
            "analysis_id": analysis_id, "generation_id": generation_id, "run_id": analysis_id,
            "data_date": snapshot["meta"]["data_date"], "source_sha256": snapshot["meta"]["source_sha256"],
            "instruction_version": INSTRUCTION_VERSION,
        }}
        manifest = generation_manifest(snapshot, history, index, previous_generation_id)
        if target.exists():
            # A colliding valid generation is reusable; an invalid collision is never overwritten.
            existing = validate_generation(target)
            if existing[0] != manifest:
                raise ContractError(f"generation {generation_id} already exists with different content")
        else:
            output.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".staging-{generation_id}-", dir=output))
            try:
                for filename, value, step in (
                    ("archive.json", snapshot, "archive_staging_write"), ("history.json", history, "history_staging_write"),
                    ("judgment-index.json", index, "judgment_index_staging_write"), ("latest.json", snapshot, "latest_staging_write"),
                ):
                    atomic_write_json(staging / filename, value); inject(step)
                atomic_write_json(staging / "manifest.json", manifest); inject("manifest_write")
                validate_generation(staging)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.parent.resolve().relative_to((output / "generations").resolve())
                staging.replace(target)
                inject("generation_rename")
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        pointer = current_pointer(manifest)
        validate_pointer_candidate(output, pointer)
        inject("current_pointer_switch")
        atomic_write_json(output / "current.json", pointer)
        loaded = load_current_generation(output)
        if loaded is None or loaded[2] != manifest:
            raise ContractError("current generation verification failed")
        return pointer
