#!/usr/bin/env python3
"""Explicit, non-destructive migration of a fixed legacy latest publication."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rotation.identity import generation_identity
from rotation.provenance import snapshot_source_hash, stable_hash
from rotation.publication import publish_generation
from rotation.validation import ContractError, load_json, validate_public_latest, validate_schema
from scripts.generate_weekly import history_item


def migrate(output: Path, generated_at: dt.datetime, source_commit: str) -> dict:
    if (output / "current.json").exists():
        raise ContractError("current publication already exists")
    legacy = output / "latest.json"
    if not legacy.is_file():
        raise ContractError("legacy output/latest.json is absent")
    snapshot = copy.deepcopy(load_json(legacy))
    validate_schema(snapshot, load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"), str(legacy))
    validate_public_latest(snapshot, verify_source_hash=False)
    analysis_id = stable_hash({"migration": "publication-1.0", "legacy": snapshot, "source_commit": source_commit})
    generated = generated_at.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    generation_id = generation_identity(analysis_id, generated, source_commit)
    snapshot["meta"].update(run_id=analysis_id, generated_at=generated, source_commit=source_commit,
                            source_snapshot=f"output/generations/{generation_id}/archive.json")
    snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)
    old_index = output / "judgments" / "index.json"
    index = load_json(old_index) if old_index.is_file() else {"index_version": "1.0", "records": []}
    index = {"index_version": "1.0", "records": index.get("records", [])}
    return publish_generation(output, snapshot, history_item(snapshot), index)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--explicit", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--generated-at", default=dt.datetime.now(dt.timezone.utc).isoformat())
    args = parser.parse_args(argv)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    migrate(args.output, dt.datetime.fromisoformat(args.generated_at.replace("Z", "+00:00")), commit)
    print("legacy files preserved; current publication migrated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
