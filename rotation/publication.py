"""Publication contract 1.1: validated generations and one atomic current pointer."""
from __future__ import annotations

import copy
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from . import INSTRUCTION_VERSION, PUBLICATION_CONTRACT_VERSION
from .consumer import validate_consumer_artifact
from .identity import safe_generation_path, validate_safe_id
from .judgments import StableJsonChangedError, StableJsonSnapshot, validate_index_records
from .provenance import atomic_write_json, canonical_bytes, stable_hash
from .publication_lock import owned_lock
from .validation import (
    ContractError, load_json, validate_public_latest,
    validate_schema,
)


GENERATION_VERSION = "1.0"
POINTER_VERSION = "1.0"
GENERATION_FILES = ("archive.json", "history.json", "judgment-index.json", "latest.json")
GENERATION_ENTRY_SET = frozenset((*GENERATION_FILES, "manifest.json"))
PLACEHOLDER_DIRECTORIES = frozenset({"archive", "history", "judgments", "predictions", "verifications"})
EMPTY_JUDGMENT_INDEX = {"index_version": "1.0", "records": []}
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
LATEST_SCHEMA = load_json(SCHEMA_ROOT / "rotation_snapshot.schema.json")
HISTORY_SCHEMA = load_json(SCHEMA_ROOT / "history_item.schema.json")
INDEX_SCHEMA = load_json(SCHEMA_ROOT / "judgment_index.schema.json")
JUDGMENT_SCHEMA = load_json(SCHEMA_ROOT / "judgment_record.schema.json")
MANIFEST_SCHEMA = load_json(SCHEMA_ROOT / "generation_manifest.schema.json")
POINTER_SCHEMA = load_json(SCHEMA_ROOT / "publication_pointer.schema.json")
PREDICTION_SCHEMA = load_json(SCHEMA_ROOT / "prediction_record.schema.json")
VERIFICATION_SCHEMA = load_json(SCHEMA_ROOT / "verification_record.schema.json")


def instruction_version_for_data_schema(schema_version: str) -> str:
    """Return the instruction identity valid when a snapshot was created."""
    return "1.1.1" if schema_version == "1.1" else INSTRUCTION_VERSION


def instruction_versions_for_data_schema(schema_version: str) -> set[str]:
    """Return read-compatible instruction identities for immutable generations."""
    return {"1.1.1"} if schema_version == "1.1" else {"1.3.0", INSTRUCTION_VERSION}


@dataclass(frozen=True)
class PublicationStartState:
    kind: Literal[
        "clean", "fixed_legacy", "partial_legacy", "ambiguous", "current",
        "invalid_current", "interrupted_transaction",
    ]
    path: str | None = None


class PublicationInventoryError(ContractError):
    """A path-only inventory error safe to surface in automation logs."""

    def __init__(self, message: str, path: str):
        super().__init__(message)
        self.path = path


def output_relative_path(output: Path, path: Path) -> str:
    if path == output:
        return "output"
    return f"output/{path.relative_to(output).as_posix()}"


def _inventory_error(output: Path, path: Path, reason: str = "unexpected publication entry") -> PublicationInventoryError:
    display = output_relative_path(output, path)
    return PublicationInventoryError(f"{reason}: {display}", display)


def _regular_entries(output: Path, directory: Path, expected: set[str] | frozenset[str]) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise _inventory_error(output, directory)
    entries = {entry.name: entry for entry in directory.iterdir()}
    unexpected = sorted(set(entries) - set(expected))
    missing = sorted(set(expected) - set(entries))
    if unexpected:
        raise _inventory_error(output, entries[unexpected[0]])
    if missing:
        raise _inventory_error(output, directory / missing[0], "missing publication entry")
    for name in sorted(expected):
        path = entries[name]
        if path.is_symlink() or not path.is_file():
            raise _inventory_error(output, path)


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
    output = _output_for(directory)
    _regular_entries(output, directory, GENERATION_ENTRY_SET)
    manifest = load_json(directory / "manifest.json")
    latest = load_json(directory / "latest.json")
    archive = load_json(directory / "archive.json")
    history = load_json(directory / "history.json")
    index_snapshot = StableJsonSnapshot.read(
        directory / "judgment-index.json",
        relative_path=output_relative_path(output, directory / "judgment-index.json"),
        label="generation judgment index",
    )
    index = index_snapshot.value
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
                      "data_date": meta["data_date"], "source_sha256": meta["source_sha256"]}
    if (
        {key: value for key, value in publication.items() if key != "instruction_version"} != index_expected
        or publication.get("instruction_version") not in instruction_versions_for_data_schema(meta["schema_version"])
    ):
        raise ContractError("generation judgment index publication identity mismatch")
    def source_loader(record: dict) -> dict | None:
        source = output.parent / record["source_snapshot"]
        return load_json(source) if source.is_file() else None
    validate_index_records(output / "judgments", index, JUDGMENT_SCHEMA, source_loader)
    hashes = {name: stable_hash({"archive.json": archive, "history.json": history, "judgment-index.json": index, "latest.json": latest}[name]) for name in GENERATION_FILES}
    if manifest["files"] != hashes:
        raise ContractError("generation file hash mismatch")
    index_snapshot.ensure_unchanged()
    return manifest, latest, history, index


def _validate_generation_chronology(child: dict, previous: dict) -> None:
    if child["data_date"] < previous["data_date"]:
        raise ContractError(
            "generation chronology violation: "
            f"generation_id={child['generation_id']} "
            f"previous_generation_id={previous['generation_id']} "
            f"child_data_date={child['data_date']} "
            f"previous_data_date={previous['data_date']}"
        )


def _validate_ancestor_chain(output: Path, manifest: dict) -> None:
    seen = {manifest["generation_id"]}
    child = manifest
    while child["previous_generation_id"] is not None:
        previous_id = child["previous_generation_id"]
        if previous_id in seen:
            raise ContractError(
                "generation history cycle: "
                f"generation_id={child['generation_id']} previous_generation_id={previous_id}"
            )
        previous_directory = safe_generation_path(output, previous_id)
        if not previous_directory.is_dir():
            raise ContractError(
                "publication pointer previous generation does not exist: "
                f"generation_id={child['generation_id']} previous_generation_id={previous_id}"
            )
        previous = validate_generation(previous_directory)[0]
        _validate_generation_chronology(child, previous)
        seen.add(previous_id)
        child = previous


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
    if pointer["publication_contract_version"] != manifest["publication_contract_version"]:
        raise ContractError("publication pointer and generation manifest contract version mismatch")
    previous = pointer["previous_generation_id"]
    if previous == generation_id:
        raise ContractError("publication pointer cannot reference itself as previous generation")
    _validate_ancestor_chain(output, manifest)
    return manifest, latest, history, index


def load_current_generation(output: Path) -> tuple[dict, Path, dict, dict, dict, dict] | None:
    pointer_path = output / "current.json"
    if not pointer_path.is_file():
        return None
    pointer = load_json(pointer_path)
    manifest, latest, history, index = validate_pointer_candidate(output, pointer)
    return pointer, safe_generation_path(output, pointer["generation_id"]), manifest, latest, history, index


def _add_regular_file(output: Path, path: Path, files: set[str]) -> None:
    if path.is_symlink() or not path.is_file():
        raise _inventory_error(output, path)
    files.add(output_relative_path(output, path))


def _validate_placeholder_directory(
    output: Path, name: str, files: set[str], *, judgment_index: dict | None = None,
) -> None:
    directory = output / name
    if not directory.exists() and not directory.is_symlink():
        return
    if directory.is_symlink() or not directory.is_dir():
        raise _inventory_error(output, directory)
    expected = {".gitkeep"}
    if name == "judgments" and judgment_index is not None:
        expected.add("index.json")
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.name not in expected:
            raise _inventory_error(output, entry)
        _add_regular_file(output, entry, files)
        if entry.name == "index.json":
            try:
                value = load_json(entry)
            except (OSError, UnicodeError, ValueError) as error:
                raise _inventory_error(output, entry, "invalid publication entry") from error
            if value != judgment_index:
                raise _inventory_error(output, entry, "invalid publication entry")


def _validate_clean_inventory(output: Path) -> set[str]:
    files: set[str] = set()
    if not output.exists() and not output.is_symlink():
        return files
    if output.is_symlink() or not output.is_dir():
        raise _inventory_error(output, output)
    for entry in sorted(output.iterdir(), key=lambda item: item.name):
        if entry.name not in PLACEHOLDER_DIRECTORIES:
            raise _inventory_error(output, entry)
    for name in sorted(PLACEHOLDER_DIRECTORIES):
        _validate_placeholder_directory(
            output, name, files,
            judgment_index=EMPTY_JUDGMENT_INDEX if name == "judgments" else None,
        )
    return files


def _validate_flat_contract_directory(
    output: Path, name: str, schema: dict, files: set[str], *, latest: bool = False,
) -> None:
    directory = output / name
    if not directory.exists() and not directory.is_symlink():
        return
    if directory.is_symlink() or not directory.is_dir():
        raise _inventory_error(output, directory)
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.name == ".gitkeep":
            _add_regular_file(output, entry, files)
            continue
        if entry.is_symlink() or not entry.is_file() or entry.suffix != ".json":
            raise _inventory_error(output, entry)
        try:
            value = load_json(entry)
            validate_schema(value, schema, output_relative_path(output, entry))
            if latest:
                validate_public_latest(value, verify_source_hash=True)
        except (ContractError, OSError, UnicodeError, ValueError) as error:
            raise _inventory_error(output, entry, "invalid publication entry") from error
        files.add(output_relative_path(output, entry))


def _validate_root_judgments(output: Path, index: dict, files: set[str]) -> None:
    directory = output / "judgments"
    if directory.is_symlink() or not directory.is_dir():
        raise _inventory_error(output, directory, "missing publication entry")
    root_index = {key: value for key, value in index.items() if key != "publication"}
    expected = {"index.json", *(entry["file"] for entry in index["records"])}
    if (directory / ".gitkeep").exists():
        expected.add(".gitkeep")
    entries = {entry.name: entry for entry in directory.iterdir()}
    for name in sorted(set(entries) - expected):
        raise _inventory_error(output, entries[name])
    for name in sorted(expected - set(entries)):
        raise _inventory_error(output, directory / name, "missing publication entry")
    index_snapshot: StableJsonSnapshot | None = None
    for name in sorted(expected):
        entry = entries[name]
        _add_regular_file(output, entry, files)
        if name == "index.json":
            index_snapshot = StableJsonSnapshot.read(
                entry,
                relative_path=output_relative_path(output, entry),
                label="root judgment index",
            )
            value = index_snapshot.value
            if value != root_index:
                raise _inventory_error(output, entry, "invalid publication entry")
    if index_snapshot is None:  # pragma: no cover - guarded by the exact inventory checks above
        raise _inventory_error(output, directory / "index.json", "missing publication entry")
    index_snapshot.ensure_unchanged()


def _validate_generation_chain(
    output: Path, current: tuple, *, allow_recoverable_orphans: bool = False,
    recoverable_records: list[dict] | None = None,
) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    generation_ids: set[str] = set()
    manifest = current[2]
    while True:
        generation_id = manifest["generation_id"]
        if generation_id in generation_ids:
            raise _inventory_error(output, output / "generations" / generation_id, "generation history cycle")
        generation_ids.add(generation_id)
        directory = safe_generation_path(output, generation_id)
        manifest, *_ = validate_generation(directory)
        for name in sorted(GENERATION_ENTRY_SET):
            files.add(output_relative_path(output, directory / name))
        previous = manifest["previous_generation_id"]
        if previous is None:
            break
        directory = safe_generation_path(output, previous)
        try:
            previous_manifest, *_ = validate_generation(directory)
        except StableJsonChangedError:
            raise
        except (ContractError, OSError, ValueError) as error:
            raise _inventory_error(output, directory, "invalid publication generation") from error
        try:
            _validate_generation_chronology(manifest, previous_manifest)
        except ContractError as error:
            raise _inventory_error(output, directory, str(error)) from error
        manifest = previous_manifest

    generations = output / "generations"
    if generations.is_symlink() or not generations.is_dir():
        raise _inventory_error(output, generations, "missing publication entry")
    for entry in sorted(generations.iterdir(), key=lambda item: item.name):
        if entry.name not in generation_ids:
            if not allow_recoverable_orphans:
                raise _inventory_error(output, entry)
            try:
                orphan_manifest, _, _, orphan_index = validate_generation(entry)
            except StableJsonChangedError:
                raise
            except (ContractError, OSError, ValueError) as error:
                raise _inventory_error(output, entry, "invalid interrupted generation") from error
            if (
                orphan_manifest["previous_generation_id"] != current[2]["generation_id"]
                or orphan_index["records"] != (
                    current[5]["records"] if recoverable_records is None else recoverable_records
                )
            ):
                raise _inventory_error(output, entry, "unrecoverable interrupted generation")
            for name in GENERATION_ENTRY_SET:
                files.add(output_relative_path(output, entry / name))
        if entry.is_symlink() or not entry.is_dir():
            raise _inventory_error(output, entry)
    return files, generation_ids


def _validate_consumer(output: Path, current: tuple, files: set[str], *, required: bool) -> None:
    consumer = output / "consumer"
    expected = consumer / "latest.json"
    if not consumer.exists() and not consumer.is_symlink():
        if required:
            raise _inventory_error(output, expected, "missing publication entry")
        return
    if consumer.is_symlink() or not consumer.is_dir():
        raise _inventory_error(output, consumer)
    entries = list(consumer.iterdir())
    if len(entries) != 1 or entries[0].name != "latest.json":
        culprit = sorted(entries, key=lambda item: item.name)[0] if entries else expected
        raise _inventory_error(output, culprit)
    _add_regular_file(output, expected, files)
    try:
        value = load_json(expected)
        validate_consumer_artifact(
            value, current[3], pointer=current[0], manifest=current[2],
        )
    except (ContractError, OSError, UnicodeError, ValueError) as error:
        raise _inventory_error(output, expected, "invalid publication entry") from error


def _validate_current_publication_inventory(
    output: Path, *, require_consumer: bool, allow_recoverable_orphans: bool = False,
    recoverable_records: list[dict] | None = None, root_judgment_index: dict | None = None,
    allow_transaction_lock: bool = False, allow_missing_empty_judgments: bool = False,
) -> set[str]:
    """Validate the complete current publication tree and return its exact tracked inventory."""
    if output.is_symlink() or not output.is_dir():
        raise _inventory_error(output, output)
    lock = output / ".publish.lock"
    if lock.exists() or lock.is_symlink():
        if not allow_transaction_lock or lock.is_symlink() or not lock.is_file():
            raise _inventory_error(output, lock, "interrupted publication transaction")
    for entry in sorted(output.iterdir(), key=lambda item: item.name):
        if entry.name.startswith(".staging-"):
            raise _inventory_error(output, entry, "interrupted publication transaction")

    current_path = output / "current.json"
    _add_regular_file(output, current_path, files := set())
    try:
        current = load_current_generation(output)
    except PublicationInventoryError:
        raise
    except StableJsonChangedError:
        raise
    except (ContractError, OSError, UnicodeError, ValueError) as error:
        raise _inventory_error(output, current_path, "invalid current publication") from error
    if current is None:
        raise _inventory_error(output, current_path, "missing publication entry")
    chain_files, _ = _validate_generation_chain(
        output, current, allow_recoverable_orphans=allow_recoverable_orphans,
        recoverable_records=recoverable_records,
    )
    files.update(chain_files)
    effective_index = current[5] if root_judgment_index is None else root_judgment_index
    judgment_directory = output / "judgments"
    if not (
        allow_missing_empty_judgments
        and not judgment_directory.exists() and not judgment_directory.is_symlink()
        and not effective_index["records"]
    ):
        _validate_root_judgments(output, effective_index, files)
    _validate_consumer(output, current, files, required=require_consumer)

    latest = output / "latest.json"
    if latest.exists() or latest.is_symlink():
        _add_regular_file(output, latest, files)
        try:
            value = load_json(latest)
            validate_schema(value, LATEST_SCHEMA, output_relative_path(output, latest))
            validate_public_latest(value, verify_source_hash=True)
        except (ContractError, OSError, UnicodeError, ValueError) as error:
            raise _inventory_error(output, latest, "invalid publication entry") from error

    for name, schema, is_latest in (
        ("archive", LATEST_SCHEMA, True), ("history", HISTORY_SCHEMA, False),
        ("predictions", PREDICTION_SCHEMA, False), ("verifications", VERIFICATION_SCHEMA, False),
    ):
        _validate_flat_contract_directory(output, name, schema, files, latest=is_latest)

    allowed = {
        "current.json", "generations", "judgments", "consumer", "latest.json",
        "archive", "history", "predictions", "verifications",
    }
    if allow_transaction_lock:
        allowed.add(".publish.lock")
    for entry in sorted(output.iterdir(), key=lambda item: item.name):
        if entry.name not in allowed:
            raise _inventory_error(output, entry)
    return files


def validate_current_publication_inventory(
    output: Path, *, require_consumer: bool, allow_recoverable_orphans: bool = False,
) -> set[str]:
    try:
        return _validate_current_publication_inventory(
            output, require_consumer=require_consumer,
            allow_recoverable_orphans=allow_recoverable_orphans,
        )
    except StableJsonChangedError as error:
        raise PublicationInventoryError(str(error), error.relative_path) from error


def _validate_orphan_inventory(
    output: Path, *, allow_transaction_lock: bool = False,
    allow_missing_empty_judgments: bool = False, allow_legacy_artifacts: bool = False,
) -> set[str]:
    files: set[str] = set()
    allowed = set(PLACEHOLDER_DIRECTORIES) | {"generations"}
    if allow_transaction_lock:
        allowed.add(".publish.lock")
    if allow_legacy_artifacts:
        allowed.add("latest.json")
    for entry in sorted(output.iterdir(), key=lambda item: item.name):
        if entry.name not in allowed:
            raise _inventory_error(output, entry)
    lock = output / ".publish.lock"
    if allow_transaction_lock and (lock.is_symlink() or not lock.is_file()):
        raise _inventory_error(output, lock, "interrupted publication transaction")
    if allow_legacy_artifacts:
        latest = output / "latest.json"
        _add_regular_file(output, latest, files)
        value = load_json(latest)
        validate_schema(value, LATEST_SCHEMA, output_relative_path(output, latest))
        validate_public_latest(value, verify_source_hash=False)
        for name, schema, is_latest in (
            ("archive", LATEST_SCHEMA, True), ("history", HISTORY_SCHEMA, False),
            ("predictions", PREDICTION_SCHEMA, False), ("verifications", VERIFICATION_SCHEMA, False),
        ):
            _validate_flat_contract_directory(output, name, schema, files, latest=is_latest)
    else:
        for name in ("archive", "history", "predictions", "verifications"):
            _validate_placeholder_directory(output, name, files)
    generations = output / "generations"
    if generations.is_symlink() or not generations.is_dir():
        raise _inventory_error(output, generations)
    entries = sorted(generations.iterdir(), key=lambda item: item.name)
    if not entries:
        raise _inventory_error(output, generations, "empty interrupted generation inventory")
    indexes = []
    for entry in entries:
        try:
            _, _, _, index = validate_generation(entry)
        except StableJsonChangedError:
            raise
        except (ContractError, OSError, ValueError) as error:
            raise _inventory_error(output, entry, "invalid interrupted generation") from error
        indexes.append(index)
        for name in GENERATION_ENTRY_SET:
            files.add(output_relative_path(output, entry / name))
    root_records = indexes[0]["records"]
    if any(index["records"] != root_records for index in indexes[1:]):
        raise _inventory_error(output, generations, "inconsistent interrupted generation inventory")
    judgment_directory = output / "judgments"
    if not (
        allow_missing_empty_judgments
        and not judgment_directory.exists() and not judgment_directory.is_symlink()
        and not indexes[0]["records"]
    ):
        _validate_root_judgments(output, indexes[0], files)
    return files


def classify_publication_start_state(output: Path) -> PublicationStartState:
    """Classify the exact on-disk state without mutation or network access."""
    if not output.exists() and not output.is_symlink():
        return PublicationStartState("clean")
    if output.is_symlink() or not output.is_dir():
        return PublicationStartState("ambiguous", "output")
    current = output / "current.json"
    if current.exists() or current.is_symlink():
        try:
            validate_current_publication_inventory(
                output, require_consumer=False, allow_recoverable_orphans=True,
            )
        except PublicationInventoryError as error:
            return PublicationStartState("invalid_current", error.path)
        return PublicationStartState("current")
    latest = output / "latest.json"
    if latest.exists() or latest.is_symlink():
        if latest.is_symlink() or not latest.is_file():
            return PublicationStartState("ambiguous", output_relative_path(output, latest))
        return PublicationStartState("fixed_legacy", output_relative_path(output, latest))
    generations = output / "generations"
    if generations.exists() or generations.is_symlink():
        try:
            _validate_orphan_inventory(output)
        except PublicationInventoryError as error:
            return PublicationStartState("ambiguous", error.path)
        return PublicationStartState("interrupted_transaction", output_relative_path(output, generations))
    archive = output / "archive"
    if archive.is_dir() and not archive.is_symlink():
        json_files = sorted(
            (path for path in archive.rglob("*.json") if path.is_file() and not path.is_symlink()),
            key=lambda path: path.relative_to(output).as_posix(),
        )
        if json_files:
            path = json_files[0]
            try:
                load_json(path)
            except (OSError, UnicodeError, ValueError):
                return PublicationStartState("ambiguous", output_relative_path(output, path))
            return PublicationStartState("partial_legacy", output_relative_path(output, path))
    try:
        _validate_clean_inventory(output)
    except PublicationInventoryError as error:
        return PublicationStartState("ambiguous", error.path)
    return PublicationStartState("clean")


def enforce_publication_start_state(output: Path) -> PublicationStartState:
    state = classify_publication_start_state(output)
    if state.kind in {"clean", "current", "interrupted_transaction"}:
        return state
    if state.kind == "fixed_legacy":
        raise RuntimeError(
            "legacy fixed publication detected; "
            "run scripts/migrate_publication_v1.py --explicit before weekly publication"
        )
    if state.kind == "partial_legacy":
        raise RuntimeError(
            "partial legacy publication detected: "
            "archive data exists but output/latest.json is absent"
        )
    if state.kind == "invalid_current":
        raise RuntimeError(f"invalid current publication: {state.path}")
    raise RuntimeError(f"ambiguous output state: unexpected path {state.path}")


def validate_repository_output_inventory(output: Path, *, require_consumer: bool = True) -> set[str]:
    """Validate either the canonical clean bootstrap tree or an exact current tree."""
    state = classify_publication_start_state(output)
    if state.kind == "clean":
        return _validate_clean_inventory(output)
    if state.kind == "current":
        return validate_current_publication_inventory(output, require_consumer=require_consumer)
    raise ContractError(f"repository publication inventory is {state.kind}: {state.path}")


def committable_publication_files(output: Path) -> set[str]:
    """Return the complete validated publication file allowlist for git staging."""
    inventory = validate_current_publication_inventory(output, require_consumer=True)
    return {
        path for path in inventory
        if path in {"output/current.json", "output/consumer/latest.json"}
        or path.startswith("output/generations/")
        or path.startswith("output/judgments/")
    }


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


_EXECUTION_META_FIELDS = frozenset({
    "generated_at", "valid_until", "hard_stop_after", "source_snapshot", "source_sha256",
})


def _logical_snapshot(snapshot: dict) -> dict:
    value = copy.deepcopy(snapshot)
    meta = value.get("meta", {})
    for field in _EXECUTION_META_FIELDS:
        meta.pop(field, None)
    return value


def _root_index(index: dict) -> dict:
    return {key: value for key, value in index.items() if key != "publication"}


def _publication_identity(snapshot: dict, history: dict, index: dict, previous_generation_id: str | None) -> dict:
    meta = snapshot["meta"]
    return {
        "analysis_id": meta["run_id"],
        "data_date": meta["data_date"],
        "source_commit": meta["source_commit"],
        "logical_snapshot": stable_hash(_logical_snapshot(snapshot)),
        "history": stable_hash(history),
        "judgment_index": stable_hash(_root_index(index)),
        "previous_generation_id": previous_generation_id,
    }


def _assert_publication_identity(
    manifest: dict, snapshot: dict, history: dict, index: dict,
    retry_snapshot: dict, retry_history: dict, retry_index: dict,
    previous_generation_id: str | None, current_data_date: str | None,
) -> None:
    actual = _publication_identity(snapshot, history, index, manifest["previous_generation_id"])
    expected = _publication_identity(
        retry_snapshot, retry_history, retry_index, previous_generation_id,
    )
    mismatched = sorted(field for field in expected if actual.get(field) != expected[field])
    if mismatched:
        raise ContractError(
            "publication identity mismatch: "
            f"generation_id={manifest['generation_id']} "
            f"previous_generation_id={manifest['previous_generation_id']} "
            f"orphan_data_date={manifest['data_date']} "
            f"current_data_date={current_data_date} "
            f"retry_snapshot_data_date={retry_snapshot['meta']['data_date']} "
            f"mismatched_identity_fields={','.join(mismatched)}"
        )


def _valid_orphans(
    output: Path, snapshot: dict, history: dict, index: dict,
    current: tuple | None,
) -> list[tuple[dict, Path]]:
    candidates = []
    generations = output / "generations"
    if not generations.is_dir():
        return candidates
    chain_ids: set[str] = set()
    manifest = current[2] if current else None
    current_generation_id = manifest["generation_id"] if manifest else None
    current_data_date = manifest["data_date"] if manifest else None
    while manifest is not None:
        generation_id = manifest["generation_id"]
        if generation_id in chain_ids:
            raise ContractError("generation history chain contains a cycle")
        chain_ids.add(generation_id)
        previous = manifest["previous_generation_id"]
        manifest = validate_generation(safe_generation_path(output, previous))[0] if previous else None
    for path in sorted(generations.iterdir(), key=lambda item: item.name):
        if path.name in chain_ids:
            continue
        try:
            manifest, orphan_snapshot, orphan_history, orphan_index = validate_generation(path)
        except StableJsonChangedError:
            raise
        except (ContractError, OSError, ValueError) as error:
            raise ContractError(f"invalid orphan generation: {path.name}") from error
        if manifest["previous_generation_id"] != current_generation_id:
            raise ContractError(f"unrelated orphan generation requires explicit recovery: {path.name}")
        if current is not None:
            _validate_generation_chronology(manifest, current[2])
        try:
            _assert_publication_identity(
                manifest, orphan_snapshot, orphan_history, orphan_index,
                snapshot, history, index, current_generation_id, current_data_date,
            )
        except ContractError as error:
            raise ContractError(
                f"unrelated orphan generation requires explicit recovery: {path.name}; {error}"
            ) from error
        candidates.append((manifest, path))
    return sorted(candidates, key=lambda item: (item[0]["generated_at"], item[0]["generation_id"]))


def _revalidate_pointer_switch(
    output: Path, expected_current: tuple | None, pointer: dict,
    snapshot: dict, history: dict, index: dict,
) -> None:
    current = load_current_generation(output)
    expected_pointer = expected_current[0] if expected_current else None
    current_pointer_value = current[0] if current else None
    if canonical_bytes(current_pointer_value) != canonical_bytes(expected_pointer):
        raise ContractError(
            "current changed before pointer switch: "
            f"expected_generation_id={expected_pointer.get('generation_id') if expected_pointer else None} "
            f"actual_generation_id={current_pointer_value.get('generation_id') if current_pointer_value else None}"
        )
    candidate = validate_pointer_candidate(output, pointer)
    current_generation_id = current[2]["generation_id"] if current else None
    current_data_date = current[2]["data_date"] if current else None
    _assert_publication_identity(
        candidate[0], candidate[1], candidate[2], candidate[3],
        snapshot, history, index, current_generation_id, current_data_date,
    )
    if current is None:
        _validate_orphan_inventory(
            output, allow_transaction_lock=True, allow_missing_empty_judgments=True,
            allow_legacy_artifacts=(output / "latest.json").is_file(),
        )
    else:
        _validate_current_publication_inventory(
            output, require_consumer=False, allow_recoverable_orphans=True,
            recoverable_records=candidate[3]["records"],
            root_judgment_index=candidate[3], allow_transaction_lock=True,
            allow_missing_empty_judgments=True,
        )
    # Re-read the candidate after the full inventory walk so a mid-validation
    # mutation cannot become current.
    reloaded = validate_pointer_candidate(output, pointer)
    if canonical_bytes(reloaded[0]) != canonical_bytes(candidate[0]):
        raise ContractError(
            "candidate changed before pointer switch: "
            f"generation_id={candidate[0]['generation_id']}"
        )


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
            _assert_publication_identity(
                current[2], current[3], current[4], current[5], snapshot, history, index,
                current[2]["previous_generation_id"], current[2]["data_date"],
            )
            return current[0]
        if current and snapshot["meta"]["data_date"] < current[2]["data_date"]:
            raise ContractError("publication data_date cannot move backwards; use explicit rollback")
        orphans = _valid_orphans(output, snapshot, history, index, current)
        if orphans:
            manifest, _ = orphans[0]
            pointer = current_pointer(manifest)
            validate_pointer_candidate(output, pointer)
            inject("current_pointer_switch")
            _revalidate_pointer_switch(output, current, pointer, snapshot, history, index)
            atomic_write_json(output / "current.json", pointer)
            return pointer
        previous_generation_id = current_generation_id
        index = {**index, "publication": {
            "analysis_id": analysis_id, "generation_id": generation_id, "run_id": analysis_id,
            "data_date": snapshot["meta"]["data_date"], "source_sha256": snapshot["meta"]["source_sha256"],
            "instruction_version": instruction_version_for_data_schema(snapshot["meta"]["schema_version"]),
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
        _revalidate_pointer_switch(output, current, pointer, snapshot, history, index)
        atomic_write_json(output / "current.json", pointer)
        loaded = load_current_generation(output)
        if loaded is None or loaded[2] != manifest:
            raise ContractError("current generation verification failed")
        return pointer
