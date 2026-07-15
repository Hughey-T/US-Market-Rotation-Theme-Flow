import copy
import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rotation.identity import generation_identity
from rotation.provenance import atomic_write_json, snapshot_source_hash
from rotation.publication import load_current_generation, publish_generation
from rotation.validation import ContractError, load_json
from scripts.export_current_latest import export_current
from scripts.generate_weekly import history_item
from scripts.migrate_publication_v1 import migrate
from tests.test_publication_contract import generation


class PublicationHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary.name) / "output"
        self.index = {"index_version": "1.0", "records": []}
        self.old = generation("2026-07-10", "old")
        self.old_pointer = publish_generation(self.output, self.old, history_item(self.old), self.index)

    def tearDown(self):
        self.temporary.cleanup()

    def assert_old_current(self):
        self.assertEqual(load_current_generation(self.output)[0], self.old_pointer)

    def test_four_invalid_staging_components_and_manifest_hash_are_rejected(self):
        for filename in ("latest.json", "archive.json", "history.json", "judgment-index.json", "manifest.json"):
            new = generation("2026-07-17", filename)
            real = atomic_write_json
            def write(path, value, *, _filename=filename):
                real(path, value)
                if path.name == _filename:
                    corrupted = load_json(path)
                    if _filename == "manifest.json":
                        corrupted["files"]["latest.json"] = "0" * 64
                    else:
                        corrupted["unexpected"] = True
                    real(path, corrupted)
            with self.subTest(filename=filename), mock.patch("rotation.publication.atomic_write_json", side_effect=write):
                with self.assertRaises(ContractError):
                    publish_generation(self.output, new, history_item(new), self.index)
                self.assert_old_current()

    def test_latest_additional_property_is_rejected_with_consistent_hash(self):
        new = generation("2026-07-17", "schema-only-mutation")
        new["unexpected"] = True
        new["meta"]["source_sha256"] = snapshot_source_hash(new)
        with self.assertRaisesRegex(ContractError, "publication latest"):
            publish_generation(self.output, new, history_item(new), self.index)
        self.assert_old_current()

    def test_pointer_is_strictly_prevalidated_before_atomic_write(self):
        new = generation("2026-07-17", "bad-pointer")
        from rotation import publication
        real = publication.current_pointer
        with mock.patch.object(publication, "current_pointer", side_effect=lambda manifest: {**real(manifest), "unexpected": True}):
            with self.assertRaisesRegex(ContractError, "pointer candidate"):
                publish_generation(self.output, new, history_item(new), self.index)
        self.assert_old_current()

    def test_unsafe_analysis_ids_are_rejected_before_generation_creation(self):
        for bad in ("bad run id", "bad/run", "..", "bad\\run", ".", "C:\\temp"):
            value = generation("2026-07-17", bad)
            value["meta"]["run_id"] = bad
            value["meta"]["source_sha256"] = snapshot_source_hash(value)
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                publish_generation(self.output, value, history_item(value), self.index)
            self.assert_old_current()

    def test_different_clock_retry_reuses_valid_orphan(self):
        first = generation("2026-07-17", "same-analysis")
        with self.assertRaises(OSError):
            publish_generation(self.output, first, history_item(first), self.index,
                               lambda step: (_ for _ in ()).throw(OSError("after rename")) if step == "generation_rename" else None)
        second = copy.deepcopy(first)
        second["meta"]["generated_at"] = "2026-07-18T00:00:00Z"
        new_generation = generation_identity(second["meta"]["run_id"], second["meta"]["generated_at"], second["meta"]["source_commit"])
        second["meta"]["source_snapshot"] = f"output/generations/{new_generation}/archive.json"
        second["meta"]["source_sha256"] = snapshot_source_hash(second)
        pointer = publish_generation(self.output, second, history_item(second), self.index)
        self.assertEqual(pointer["generation_id"], first["meta"]["source_snapshot"].split("/")[2])
        self.assertEqual(len(list((self.output / "generations").iterdir())), 2)
        self.assertEqual(list(self.output.glob(".staging-*")), [])
        self.assertFalse((self.output / ".publish.lock").exists())

    def test_invalid_orphan_is_ignored_and_export_resolves_current(self):
        invalid = self.output / "generations" / ("f" * 64)
        invalid.mkdir(parents=True); (invalid / "manifest.json").write_text("{}", encoding="utf-8")
        new = generation("2026-07-17", "new-valid")
        pointer = publish_generation(self.output, new, history_item(new), self.index)
        exported = Path(self.temporary.name) / "latest.json"
        export_current(self.output, exported)
        self.assertEqual(load_json(exported)["meta"]["run_id"], pointer["analysis_id"])

    def test_multiple_valid_orphans_choose_earliest_deterministically(self):
        first = generation("2026-07-17", "multiple-orphans")
        with self.assertRaises(OSError):
            publish_generation(self.output, first, history_item(first), self.index,
                               lambda step: (_ for _ in ()).throw(OSError("orphan one")) if step == "generation_rename" else None)
        second = copy.deepcopy(first); second["meta"]["generated_at"] = "2026-07-12T00:00:00Z"
        second_id = generation_identity(second["meta"]["run_id"], second["meta"]["generated_at"], second["meta"]["source_commit"])
        second["meta"]["source_snapshot"] = f"output/generations/{second_id}/archive.json"
        second["meta"]["source_sha256"] = snapshot_source_hash(second)
        with tempfile.TemporaryDirectory() as other_directory:
            other = Path(other_directory) / "output"
            publish_generation(other, self.old, history_item(self.old), self.index)
            with self.assertRaises(OSError):
                publish_generation(other, second, history_item(second), self.index,
                                   lambda step: (_ for _ in ()).throw(OSError("orphan two")) if step == "generation_rename" else None)
            shutil.copytree(other / "generations" / second_id, self.output / "generations" / second_id)
        retry = copy.deepcopy(second); retry["meta"]["generated_at"] = "2026-07-13T00:00:00Z"
        retry_id = generation_identity(retry["meta"]["run_id"], retry["meta"]["generated_at"], retry["meta"]["source_commit"])
        retry["meta"]["source_snapshot"] = f"output/generations/{retry_id}/archive.json"
        retry["meta"]["source_sha256"] = snapshot_source_hash(retry)
        pointer = publish_generation(self.output, retry, history_item(retry), self.index)
        first_id = first["meta"]["source_snapshot"].split("/")[2]
        self.assertEqual(pointer["generation_id"], first_id)

    def test_previous_generation_id_schema_violation_keeps_current(self):
        current = load_current_generation(self.output)
        manifest_path = current[1] / "manifest.json"
        manifest = load_json(manifest_path); manifest["previous_generation_id"] = "../bad"
        atomic_write_json(manifest_path, manifest)
        with self.assertRaises(ContractError):
            load_current_generation(self.output)


class MigrationBootstrapTests(unittest.TestCase):
    def test_explicit_migration_preserves_legacy_latest_and_creates_current(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"; output.mkdir()
            legacy = generation("2026-07-10", "legacy-fixed")
            atomic_write_json(output / "latest.json", legacy)
            before = (output / "latest.json").read_bytes()
            pointer = migrate(output, dt.datetime(2026, 7, 12, tzinfo=dt.timezone.utc), "b" * 40)
            self.assertEqual((output / "latest.json").read_bytes(), before)
            self.assertEqual(load_current_generation(output)[0], pointer)

    def test_failed_explicit_migration_preserves_invalid_legacy_and_no_current(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"; output.mkdir()
            legacy = generation("2026-07-10", "legacy-invalid"); legacy["unexpected"] = True
            atomic_write_json(output / "latest.json", legacy)
            before = (output / "latest.json").read_bytes()
            with self.assertRaises(ContractError):
                migrate(output, dt.datetime(2026, 7, 12, tzinfo=dt.timezone.utc), "b" * 40)
            self.assertEqual((output / "latest.json").read_bytes(), before)
            self.assertFalse((output / "current.json").exists())


if __name__ == "__main__":
    unittest.main()
