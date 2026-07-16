import copy
import unittest
from pathlib import Path

from rotation.classification import classify_theme
from rotation.condition_audit import positioning_predicate
from rotation.validation import ContractError, load_json, validate_latest_semantics
from tests.test_pipeline_contract import build_synthetic, synthetic_inputs
from tests.test_generation_e2e import generate


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class CanonicalConditionAuditTests(unittest.TestCase):
    def test_positioning_truth_table_has_explicit_expected_results(self):
        cases = (
            (0.08, 0.61, 1.00, 0.60, True),
            (0.00, 0.40, 1.80, 0.39, True),
            (-0.08, 0.61, 1.80, 0.39, True),
            (0.00, 0.61, 1.00, 0.60, False),
            (0.07, 0.61, 1.79, 0.39, False),
            (0.00, 0.40, 1.00, 0.60, False),
            (None, 0.61, 1.80, 0.39, None),
        )
        for rel1, top1, volume, advance, expected in cases:
            with self.subTest(values=(rel1, top1, volume, advance)):
                self.assertIs(positioning_predicate(rel1, top1, volume, advance), expected)
    def test_all_canonical_fixtures_have_independent_explicit_condition_ids(self):
        for path in sorted(FIXTURES.glob("latest_*.json")):
            source = load_json(path)
            theme = next(iter(source["themes"].values()))
            flags, classifications = classify_theme(theme["metrics"], theme["trends"], theme["quality"], theme["by_role"])
            with self.subTest(path=path.name):
                self.assertEqual(flags["matched_conditions"], theme["condition_flags"]["matched_conditions"])
                self.assertEqual(flags["unmatched_conditions"], theme["condition_flags"]["unmatched_conditions"])
                self.assertEqual(classifications["evidence"]["matched_conditions"], theme["classifications"]["evidence"]["matched_conditions"])

    def test_production_p1_condition_ids_match_canonical_fixture(self):
        generated = build_synthetic()["themes"]["fixture_theme"]
        canonical = load_json(FIXTURES / "latest_p1_diffusion.json")["themes"]["fixture_theme"]
        self.assertEqual(generated["condition_flags"]["matched_conditions"], canonical["condition_flags"]["matched_conditions"])
        self.assertEqual(generated["condition_flags"]["unmatched_conditions"], canonical["condition_flags"]["unmatched_conditions"])
        self.assertEqual(generated["classifications"]["evidence"]["matched_conditions"], canonical["classifications"]["evidence"]["matched_conditions"])

    def test_production_p2_p5_and_overheat_outflow_have_specific_ids(self):
        config, master, observations, history, previous = synthetic_inputs()
        members = {member["ticker"] for member in master["themes"][0]["members"]}
        for ticker in members:
            observations[ticker].update(return_13w=0.25, volume_ratio_20d_60d=1.30, within_5pct_52w_high=True)
        p2 = generate(config, master, observations, history, previous)["themes"]["fixture_theme"]
        self.assertIn("PH_OVERHEAT_VOLUME_130", p2["condition_flags"]["matched_conditions"])
        self.assertIn("EV_VOLUME_110", p2["classifications"]["evidence"]["matched_conditions"])

        config, master, observations, history, previous = synthetic_inputs()
        members = {member["ticker"] for member in master["themes"][0]["members"]}
        for ticker in members:
            observations[ticker].update(return_1w=-0.01, return_4w=-0.01, return_13w=-0.02, above_50dma=False, within_5pct_52w_high=False, volume_ratio_20d_60d=1.20)
        for item, rel, count in zip(history, (0.08, 0.04, 0.00), (3, 2, 1)):
            item["themes"]["fixture_theme"].update(equal_weight_rel_spy_4w=rel, advance_count_4w=count, above_50dma_count=count, pct_above_50dma=count / 6)
        p5 = generate(config, master, observations, history, previous)["themes"]["fixture_theme"]
        self.assertIn("P5_REL_ALL_NONPOSITIVE", p5["condition_flags"]["matched_conditions"])
        self.assertEqual(p5["classifications"]["evidence"]["matched_conditions"], ["EV_REL_ALL_NONPOSITIVE", "EV_BREADTH_WEAK", "EV_DIRECTION_OUTFLOW"])

        config, master, observations, history, previous = synthetic_inputs()
        members = {member["ticker"] for member in master["themes"][0]["members"]}
        for ticker in members:
            observations[ticker].update(return_4w=-0.01, return_13w=0.25, above_50dma=False, within_5pct_52w_high=True, volume_ratio_20d_60d=1.40)
        for item, rel, count in zip(history, (0.03, 0.01, -0.01), (4, 3, 2)):
            item["themes"]["fixture_theme"].update(equal_weight_rel_spy_4w=rel, advance_count_4w=count, above_50dma_count=count, pct_above_50dma=count / 6)
        outflow = generate(config, master, observations, history, previous)["themes"]["fixture_theme"]
        self.assertIn("DIR_OUTFLOW_VOLUME_120", outflow["condition_flags"]["matched_conditions"])
        self.assertIn("EV_DIRECTION_OUTFLOW", outflow["classifications"]["evidence"]["matched_conditions"])

    def test_market_cap_and_worsening_four_week_trend_are_contrary_evidence(self):
        initial = load_json(FIXTURES / "latest_single_name_concentration.json")["themes"]["fixture_theme"]
        flags, _ = classify_theme(initial["metrics"], initial["trends"], initial["quality"], initial["by_role"])
        self.assertIn("WEIGHTING_MARKET_CAP_LED", flags["contrary_evidence"])
        self.assertNotIn("WEIGHTING_MARKET_CAP_LED", flags["matched_conditions"])

        overheat = load_json(FIXTURES / "latest_overheat_outflow.json")["themes"]["fixture_theme"]
        flags, _ = classify_theme(overheat["metrics"], overheat["trends"], overheat["quality"], overheat["by_role"])
        self.assertIn("REL_4W_TREND_WORSENING", flags["contrary_evidence"])

    def test_condition_id_delete_add_and_reorder_mutations_fail(self):
        base = build_synthetic()
        mutations = []
        value = copy.deepcopy(base); value["themes"]["fixture_theme"]["condition_flags"]["matched_conditions"].pop(); mutations.append(value)
        value = copy.deepcopy(base); value["themes"]["fixture_theme"]["condition_flags"]["matched_conditions"].append("PH_BOGUS"); mutations.append(value)
        value = copy.deepcopy(base); value["themes"]["fixture_theme"]["condition_flags"]["matched_conditions"].reverse(); mutations.append(value)
        value = copy.deepcopy(base); value["themes"]["fixture_theme"]["classifications"]["evidence"]["matched_conditions"].pop(); mutations.append(value)
        for value in mutations:
            with self.subTest(value=value["themes"]["fixture_theme"]["condition_flags"]), self.assertRaisesRegex(ContractError, "matched_conditions"):
                validate_latest_semantics(value)


if __name__ == "__main__":
    unittest.main()
