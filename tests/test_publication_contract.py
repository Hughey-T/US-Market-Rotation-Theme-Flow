import copy
import tempfile
import unittest
from pathlib import Path

from rotation.provenance import atomic_write_json, snapshot_source_hash, stable_hash
from rotation.publication import committed_history, instruction_version_for_data_schema, instruction_versions_for_data_schema, load_current_generation, publish_generation
from rotation.validation import ContractError, load_json, validate_latest_semantics, validate_public_latest
from scripts.generate_weekly import history_item
from scripts.export_current_latest import export_current
from scripts.export_consumer_projection import export_consumer_projection
from scripts.export_consumer_details import export_consumer_details
from scripts.export_consumer_v2 import export_consumer_v2
from scripts.validate_repository import validate_public_outputs
from tests.test_pipeline_contract import build_synthetic


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")
FAILURE_POINTS = (
    "archive_staging_write",
    "history_staging_write",
    "judgment_index_staging_write",
    "latest_staging_write",
    "manifest_write",
    "generation_rename",
    "current_pointer_switch",
)


def generation(data_date: str, suffix: str):
    value = copy.deepcopy(build_synthetic())
    run_id = stable_hash({"data_date": data_date, "suffix": suffix, "kind": "analysis"})
    generation_id = stable_hash({"run_id": run_id, "generated_at": value["meta"]["generated_at"]})
    value["meta"].update(
        data_date=data_date,
        run_id=run_id,
        source_snapshot=f"output/generations/{generation_id}/archive.json",
    )
    value["meta"]["source_sha256"] = snapshot_source_hash(value)
    return value


class PublicLatestContractTests(unittest.TestCase):
    def test_instruction_identity_follows_snapshot_schema_for_legacy_generation_validation(self):
        self.assertEqual(instruction_version_for_data_schema("1.1"), "1.1.1")
        self.assertEqual(instruction_version_for_data_schema("1.2"), "1.5.0")
        self.assertEqual(
            instruction_versions_for_data_schema("1.2"),
            {"1.3.0", "1.4.0", "1.5.0"},
        )

    def test_generic_failed_manifest_is_valid_but_public_latest_rejects_it(self):
        value = generation("2026-07-10", "failed-manifest")
        value["meta"].update(status="failed", failure_reason="diagnostic only")
        value["meta"]["source_sha256"] = snapshot_source_hash(value)
        validate_latest_semantics(value, verify_source_hash=True)
        with self.assertRaisesRegex(ContractError, "status=success"):
            validate_public_latest(value)

    def test_repository_public_output_contract_absent_success_and_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(validate_public_outputs(root, SCHEMA), 0)
            output = root / "output"
            output.mkdir()
            success = generation("2026-07-10", "public-success")
            atomic_write_json(output / "latest.json", success)
            self.assertEqual(validate_public_outputs(root, SCHEMA), 1)
            failed = copy.deepcopy(success)
            failed["meta"].update(status="failed", failure_reason="diagnostic only")
            failed["meta"]["source_sha256"] = snapshot_source_hash(failed)
            atomic_write_json(output / "latest.json", failed)
            with self.assertRaisesRegex(ContractError, "status=success"):
                validate_public_outputs(root, SCHEMA)

    def test_consumer_projection_must_match_authoritative_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            index = {"index_version": "1.0", "records": []}
            current = generation("2026-07-10", "consumer-current")
            publish_generation(output, current, history_item(current), index)
            consumer_path = output / "consumer" / "latest.json"
            export_current(output, consumer_path)
            export_consumer_projection(output, output / "consumer/v1/latest.json")
            export_consumer_details(output, output / "consumer/v1/details")
            export_consumer_v2(output, output / "consumer/v2")
            self.assertEqual(validate_public_outputs(root, SCHEMA), 2)
            projected = load_json(output / "consumer/v1/latest.json")
            self.assertEqual(projected["user_view"], current["user_view"])
            self.assertNotIn("themes", projected)
            projected["source_identity"]["generation_id"] = "b" * 64
            atomic_write_json(output / "consumer/v1/latest.json", projected)
            with self.assertRaisesRegex(ContractError, "generation ID mismatch"):
                validate_public_outputs(root, SCHEMA)


class TransactionalPublicationTests(unittest.TestCase):
    def test_publication_1_1_writes_new_identity_and_reads_1_0(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            value = generation("2026-07-10", "publication-version")
            publish_generation(output, value, history_item(value), {"index_version": "1.0", "records": []})
            current = load_current_generation(output)
            self.assertEqual(current[0]["publication_contract_version"], "1.1")
            self.assertEqual(current[2]["publication_contract_version"], "1.1")

            manifest_path = current[1] / "manifest.json"
            manifest = load_json(manifest_path)
            manifest["publication_contract_version"] = "1.0"
            atomic_write_json(manifest_path, manifest)
            pointer = load_json(output / "current.json")
            pointer["publication_contract_version"] = "1.0"
            pointer["manifest_sha256"] = stable_hash(manifest)
            atomic_write_json(output / "current.json", pointer)
            self.assertEqual(load_current_generation(output)[0]["publication_contract_version"], "1.0")

            pointer["publication_contract_version"] = "1.1"
            atomic_write_json(output / "current.json", pointer)
            with self.assertRaisesRegex(ContractError, "contract version mismatch"):
                load_current_generation(output)

    def test_all_seven_failure_points_preserve_current_and_retry(self):
        index = {"index_version": "1.0", "records": []}
        for point in FAILURE_POINTS:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                old = generation("2026-07-10", "old-generation")
                new = generation("2026-07-17", f"new-{point}")
                old_pointer = publish_generation(output, old, history_item(old), index)

                def fail(step):
                    if step == point:
                        raise OSError(f"injected at {step}")

                with self.assertRaisesRegex(OSError, point):
                    publish_generation(output, new, history_item(new), index, fail)
                current = load_current_generation(output)
                self.assertEqual(current[0], old_pointer)
                self.assertEqual([row["data_date"] for row in committed_history(output)], ["2026-07-10"])
                self.assertEqual(current[5]["records"], index["records"])
                self.assertEqual(current[5]["publication"]["run_id"], old["meta"]["run_id"])
                new_pointer = publish_generation(output, new, history_item(new), index)
                self.assertEqual(load_current_generation(output)[0], new_pointer)
                self.assertEqual([row["data_date"] for row in committed_history(output)], ["2026-07-10", "2026-07-17"])

    def test_same_run_is_idempotent_and_does_not_duplicate_history(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            value = generation("2026-07-10", "idempotent")
            index = {"index_version": "1.0", "records": []}
            first = publish_generation(output, value, history_item(value), index)
            second = publish_generation(output, value, history_item(value), index)
            self.assertEqual(first, second)
            self.assertEqual(len(committed_history(output)), 1)

    def test_same_date_different_analysis_creates_an_explicit_new_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            index = {"index_version": "1.0", "records": []}
            first = generation("2026-07-10", "first")
            second = generation("2026-07-10", "second")
            publish_generation(output, first, history_item(first), index)
            second_pointer = publish_generation(output, second, history_item(second), index)
            self.assertNotEqual(second_pointer["analysis_id"], first["meta"]["run_id"])
            self.assertEqual(load_current_generation(output)[3], second)

    def test_publication_lock_rejects_concurrent_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir()
            (output / ".publish.lock").write_text("held", encoding="utf-8")
            value = generation("2026-07-10", "locked")
            with self.assertRaisesRegex(ContractError, "in progress"):
                publish_generation(output, value, history_item(value), {"index_version": "1.0", "records": []})


if __name__ == "__main__":
    unittest.main()
