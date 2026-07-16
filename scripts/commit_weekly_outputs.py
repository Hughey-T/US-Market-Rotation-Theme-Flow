#!/usr/bin/env python3
"""Commit one validated publication transaction; never hide git failures."""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.publication import committable_publication_files, validate_current_publication_inventory

try:
    from scripts.validate_immutable_judgments import validate_immutable_judgments
except ModuleNotFoundError:  # Direct execution from scripts/.
    from validate_immutable_judgments import validate_immutable_judgments


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


def _validate_staged_allowlist(repo: Path, allowed: set[str]) -> None:
    staged = [
        path for path in _git(repo, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
        if path
    ]
    unexpected = sorted(path for path in staged if path.replace("\\", "/") not in allowed)
    if unexpected:
        raise RuntimeError(f"publication commit contains paths outside the allowlist: {unexpected}")


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
    full_inventory = validate_current_publication_inventory(repo / "output", require_consumer=True)
    allowed = committable_publication_files(repo / "output")
    _validate_staged_allowlist(repo, allowed)
    tracked_before = {
        path for path in _git(repo, "ls-files", "--", "output").stdout.splitlines() if path
    }
    unexpected_tracked = sorted(tracked_before - full_inventory)
    if unexpected_tracked:
        raise RuntimeError(f"tracked publication inventory contains unexpected paths: {unexpected_tracked}")
    noncommittable = full_inventory - allowed
    untracked_noncommittable = sorted(noncommittable - tracked_before)
    if untracked_noncommittable:
        raise RuntimeError(
            f"validated legacy or placeholder paths must already be tracked: {untracked_noncommittable}"
        )
    changed_noncommittable = [
        path for path in sorted(noncommittable)
        if _git(repo, "diff", "--quiet", "--", path, check=False).returncode != 0
    ]
    if changed_noncommittable:
        raise RuntimeError(
            f"publication commit cannot modify legacy or placeholder paths: {changed_noncommittable}"
        )
    expected_blobs = {
        path: _git(repo, "hash-object", "--", path).stdout.strip() for path in sorted(allowed)
    }
    _git(repo, "diff", "--check")
    _git(repo, "add", "--", *sorted(allowed))
    _git(repo, "diff", "--cached", "--check")
    _validate_staged_allowlist(repo, allowed)
    staged = _git(repo, "diff", "--cached", "--quiet", check=False)
    if staged.returncode not in (0, 1):
        raise subprocess.CalledProcessError(staged.returncode, staged.args, staged.stdout, staged.stderr)
    committed = staged.returncode == 1
    if committed:
        message = f"weekly data {dt.datetime.now(dt.timezone.utc).date().isoformat()}"
        _git(repo, "commit", "-m", message)
    tracked_output = {
        path for path in _git(repo, "ls-tree", "-r", "--name-only", "HEAD", "--", "output").stdout.splitlines()
        if path
    }
    if tracked_output != full_inventory:
        unexpected = sorted(tracked_output - full_inventory)
        missing = sorted(full_inventory - tracked_output)
        raise RuntimeError(
            f"publication commit inventory mismatch; unexpected={unexpected}, missing={missing}"
        )
    committed_blobs = {
        path: _git(repo, "rev-parse", f"HEAD:{path}").stdout.strip() for path in sorted(allowed)
    }
    if committed_blobs != expected_blobs:
        changed = sorted(path for path in allowed if committed_blobs[path] != expected_blobs[path])
        raise RuntimeError(f"publication commit bytes differ from validated inventory: {changed}")
    if push:
        if not bootstrap:
            validate_immutable_judgments(repo, expected_remote, "HEAD")
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
