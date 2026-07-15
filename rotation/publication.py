"""Generation-scoped transactional publication with an atomic current pointer."""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .provenance import atomic_write_json, canonical_bytes, stable_hash
from .validation import ContractError, load_json, validate_public_latest, validate_schema


GENERATION_VERSION = "1.0"
POINTER_VERSION = "1.0"
GENERATION_FILES = ("archive.json", "history.json", "judgment-index.json", "latest.json")
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
MANIFEST_SCHEMA = load_json(SCHEMA_ROOT / "generation_manifest.schema.json")
POINTER_SCHEMA = load_json(SCHEMA_ROOT / "publication_pointer.schema.json")


def generation_manifest(snapshot: dict, history: dict, index: dict, previous_run_id: str | None) -> dict:
    files = {
        "archive.json": stable_hash(snapshot),
        "history.json": stable_hash(history),
        "judgment-index.json": stable_hash(index),
        "latest.json": stable_hash(snapshot),
    }
    return {
        "generation_version": GENERATION_VERSION,
        "run_id": snapshot["meta"]["run_id"],
        "data_date": snapshot["meta"]["data_date"],
        "source_sha256": snapshot["meta"]["source_sha256"],
        "previous_run_id": previous_run_id,
        "files": files,
    }


def current_pointer(manifest: dict) -> dict:
    run_id = manifest["run_id"]
    return {
        "pointer_version": POINTER_VERSION,
        "run_id": run_id,
        "data_date": manifest["data_date"],
        "generation": f"generations/{run_id}",
        "manifest_sha256": stable_hash(manifest),
    }


def validate_generation(directory: Path) -> tuple[dict, dict, dict, dict]:
    manifest = load_json(directory / "manifest.json")
    validate_schema(manifest, MANIFEST_SCHEMA, str(directory / "manifest.json"))
    if manifest.get("generation_version") != GENERATION_VERSION:
        raise ContractError(f"unsupported generation manifest: {directory}")
    missing = [name for name in (*GENERATION_FILES, "manifest.json") if not (directory / name).is_file()]
    if missing:
        raise ContractError(f"generation is incomplete: {missing}")
    latest = load_json(directory / "latest.json")
    archive = load_json(directory / "archive.json")
    history = load_json(directory / "history.json")
    index = load_json(directory / "judgment-index.json")
    validate_public_latest(latest, verify_source_hash=True)
    validate_public_latest(archive, verify_source_hash=True)
    if canonical_bytes(latest) != canonical_bytes(archive):
        raise ContractError("generation latest/archive mismatch")
    meta = latest["meta"]
    expected_source = f"output/generations/{meta['run_id']}/archive.json"
    if meta.get("source_snapshot") != expected_source:
        raise ContractError(f"generation source_snapshot mismatch; expected {expected_source}")
    for field in ("run_id", "data_date", "source_sha256"):
        if manifest.get(field) != meta.get(field):
            raise ContractError(f"generation manifest {field} mismatch")
    if history.get("data_date") != meta.get("data_date"):
        raise ContractError("generation history data_date mismatch")
    if history.get("schema_version") != meta.get("schema_version") or history.get("methodology_version") != meta.get("methodology_version"):
        raise ContractError("generation history version mismatch")
    publication = index.get("publication", {})
    for field in ("run_id", "data_date", "source_sha256"):
        if publication.get(field) != meta.get(field):
            raise ContractError(f"generation judgment index {field} mismatch")
    expected_hashes = {
        "archive.json": stable_hash(archive),
        "history.json": stable_hash(history),
        "judgment-index.json": stable_hash(index),
        "latest.json": stable_hash(latest),
    }
    if manifest.get("files") != expected_hashes:
        raise ContractError("generation file hash mismatch")
    return manifest, latest, history, index


def load_current_generation(output: Path) -> tuple[dict, Path, dict, dict, dict, dict] | None:
    pointer_path = output / "current.json"
    if not pointer_path.is_file():
        return None
    pointer = load_json(pointer_path)
    validate_schema(pointer, POINTER_SCHEMA, str(pointer_path))
    if pointer.get("pointer_version") != POINTER_VERSION:
        raise ContractError("unsupported current pointer")
    relative = pointer.get("generation")
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ContractError("unsafe current generation path")
    directory = output / relative
    manifest, latest, history, index = validate_generation(directory)
    if pointer.get("run_id") != manifest.get("run_id") or pointer.get("data_date") != manifest.get("data_date"):
        raise ContractError("current pointer identity mismatch")
    if pointer.get("manifest_sha256") != stable_hash(manifest):
        raise ContractError("current pointer manifest hash mismatch")
    return pointer, directory, manifest, latest, history, index


def committed_history(output: Path, limit: int = 12) -> list[dict]:
    current = load_current_generation(output)
    if current is None:
        return []
    values = []
    seen = set()
    manifest = current[2]
    directory = current[1]
    while manifest and len(values) < limit:
        run_id = manifest["run_id"]
        if run_id in seen:
            raise ContractError("generation history chain contains a cycle")
        seen.add(run_id)
        _, _, history, _ = validate_generation(directory)
        values.append(history)
        previous = manifest.get("previous_run_id")
        if previous is None:
            break
        directory = output / "generations" / previous
        manifest, _, _, _ = validate_generation(directory)
    values.reverse()
    # One committed item per data date, even after an idempotent retry.
    by_date = {value["data_date"]: value for value in values}
    return [by_date[key] for key in sorted(by_date)][-limit:]


@contextmanager
def publication_lock(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".publish.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ContractError("another publication is in progress") from error
    os.close(descriptor)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def publish_generation(
    output: Path,
    snapshot: dict,
    history: dict,
    index: dict,
    failure_injector: Callable[[str], None] | None = None,
) -> dict:
    """Stage a complete generation and atomically switch the public pointer."""
    validate_public_latest(snapshot, verify_source_hash=True)
    inject = failure_injector or (lambda _step: None)
    run_id = snapshot["meta"]["run_id"]
    index = {
        **index,
        "publication": {
            "run_id": run_id,
            "data_date": snapshot["meta"]["data_date"],
            "source_sha256": snapshot["meta"]["source_sha256"],
        },
    }
    generations = output / "generations"
    target = generations / run_id
    with publication_lock(output):
        current = load_current_generation(output)
        previous_run_id = current[2]["run_id"] if current else None
        if current and previous_run_id == run_id:
            if current[3] != snapshot or current[4] != history or current[5] != index:
                raise ContractError(f"current generation {run_id} has different content")
            return current[0]
        if current and current[2]["data_date"] == snapshot["meta"]["data_date"] and previous_run_id != run_id:
            raise ContractError("same data_date already has a different published generation")
        manifest = generation_manifest(snapshot, history, index, previous_run_id)
        pointer = current_pointer(manifest)
        if target.exists():
            existing_manifest, existing_latest, existing_history, existing_index = validate_generation(target)
            if any((
                existing_manifest != manifest,
                canonical_bytes(existing_latest) != canonical_bytes(snapshot),
                existing_history != history,
                existing_index != index,
            )):
                raise ContractError(f"generation {run_id} already exists with different content")
        else:
            generations.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".staging-{run_id}-", dir=output))
            try:
                for filename, value, step in (
                    ("archive.json", snapshot, "archive_staging_write"),
                    ("history.json", history, "history_staging_write"),
                    ("judgment-index.json", index, "judgment_index_staging_write"),
                    ("latest.json", snapshot, "latest_staging_write"),
                ):
                    atomic_write_json(staging / filename, value)
                    inject(step)
                atomic_write_json(staging / "manifest.json", manifest)
                inject("manifest_write")
                validate_generation(staging)
                inject("generation_rename")
                os.replace(staging, target)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        inject("current_pointer_switch")
        atomic_write_json(output / "current.json", pointer)
        loaded = load_current_generation(output)
        if loaded is None or loaded[2] != manifest:
            raise ContractError("current generation verification failed")
        return pointer
