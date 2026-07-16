import copy
import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rotation.identity import generation_identity
from rotation.provenance import atomic_write_json, file_sha256, snapshot_source_hash
from rotation.publication import load_current_generation, publish_generation, validate_current_publication_inventory
from rotation.validation import ContractError, load_json
from scripts import generate_weekly
from scripts.generate_weekly import history_item
from scripts.migrate_publication_v1 import migrate
from tests.test_publication_contract import generation


ROOT = Path(__file__).resolve().parents[1]


class AcquisitionStarted(RuntimeError):
    pass


def output_signature(output: Path):
    if not output.exists():
        return None
    values = []
    for path in sorted(output.rglob("*"), key=lambda item: item.relative_to(output).as_posix()):
        kind = "symlink" if path.is_symlink() else "directory" if path.is_dir() else "file"
        content = path.read_bytes() if kind == "file" else None
        values.append((path.relative_to(output).as_posix(), kind, content))
    return values


class PublicationBootstrapStateTests(unittest.TestCase):
    def canonical_output(self, directory: str) -> Path:
        output = Path(directory) / "output"
        (output / "judgments").mkdir(parents=True)
        atomic_write_json(output / "judgments/index.json", {"index_version": "1.0", "records": []})
        value = generation("2026-07-10", "preflight-current")
        publish_generation(output, value, history_item(value), {"index_version": "1.0", "records": []})
        return output

    def assert_reaches_acquisition(self, output: Path):
        acquisition = mock.Mock(side_effect=AcquisitionStarted("acquisition reached"))
        with mock.patch.object(generate_weekly, "OUTPUT", output), mock.patch.object(
            generate_weekly, "download_observations", acquisition
        ):
            with self.assertRaisesRegex(AcquisitionStarted, "acquisition reached"):
                generate_weekly.main([])
        acquisition.assert_called_once()

    def assert_rejected_before_acquisition(self, output: Path, message: str):
        before = output_signature(output)
        acquisition = mock.Mock(side_effect=AssertionError("network acquisition must not start"))
        with mock.patch.object(generate_weekly, "OUTPUT", output), mock.patch.object(
            generate_weekly, "download_observations", acquisition
        ):
            with self.assertRaisesRegex(RuntimeError, message):
                generate_weekly.main([])
        acquisition.assert_not_called()
        self.assertEqual(output_signature(output), before)

    def test_clean_bootstrap_shapes_reach_acquisition(self):
        shapes = (
            "output-absent", "output-empty", "archive-empty", "empty-placeholder",
            "crlf-placeholder", "main-placeholder-shape",
        )
        for shape in shapes:
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                if shape == "output-empty":
                    output.mkdir()
                elif shape == "archive-empty":
                    (output / "archive").mkdir(parents=True)
                elif shape == "empty-placeholder":
                    (output / "archive").mkdir(parents=True)
                    (output / "archive" / ".gitkeep").write_bytes(b"")
                elif shape == "crlf-placeholder":
                    (output / "archive").mkdir(parents=True)
                    (output / "archive" / ".gitkeep").write_bytes(b"\r\n")
                elif shape == "main-placeholder-shape":
                    shutil.copytree(ROOT / "output", output)
                self.assertEqual(generate_weekly.classify_publication_start_state(output).kind, "clean")
                self.assert_reaches_acquisition(output)

    def test_fixed_legacy_latest_is_rejected_with_migration_guidance(self):
        for with_placeholder in (False, True):
            with self.subTest(with_placeholder=with_placeholder), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                output.mkdir()
                (output / "latest.json").write_text("{}\n", encoding="utf-8")
                if with_placeholder:
                    (output / "archive").mkdir()
                    (output / "archive" / ".gitkeep").write_bytes(b"")
                state = generate_weekly.classify_publication_start_state(output)
                self.assertEqual((state.kind, state.path), ("fixed_legacy", "output/latest.json"))
                self.assert_rejected_before_acquisition(output, "legacy fixed publication detected.*migrate_publication_v1.py --explicit")

    def test_archive_only_legacy_is_distinct_and_rejected(self):
        archives = {
            "one": {"2026-07-10.json": b"{}\n"},
            "multiple": {"2026-07-10.json": b"{}\n", "2026-07-17.json": b"{}\n"},
            "nested": {"2026/07/2026-07-10.json": b"{}\n"},
        }
        for name, files in archives.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                for relative, content in files.items():
                    path = output / "archive" / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                state = generate_weekly.classify_publication_start_state(output)
                self.assertEqual(state.kind, "partial_legacy")
                self.assert_rejected_before_acquisition(
                    output, "partial legacy publication detected: archive data exists but output/latest.json is absent"
                )

    def test_ambiguous_entries_fail_closed_and_report_only_path(self):
        entries = (
            "unknown.txt", "unknown-directory", "archive/notes.txt", "archive/unknown-directory", "archive/broken.json",
        )
        for relative in entries:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                path = output / relative
                if "directory" in path.name:
                    path.mkdir(parents=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("not json" if path.suffix == ".json" else "secret body must not appear", encoding="utf-8")
                expected = f"output/{relative}"
                state = generate_weekly.classify_publication_start_state(output)
                self.assertEqual((state.kind, state.path), ("ambiguous", expected))
                self.assert_rejected_before_acquisition(output, f"ambiguous output state: unexpected path {expected}")

    def test_invalid_current_and_unknown_files_are_rejected_before_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            (output / "archive").mkdir(parents=True)
            (output / "current.json").write_text("{}\n", encoding="utf-8")
            (output / "latest.json").write_text("{}\n", encoding="utf-8")
            (output / "archive" / "2026-07-10.json").write_text("{}\n", encoding="utf-8")
            (output / "unknown.txt").write_text("preserved", encoding="utf-8")
            state = generate_weekly.classify_publication_start_state(output)
            self.assertEqual((state.kind, state.path), ("invalid_current", "output/current.json"))
            self.assert_rejected_before_acquisition(output, "invalid current publication: output/current.json")

    def test_known_directories_with_data_are_not_clean_bootstrap(self):
        names = (
            "archive", "history", "judgments", "predictions", "verifications", "consumer", "generations",
        )
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                path = output / name / "secret.txt"
                path.parent.mkdir(parents=True)
                path.write_text("sensitive body", encoding="utf-8")
                state = generate_weekly.classify_publication_start_state(output)
                expected = (
                    f"output/{name}" if name == "consumer" else f"output/{name}/secret.txt"
                )
                self.assertEqual((state.kind, state.path), ("ambiguous", expected))
                self.assert_rejected_before_acquisition(
                    output, f"ambiguous output state: unexpected path {expected}",
                )

    def test_lock_and_staging_are_rejected_before_acquisition(self):
        shapes = {
            "lock": ((".publish.lock", False),),
            "staging-empty": ((".staging-stale", True),),
            "staging-data": ((".staging-stale/secret.txt", False),),
            "multiple-staging": ((".staging-a", True), (".staging-b", True)),
            "lock-and-staging": ((".publish.lock", False), (".staging-stale", True)),
        }
        for name, entries in shapes.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                for relative, directory_entry in entries:
                    path = output / relative
                    if directory_entry:
                        path.mkdir(parents=True)
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("transaction debris", encoding="utf-8")
                state = generate_weekly.classify_publication_start_state(output)
                self.assertEqual(state.kind, "ambiguous")
                self.assert_rejected_before_acquisition(output, "ambiguous output state")

    def test_current_with_lock_or_generation_like_staging_stops_before_acquisition(self):
        for shape in ("lock", "generation-like-staging"):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as directory:
                output = self.canonical_output(directory)
                if shape == "lock":
                    (output / ".publish.lock").write_text("held", encoding="utf-8")
                else:
                    current = load_current_generation(output)
                    shutil.copytree(current[1], output / ".staging-valid-looking")
                state = generate_weekly.classify_publication_start_state(output)
                self.assertEqual(state.kind, "invalid_current")
                self.assert_rejected_before_acquisition(output, "invalid current publication")

    def test_invalid_current_variants_stop_before_acquisition(self):
        for mutation in (
            "empty", "malformed", "schema", "missing-generation", "manifest-hash",
            "generation-path", "source-hash",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                output = self.canonical_output(directory)
                current = output / "current.json"
                if mutation == "empty":
                    current.write_bytes(b"")
                elif mutation == "malformed":
                    current.write_text("{", encoding="utf-8")
                elif mutation == "source-hash":
                    generation_dir = load_current_generation(output)[1]
                    value = load_json(generation_dir / "latest.json")
                    value["meta"]["source_sha256"] = "0" * 64
                    atomic_write_json(generation_dir / "latest.json", value)
                else:
                    value = load_json(current)
                    if mutation == "schema":
                        value = {}
                    elif mutation == "missing-generation":
                        value["generation_id"] = "f" * 64
                        value["generation"] = f"generations/{'f' * 64}"
                    elif mutation == "manifest-hash":
                        value["manifest_sha256"] = "0" * 64
                    elif mutation == "generation-path":
                        value["generation"] = f"generations/{'f' * 64}"
                    atomic_write_json(current, value)
                state = generate_weekly.classify_publication_start_state(output)
                self.assertEqual(state.kind, "invalid_current")
                self.assert_rejected_before_acquisition(output, "invalid current publication")

    def test_unknown_generation_and_judgment_entries_fail_current_preflight(self):
        for location in ("generation", "judgments", "judgments-json", "orphan"):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as directory:
                output = self.canonical_output(directory)
                current = load_current_generation(output)
                if location == "generation":
                    path = current[1] / "secret.txt"
                elif location == "judgments":
                    path = output / "judgments/secret.txt"
                elif location == "judgments-json":
                    path = output / "judgments/unreferenced.json"
                else:
                    path = output / "generations/invalid-orphan/secret.txt"
                    path.parent.mkdir()
                path.write_text("sensitive body", encoding="utf-8")
                state = generate_weekly.classify_publication_start_state(output)
                expected = (
                    "output/generations/invalid-orphan" if location == "orphan"
                    else f"output/{path.relative_to(output).as_posix()}"
                )
                self.assertEqual((state.kind, state.path), (
                    "invalid_current", expected,
                ))
                self.assert_rejected_before_acquisition(output, "invalid current publication")

    def test_broken_consumer_symlink_shape_is_not_treated_as_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.canonical_output(directory)
            consumer = output / "consumer"
            consumer.mkdir()
            real_exists, real_symlink = Path.exists, Path.is_symlink
            with mock.patch.object(
                Path, "exists", autospec=True,
                side_effect=lambda path: False if path == consumer else real_exists(path),
            ), mock.patch.object(
                Path, "is_symlink", autospec=True,
                side_effect=lambda path: True if path == consumer else real_symlink(path),
            ):
                state = generate_weekly.classify_publication_start_state(output)
            self.assertEqual((state.kind, state.path), ("invalid_current", "output/consumer"))


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

    def test_stale_orphan_cannot_roll_current_back_after_newer_publication(self):
        stale = generation("2026-07-17", "stale-orphan")
        with self.assertRaises(OSError):
            publish_generation(
                self.output, stale, history_item(stale), self.index,
                lambda step: (_ for _ in ()).throw(OSError("after rename")) if step == "generation_rename" else None,
            )
        newest = generation("2026-07-24", "newest")
        with self.assertRaisesRegex(ContractError, "unrelated orphan generation"):
            publish_generation(self.output, newest, history_item(newest), self.index)
        shutil.rmtree(self.output / "generations" / stale["meta"]["source_snapshot"].split("/")[2])
        newest_pointer = publish_generation(self.output, newest, history_item(newest), self.index)
        with self.assertRaisesRegex(ContractError, "cannot move backwards"):
            publish_generation(self.output, stale, history_item(stale), self.index)
        self.assertEqual(load_current_generation(self.output)[0], newest_pointer)

    def test_fresh_older_analysis_requires_explicit_rollback(self):
        newest = generation("2026-07-24", "newest-first")
        newest_pointer = publish_generation(self.output, newest, history_item(newest), self.index)
        older = generation("2026-07-17", "fresh-but-older")
        with self.assertRaisesRegex(ContractError, "cannot move backwards"):
            publish_generation(self.output, older, history_item(older), self.index)
        self.assertEqual(load_current_generation(self.output)[0], newest_pointer)

    def test_invalid_orphan_is_rejected_without_changing_current(self):
        invalid = self.output / "generations" / ("f" * 64)
        invalid.mkdir(parents=True); (invalid / "manifest.json").write_text("{}", encoding="utf-8")
        new = generation("2026-07-17", "new-valid")
        with self.assertRaisesRegex(ContractError, "invalid orphan generation"):
            publish_generation(self.output, new, history_item(new), self.index)
        self.assert_old_current()

    def test_valid_unrelated_orphan_is_rejected_without_auto_deletion(self):
        unrelated = generation("2026-07-17", "unrelated-orphan")
        with self.assertRaises(OSError):
            publish_generation(
                self.output, unrelated, history_item(unrelated), self.index,
                lambda step: (_ for _ in ()).throw(OSError("after rename")) if step == "generation_rename" else None,
            )
        orphan = self.output / "generations" / unrelated["meta"]["source_snapshot"].split("/")[2]
        retry = generation("2026-07-17", "different-analysis")
        with self.assertRaisesRegex(ContractError, "unrelated orphan generation"):
            publish_generation(self.output, retry, history_item(retry), self.index)
        self.assertTrue(orphan.is_dir())
        self.assert_old_current()

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

    def test_exact_inventory_allows_a_valid_immutable_judgment_addition(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "output"
        judgments = output / "judgments"
        judgments.mkdir(parents=True)
        empty = {"index_version": "1.0", "records": []}
        atomic_write_json(judgments / "index.json", empty)
        source = load_json(ROOT / "tests/fixtures/latest_normal.json")
        publish_generation(output, source, history_item(source), empty)
        record = load_json(ROOT / "tests/fixtures/judgment_record.json")
        record_path = judgments / "judgment.json"
        atomic_write_json(record_path, record)
        index = {"index_version": "1.0", "records": [{
            "file": record_path.name,
            "sha256": file_sha256(record_path),
            "judgment_id": record["judgment_id"],
            "data_date": record["data_date"],
            "content": record,
        }]}
        atomic_write_json(judgments / "index.json", index)
        latest = generation("2026-07-17", "valid-judgment-addition")
        publish_generation(output, latest, history_item(latest), index)
        inventory = validate_current_publication_inventory(output, require_consumer=False)
        self.assertIn("output/judgments/judgment.json", inventory)


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
            self.assertEqual(generate_weekly.classify_publication_start_state(output).kind, "current")

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
