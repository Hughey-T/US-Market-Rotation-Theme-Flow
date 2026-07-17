#!/usr/bin/env python3
"""Export one deterministic lightweight consumer from the authoritative current generation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.consumer import (
    CONSUMER_FILE_SIZE_LIMIT,
    build_consumer_snapshot,
    validate_consumer_artifact,
    validate_consumer_snapshot,
)
from rotation.provenance import atomic_write_json, canonical_bytes
from rotation.publication import load_current_generation
from rotation.validation import ContractError, load_json, validate_public_latest, validate_schema


LATEST_SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")


def export_current(output: Path, destination: Path) -> Path:
    current = load_current_generation(output)
    if current is None:
        raise ContractError("output/current.json is absent; no authoritative generation is available")
    pointer, _, manifest, latest, _, _ = current
    validate_schema(latest, LATEST_SCHEMA, "current latest before export")
    validate_public_latest(latest, verify_source_hash=True)
    legacy_without_user_view = latest.get("user_view") is None
    consumer = latest if legacy_without_user_view else build_consumer_snapshot(latest)
    if legacy_without_user_view:
        validate_consumer_artifact(
            consumer, latest, pointer=pointer, manifest=manifest,
        )
    else:
        validate_consumer_snapshot(consumer, latest, pointer=pointer, manifest=manifest)
    atomic_write_json(destination, consumer)
    file_size = destination.stat().st_size
    if not legacy_without_user_view and file_size > CONSUMER_FILE_SIZE_LIMIT:
        destination.unlink(missing_ok=True)
        raise ContractError(
            f"consumer file exceeds {CONSUMER_FILE_SIZE_LIMIT} bytes: {file_size}"
        )
    exported = load_json(destination)
    if legacy_without_user_view:
        validate_consumer_artifact(
            exported, latest, pointer=pointer, manifest=manifest,
        )
    else:
        validate_consumer_snapshot(exported, latest, pointer=pointer, manifest=manifest)
    if canonical_bytes(exported) != canonical_bytes(consumer):
        raise ContractError("exported consumer differs from deterministic projection")
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
