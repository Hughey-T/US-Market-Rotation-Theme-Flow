#!/usr/bin/env python3
"""Export one validated immutable consumer v4 generation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.consumer_v4 import export_consumer_v4, load_and_validate_consumer_v4
from rotation.publication import load_current_generation
from rotation.validation import load_json, validate_public_latest


def export_from_snapshot(snapshot: dict, destination: Path) -> dict:
    validate_public_latest(snapshot, verify_source_hash=True)
    pointer = export_consumer_v4(snapshot, destination)
    load_and_validate_consumer_v4(destination)
    return pointer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--destination", type=Path, default=ROOT / "output" / "consumer" / "v4")
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    args = parser.parse_args(argv)
    if args.snapshot:
        snapshot = load_json(args.snapshot)
    else:
        current = load_current_generation(args.output)
        if current is None:
            raise RuntimeError("authoritative current generation is unavailable")
        snapshot = current[3]
    pointer = export_from_snapshot(snapshot, args.destination)
    print(f"consumer v4 exported: generation_id={pointer['generation_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
