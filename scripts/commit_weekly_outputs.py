#!/usr/bin/env python3
"""Commit one validated publication transaction; never hide git failures."""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path


PUBLICATION_PATHS = ("output/current.json", "output/generations", "output/judgments")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=check)


def commit_weekly_outputs(repo: Path, *, push: bool = True, configure_identity: bool = True) -> bool:
    if configure_identity:
        _git(repo, "config", "user.name", "github-actions[bot]")
        _git(repo, "config", "user.email", "github-actions[bot]@users.noreply.github.com")
    _git(repo, "diff", "--check")
    _git(repo, "add", "--", *PUBLICATION_PATHS)
    staged = _git(repo, "diff", "--cached", "--quiet", check=False)
    if staged.returncode not in (0, 1):
        raise subprocess.CalledProcessError(staged.returncode, staged.args, staged.stdout, staged.stderr)
    committed = staged.returncode == 1
    if committed:
        message = f"weekly data {dt.datetime.now(dt.timezone.utc).date().isoformat()}"
        _git(repo, "commit", "-m", message)
    if push:
        _git(repo, "push")
    return committed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--no-configure-identity", action="store_true")
    args = parser.parse_args(argv)
    committed = commit_weekly_outputs(args.repo, push=not args.no_push, configure_identity=not args.no_configure_identity)
    print("committed validated publication" if committed else "no changes to commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
