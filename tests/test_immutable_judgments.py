import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from rotation.validation import ContractError
from scripts.validate_immutable_judgments import validate_immutable_judgments


class ImmutableJudgmentBaseComparisonTests(unittest.TestCase):
    def git(self, repo, *args):
        return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    def make_repo(self):
        temporary = tempfile.TemporaryDirectory()
        repo = Path(temporary.name)
        self.git(repo, "init", "-b", "main")
        self.git(repo, "config", "user.name", "test")
        self.git(repo, "config", "user.email", "test@example.com")
        self.write_json(repo / "output/judgments/judgment_base.json", {"value": "immutable"})
        self.write_json(repo / "output/judgments/index.json", {"records": []})
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-m", "base")
        return temporary, repo, self.git(repo, "rev-parse", "HEAD")

    def test_existing_record_change_and_reindex_are_rejected(self):
        temporary, repo, base = self.make_repo()
        try:
            self.write_json(repo / "output/judgments/judgment_base.json", {"value": "changed"})
            self.write_json(repo / "output/judgments/index.json", {"records": ["updated"]})
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-m", "rewrite record and index")
            with self.assertRaisesRegex(ContractError, "judgment_base.json"):
                validate_immutable_judgments(repo, base)
        finally:
            temporary.cleanup()

    def test_new_record_and_index_update_are_allowed(self):
        temporary, repo, base = self.make_repo()
        try:
            self.write_json(repo / "output/judgments/judgment_new.json", {"value": "new"})
            self.write_json(repo / "output/judgments/index.json", {"records": ["new"]})
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-m", "append record")
            validate_immutable_judgments(repo, base)
        finally:
            temporary.cleanup()

    def test_delete_and_rename_are_rejected(self):
        for operation in ("delete", "rename"):
            temporary, repo, base = self.make_repo()
            try:
                path = repo / "output/judgments/judgment_base.json"
                if operation == "delete":
                    path.unlink()
                else:
                    path.rename(repo / "output/judgments/judgment_renamed.json")
                self.git(repo, "add", "-A")
                self.git(repo, "commit", "-m", operation)
                with self.subTest(operation=operation), self.assertRaises(ContractError):
                    validate_immutable_judgments(repo, base)
            finally:
                temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
