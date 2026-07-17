import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rotation.consumer import (
    CONSUMER_CANONICAL_SIZE_LIMIT,
    CONSUMER_FILE_SIZE_LIMIT,
    CONSUMER_SCHEMA,
    DETAILS_CANONICAL_SIZE_LIMIT,
    DETAILS_FILE_SIZE_LIMIT,
    DETAILS_SCHEMA,
    build_consumer_details,
    build_consumer_snapshot,
    validate_consumer_detail,
    validate_consumer_snapshot,
)
from rotation.consumer_compat import acquire_consumer, detail_matches_consumer
from rotation.provenance import atomic_write_json, canonical_bytes
from rotation.publication import (
    classify_publication_start_state,
    load_current_generation,
    publish_generation,
    validate_current_publication_inventory,
)
from rotation.validation import ContractError, load_json, validate_schema
from scripts.export_consumer_details import export_consumer_details
from scripts.export_consumer_projection import export_consumer_projection
from scripts.export_current_latest import export_current
from scripts.generate_weekly import history_item
from scripts.validate_repository import validate_public_outputs
from tests.test_publication_contract import generation


ROOT = Path(__file__).resolve().parents[1]
LATEST_SCHEMA = load_json(ROOT / "schemas/rotation_snapshot.schema.json")


def publish_and_export(output: Path, latest: dict) -> None:
    publish_generation(output, latest, history_item(latest), {"index_version": "1.0", "records": []})
    export_current(output, output / "consumer/latest.json")
    export_consumer_projection(output, output / "consumer/v1/latest.json")
    export_consumer_details(output, output / "consumer/v1/details")


class ConsumerProjectionTests(unittest.TestCase):
    def setUp(self):
        self.latest = generation("2026-07-17", "consumer-projection")
        self.consumer = build_consumer_snapshot(self.latest)
        self.details = build_consumer_details(self.latest)

    def test_old_consumer_remains_exact_full_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            publish_and_export(output, self.latest)
            legacy = load_json(output / "consumer/latest.json")
            self.assertEqual(canonical_bytes(legacy), canonical_bytes(self.latest))
            self.assertIn("themes", legacy)
            self.assertNotIn("consumer_contract_version", legacy)

    def test_live_migration_shape_accepts_old_full_only_then_requires_complete_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            atomic_write_json(output / "judgments/index.json", {"index_version": "1.0", "records": []})
            publish_generation(output, self.latest, history_item(self.latest), {"index_version": "1.0", "records": []})
            export_current(output, output / "consumer/latest.json")
            self.assertEqual(classify_publication_start_state(output).kind, "current")
            validate_current_publication_inventory(output, require_consumer=False)
            with self.assertRaises(ContractError):
                validate_current_publication_inventory(output, require_consumer=True)
            export_consumer_projection(output, output / "consumer/v1/latest.json")
            export_consumer_details(output, output / "consumer/v1/details")
            validate_current_publication_inventory(output, require_consumer=True)

    def test_legacy_generation_requires_full_only_and_rejects_v1(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            index = {"index_version": "1.0", "records": []}
            atomic_write_json(output / "judgments/index.json", index)
            legacy = load_json(ROOT / "tests/fixtures/latest_normal.json")
            publish_generation(output, legacy, history_item(legacy), index)
            export_current(output, output / "consumer/latest.json")
            validate_current_publication_inventory(output, require_consumer=True)
            with self.assertRaisesRegex(ContractError, "data schema 1.2"):
                export_consumer_projection(output, output / "consumer/v1/latest.json")
            (output / "consumer/v1").mkdir(parents=True)
            with self.assertRaises(ContractError):
                validate_current_publication_inventory(output, require_consumer=True)

    def test_lightweight_schema_size_and_exact_user_view(self):
        validate_schema(self.consumer, CONSUMER_SCHEMA, "consumer fixture")
        self.assertLessEqual(len(canonical_bytes(self.consumer)), CONSUMER_CANONICAL_SIZE_LIMIT)
        self.assertEqual(canonical_bytes(self.consumer["user_view"]), canonical_bytes(self.latest["user_view"]))
        excluded = {
            "not_implemented", "market_regime", "style_factor", "sectors", "industries",
            "themes", "theme_shortlist", "dynamic_discovery", "candidate_buckets",
            "company_candidates", "history_weekly", "previous_judgments",
        }
        self.assertTrue(excluded.isdisjoint(self.consumer))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            publish_and_export(output, self.latest)
            self.assertLessEqual((output / "consumer/v1/latest.json").stat().st_size, CONSUMER_FILE_SIZE_LIMIT)

    def test_all_six_details_schema_identity_size_and_no_internal_lens_source(self):
        self.assertEqual([item["phase"] for item in self.details], list(range(1, 7)))
        for phase, detail in enumerate(self.details, 1):
            validate_schema(detail, DETAILS_SCHEMA, f"phase {phase}")
            validate_consumer_detail(detail, self.latest, phase=phase)
            self.assertLessEqual(len(canonical_bytes(detail)), DETAILS_CANONICAL_SIZE_LIMIT)
            self.assertEqual(detail["source_identity"], self.consumer["source_identity"])
            for field in ("run_id", "source_commit", "source_sha256", "data_date"):
                self.assertEqual(detail["meta"][field], self.consumer["meta"][field])
            self.assertNotIn("research_lens_source", json.dumps(detail, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            publish_and_export(output, self.latest)
            for phase in range(1, 7):
                self.assertLessEqual((output / f"consumer/v1/details/phase-{phase}.json").stat().st_size, DETAILS_FILE_SIZE_LIMIT)

    def test_phase_details_have_specific_human_readable_content(self):
        required = {
            1: {"market_environment", "representative_indicators", "global_quality"},
            2: {"comparisons", "moving_average_state", "interpretation_notes"},
            3: {"top_sectors", "bottom_sectors", "dynamic_selected", "dynamic_excluded"},
            4: {"buckets"},
            5: {"companies", "caution"},
            6: {"market_basis", "bucket_counts", "change_conditions", "not_implemented"},
        }
        for phase, detail in enumerate(self.details, 1):
            self.assertTrue(required[phase].issubset(detail["detail_view"]))
        phase4 = json.dumps(self.details[3], ensure_ascii=False)
        self.assertNotIn('"P1"', phase4)
        self.assertIn("今調べる候補", phase4)

    def test_projection_and_details_are_byte_deterministic(self):
        self.assertEqual(canonical_bytes(self.consumer), canonical_bytes(build_consumer_snapshot(copy.deepcopy(self.latest))))
        self.assertEqual(
            [canonical_bytes(item) for item in self.details],
            [canonical_bytes(item) for item in build_consumer_details(copy.deepcopy(self.latest))],
        )

    def assert_consumer_rejected(self, mutation, message):
        value = copy.deepcopy(self.consumer)
        mutation(value)
        with self.assertRaisesRegex(ContractError, message):
            validate_consumer_snapshot(value, self.latest)

    def test_consumer_identity_status_and_phase_contract_rejections(self):
        cases = (
            (lambda v: v["source_identity"].update(generation_id="b" * 64), "generation ID mismatch"),
            (lambda v: v["source_identity"].update(analysis_id="b" * 64), "analysis ID mismatch"),
            (lambda v: v["meta"].update(run_id="b" * 64), "run ID mismatch"),
            (lambda v: v["meta"].update(source_sha256="b" * 64), "SHA-256 mismatch"),
            (lambda v: v["meta"].update(status="failed", failure_reason="diagnostic"), "status=success"),
            (lambda v: v["meta"]["global_quality"].update(critical_missing=["SPY"]), "critical_missing"),
            (lambda v: v.update(consumer_contract_version="9.9"), "unsupported consumer contract version"),
            (lambda v: v["user_view"]["phases"].pop(), "too short"),
        )
        for mutation, message in cases:
            with self.subTest(message=message):
                self.assert_consumer_rejected(mutation, message)

    def test_detail_phase_and_all_identity_mismatches_are_rejected(self):
        mutations = (
            (lambda v: v.update(phase=2), "phase mismatch"),
            (lambda v: v["source_identity"].update(analysis_id="b" * 64), "source identity mismatch"),
            (lambda v: v["source_identity"].update(generation_id="b" * 64), "source identity mismatch"),
            (lambda v: v["meta"].update(run_id="b" * 64), "meta mismatch"),
            (lambda v: v["meta"].update(source_commit="b" * 40), "meta mismatch"),
            (lambda v: v["meta"].update(source_sha256="b" * 64), "meta mismatch"),
            (lambda v: v["meta"].update(data_date="2026-01-01"), "meta mismatch"),
        )
        for mutation, message in mutations:
            with self.subTest(message=message):
                value = copy.deepcopy(self.details[0])
                mutation(value)
                with self.assertRaisesRegex(ContractError, message):
                    validate_consumer_detail(value, self.latest, phase=1)

    def test_compatibility_primary_404_fallback_and_fail_closed(self):
        primary = json.dumps(self.consumer, ensure_ascii=False)
        legacy = json.dumps(self.latest, ensure_ascii=False)
        mode, value = acquire_consumer(200, primary)
        self.assertEqual((mode, value["user_view"]), ("lightweight", self.latest["user_view"]))
        mode, value = acquire_consumer(404, "", legacy_status=200, legacy_body=legacy)
        self.assertEqual((mode, value["user_view"]), ("legacy_full_snapshot", self.latest["user_view"]))
        for broken in (primary[:-1], "{}"):
            with self.subTest(broken=broken[-10:]):
                with self.assertRaises(ContractError):
                    acquire_consumer(200, broken, legacy_status=200, legacy_body=legacy)
        bad_identity = copy.deepcopy(self.consumer)
        bad_identity["source_identity"]["analysis_id"] = "b" * 64
        with self.assertRaisesRegex(ContractError, "identity mismatch"):
            acquire_consumer(200, json.dumps(bad_identity), legacy_status=200, legacy_body=legacy)
        invalid_cases = []
        bad_contract = copy.deepcopy(self.consumer); bad_contract["consumer_contract_version"] = "9.9"; invalid_cases.append(bad_contract)
        bad_status = copy.deepcopy(self.consumer); bad_status["meta"].update(status="failed", failure_reason="failed"); invalid_cases.append(bad_status)
        bad_missing = copy.deepcopy(self.consumer); bad_missing["meta"]["global_quality"]["critical_missing"] = ["SPY"]; invalid_cases.append(bad_missing)
        bad_phases = copy.deepcopy(self.consumer); bad_phases["user_view"]["phases"].pop(); invalid_cases.append(bad_phases)
        bad_validity = copy.deepcopy(self.consumer); bad_validity["meta"]["valid_until"] = bad_validity["meta"]["generated_at"]; invalid_cases.append(bad_validity)
        for invalid in invalid_cases:
            with self.assertRaises(ContractError):
                acquire_consumer(200, json.dumps(invalid), legacy_status=200, legacy_body=legacy)
        with self.assertRaisesRegex(ContractError, "hard_stop_after"):
            acquire_consumer(
                200, primary, legacy_status=200, legacy_body=legacy,
                now=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
            )
        with self.assertRaisesRegex(ContractError, "fallback is forbidden"):
            acquire_consumer(500, "", legacy_status=200, legacy_body=legacy)

    def test_detail_failure_or_mismatch_does_not_change_normal_result(self):
        normal = copy.deepcopy(self.consumer["user_view"])
        self.assertTrue(detail_matches_consumer(self.details[2], self.consumer, 3))
        bad = copy.deepcopy(self.details[2]); bad["meta"]["source_sha256"] = "b" * 64
        self.assertFalse(detail_matches_consumer(bad, self.consumer, 3))
        self.assertEqual(self.consumer["user_view"], normal)

    def test_inventory_is_exact_and_rejects_missing_duplicate_unknown_and_symlink(self):
        mutations = ("missing", "duplicate", "unknown", "phase")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                publish_and_export(output, self.latest)
                details = output / "consumer/v1/details"
                if mutation == "missing":
                    (details / "phase-6.json").unlink()
                elif mutation == "duplicate":
                    atomic_write_json(details / "phase-7.json", self.details[5])
                elif mutation == "unknown":
                    (details / "notes.txt").write_text("unexpected", encoding="utf-8")
                elif mutation == "phase":
                    value = load_json(details / "phase-2.json"); value["phase"] = 1
                    atomic_write_json(details / "phase-2.json", value)
                with self.assertRaises(ContractError):
                    validate_current_publication_inventory(output, require_consumer=True)

    def test_inventory_rejects_detail_symlink_without_platform_privilege(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            publish_and_export(output, self.latest)
            target = output / "consumer/v1/details/phase-1.json"
            real_is_symlink = Path.is_symlink

            def report_target_as_symlink(path):
                return path == target or real_is_symlink(path)

            with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=report_target_as_symlink):
                with self.assertRaises(ContractError):
                    validate_current_publication_inventory(output, require_consumer=True)

    def test_repository_validator_regenerates_complete_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "output"
            publish_and_export(output, self.latest)
            self.assertEqual(validate_public_outputs(root, LATEST_SCHEMA), 2)
            value = load_json(output / "consumer/v1/details/phase-4.json")
            value["detail_view"]["title"] += "改ざん"
            atomic_write_json(output / "consumer/v1/details/phase-4.json", value)
            with self.assertRaisesRegex(ContractError, "deterministic authoritative projection"):
                validate_public_outputs(root, LATEST_SCHEMA)


if __name__ == "__main__":
    unittest.main()
