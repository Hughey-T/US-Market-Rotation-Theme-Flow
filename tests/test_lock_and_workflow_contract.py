import datetime as dt
import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rotation.judgments import StableJsonSnapshot
from rotation.provenance import atomic_write_json, file_sha256, stable_hash
from rotation.publication import load_current_generation, publish_generation
from rotation.publication_lock import acquire, inspect, owned_lock, recover, release
from rotation.validation import ContractError, load_json
from scripts.commit_weekly_outputs import PUBLICATION_BRANCH, _validate_staged_allowlist, commit_weekly_outputs
from scripts.export_current_latest import export_current
from scripts.generate_weekly import history_item
from scripts.validate_immutable_judgments import validate_immutable_judgments
from tests.test_publication_contract import generation


ROOT = Path(__file__).resolve().parents[1]


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
        judgment_dir = repo / "output/judgments"
        judgment_dir.mkdir(parents=True)
        atomic_write_json(judgment_dir / "index.json", {"index_version": "1.0", "records": []})
        for name in ("archive", "history", "predictions", "verifications"):
            placeholder = repo / "output" / name / ".gitkeep"
            placeholder.parent.mkdir(parents=True)
            placeholder.write_bytes(b"\n")
        value = generation("2026-07-10", "workflow-base")
        publish_generation(repo / "output", value, history_item(value), {"index_version": "1.0", "records": []})
        export_current(repo / "output", repo / "output/consumer/latest.json")
        self.git(repo, "add", "."); self.git(repo, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "base")
        return temporary, repo

    def advance(self, repo, suffix, data_date="2026-07-17"):
        value = generation(data_date, suffix)
        publish_generation(repo / "output", value, history_item(value), {"index_version": "1.0", "records": []})
        export_current(repo / "output", repo / "output/consumer/latest.json")

    def add_judgment_publication(self, repo):
        output = repo / "output"
        judgments = output / "judgments"
        empty = {"index_version": "1.0", "records": []}
        source = load_json(ROOT / "tests/fixtures/latest_normal.json")
        publish_generation(output, source, history_item(source), empty)
        export_current(output, output / "consumer/latest.json")
        record = load_json(ROOT / "tests/fixtures/judgment_record.json")
        record_path = judgments / "judgment.json"
        atomic_write_json(record_path, record)
        index = {"index_version": "1.0", "records": [{
            "file": record_path.name, "sha256": file_sha256(record_path),
            "judgment_id": record["judgment_id"], "data_date": record["data_date"],
            "content": record,
        }]}
        atomic_write_json(judgments / "index.json", index)
        latest = generation("2026-07-17", "direct-push-judgment")
        publish_generation(output, latest, history_item(latest), index)
        export_current(output, output / "consumer/latest.json")

    def tamper_judgment_content_with_regenerated_hashes(self, repo):
        output = repo / "output"
        current = load_current_generation(output)
        index_path = current[1] / "judgment-index.json"
        index = load_json(index_path)
        index["records"][0]["content"]["theme_judgments"][0]["one_line"] = "commit-helper tamper"
        atomic_write_json(index_path, index)
        atomic_write_json(
            output / "judgments/index.json",
            {key: value for key, value in index.items() if key != "publication"},
        )
        manifest_path = current[1] / "manifest.json"
        manifest = load_json(manifest_path)
        manifest["files"]["judgment-index.json"] = stable_hash(index)
        atomic_write_json(manifest_path, manifest)
        pointer = load_json(output / "current.json")
        pointer["manifest_sha256"] = stable_hash(manifest)
        atomic_write_json(output / "current.json", pointer)

    def test_noop_success_commit_success_and_exact_staging(self):
        temporary, repo = self.make_repo()
        try:
            self.assertFalse(commit_weekly_outputs(repo, push=False))
            self.advance(repo, "commit-success")
            (repo / "output/.publish.lock").write_text("lock", encoding="utf-8")
            (repo / "output/.staging-x").mkdir()
            with self.assertRaisesRegex(ContractError, "interrupted publication transaction"):
                commit_weekly_outputs(repo, push=False)
            (repo / "output/.publish.lock").unlink()
            (repo / "output/.staging-x").rmdir()
            self.assertTrue(commit_weekly_outputs(repo, push=False))
            names = self.git(repo, "show", "--pretty=", "--name-only", "HEAD").stdout
            self.assertIn("output/current.json", names); self.assertNotIn(".publish.lock", names); self.assertNotIn(".staging", names)
        finally: temporary.cleanup()

    def test_commit_hook_identity_and_push_failures_are_not_hidden(self):
        temporary, repo = self.make_repo()
        try:
            self.git(repo, "config", "--unset", "user.name", check=False); self.git(repo, "config", "--unset", "user.email", check=False)
            self.advance(repo, "identity-failure")
            with self.assertRaises(subprocess.CalledProcessError): commit_weekly_outputs(repo, push=False, configure_identity=False)
            self.git(repo, "config", "user.name", "test"); self.git(repo, "config", "user.email", "test@example.com")
            hook = repo / ".git/hooks/pre-commit"; hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8"); os.chmod(hook, 0o755)
            with self.assertRaises(subprocess.CalledProcessError): commit_weekly_outputs(repo, push=False)
            hook.unlink(); commit_weekly_outputs(repo, push=False)
            self.git(repo, "switch", "-c", PUBLICATION_BRANCH)
            with self.assertRaises(subprocess.CalledProcessError): commit_weekly_outputs(repo, push=True, bootstrap=True)
        finally: temporary.cleanup()

    def test_commit_rejects_hook_mutation_of_validated_bytes_before_push(self):
        temporary, repo = self.make_repo()
        try:
            self.advance(repo, "hook-byte-mutation")
            hook = repo / ".git/hooks/pre-commit"
            hook.write_text(
                "#!/bin/sh\nprintf '{}\\n' > output/current.json\ngit add output/current.json\n",
                encoding="utf-8",
            )
            os.chmod(hook, 0o755)
            with self.assertRaisesRegex(RuntimeError, "commit bytes differ from validated inventory"):
                commit_weekly_outputs(repo, push=False)
        finally:
            temporary.cleanup()

    def test_workflow_has_strict_shell_and_no_commit_failure_mask(self):
        text = (Path(__file__).resolve().parents[1] / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
        test_workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/test.yml").read_text(encoding="utf-8")
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
        self.assertLess(text.index("- name: Offline preflight"), text.index("- name: Bootstrap or update publication work"))
        self.assertLess(text.index("- name: Bootstrap or update publication work"), text.index("- name: Generate, validate, and publish"))
        self.assertIn("push:\n    branches: [main]", test_workflow)

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
            self.advance(repo, "first-push")
            self.assertTrue(commit_weekly_outputs(repo, push=True, bootstrap=True))
            publication_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/publication").stdout.strip(), publication_sha)
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/main").stdout.strip(), main_before.stdout.strip())
            self.advance(repo, "second-push", "2026-07-24")
            self.assertTrue(commit_weekly_outputs(repo, push=True, expected_remote=publication_sha))
            second_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/publication").stdout.strip(), second_sha)
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/main").stdout.strip(), main_before.stdout.strip())
        finally:
            remote_temporary.cleanup()
            temporary.cleanup()

    def test_bootstrap_and_nonbootstrap_direct_push_reject_content_mismatch(self):
        for bootstrap in (True, False):
            with self.subTest(bootstrap=bootstrap):
                temporary, repo = self.make_repo()
                remote_temporary = tempfile.TemporaryDirectory()
                try:
                    remote = Path(remote_temporary.name)
                    self.git(remote, "init", "--bare")
                    self.git(repo, "remote", "add", "origin", str(remote))
                    self.git(repo, "push", "origin", "main:main")
                    expected = self.git(repo, "rev-parse", "HEAD").stdout.strip()
                    if not bootstrap:
                        self.git(repo, "push", "origin", "main:publication")
                    self.git(repo, "switch", "-c", PUBLICATION_BRANCH)
                    self.add_judgment_publication(repo)
                    self.tamper_judgment_content_with_regenerated_hashes(repo)
                    local_before = self.git(repo, "rev-parse", "HEAD").stdout.strip()
                    with self.assertRaisesRegex(ContractError, "invalid current publication|judgment index"):
                        commit_weekly_outputs(
                            repo, push=True, bootstrap=bootstrap,
                            expected_remote=None if bootstrap else expected,
                        )
                    self.assertEqual(self.git(repo, "rev-parse", "HEAD").stdout.strip(), local_before)
                    remote_ref = self.git(
                        remote, "rev-parse", "--verify", "refs/heads/publication", check=False,
                    )
                    if bootstrap:
                        self.assertNotEqual(remote_ref.returncode, 0)
                    else:
                        self.assertEqual(remote_ref.stdout.strip(), expected)
                finally:
                    remote_temporary.cleanup()
                    temporary.cleanup()

    def test_bootstrap_and_nonbootstrap_commit_reject_index_toctou(self):
        for bootstrap in (True, False):
            for location in ("generation", "root"):
                with self.subTest(bootstrap=bootstrap, location=location):
                    temporary, repo = self.make_repo()
                    remote_temporary = tempfile.TemporaryDirectory()
                    try:
                        remote = Path(remote_temporary.name)
                        self.git(remote, "init", "--bare")
                        self.git(repo, "remote", "add", "origin", str(remote))
                        self.git(repo, "push", "origin", "main:main")
                        expected = self.git(repo, "rev-parse", "HEAD").stdout.strip()
                        if not bootstrap:
                            self.git(repo, "push", "origin", "main:publication")
                        self.git(repo, "switch", "-c", PUBLICATION_BRANCH)
                        self.add_judgment_publication(repo)
                        current = load_current_generation(repo / "output")
                        target = (
                            current[1] / "judgment-index.json"
                            if location == "generation"
                            else repo / "output/judgments/index.json"
                        )
                        local_before = self.git(repo, "rev-parse", "HEAD").stdout.strip()
                        pointer_before = (repo / "output/current.json").read_bytes()
                        real_ensure_unchanged = StableJsonSnapshot.ensure_unchanged
                        changed = False

                        def change_then_compare(snapshot):
                            nonlocal changed
                            if snapshot.path == target and not changed:
                                value = load_json(target)
                                value["records"][0]["content"]["theme_judgments"][0]["one_line"] = "TOCTOU"
                                atomic_write_json(target, value)
                                changed = True
                            return real_ensure_unchanged(snapshot)

                        with mock.patch.object(
                            StableJsonSnapshot, "ensure_unchanged", autospec=True,
                            side_effect=change_then_compare,
                        ):
                            with self.assertRaisesRegex(
                                ContractError, "judgment index changed during validation",
                            ):
                                commit_weekly_outputs(
                                    repo, push=True, bootstrap=bootstrap,
                                    expected_remote=None if bootstrap else expected,
                                )
                        self.assertTrue(changed)
                        self.assertEqual(
                            self.git(repo, "rev-parse", "HEAD").stdout.strip(), local_before,
                        )
                        self.assertEqual((repo / "output/current.json").read_bytes(), pointer_before)
                        remote_ref = self.git(
                            remote, "rev-parse", "--verify", "refs/heads/publication", check=False,
                        )
                        if bootstrap:
                            self.assertNotEqual(remote_ref.returncode, 0)
                        else:
                            self.assertEqual(remote_ref.stdout.strip(), expected)
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

            self.advance(repo, "remote-advance")
            with self.assertRaisesRegex(RuntimeError, "advanced after checkout"):
                commit_weekly_outputs(repo, push=True, expected_remote=expected)
            self.assertEqual(self.git(remote, "rev-parse", "refs/heads/publication").stdout.strip(), remote_advanced)
        finally:
            other_temporary.cleanup()
            remote_temporary.cleanup()
            temporary.cleanup()

    def test_pre_staged_path_outside_publication_allowlist_is_rejected(self):
        temporary, repo = self.make_repo()
        try:
            outside = repo / "outside_allowlist.txt"
            outside.write_text("base\n", encoding="utf-8")
            self.git(repo, "add", outside.name)
            self.git(repo, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "tracked outside path")
            outside.write_text("staged change\n", encoding="utf-8")
            self.git(repo, "add", outside.name)
            self.advance(repo, "pre-staged")
            with self.assertRaisesRegex(RuntimeError, "outside the allowlist"):
                commit_weekly_outputs(repo, push=False)
        finally:
            temporary.cleanup()

    def test_staged_allowlist_compares_exact_files_not_directory_prefixes(self):
        temporary, repo = self.make_repo()
        try:
            secret = repo / "output/generations/secret.txt"
            secret.write_text("sensitive body", encoding="utf-8")
            self.git(repo, "add", "output/generations/secret.txt")
            with self.assertRaisesRegex(RuntimeError, "outside the allowlist"):
                _validate_staged_allowlist(repo, {"output/current.json"})
        finally:
            temporary.cleanup()

    def test_commit_rejects_unknown_root_generation_and_judgment_entries(self):
        for location in ("root", "generation", "judgments"):
            with self.subTest(location=location):
                temporary, repo = self.make_repo()
                try:
                    self.advance(repo, f"unknown-{location}")
                    if location == "root":
                        path = repo / "output/secret.txt"
                    elif location == "generation":
                        current = load_current_generation(repo / "output")
                        path = current[1] / "secret.txt"
                    else:
                        path = repo / "output/judgments/secret.txt"
                    path.write_text("sensitive body", encoding="utf-8")
                    if location == "root":
                        self.git(repo, "add", "output/secret.txt")
                    before = self.git(repo, "rev-parse", "HEAD").stdout.strip()
                    with self.assertRaisesRegex(ContractError, "publication entry"):
                        commit_weekly_outputs(repo, push=False)
                    self.assertEqual(self.git(repo, "rev-parse", "HEAD").stdout.strip(), before)
                finally:
                    temporary.cleanup()

    def test_commit_rejects_unknown_deletion_and_legacy_placeholder_change(self):
        for mutation in ("delete", "modify"):
            with self.subTest(mutation=mutation):
                temporary, repo = self.make_repo()
                try:
                    self.advance(repo, f"placeholder-{mutation}")
                    placeholder = repo / "output/archive/.gitkeep"
                    if mutation == "delete":
                        placeholder.unlink()
                    else:
                        placeholder.write_bytes(b"changed")
                    with self.assertRaisesRegex(RuntimeError, "publication|placeholder"):
                        commit_weekly_outputs(repo, push=False)
                finally:
                    temporary.cleanup()

    def test_publication_push_rejects_changed_existing_judgment(self):
        temporary, repo = self.make_repo()
        try:
            record = repo / "output/judgments/existing.json"
            record.write_text('{"value":"immutable"}\n', encoding="utf-8")
            self.git(repo, "add", str(record.relative_to(repo)))
            self.git(repo, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "add immutable judgment")
            expected = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            record.write_text('{"value":"rewritten"}\n', encoding="utf-8")
            self.git(repo, "add", str(record.relative_to(repo)))
            self.git(repo, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "rewrite")
            with self.assertRaisesRegex(ContractError, "immutable judgment"):
                validate_immutable_judgments(repo, expected, "HEAD")
        finally:
            temporary.cleanup()

    def test_publication_push_allows_new_judgment_record(self):
        temporary, repo = self.make_repo()
        try:
            expected = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            (repo / "output/judgments/new.json").write_text('{"value":"new"}\n', encoding="utf-8")
            self.git(repo, "add", "output/judgments/new.json")
            self.git(repo, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "add")
            validate_immutable_judgments(repo, expected, "HEAD")
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
