#!/usr/bin/env python3
"""Create an explicit, non-publishable 1.0 -> 1.1 migration report.

The adapter never guesses fields absent from 1.0.  Operators must regenerate a
strict 1.1 snapshot from source observations after reviewing this report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.legacy import read_legacy_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--explicit", action="store_true", help="required acknowledgement that 1.0 is not silently accepted")
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    report = read_legacy_snapshot(value, explicit=args.explicit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
