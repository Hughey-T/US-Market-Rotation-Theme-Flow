import copy
import tempfile
import unittest
from pathlib import Path

from rotation.consumer import (
    CONSUMER_CANONICAL_SIZE_LIMIT,
    CONSUMER_FILE_SIZE_LIMIT,
    CONSUMER_SCHEMA,
    build_consumer_snapshot,
    validate_consumer_snapshot,
)
from rotation.provenance import canonical_bytes
from rotation.publication import load_current_generation, publish_generation
from rotation.validation import ContractError, load_json, validate_schema
from scripts.export_current_latest import export_current
from scripts.generate_weekly import history_item
from scripts.validate_repository import validate_public_outputs
from tests.test_publication_contract import generation


class ConsumerProjectionTests(unittest.TestCase):
    def setUp(self):
        self.latest = generation("2026-07-17", "consumer-projection")
        self.consumer = build_consumer_snapshot(self.latest)

    def test_consumer_schema_and_size_limits(self):
        validate_schema(self.consumer, CONSUMER_SCHEMA, "consumer fixture")
        self.assertLessEqual(len(canonical_bytes(self.consumer)), CONSUMER_CANONICAL_SIZE_LIMIT)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            publish_generation(output, self.latest, history_item(self.latest), {"index_version": "1.0", "records": []})
            destination = output / "consumer/latest.json"
            export_current(output, destination)
            self.assertLessEqual(destination.stat().st_size, CONSUMER_FILE_SIZE_LIMIT)

    def test_user_view_is_an_exact_copy(self):
        self.assertEqual(self.consumer["user_view"], self.latest["user_view"])
        self.assertEqual(canonical_bytes(self.consumer["user_view"]), canonical_bytes(self.latest["user_view"]))

    def test_large_audit_fields_are_excluded(self):
        excluded = {
            "not_implemented", "market_regime", "style_factor", "sectors", "industries",
            "themes", "theme_shortlist", "dynamic_discovery", "candidate_buckets",
            "company_candidates", "history_weekly", "previous_judgments",
        }
        self.assertTrue(excluded.isdisjoint(self.consumer))
        self.assertEqual(set(self.consumer), {"consumer_contract_version", "source_identity", "meta", "user_view"})

    def test_projection_is_byte_deterministic(self):
        self.assertEqual(
            canonical_bytes(build_consumer_snapshot(self.latest)),
            canonical_bytes(build_consumer_snapshot(copy.deepcopy(self.latest))),
        )

    def assert_rejected(self, mutation, message):
        value = copy.deepcopy(self.consumer)
        mutation(value)
        with self.assertRaisesRegex(ContractError, message):
            validate_consumer_snapshot(value, self.latest)

    def test_source_generation_id_mismatch_is_rejected(self):
        self.assert_rejected(lambda value: value["source_identity"].update(generation_id="b" * 64), "generation ID mismatch")

    def test_analysis_id_mismatch_is_rejected(self):
        self.assert_rejected(lambda value: value["source_identity"].update(analysis_id="b" * 64), "analysis ID mismatch")

    def test_run_id_mismatch_is_rejected(self):
        self.assert_rejected(lambda value: value["meta"].update(run_id="b" * 64), "run ID mismatch")

    def test_source_sha256_mismatch_is_rejected(self):
        self.assert_rejected(lambda value: value["meta"].update(source_sha256="b" * 64), "SHA-256 mismatch")

    def test_failed_status_is_rejected(self):
        self.assert_rejected(lambda value: value["meta"].update(status="failed", failure_reason="diagnostic"), "status=success")

    def test_critical_missing_is_rejected(self):
        self.assert_rejected(lambda value: value["meta"]["global_quality"].update(critical_missing=["SPY"]), "critical_missing")

    def test_unsupported_contract_version_is_rejected(self):
        self.assert_rejected(lambda value: value.update(consumer_contract_version="9.9"), "unsupported consumer contract version")

    def test_phase_count_is_exactly_six(self):
        self.assert_rejected(lambda value: value["user_view"]["phases"].pop(), "too short")

    def test_phase_required_display_field_is_enforced(self):
        self.assert_rejected(lambda value: value["user_view"]["phases"][0].pop("next_checks"), "next_checks")

    def test_pointer_and_manifest_identity_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            publish_generation(output, self.latest, history_item(self.latest), {"index_version": "1.0", "records": []})
            current = load_current_generation(output)
            bad_pointer = copy.deepcopy(current[0]); bad_pointer["generation_id"] = "b" * 64
            with self.assertRaisesRegex(ContractError, "current pointer"):
                validate_consumer_snapshot(self.consumer, self.latest, pointer=bad_pointer, manifest=current[2])
            bad_manifest = copy.deepcopy(current[2]); bad_manifest["analysis_id"] = "b" * 64
            with self.assertRaisesRegex(ContractError, "generation manifest"):
                validate_consumer_snapshot(self.consumer, self.latest, pointer=current[0], manifest=bad_manifest)

    def test_repository_validator_regenerates_and_detects_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            publish_generation(output, self.latest, history_item(self.latest), {"index_version": "1.0", "records": []})
            consumer_path = output / "consumer/latest.json"
            export_current(output, consumer_path)
            self.assertEqual(validate_public_outputs(root, load_json(Path(__file__).resolve().parents[1] / "schemas/rotation_snapshot.schema.json")), 2)
            value = load_json(consumer_path)
            value["user_view"]["phases"][0]["conclusion"] += "改ざん"
            from rotation.provenance import atomic_write_json
            atomic_write_json(consumer_path, value)
            with self.assertRaisesRegex(ContractError, "user_view differs"):
                validate_public_outputs(root, load_json(Path(__file__).resolve().parents[1] / "schemas/rotation_snapshot.schema.json"))

    def test_legacy_full_consumer_is_migrated_to_projection(self):
        from rotation.provenance import atomic_write_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            publish_generation(output, self.latest, history_item(self.latest), {"index_version": "1.0", "records": []})
            consumer_path = output / "consumer/latest.json"
            atomic_write_json(consumer_path, self.latest)
            self.assertEqual(validate_public_outputs(root, load_json(Path(__file__).resolve().parents[1] / "schemas/rotation_snapshot.schema.json")), 2)
            export_current(output, consumer_path)
            migrated = load_json(consumer_path)
            self.assertEqual(migrated["consumer_contract_version"], "1.0")
            self.assertNotIn("themes", migrated)


if __name__ == "__main__":
    unittest.main()
