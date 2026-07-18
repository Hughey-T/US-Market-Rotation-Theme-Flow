#!/usr/bin/env python3
"""Export deterministic Custom GPT consumer payloads below 4 KiB each."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.consumer_v2 import (
    CONSUMER_V2_FILE_SIZE_LIMIT,
    build_consumer_v2_payloads,
    consumer_v2_file_bytes,
    load_consumer_v2_file,
    validate_consumer_v2_payloads,
)
from rotation.provenance import canonical_bytes
from rotation.publication import load_current_generation
from rotation.validation import ContractError


def _write_canonical_json(path: Path, value: dict) -> None:
    raw = consumer_v2_file_bytes(value)
    size = len(raw)
    if size > CONSUMER_V2_FILE_SIZE_LIMIT:
        raise ContractError(
            f"consumer v2 file exceeds "
            f"{CONSUMER_V2_FILE_SIZE_LIMIT} bytes: "
            f"{path} ({size} bytes)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _read_chunk_tree(
    root: Path,
    kind: str,
    inventory: list[dict],
) -> dict[int, list[dict]]:
    values: dict[int, list[dict]] = {}

    for item in inventory:
        phase = item["phase"]
        part_count = item["part_count"]
        phase_dir = root / kind / f"phase-{phase}"

        values[phase] = [
            load_consumer_v2_file(
                phase_dir / f"part-{part}.json",
                f"consumer v2 {kind} phase {phase} part {part}",
            )
            for part in range(1, part_count + 1)
        ]

    return values


def export_consumer_v2(output: Path, destination: Path) -> list[Path]:
    if destination.is_symlink():
        raise ContractError(
            "consumer v2 destination must not be a symlink"
        )
    if destination.exists() and not destination.is_dir():
        raise ContractError(
            "consumer v2 destination must be a directory"
        )
    if destination.parent.is_symlink():
        raise ContractError(
            "consumer v2 destination parent must not be a symlink"
        )

    current = load_current_generation(output)
    if current is None:
        raise ContractError(
            "output/current.json is absent; "
            "no authoritative generation is available"
        )

    latest = current[3]
    if latest.get("meta", {}).get("schema_version") != "1.2":
        raise ContractError(
            "consumer v2 requires authoritative data schema 1.2"
        )

    manifest, phase_chunks, detail_chunks = (
        build_consumer_v2_payloads(latest)
    )
    validate_consumer_v2_payloads(
        manifest,
        phase_chunks,
        detail_chunks,
        latest,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
    )

    written: list[Path] = []

    try:
        manifest_path = temporary / "manifest.json"
        _write_canonical_json(manifest_path, manifest)
        written.append(manifest_path)

        for kind, collection in (
            ("phases", phase_chunks),
            ("details", detail_chunks),
        ):
            for phase in range(1, 7):
                for part, payload in enumerate(
                    collection[phase],
                    1,
                ):
                    path = (
                        temporary
                        / kind
                        / f"phase-{phase}"
                        / f"part-{part}.json"
                    )
                    _write_canonical_json(path, payload)
                    written.append(path)

        exported_manifest = load_consumer_v2_file(
            temporary / "manifest.json",
            "consumer v2 manifest",
        )
        exported_phases = _read_chunk_tree(
            temporary,
            "phases",
            exported_manifest["phase_inventory"],
        )
        exported_details = _read_chunk_tree(
            temporary,
            "details",
            exported_manifest["detail_inventory"],
        )

        validate_consumer_v2_payloads(
            exported_manifest,
            exported_phases,
            exported_details,
            latest,
        )

        expected = {
            path.relative_to(temporary).as_posix()
            for path in written
        }
        actual = {
            path.relative_to(temporary).as_posix()
            for path in temporary.rglob("*")
            if path.is_file()
        }

        if actual != expected:
            raise ContractError(
                "consumer v2 temporary inventory mismatch"
            )

        backup = destination.with_name(
            f".{destination.name}.previous"
        )
        if backup.exists() or backup.is_symlink():
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink()

        moved_old = False

        try:
            if destination.exists():
                os.replace(destination, backup)
                moved_old = True

            os.replace(temporary, destination)

            if moved_old:
                shutil.rmtree(backup)

        except Exception:
            if (
                moved_old
                and not destination.exists()
                and backup.exists()
            ):
                os.replace(backup, destination)
            raise

        return [
            destination / path.relative_to(temporary)
            for path in written
        ]

    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output",
    )
    args = parser.parse_args(argv)

    for path in export_consumer_v2(
        args.output,
        args.destination,
    ):
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
