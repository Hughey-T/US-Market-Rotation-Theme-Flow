#!/usr/bin/env python3
"""Export six deterministic, identity-bound Custom GPT detail projections."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.consumer import (
    DETAILS_FILE_SIZE_LIMIT,
    build_consumer_details,
    validate_consumer_detail,
)
from rotation.provenance import atomic_write_json, canonical_bytes
from rotation.publication import load_current_generation
from rotation.validation import ContractError, load_json


def export_consumer_details(output: Path, destination: Path) -> list[Path]:
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ContractError("consumer details destination must be a regular directory")
    current = load_current_generation(output)
    if current is None:
        raise ContractError("output/current.json is absent; no authoritative generation is available")
    latest = current[3]
    if latest.get("meta", {}).get("schema_version") != "1.2":
        raise ContractError("consumer details require authoritative data schema 1.2")
    details = build_consumer_details(latest)
    destination.mkdir(parents=True, exist_ok=True)
    expected_names = {f"phase-{phase}.json" for phase in range(1, 7)}
    if any(path.is_symlink() for path in destination.iterdir()):
        raise ContractError("consumer detail files must not be symlinks")
    existing = {path.name for path in destination.iterdir()}
    if existing - expected_names:
        raise ContractError(f"unknown consumer detail files: {sorted(existing - expected_names)}")
    paths = []
    for phase, detail in enumerate(details, 1):
        validate_consumer_detail(detail, latest, phase=phase)
        path = destination / f"phase-{phase}.json"
        atomic_write_json(path, detail)
        if path.stat().st_size > DETAILS_FILE_SIZE_LIMIT:
            path.unlink(missing_ok=True)
            raise ContractError(f"consumer phase {phase} detail file exceeds {DETAILS_FILE_SIZE_LIMIT} bytes")
        exported = load_json(path)
        validate_consumer_detail(exported, latest, phase=phase)
        if canonical_bytes(exported) != canonical_bytes(detail):
            raise ContractError(f"consumer phase {phase} detail differs after export")
        paths.append(path)
    return paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    args = parser.parse_args(argv)
    for path in export_consumer_details(args.output, args.destination):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
