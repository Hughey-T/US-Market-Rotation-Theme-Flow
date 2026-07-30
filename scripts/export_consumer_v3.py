#!/usr/bin/env python3
"""Publish v3 to an immutable generation tree, then atomically update latest."""
from __future__ import annotations
import argparse, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from rotation.consumer_v3 import build_consumer_v3, canonical_file_bytes, validate_consumer_v3
from rotation.publication import load_current_generation
from rotation.validation import ContractError, load_json


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(canonical_file_bytes(value))


def export_consumer_v3(output: Path, destination: Path) -> list[Path]:
    current = load_current_generation(output)
    if current is None: raise ContractError("no authoritative generation")
    pointer, manifest, phases, details, handoffs = build_consumer_v3(current[3])
    validate_consumer_v3(pointer, manifest, phases, details, handoffs)
    generation = destination / "generations" / pointer["generation_id"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".v3-") as temp:
        staged = Path(temp) / "generation"; _write(staged / "manifest.json", manifest)
        for kind, values in (("phases", phases), ("details", details)):
            for phase, chunks in values.items():
                for chunk in chunks: _write(staged / kind / f"phase-{phase}" / f"part-{chunk['part']}.json", chunk)
        for chunk in handoffs:
            _write(staged / "handoffs" / f"part-{chunk['part']}.json", chunk)
        if generation.exists():
            expected = {p.relative_to(staged): p.read_bytes() for p in staged.rglob("*") if p.is_file()}
            actual = {p.relative_to(generation): p.read_bytes() for p in generation.rglob("*") if p.is_file()}
            if actual != expected: raise ContractError("immutable generation collision")
        else:
            generation.parent.mkdir(parents=True, exist_ok=True); os.replace(staged, generation)
    destination.mkdir(parents=True, exist_ok=True)
    temporary_pointer = destination / ".manifest.json.tmp"; _write(temporary_pointer, pointer); os.replace(temporary_pointer, destination / "manifest.json")
    return [p for p in generation.rglob("*") if p.is_file()] + [destination / "manifest.json"]


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("destination", nargs="?", default="output/consumer/v3"); parser.add_argument("--output", default="output")
    args = parser.parse_args(); export_consumer_v3(Path(args.output), Path(args.destination))
if __name__ == "__main__": main()
