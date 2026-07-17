#!/usr/bin/env python3
"""Export the deterministic lightweight Custom GPT consumer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.consumer import (
    CONSUMER_FILE_SIZE_LIMIT,
    build_consumer_snapshot,
    validate_consumer_snapshot,
)
from rotation.provenance import atomic_write_json, canonical_bytes
from rotation.publication import load_current_generation
from rotation.validation import ContractError, load_json


def export_consumer_projection(output: Path, destination: Path) -> Path:
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ContractError("lightweight consumer destination must not be a symlink")
    current = load_current_generation(output)
    if current is None:
        raise ContractError("output/current.json is absent; no authoritative generation is available")
    pointer, _, manifest, latest, _, _ = current
    if latest.get("meta", {}).get("schema_version") != "1.2":
        raise ContractError("lightweight consumer requires authoritative data schema 1.2")
    consumer = build_consumer_snapshot(latest)
    validate_consumer_snapshot(consumer, latest, pointer=pointer, manifest=manifest)
    atomic_write_json(destination, consumer)
    if destination.stat().st_size > CONSUMER_FILE_SIZE_LIMIT:
        destination.unlink(missing_ok=True)
        raise ContractError(f"consumer file exceeds {CONSUMER_FILE_SIZE_LIMIT} bytes")
    exported = load_json(destination)
    validate_consumer_snapshot(exported, latest, pointer=pointer, manifest=manifest)
    if canonical_bytes(exported) != canonical_bytes(consumer):
        raise ContractError("exported consumer differs from deterministic projection")
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    args = parser.parse_args(argv)
    print(export_consumer_projection(args.output, args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
