#!/usr/bin/env python3
"""Resolve publication contract 1.0 and export one validated latest.json."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.provenance import atomic_write_json, canonical_bytes
from rotation.publication import load_current_generation
from rotation.validation import ContractError, load_json, validate_public_latest, validate_schema


LATEST_SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")


def export_current(output: Path, destination: Path) -> Path:
    current = load_current_generation(output)
    if current is None:
        raise ContractError("output/current.json is absent; no authoritative generation is available")
    latest = current[3]
    validate_schema(latest, LATEST_SCHEMA, "current latest before export")
    validate_public_latest(latest, verify_source_hash=True)
    atomic_write_json(destination, latest)
    exported = load_json(destination)
    validate_schema(exported, LATEST_SCHEMA, str(destination))
    validate_public_latest(exported, verify_source_hash=True)
    if canonical_bytes(exported) != canonical_bytes(latest):
        raise ContractError("exported latest differs from current generation")
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
