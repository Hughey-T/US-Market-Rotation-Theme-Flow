import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rotation.classification import classify_theme
from rotation.metrics import aggregate_theme
from rotation.provenance import snapshot_source_hash
from rotation.publication import publish_generation
from rotation.regime import classify_market_regime
from rotation.shortlist import apply_shortlist
from rotation.thresholds import equal_weight_led, market_cap_led, weighting_divergence
from rotation.validation import (
    ContractError,
    load_json,
    validate_judgment_semantics,
    validate_latest_semantics,
    validate_schema,
)
from scripts import generate_weekly


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
LATEST_SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")


class SemanticValidatorTests(unittest.TestCase):
    def test_all_fixture_and_sample_regimes_are_canonical(self):
        paths = sorted(FIXTURES.glob("latest_*.json")) + [ROOT / "docs" / "sample_latest.json"]
        for path in paths:
            with self.subTest(path=path.name):
                latest = load_json(path)
                self.assertEqual(
                    latest["market_regime"],
                    classify_market_regime(latest["market_regime"]["inputs"]),
                )
                validate_schema(latest, LATEST_SCHEMA, path.name)
                validate_latest_semantics(latest, verify_source_hash=True)

    def test_every_saved_regime_field_is_semantically_enforced(self):
        def mutate(path, operation):
            latest = load_json(FIXTURES / "latest_normal.json")
            operation(latest["market_regime"])
            latest["meta"]["source_sha256"] = snapshot_source_hash(latest)
            with self.subTest(path=path):
                with self.assertRaisesRegex(ContractError, "market_regime"):
                    validate_latest_semantics(latest, verify_source_hash=True)

        def replace_secondary(regime):
            regime["classification"]["secondary_regimes"][1] = "defensive_shift"

        def delete_classification_contrary(regime):
            inputs = dict(regime["inputs"], vix_change_4w=3)
            regime.clear()
            regime.update(classify_market_regime(inputs))
            regime["classification"]["contrary_evidence"].pop()

        def delete_candidate_contrary(regime):
            inputs = dict(regime["inputs"], rsp_minus_spy_4w_trend_3w="improving")
            regime.clear()
            regime.update(classify_market_regime(inputs))
            regime["candidate_flags"]["large_growth_concentration"]["contrary_evidence"].pop()

        cases = {
            "classification.primary_regime": lambda regime: regime["classification"].update(primary_regime="directionless"),
            "classification.secondary_regimes.delete": lambda regime: regime["classification"]["secondary_regimes"].pop(),
            "classification.secondary_regimes.add": lambda regime: regime["classification"]["secondary_regimes"].append("defensive_shift"),
            "classification.secondary_regimes.change": replace_secondary,
            "classification.confidence": lambda regime: regime["classification"].update(confidence="high"),
            "classification.matched_conditions.delete": lambda regime: regime["classification"]["matched_conditions"].pop(),
            "classification.matched_conditions.add": lambda regime: regime["classification"]["matched_conditions"].append("R_FAKE"),
            "classification.contrary_evidence.add": lambda regime: regime["classification"]["contrary_evidence"].append("R_FAKE"),
            "classification.contrary_evidence.delete": delete_classification_contrary,
            "candidate_flags.delete": lambda regime: regime["candidate_flags"].pop("defensive_shift"),
            "candidate_flags.add": lambda regime: regime["candidate_flags"].update(fake_candidate=copy.deepcopy(regime["candidate_flags"]["defensive_shift"])),
            "candidate_flags.boolean": lambda regime: regime["candidate_flags"]["broad_risk_on"].update(eligible=False),
            "candidate_flags.matched_conditions": lambda regime: regime["candidate_flags"]["broad_risk_on"]["matched_conditions"].pop(),
            "candidate_flags.contrary_evidence": lambda regime: regime["candidate_flags"]["large_growth_concentration"]["contrary_evidence"].append("R_FAKE"),
            "candidate_flags.contrary_evidence.delete": delete_candidate_contrary,
            "inputs.trend": lambda regime: regime["inputs"].update(rsp_minus_spy_4w_trend_3w="improving"),
        }
        for path, operation in cases.items():
            mutate(path, operation)

    def test_candidate_unmatched_conditions_are_semantically_enforced_before_publication(self):
        candidate_id = "large_growth_concentration"

        def replace_condition(values):
            values[0] = "R_FAKE"

        operations = {
            "delete": lambda values: values.pop(),
            "add": lambda values: values.append("R_FAKE"),
            "replace": replace_condition,
            "reorder": lambda values: values.reverse(),
        }
        error_path = rf"market_regime\.candidate_flags\.{candidate_id}\.unmatched_conditions"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, operation in operations.items():
                with self.subTest(operation=label):
                    latest = load_json(FIXTURES / "latest_normal.json")
                    unmatched = latest["market_regime"]["candidate_flags"][candidate_id]["unmatched_conditions"]
                    self.assertGreaterEqual(len(unmatched), 2)
                    operation(unmatched)
                    latest["meta"]["source_sha256"] = snapshot_source_hash(latest)
                    validate_schema(latest, LATEST_SCHEMA, f"unmatched conditions {label}")
                    with self.assertRaisesRegex(ContractError, error_path):
                        validate_latest_semantics(latest, verify_source_hash=True)
                    output = root / label / "output"
                    with self.assertRaisesRegex(ContractError, error_path):
                        publish_generation(
                            output,
                            latest,
                            generate_weekly.history_item(latest),
                            {"index_version": "1.0", "records": []},
                        )
                    self.assertFalse(output.exists())

    def test_regime_schema_closes_candidate_secondary_and_trend_shapes(self):
        cases = []

        unknown_secondary = load_json(FIXTURES / "latest_normal.json")
        unknown_secondary["market_regime"]["classification"]["secondary_regimes"] = ["unknown"]
        cases.append(("unknown secondary", unknown_secondary))

        duplicate_secondary = load_json(FIXTURES / "latest_normal.json")
        duplicate_secondary["market_regime"]["classification"]["secondary_regimes"] = ["broad_risk_on", "broad_risk_on"]
        cases.append(("duplicate secondary", duplicate_secondary))

        unknown_candidate = load_json(FIXTURES / "latest_normal.json")
        unknown_candidate["market_regime"]["candidate_flags"]["unknown"] = copy.deepcopy(unknown_candidate["market_regime"]["candidate_flags"]["broad_risk_on"])
        cases.append(("unknown candidate", unknown_candidate))

        missing_candidate = load_json(FIXTURES / "latest_normal.json")
        missing_candidate["market_regime"]["candidate_flags"].pop("broad_risk_on")
        cases.append(("missing candidate", missing_candidate))

        wrong_candidate = load_json(FIXTURES / "latest_normal.json")
        wrong_candidate["market_regime"]["candidate_flags"]["broad_risk_on"] = True
        cases.append(("wrong candidate value", wrong_candidate))

        for field in ("rsp_minus_spy_4w_trend_3w", "iwm_minus_spy_4w_trend_3w", "dbc_rel_spy_4w_trend_3w"):
            missing_trend = load_json(FIXTURES / "latest_normal.json")
            missing_trend["market_regime"]["inputs"].pop(field)
            cases.append((f"missing {field}", missing_trend))

        invalid_trend = load_json(FIXTURES / "latest_normal.json")
        invalid_trend["market_regime"]["inputs"]["rsp_minus_spy_4w_trend_3w"] = "sideways"
        cases.append(("invalid trend", invalid_trend))

        for label, latest in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ContractError, "JSON Schema"):
                    validate_schema(latest, LATEST_SCHEMA, label)

    def test_regime_object_key_order_is_semantically_irrelevant(self):
        latest = load_json(FIXTURES / "latest_normal.json")
        expected_hash = latest["meta"]["source_sha256"]
        regime = latest["market_regime"]
        regime["inputs"] = dict(reversed(list(regime["inputs"].items())))
        regime["candidate_flags"] = dict(reversed(list(regime["candidate_flags"].items())))
        latest["market_regime"] = dict(reversed(list(regime.items())))
        self.assertEqual(snapshot_source_hash(latest), expected_hash)
        validate_schema(latest, LATEST_SCHEMA, "reordered regime objects")
        validate_latest_semantics(latest, verify_source_hash=True)

    def test_regime_primary_cannot_be_repeated_as_secondary(self):
        latest = load_json(FIXTURES / "latest_normal.json")
        latest["market_regime"]["classification"].update(
            primary_regime="broad_risk_on",
            secondary_regimes=["broad_risk_on", "cyclical_recovery_expectation"],
        )
        latest["meta"]["source_sha256"] = snapshot_source_hash(latest)
        validate_schema(latest, LATEST_SCHEMA, "primary repeated as secondary")
        with self.assertRaisesRegex(ContractError, "market_regime.classification"):
            validate_latest_semantics(latest, verify_source_hash=True)

    def test_T53_success_rejects_critical_missing(self):
        latest = load_json(FIXTURES / "latest_normal.json")
        latest["meta"]["global_quality"]["critical_missing"] = ["SPY"]
        with self.assertRaisesRegex(ContractError, "critical_missing"):
            validate_latest_semantics(latest)

    def test_T54_status_and_failure_reason_are_consistent(self):
        failed = load_json(FIXTURES / "latest_normal.json")
        failed["meta"].update(status="failed", failure_reason=None)
        with self.assertRaisesRegex(ContractError, "non-empty failure_reason"):
            validate_latest_semantics(failed)
        success = load_json(FIXTURES / "latest_normal.json")
        success["meta"]["failure_reason"] = "unexpected"
        with self.assertRaisesRegex(ContractError, "successful artifact has failure_reason"):
            validate_latest_semantics(success)

    def test_T55_judgment_internal_rule_and_rank_mismatches_fail(self):
        source = load_json(FIXTURES / "latest_normal.json")
        cases = []
        wrong_priority = load_json(FIXTURES / "judgment_record.json")
        wrong_priority["theme_judgments"][0]["research_priority_rule"] = "P5"
        cases.append(wrong_priority)
        wrong_timing = load_json(FIXTURES / "judgment_record.json")
        wrong_timing["theme_judgments"][0].update(timing_rule="T2", timing_status="favorable")
        cases.append(wrong_timing)
        wrong_rank = load_json(FIXTURES / "judgment_record.json")
        wrong_rank["theme_judgments"][0].update(selected_for_deep_dive=False, shortlist_rank=1)
        cases.append(wrong_rank)
        for record in cases:
            with self.subTest(record=record["theme_judgments"][0]):
                with self.assertRaises(ContractError):
                    validate_judgment_semantics(record, source)

    def test_T56_judgment_source_identity_and_theme_copy_mismatch_fail(self):
        source = load_json(FIXTURES / "latest_normal.json")
        wrong_hash = load_json(FIXTURES / "judgment_record.json")
        wrong_hash["source_sha256"] = "b" * 64
        with self.assertRaisesRegex(ContractError, "source_sha256"):
            validate_judgment_semantics(wrong_hash, source)
        changed_theme = load_json(FIXTURES / "judgment_record.json")
        changed_theme["theme_judgments"][0]["direction"] = "flat"
        with self.assertRaisesRegex(ContractError, "direction does not match"):
            validate_judgment_semantics(changed_theme, source)
        with self.assertRaisesRegex(ContractError, "unavailable"):
            validate_judgment_semantics(load_json(FIXTURES / "judgment_record.json"), None)

    def test_T57_judgment_duplicate_rank_and_ineligible_selection_fail(self):
        source = load_json(FIXTURES / "latest_normal.json")
        duplicate = load_json(FIXTURES / "judgment_record.json")
        duplicate["theme_judgments"].append(copy.deepcopy(duplicate["theme_judgments"][0]))
        with self.assertRaisesRegex(ContractError, "duplicated"):
            validate_judgment_semantics(duplicate, source)
        ineligible = load_json(FIXTURES / "judgment_record.json")
        theme = ineligible["theme_judgments"][0]
        theme.update(research_priority="low_priority", research_priority_rule="P5")
        with self.assertRaisesRegex(ContractError, "shortlist-ineligible"):
            validate_judgment_semantics(ineligible, source)

    def test_T58_canonical_shortlist_reason_codes_match_all_fixtures(self):
        for path in sorted(FIXTURES.glob("latest_*.json")):
            latest = load_json(path)
            theme_id, theme = next(iter(latest["themes"].items()))
            recomputed, _ = apply_shortlist({theme_id: theme})
            self.assertEqual(recomputed[theme_id]["shortlist_reason_codes"], theme["shortlist_reason_codes"], path.name)

    def test_T59_shortlist_reason_codes_are_input_order_independent(self):
        base = load_json(FIXTURES / "latest_normal.json")["themes"]["fixture_theme"]
        themes = {theme_id: dict(copy.deepcopy(base), theme_id=theme_id) for theme_id in ("z", "a", "m", "b", "q", "c")}
        first, _ = apply_shortlist(themes)
        second, _ = apply_shortlist(dict(reversed(list(themes.items()))))
        self.assertEqual({key: value["shortlist_reason_codes"] for key, value in first.items()}, {key: value["shortlist_reason_codes"] for key, value in second.items()})

    def test_T60_diffusion_flag_is_tristate(self):
        base = load_json(FIXTURES / "latest_normal.json")["themes"]["fixture_theme"]
        metrics = copy.deepcopy(base["metrics"])
        metrics.update(equal_weight_rel_spy_4w=-0.01, pct_above_50dma=None)
        flags, _ = classify_theme(metrics, base["trends"], base["quality"], base["by_role"])
        self.assertIsNone(flags["phase_diffusion"])

    def test_T61_overheat_flag_is_tristate(self):
        base = load_json(FIXTURES / "latest_normal.json")["themes"]["fixture_theme"]
        metrics = copy.deepcopy(base["metrics"])
        metrics.update(
            equal_weight_rel_spy_13w=None,
            pct_within_5pct_52w_high=0.33,
            volume_ratio_20d_60d=1.30,
        )
        flags, _ = classify_theme(metrics, base["trends"], base["quality"], base["by_role"])
        self.assertIsNone(flags["phase_price_overheat"])

    def test_T62_outflow_and_concentration_flags_are_tristate(self):
        base = load_json(FIXTURES / "latest_normal.json")["themes"]["fixture_theme"]
        metrics = copy.deepcopy(base["metrics"])
        metrics.update(
            equal_weight_rel_spy_4w=None,
            equal_weight_return_4w=0.01,
            volume_ratio_20d_60d=1.00,
            top1_contribution_ratio=None,
            top3_contribution_ratio=0.90,
        )
        trends = dict(
            base["trends"],
            rel_spy_4w_trend_3w="worsening",
            advance_breadth_trend_3w="worsening",
            above_50dma_breadth_trend_3w="worsening",
        )
        flags, _ = classify_theme(metrics, trends, base["quality"], base["by_role"])
        self.assertIsNone(flags["direction_outflow_signal"])
        self.assertIsNone(flags["broad_concentration_pass"])

    def test_T63_equal_weight_led_boundary_and_null(self):
        self.assertTrue(equal_weight_led(-0.03))
        self.assertTrue(equal_weight_led(-0.0300001))
        self.assertFalse(equal_weight_led(-0.0299999))
        self.assertIsNone(equal_weight_led(None))
        self.assertTrue(market_cap_led(0.03))
        self.assertEqual(weighting_divergence(0.26, 0.29), -0.03)
        rows = [
            {"return_1w": 0.0, "return_4w": 0.23, "return_13w": 0.0, "market_cap": 3.0},
            {"return_1w": 0.0, "return_4w": 0.35, "return_13w": 0.0, "market_cap": 1.0},
        ]
        metrics, _ = aggregate_theme(rows, {"1w": 0.0, "4w": 0.0, "13w": 0.0})
        self.assertEqual(metrics["weighting_divergence_4w"], -0.03)
        self.assertTrue(metrics["equal_weight_led"])
        round_tripped = json.loads(json.dumps(metrics))
        self.assertTrue(equal_weight_led(round_tripped["weighting_divergence_4w"]))
        for row in rows:
            row["market_cap"] = None
        metrics, _ = aggregate_theme(rows, {"1w": 0.0, "4w": 0.0, "13w": 0.0})
        self.assertIsNone(metrics["equal_weight_led"])

    def test_T64_failed_publish_preserves_existing_latest_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            latest_path = output / "latest.json"
            latest_path.write_bytes(b'{"status":"success"}\n')
            before = hashlib.sha256(latest_path.read_bytes()).hexdigest()
            failed = load_json(FIXTURES / "latest_normal.json")
            failed["meta"].update(status="failed", failure_reason="generation failed")
            failed["meta"]["source_sha256"] = snapshot_source_hash(failed)
            with mock.patch.object(generate_weekly, "ROOT", root), mock.patch.object(generate_weekly, "OUTPUT", output), mock.patch.object(generate_weekly, "HISTORY", output / "history"), mock.patch.object(generate_weekly, "JUDGMENTS", output / "judgments"):
                with self.assertRaisesRegex(ContractError, "status=success"):
                    generate_weekly.publish(failed, {"index_version": "1.0", "records": []})
            self.assertEqual(hashlib.sha256(latest_path.read_bytes()).hexdigest(), before)

    def test_T65_withdrawal_conditions_are_unique_resolvable_and_type_safe(self):
        source = load_json(FIXTURES / "latest_normal.json")
        schema = load_json(ROOT / "schemas" / "judgment_record.schema.json")

        duplicate = load_json(FIXTURES / "judgment_record.json")
        duplicate["theme_judgments"][0]["withdrawal_conditions"][1]["condition_id"] = duplicate["theme_judgments"][0]["withdrawal_conditions"][0]["condition_id"]
        with self.assertRaisesRegex(ContractError, "duplicate withdrawal condition_id"):
            validate_judgment_semantics(duplicate, source)

        missing = load_json(FIXTURES / "judgment_record.json")
        missing["theme_judgments"][0]["withdrawal_conditions"][0]["field_path"] = "themes.fixture_theme.metrics.not_a_field"
        with self.assertRaisesRegex(ContractError, "absent from source latest"):
            validate_judgment_semantics(missing, source)

        wrong_type = load_json(FIXTURES / "judgment_record.json")
        wrong_type["theme_judgments"][0]["withdrawal_conditions"][0].update(
            field_path="themes.fixture_theme.classifications.phase", operator="==", value=1,
        )
        with self.assertRaisesRegex(ContractError, "value type does not match"):
            validate_judgment_semantics(wrong_type, source)

        null_numeric_source = copy.deepcopy(source)
        null_numeric_source["themes"]["fixture_theme"]["metrics"]["market_cap_weight_rel_spy_4w"] = None
        null_numeric_source["meta"]["source_sha256"] = snapshot_source_hash(null_numeric_source)
        null_wrong_type = load_json(FIXTURES / "judgment_record.json")
        null_wrong_type["source_sha256"] = null_numeric_source["meta"]["source_sha256"]
        null_wrong_type["theme_judgments"][0]["key_metrics"]["market_cap_weight_rel_spy_4w"] = None
        null_wrong_type["theme_judgments"][0]["withdrawal_conditions"][0].update(
            field_path="themes.fixture_theme.metrics.market_cap_weight_rel_spy_4w",
            operator="==",
            value="not-a-number",
        )
        with self.assertRaisesRegex(ContractError, "source field schema"):
            validate_judgment_semantics(null_wrong_type, null_numeric_source)

        ordered_string = load_json(FIXTURES / "judgment_record.json")
        ordered_string["theme_judgments"][0]["withdrawal_conditions"][0]["value"] = "zero"
        with self.assertRaisesRegex(ContractError, "JSON Schema"):
            validate_schema(ordered_string, schema, "ordered string withdrawal")


if __name__ == "__main__":
    unittest.main()
