#!/usr/bin/env python3
"""Reject changes to judgment records that already exist on the PR base."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.validation import ContractError


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout


def immutable_judgment_violations(repo: Path, base: str, head: str = "HEAD") -> list[str]:
    _git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")
    _git(repo, "rev-parse", "--verify", f"{head}^{{commit}}")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, head],
        cwd=repo, text=True, capture_output=True,
    )
    if ancestor.returncode != 0:
        if ancestor.returncode == 1:
            raise ContractError(f"immutable judgment base is not an ancestor of head: {base} -> {head}")
        ancestor.check_returncode()
    output = _git(repo, "diff", "--name-status", "--find-renames", f"{base}..{head}", "--", "output/judgments")
    violations = []
    for line in output.splitlines():
        fields = line.split("\t")
        status, paths = fields[0], fields[1:]
        records = [
            path for path in paths
            if path.startswith("output/judgments/") and path.endswith(".json") and Path(path).name != "index.json"
        ]
        if records and not status.startswith("A"):
            violations.append(f"{status}: {' -> '.join(records)}")
    return violations


def validate_immutable_judgments(repo: Path, base: str, head: str = "HEAD") -> None:
    violations = immutable_judgment_violations(repo, base, head)
    if violations:
        raise ContractError(
            "immutable judgment records differ from the pull-request base:\n"
            + "\n".join(f"- {violation}" for violation in violations)
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        validate_immutable_judgments(args.repo, args.base, args.head)
    except (ContractError, subprocess.CalledProcessError) as error:
        print(f"immutable judgment validation failed:\n{error}", file=sys.stderr)
        return 1
    print("immutable judgment validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
