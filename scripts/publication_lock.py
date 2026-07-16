#!/usr/bin/env python3
"""Inspect or explicitly recover the publication lock."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rotation.publication_lock import inspect, recover


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inspect", "recover"))
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--stale-after-hours", type=float, default=6.0)
    args = parser.parse_args(argv)
    path = args.output / ".publish.lock"
    ttl = dt.timedelta(hours=args.stale_after_hours)
    if args.action == "inspect":
        print(json.dumps(inspect(path, stale_after=ttl), indent=2, sort_keys=True))
    else:
        recover(path, stale_after=ttl)
        print(f"recovered {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
