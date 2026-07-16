import datetime as dt
import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rotation.publication_lock import acquire, inspect, owned_lock, recover, release
from rotation.validation import ContractError
from scripts.commit_weekly_outputs import PUBLICATION_BRANCH, PUBLICATION_PATHS, commit_weekly_outputs


class PublicationLockTests(unittest.TestCase):
    def test_acquire_compete_exception_token_and_recovery_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".publish.lock"
            metadata = acquire(path, "a" * 64)
            with self.assertRaisesRegex(ContractError, "in progress"):
                acquire(path, "b" * 64)
            with self.assertRaisesRegex(ContractError, "token mismatch"):
                release(path, "0" * 32)
            release(path, metadata["token"]); self.assertFalse(path.exists())
            with self.assertRaises(RuntimeError):
                with owned_lock(path, "a" * 64):
                    raise RuntimeError("boom")
            self.assertFalse(path.exists())

    def test_ttl_live_pid_dead_pid_and_malformed_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".publish.lock"
            old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=7)).isoformat().replace("+00:00", "Z")
            value = {"token": "a" * 32, "pid": os.getpid(), "host": socket.gethostname(), "created_at": old, "operation_id": "op"}
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertFalse(inspect(path)["stale_candidate"])
            with self.assertRaises(ContractError): recover(path, stale_after=dt.timedelta(hours=6))
            value["pid"] = 99999999; path.write_text(json.dumps(value), encoding="utf-8")
            self.assertTrue(recover(path, stale_after=dt.timedelta(hours=6)))
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(ContractError): recover(path, stale_after=dt.timedelta(hours=6))


class WorkflowContractTests(unittest.TestCase):
    def git(self, repo, *args, check=True):
        return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=check)

    def make_repo(self):
        temporary = tempfile.TemporaryDirectory(); repo = Path(temporary.name)
        self.git(repo, "init", "-b", "main")
        for relative in PUBLICATION_PATHS:
            path = repo / relative
            if Path(relative).suffix: path.parent.mkdir(parents=True, exist_ok=True); path.write_text("{}", encoding="utf-8")
            else: path.mkdir(parents=True, exist_ok=True); (path / ".keep").write_text("x", encoding="utf-8")
        self.git(repo, "add", "."); self.git(repo, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "base")
        return temporary, repo

    def test_noop_success_commit_success_and_exact_staging(self):
        temporary, repo = self.make_repo()
        try:
            self.assertFalse(commit_weekly_outputs(repo, push=False))
            (repo / "output/current.json").write_text('{"new":1}', encoding="utf-8")
            (repo / "output/.publish.lock").write_text("lock", encoding="utf-8")
            (repo / "output/.staging-x").mkdir()
            self.assertTrue(commit_weekly_outputs(repo, push=False))
            names = self.git(repo, "show", "--pretty=", "--name-only", "HEAD").stdout
            self.assertIn("output/current.json", names); self.assertNotIn(".publish.lock", names); self.assertNotIn(".staging", names)
        finally: temporary.cleanup()

    def test_commit_hook_identity_and_push_failures_are_not_hidden(self):
        temporary, repo = self.make_repo()
        try:
            self.git(repo, "config", "--unset", "user.name", check=False); self.git(repo, "config", "--unset", "user.email", check=False)
            (repo / "output/current.json").write_text('{"new":1}', encoding="utf-8")
            with self.assertRaises(subprocess.CalledProcessError): commit_weekly_outputs(repo, push=False, configure_identity=False)
            self.git(repo, "config", "user.name", "test"); self.git(repo, "config", "user.email", "test@example.com")
            hook = repo / ".git/hooks/pre-commit"; hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8"); os.chmod(hook, 0o755)
            with self.assertRaises(subprocess.CalledProcessError): commit_weekly_outputs(repo, push=False)
            hook.unlink(); commit_weekly_outputs(repo, push=False)
            self.git(repo, "switch", "-c", PUBLICATION_BRANCH)
            with self.assertRaises(subprocess.CalledProcessError): commit_weekly_outputs(repo, push=True, bootstrap=True)
        finally: temporary.cleanup()

    def test_workflow_has_strict_shell_and_no_commit_failure_mask(self):
        text = (Path(__file__).resolve().parents[1] / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", text)
        self.assertNotIn("|| echo", text)
        self.assertIn("git switch -c publication origin/main", text)
        self.assertIn("git switch --track -c publication origin/publication", text)
        self.assertIn("contents: write", text)
        self.assertNotIn("pull-requests: write", text)
        self.assertIn("git fetch origin publication", text)
        self.assertIn("--expected-remote", text)
        self.assertIn("--bootstrap", text)
        self.assertIn("git worktree add --detach", text)

    def test_publication_push_is_fast_forward_and_does_not_update_main(self):
        temporary, repo = self.make_repo()
        remote_temporary = tempfile.TemporaryDirectory()
        try:
            remote = Path(remote_temporary.name)
            self.git(remote, "init", "--bare")
            self.git(repo, "remote", "add", "origin", str(remote))
            self.git(repo, "push", "origin", "main:main")
            main_before = self.git(repo, "rev-parse", "HEAD")
            self.git(repo, "switch", "-c", PUBLICATION_BRANCH)
            (repo / "output/current.json").write_text('{"new":1}', encoding="utf-8")
            self.assertTrue(commit_weekly_outputs(repo, push=True, bootstrap=True))
            publication_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/publication").stdout.strip(), publication_sha)
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/main").stdout.strip(), main_before.stdout.strip())
            (repo / "output/current.json").write_text('{"new":2}', encoding="utf-8")
            self.assertTrue(commit_weekly_outputs(repo, push=True, expected_remote=publication_sha))
            second_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/publication").stdout.strip(), second_sha)
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/main").stdout.strip(), main_before.stdout.strip())
        finally:
            remote_temporary.cleanup()
            temporary.cleanup()

    def test_publication_stops_when_remote_advanced_after_checkout(self):
        temporary, repo = self.make_repo()
        remote_temporary = tempfile.TemporaryDirectory()
        other_temporary = tempfile.TemporaryDirectory()
        try:
            remote = Path(remote_temporary.name)
            other = Path(other_temporary.name)
            self.git(remote, "init", "--bare")
            self.git(repo, "remote", "add", "origin", str(remote))
            self.git(repo, "push", "origin", "main:publication")
            expected = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.git(repo, "switch", "-c", PUBLICATION_BRANCH)

            self.git(other.parent, "clone", str(remote), str(other))
            self.git(other, "switch", "publication")
            self.git(other, "config", "user.name", "other")
            self.git(other, "config", "user.email", "other@example.com")
            (other / "external.txt").write_text("advanced", encoding="utf-8")
            self.git(other, "add", "external.txt")
            self.git(other, "commit", "-m", "external advance")
            self.git(other, "push", "origin", "publication")
            remote_advanced = self.git(other, "rev-parse", "HEAD").stdout.strip()

            (repo / "output/current.json").write_text('{"new":1}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "advanced after checkout"):
                commit_weekly_outputs(repo, push=True, expected_remote=expected)
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/publication").stdout.strip(), remote_advanced)
        finally:
            other_temporary.cleanup()
            remote_temporary.cleanup()
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
