from __future__ import annotations

import unittest

from scripts.commit_weekly_outputs import commit_weekly_outputs
from tests.test_lock_and_workflow_contract import WorkflowContractTests


class StaleConsumerV2PruningTests(unittest.TestCase):
    def make_helper(self) -> WorkflowContractTests:
        return WorkflowContractTests(methodName="runTest")

    def test_missing_tracked_consumer_v2_chunk_is_pruned(self):
        helper = self.make_helper()
        temporary, repo = helper.make_repo()
        try:
            stale = (
                repo
                / "output/consumer/v2/phases/phase-5/part-999.json"
            )
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("{}\n", encoding="utf-8")
            relative = stale.relative_to(repo).as_posix()
            helper.git(repo, "add", relative)
            helper.git(
                repo,
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "track stale generated chunk",
            )
            stale.unlink()

            helper.advance(repo, "prune-stale-v2")
            self.assertFalse(stale.exists())
            self.assertTrue(commit_weekly_outputs(repo, push=False))
            self.assertNotEqual(
                helper.git(
                    repo,
                    "cat-file",
                    "-e",
                    f"HEAD:{relative}",
                    check=False,
                ).returncode,
                0,
            )
        finally:
            temporary.cleanup()

    def test_missing_unknown_consumer_v2_path_is_still_rejected(self):
        helper = self.make_helper()
        temporary, repo = helper.make_repo()
        try:
            unknown = repo / "output/consumer/v2/secret.json"
            unknown.parent.mkdir(parents=True, exist_ok=True)
            unknown.write_text("{}\n", encoding="utf-8")
            relative = unknown.relative_to(repo).as_posix()
            helper.git(repo, "add", relative)
            helper.git(
                repo,
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "track unknown consumer path",
            )
            unknown.unlink()

            helper.advance(repo, "reject-unknown-v2")
            self.assertFalse(unknown.exists())
            with self.assertRaisesRegex(
                RuntimeError,
                "tracked publication inventory contains unexpected paths",
            ):
                commit_weekly_outputs(repo, push=False)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
