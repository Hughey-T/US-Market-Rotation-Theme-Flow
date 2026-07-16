#!/usr/bin/env python3
"""Commit one validated publication transaction; never hide git failures."""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path


PUBLICATION_PATHS = ("output/current.json", "output/generations", "output/judgments", "output/consumer/latest.json")
PUBLICATION_BRANCH = "publication"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=check)


def _push_publication(repo: Path, branch: str, expected_remote: str | None, bootstrap: bool) -> None:
    remote = _git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{branch}", check=False)
    if remote.returncode not in (0, 2):
        raise subprocess.CalledProcessError(remote.returncode, remote.args, remote.stdout, remote.stderr)
    if remote.returncode == 2:
        raise subprocess.CalledProcessError(remote.returncode, remote.args, remote.stdout, remote.stderr)
    current_remote = remote.stdout.split()[0] if remote.stdout.strip() else None
    if bootstrap:
        if current_remote is not None:
            raise RuntimeError(f"{branch} appeared during bootstrap; refusing to overwrite it")
    else:
        if expected_remote is None or current_remote != expected_remote:
            raise RuntimeError(f"{branch} advanced after checkout; refusing non-fast-forward publication")
        ancestor = _git(repo, "merge-base", "--is-ancestor", expected_remote, "HEAD", check=False)
        if ancestor.returncode != 0:
            raise RuntimeError(f"local publication is not a fast-forward of {expected_remote}")
    _git(repo, "push", "origin", f"HEAD:refs/heads/{branch}")


def commit_weekly_outputs(
    repo: Path, *, push: bool = True, branch: str = PUBLICATION_BRANCH,
    expected_remote: str | None = None, bootstrap: bool = False, configure_identity: bool = True,
) -> bool:
    _git(repo, "check-ref-format", "--branch", branch)
    if push and _git(repo, "branch", "--show-current").stdout.strip() != branch:
        raise RuntimeError(f"weekly publication must run on {branch}")
    if push and (bootstrap == (expected_remote is not None)):
        raise RuntimeError("push requires exactly one of bootstrap or expected_remote")
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
        _push_publication(repo, branch, expected_remote, bootstrap)
    return committed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--branch", default=PUBLICATION_BRANCH)
    parser.add_argument("--expected-remote")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--no-configure-identity", action="store_true")
    args = parser.parse_args(argv)
    committed = commit_weekly_outputs(
        args.repo, push=not args.no_push, branch=args.branch,
        expected_remote=args.expected_remote, bootstrap=args.bootstrap,
        configure_identity=not args.no_configure_identity,
    )
    print("committed validated publication" if committed else "no changes to commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
