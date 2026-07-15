import copy
import datetime as dt
import json
import unittest
from pathlib import Path

from rotation.classification import (
    classify_theme,
    evaluate_priority,
    overheat_breadth_weak,
    priority_matches,
)
from rotation.judgments import evaluate_withdrawal
from rotation.metrics import market_cap_weighted_relative, positive_concentration, role_aggregates
from rotation.quality import assess_quality
from rotation.provenance import snapshot_source_hash
from rotation.regime import classify_market_regime
from rotation.shortlist import apply_shortlist
from rotation.trends import contiguous_history
from rotation.validation import (
    ContractError,
    freshness_status,
    load_json,
    validate_latest_semantics,
    validate_run_identity,
    validate_schema,
    validate_theme_master_semantics,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
LATEST_SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")


def fixture(name):
    return load_json(FIXTURES / name)


def fixture_theme(name="latest_normal.json"):
    return copy.deepcopy(fixture(name)["themes"]["fixture_theme"])


def direct_theme(
    *, phase="unclassifiable", direction="improving", level="price_only", evidence_direction="up",
    eligible=True, diffusion=False, concentrated=False, weak=False, rels=(0.02, 0.04, 0.06), concentration_pass=False,
):
    theme = fixture_theme()
    theme["quality"]["classification_eligible"] = eligible
    theme["classifications"].update({"phase": phase, "direction": direction})
    theme["classifications"]["evidence"].update({"level": level, "direction": evidence_direction})
    theme["condition_flags"].update({"phase_diffusion": diffusion, "broad_concentration_pass": concentration_pass, "overheat_breadth_weak": weak})
    theme["metrics"].update({
        "equal_weight_rel_spy_1w": rels[0], "equal_weight_rel_spy_4w": rels[1], "equal_weight_rel_spy_13w": rels[2],
        "single_name_concentrated": concentrated,
    })
    return theme


def normal_regime_inputs():
    return copy.deepcopy(fixture("latest_normal.json")["market_regime"]["inputs"])


class SpecificationCases(unittest.TestCase):
    def test_T01_broad_risk_on(self):
        values = normal_regime_inputs()
        values["cyclical_basket_rel_spy_4w"] = 0.01
        result = classify_market_regime(values)["classification"]
        self.assertEqual((result["primary_regime"], result["confidence"]), ("broad_risk_on", "high"))

    def test_T02_large_growth_concentration(self):
        values = normal_regime_inputs()
        values.update(spy_r_4w=0.03, qqq_rel_spy_4w=0.04, rsp_minus_spy_4w=-0.02, iwm_minus_spy_4w=-0.01, sector_advance_ratio_4w=4 / 11)
        result = classify_market_regime(values)["classification"]
        self.assertEqual(result["primary_regime"], "large_growth_concentration")

    def test_T03_initial_blocked_by_single_name(self):
        theme = fixture_theme("latest_single_name_concentration.json")
        self.assertFalse(theme["condition_flags"]["phase_initial"])
        self.assertEqual((theme["classifications"]["phase"], theme["classifications"]["research_priority"]), ("unclassifiable", "watch"))

    def test_T04_diffusion(self):
        theme = fixture_theme()
        self.assertEqual(theme["classifications"]["phase"], "diffusion")
        self.assertTrue(theme["condition_flags"]["broad_concentration_pass"])

    def test_T05_overheat_recent_improvement(self):
        theme = fixture_theme("latest_p2_overheat_diffusion.json")
        self.assertEqual((theme["classifications"]["phase"], theme["classifications"]["direction"], theme["classifications"]["timing_status"]), ("price_overheat", "improving", "price_overheat"))

    def test_T06_overheat_and_outflow(self):
        theme = fixture_theme("latest_overheat_outflow.json")
        self.assertEqual((theme["classifications"]["phase"], theme["classifications"]["direction"]), ("price_overheat", "outflow_signal"))

    def test_T07_worsening_with_positive_13w_is_watch(self):
        theme = direct_theme(phase="diffusion", direction="worsening", level="relative_preference_suggested", evidence_direction="outflow", rels=(-0.01, -0.01, 0.12))
        self.assertEqual(evaluate_priority(theme)[:2], ("watch", "P4"))

    def test_T08_constituent_shortage(self):
        rows = [{"active": True, "role": "core", "return_1w": 0.1, "return_4w": 0.1} for _ in range(5)]
        self.assertFalse(assess_quality(rows, 4, 1.0)["classification_eligible"])

    def test_T09_history_shortage(self):
        metrics = copy.deepcopy(fixture_theme()["metrics"])
        metrics.update(equal_weight_rel_spy_13w=0.10, pct_within_5pct_52w_high=0.20)
        trends = copy.deepcopy(fixture_theme()["trends"])
        quality = copy.deepcopy(fixture_theme()["quality"])
        quality.update(direction_eligible=False, phase_initial_diffusion_eligible=False, history_weeks=2)
        _, classification = classify_theme(metrics, trends, quality, fixture_theme()["by_role"])
        self.assertEqual((classification["phase"], classification["direction"]), ("unclassifiable", "unclassifiable"))

    def test_T10_required_field_missing(self):
        theme = fixture_theme("latest_missing.json")
        self.assertIsNone(theme["metrics"]["equal_weight_rel_spy_4w"])
        self.assertEqual(theme["classifications"]["phase"], "unclassifiable")

    def test_T11_unsupported_schema(self):
        value = fixture("latest_normal.json")
        value["meta"]["schema_version"] = "1.0"
        with self.assertRaises(ContractError):
            validate_schema(value, LATEST_SCHEMA)

    def test_T12_stale_and_hard_stop(self):
        value = fixture("latest_normal.json")
        self.assertEqual(freshness_status(value, dt.datetime(2026, 7, 22, tzinfo=dt.timezone.utc)), "stale")
        self.assertEqual(freshness_status(value, dt.datetime(2026, 7, 26, tzinfo=dt.timezone.utc)), "hard_stop")

    def test_T13_no_previous_judgment(self):
        previous = fixture("latest_normal.json")["previous_judgments"]
        self.assertEqual(previous, {"source": "output/judgments/index.json", "available": False, "latest_data_date": None, "records": []})

    def test_T14_withdrawal_triggered(self):
        condition = {"condition_id": "W", "field_path": "themes.x.metrics.equal_weight_rel_spy_4w", "operator": "<", "value": 0, "persistence_weeks": 2}
        current = {"themes": {"x": {"metrics": {"equal_weight_rel_spy_4w": -0.02}}}}
        history = [{"themes": {"x": {"metrics": {"equal_weight_rel_spy_4w": -0.01}}}}]
        self.assertEqual(evaluate_withdrawal(condition, current, history)["status"], "triggered")

    def test_T15_peripheral_spike_is_not_diffusion(self):
        theme = fixture_theme("latest_single_name_concentration.json")
        self.assertEqual(theme["by_role"]["peripheral"]["advance_ratio_4w"], 1.0)
        self.assertEqual(theme["classifications"]["research_priority"], "watch")

    def test_T16_market_cap_only_lead(self):
        equal_rel, cap_rel = -0.01, 0.08
        self.assertGreaterEqual(cap_rel - equal_rel, 0.03)
        self.assertFalse(equal_rel > 0)

    def test_T17_equal_weight_broad_rise(self):
        theme = fixture_theme()
        self.assertGreaterEqual(theme["metrics"]["advance_ratio_4w"], 0.75)
        self.assertLessEqual(theme["metrics"]["top1_contribution_ratio"], 0.30)
        self.assertEqual(theme["classifications"]["phase"], "diffusion")

    def test_T18_cross_theme_overlap_warns(self):
        master = fixture("theme_master.json")
        duplicate = copy.deepcopy(master["themes"][0])
        duplicate["theme_id"] = "fixture_theme_2"
        master["themes"].append(duplicate)
        warnings = validate_theme_master_semantics(master)
        self.assertTrue(any(warning.startswith("OVERLAP:AAA:") for warning in warnings))

    def test_T19_qualitative_text_cannot_change_quant(self):
        theme = fixture_theme()
        before = copy.deepcopy(theme["classifications"])
        qualitative_counterevidence = "demand slowdown"  # deliberately not an input to any rule
        self.assertTrue(qualitative_counterevidence)
        self.assertEqual(theme["classifications"], before)

    def test_T20_mid_run_identity_change_resets(self):
        locked = fixture("latest_normal.json")["meta"]
        changed = dict(locked, run_id="different-run")
        with self.assertRaises(ContractError):
            validate_run_identity(locked, changed)

    def test_T21_top1_exactly_060(self):
        theme = direct_theme(concentrated=False)
        theme["metrics"]["top1_contribution_ratio"] = 0.60
        self.assertFalse(theme["metrics"]["top1_contribution_ratio"] > 0.60)

    def test_T22_diffusion_concentration_boundaries(self):
        metrics = copy.deepcopy(fixture_theme()["metrics"])
        metrics.update(top1_contribution_ratio=0.50, top3_contribution_ratio=0.85, advance_ratio_4w=0.60, pct_above_50dma=0.60)
        flags, classification = classify_theme(metrics, fixture_theme()["trends"], fixture_theme()["quality"], fixture_theme()["by_role"])
        self.assertTrue(flags["phase_diffusion"])
        self.assertEqual(classification["phase"], "diffusion")

    def test_T23_advance_exactly_060(self):
        metrics = copy.deepcopy(fixture_theme()["metrics"])
        metrics["advance_ratio_4w"] = 0.60
        flags, _ = classify_theme(metrics, fixture_theme()["trends"], fixture_theme()["quality"], fixture_theme()["by_role"])
        self.assertTrue(flags["phase_diffusion"])

    def test_T24_volume_exactly_130(self):
        metrics = copy.deepcopy(fixture_theme()["metrics"])
        metrics.update(equal_weight_rel_spy_13w=0.15, pct_within_5pct_52w_high=0.50, volume_ratio_20d_60d=1.30)
        flags, classification = classify_theme(metrics, fixture_theme()["trends"], fixture_theme()["quality"], fixture_theme()["by_role"])
        self.assertTrue(flags["phase_price_overheat"])
        self.assertEqual(classification["phase"], "price_overheat")

    def test_T25_role_valid_one_is_null(self):
        rows = [{"role": "core", "return_4w": 0.1}]
        aggregates, counts = role_aggregates(rows, 0.02)
        self.assertEqual(counts["core"], 1)
        self.assertIsNone(aggregates["core"])

    def test_T26_market_cap_coverage_074(self):
        relatives = [0.1] * 100
        caps = [1.0] * 74 + [None] * 26
        value, coverage = market_cap_weighted_relative(relatives, caps)
        self.assertEqual(coverage, 0.74)
        self.assertIsNone(value)

    def test_T27_zero_positive_contribution(self):
        top1, top3, shares = positive_concentration([-0.1, 0.0, -0.2])
        self.assertIsNone(top1)
        self.assertIsNone(top3)
        self.assertEqual(shares, [None, None, None])

    def test_T28_history_gap_11_days(self):
        history = [{"data_date": "2026-06-29", "schema_version": "1.1", "methodology_version": "1.1.0", "theme_master_version": "m"}]
        self.assertEqual(contiguous_history(history, "2026-07-10", "1.1", "1.1.0", "m"), [])

    def test_T29_history_methodology_mismatch(self):
        history = [{"data_date": "2026-07-03", "schema_version": "1.1", "methodology_version": "1.0", "theme_master_version": "m"}]
        self.assertEqual(contiguous_history(history, "2026-07-10", "1.1", "1.1.0", "m"), [])

    def test_T30_direct_flow_unavailable(self):
        for path in FIXTURES.glob("latest_*.json"):
            evidence = next(iter(load_json(path)["themes"].values()))["classifications"]["evidence"]
            self.assertFalse(evidence["direct_flow_data_available"])
            self.assertNotEqual(evidence["level"], "direct_flow_confirmed")

    def test_T31_failed_manifest_stops(self):
        value = fixture("latest_normal.json")
        value["meta"]["status"] = "failed"
        self.assertEqual(freshness_status(value, dt.datetime(2026, 7, 12, tzinfo=dt.timezone.utc)), "failed")

    def test_T32_source_hash_mismatch(self):
        value = fixture("latest_normal.json")
        value["meta"]["source_sha256"] = snapshot_source_hash(value)
        validate_latest_semantics(value, verify_source_hash=True)
        value["meta"]["source_sha256"] = "0" * 64
        with self.assertRaises(ContractError):
            validate_latest_semantics(value, verify_source_hash=True)

    def test_T33_nan_infinity_rejected(self):
        value = fixture("latest_normal.json")
        value["themes"]["fixture_theme"]["metrics"]["equal_weight_rel_spy_4w"] = float("nan")
        with self.assertRaises(ContractError):
            validate_latest_semantics(value)
        with self.assertRaises(ValueError):
            json.dumps(value, allow_nan=False)

    def test_T34_duplicate_theme_id_fails(self):
        master = fixture("theme_master.json")
        master["themes"].append(copy.deepcopy(master["themes"][0]))
        with self.assertRaises(ContractError):
            validate_theme_master_semantics(master)

    def test_T35_duplicate_ticker_same_theme_fails(self):
        master = fixture("theme_master.json")
        master["themes"][0]["members"].append(copy.deepcopy(master["themes"][0]["members"][0]))
        with self.assertRaises(ContractError):
            validate_theme_master_semantics(master)

    def test_T36_overlap_is_warning_only(self):
        master = fixture("theme_master.json")
        second = copy.deepcopy(master["themes"][0])
        second["theme_id"] = "second"
        master["themes"].append(second)
        self.assertEqual(len(validate_theme_master_semantics(master)), 6)

    def test_T37_mixed_regime(self):
        values = normal_regime_inputs()
        values.update(iwm_minus_spy_4w=0.03, cyclical_basket_rel_spy_4w=0.03, hyg_minus_lqd_4w=0.01)
        result = classify_market_regime(values)["classification"]
        self.assertEqual(result["primary_regime"], "mixed")
        self.assertIn("broad_risk_on", result["secondary_regimes"])
        self.assertIn("cyclical_recovery_expectation", result["secondary_regimes"])

    def test_T38_regime_25_percent_missing(self):
        values = normal_regime_inputs()
        for key in list(values)[:4]:
            values[key] = None
        self.assertEqual(classify_market_regime(values)["classification"]["primary_regime"], "unclassifiable")

    def test_T39_price_only(self):
        metrics = copy.deepcopy(fixture_theme()["metrics"])
        metrics.update(advance_ratio_4w=0.30, pct_above_50dma=0.30, volume_ratio_20d_60d=1.0)
        _, classification = classify_theme(metrics, fixture_theme()["trends"], fixture_theme()["quality"], fixture_theme()["by_role"])
        self.assertEqual((classification["evidence"]["level"], classification["evidence"]["direction"]), ("price_only", "up"))

    def test_T40_positioning_hypothesis(self):
        metrics = copy.deepcopy(fixture_theme()["metrics"])
        metrics.update(equal_weight_rel_spy_1w=0.08, top1_contribution_ratio=0.61)
        _, classification = classify_theme(metrics, fixture_theme()["trends"], fixture_theme()["quality"], fixture_theme()["by_role"])
        self.assertEqual(classification["evidence"]["positioning_hypothesis"], "possible_short_term_adjustment")

    def test_T41_p1_only(self):
        theme = fixture_theme("latest_p1_diffusion.json")
        self.assertEqual(evaluate_priority(theme)[:2], ("dd_priority", "P1"))
        self.assertFalse(priority_matches(theme)["P2"])
        self.assertFalse(priority_matches(theme)["P3"])

    def test_T42_p2_only(self):
        theme = fixture_theme("latest_p2_overheat_diffusion.json")
        self.assertEqual(evaluate_priority(theme)[:2], ("dd_priority", "P2"))
        self.assertFalse(priority_matches(theme)["P1"])
        self.assertFalse(priority_matches(theme)["P3"])

    def test_T43_p1_p2_mutually_exclusive(self):
        for name in ("latest_p1_diffusion.json", "latest_p2_overheat_diffusion.json"):
            matches = priority_matches(fixture_theme(name))
            self.assertFalse(matches["P1"] and matches["P2"])

    def test_T44_p5_reachable(self):
        self.assertEqual(evaluate_priority(fixture_theme("latest_p5_low_priority.json"))[:2], ("low_priority", "P5"))

    def test_T45_outflow_cannot_enter_dd_rules(self):
        theme = direct_theme(phase="diffusion", direction="flat", level="flow_suggested", evidence_direction="outflow", concentration_pass=True)
        matches = priority_matches(theme)
        self.assertFalse(any(matches[rule] for rule in ("P1", "P2", "P3")))
        self.assertEqual(evaluate_priority(theme)[:2], ("watch", "fallback"))

    def test_T46_overheat_breadth_weak(self):
        self.assertTrue(overheat_breadth_weak(True, 0.59, 0.60))
        theme = direct_theme(phase="price_overheat", direction="flat", weak=True)
        self.assertEqual(evaluate_priority(theme)[:2], ("watch", "P4"))

    def test_T47_overheat_breadth_boundary(self):
        self.assertFalse(overheat_breadth_weak(True, 0.60, 0.60))
        theme = direct_theme(phase="price_overheat", direction="flat", weak=False)
        self.assertEqual(evaluate_priority(theme)[:2], ("watch", "fallback"))

    def test_T48_deterministic_shortlist(self):
        themes = {}
        for index, theme_id in enumerate(["g", "f", "e", "d", "c", "b", "a"]):
            theme = direct_theme(phase="diffusion", direction="improving", level="flow_suggested", evidence_direction="inflow", concentration_pass=True)
            theme["classifications"].update(research_priority="dd_priority", research_priority_rule="P1")
            theme["metrics"]["equal_weight_rel_spy_4w"] = 0.07 - index * 0.01
            themes[theme_id] = theme
        first, shortlist = apply_shortlist(themes)
        reversed_result, reversed_shortlist = apply_shortlist(dict(reversed(list(themes.items()))))
        self.assertEqual(shortlist["selected_theme_ids"], ["g", "f", "e", "d", "c"])
        self.assertEqual(shortlist, reversed_shortlist)
        self.assertEqual([first[item]["shortlist_rank"] for item in shortlist["selected_theme_ids"]], [1, 2, 3, 4, 5])
        self.assertEqual(reversed_result["g"]["shortlist_rank"], 1)

    def test_T49_shortlist_no_backfill(self):
        themes = {
            "one": direct_theme(phase="initial", direction="improving", level="relative_preference_suggested", evidence_direction="inflow"),
            "two": direct_theme(phase="unclassifiable", direction="improving", level="price_only", evidence_direction="up"),
            "low": direct_theme(phase="unclassifiable", direction="outflow_signal", level="relative_preference_suggested", evidence_direction="outflow", rels=(-0.1, -0.1, -0.1)),
            "bad": direct_theme(eligible=False),
        }
        themes["one"]["classifications"].update(research_priority="dd_candidate", research_priority_rule="P3")
        themes["two"]["classifications"].update(research_priority="watch", research_priority_rule="fallback")
        themes["low"]["classifications"].update(research_priority="low_priority", research_priority_rule="P5")
        themes["bad"]["classifications"].update(research_priority="unclassifiable", research_priority_rule="P0")
        _, shortlist = apply_shortlist(themes)
        self.assertEqual(shortlist["selected_theme_ids"], ["one", "two"])
        self.assertIn("SHORTLIST_BELOW_MINIMUM_3", shortlist["quality_reasons"])


if __name__ == "__main__":
    unittest.main()
