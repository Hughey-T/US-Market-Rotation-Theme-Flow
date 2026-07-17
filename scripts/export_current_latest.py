#!/usr/bin/env python3
"""Export the authoritative full snapshot to the legacy compatibility URL."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.consumer import validate_legacy_full_consumer
from rotation.provenance import atomic_write_json, canonical_bytes
from rotation.publication import load_current_generation
from rotation.validation import ContractError, load_json, validate_public_latest, validate_schema


LATEST_SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")


def export_current(output: Path, destination: Path) -> Path:
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ContractError("legacy consumer destination must not be a symlink")
    current = load_current_generation(output)
    if current is None:
        raise ContractError("output/current.json is absent; no authoritative generation is available")
    pointer, _, manifest, latest, _, _ = current
    validate_schema(latest, LATEST_SCHEMA, "current latest before export")
    validate_public_latest(latest, verify_source_hash=True)
    validate_legacy_full_consumer(latest, latest, pointer=pointer, manifest=manifest)
    atomic_write_json(destination, latest)
    exported = load_json(destination)
    validate_legacy_full_consumer(exported, latest, pointer=pointer, manifest=manifest)
    if canonical_bytes(exported) != canonical_bytes(latest):
        raise ContractError("legacy consumer differs from authoritative current snapshot")
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    args = parser.parse_args(argv)
    print(export_current(args.output, args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
