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


class SemanticValidatorTests(unittest.TestCase):
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

        ordered_string = load_json(FIXTURES / "judgment_record.json")
        ordered_string["theme_judgments"][0]["withdrawal_conditions"][0]["value"] = "zero"
        with self.assertRaisesRegex(ContractError, "JSON Schema"):
            validate_schema(ordered_string, schema, "ordered string withdrawal")


if __name__ == "__main__":
    unittest.main()
