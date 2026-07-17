import copy
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from rotation.decisions import BUCKET_NAMES, _research_lens, build_candidate_buckets, select_companies
from rotation.discovery import discover_dynamic_industries
from rotation.interaction import ConversationSession
from rotation.legacy import migrate_candidate_buckets_2_to_3
from rotation.metrics import aggregate_theme
from rotation.presentation import build_user_view, render_phase
from rotation.provenance import snapshot_source_hash
from rotation.validation import ContractError, validate_latest_semantics
from rotation.validation import load_json, validate_schema
from tests.test_pipeline_contract import build_synthetic, synthetic_inputs
from scripts.generate_weekly import classify_publication_start_state, ticker_observation


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "classification_eligible", "direction_eligible", "condition_flags", "matched_conditions",
    "unmatched_conditions", "source_sha256", "run_id", "EV_", "SL_", "Q_", "P1", "P2", "P3", "P4", "P5",
)


class UserExperienceContracts(unittest.TestCase):
    def test_four_bucket_contract_is_complete_exclusive_and_total(self):
        snapshot = build_synthetic()
        buckets = snapshot["candidate_buckets"]
        self.assertEqual(buckets["selection_version"], "3.0")
        self.assertEqual(tuple(name for name in buckets if name in BUCKET_NAMES), BUCKET_NAMES)
        memberships = [
            (item["id"], item["source"])
            for name in BUCKET_NAMES for item in buckets[name]
        ]
        known = {(key, "fixed_theme") for key in snapshot["themes"]} | {(key, "dynamic_industry") for key in snapshot["dynamic_discovery"]["candidates"]}
        self.assertEqual(set(memberships), known)
        self.assertEqual(len(memberships), len(set(memberships)))

    def test_long_term_bucket_requires_supported_context_and_weak_price(self):
        snapshot = build_synthetic()
        theme = snapshot["themes"]["fixture_theme"]
        theme["metrics"].update(equal_weight_rel_spy_4w=-0.02, equal_weight_rel_spy_13w=-0.01, advance_ratio_4w=0.30, pct_above_50dma=0.30)
        theme["structural_context"] = {"version": "1.0", "status": "supported", "as_of": "2026-07-10", "summary": "test context", "source_category": ["test"]}
        buckets = build_candidate_buckets(snapshot["themes"], {"candidate_ids": [], "candidates": {}})
        self.assertEqual(buckets["long_term_context_price_weak"][0]["id"], "fixture_theme")
        theme["structural_context"]["status"] = "not_assessed"
        buckets = build_candidate_buckets(snapshot["themes"], {"candidate_ids": [], "candidates": {}})
        self.assertFalse(buckets["long_term_context_price_weak"])
        self.assertEqual(buckets["avoid_now"][0]["id"], "fixture_theme")

    def test_missing_price_metrics_are_not_claimed_as_price_weakness(self):
        snapshot = build_synthetic()
        theme = snapshot["themes"]["fixture_theme"]
        theme["metrics"].update(equal_weight_rel_spy_4w=None, equal_weight_rel_spy_13w=None, advance_ratio_4w=None, pct_above_50dma=None)
        theme["structural_context"] = {"version": "1.0", "status": "supported", "as_of": "2026-07-10", "summary": "test context", "source_category": ["test"]}
        buckets = build_candidate_buckets(snapshot["themes"], {"candidate_ids": [], "candidates": {}})
        self.assertFalse(buckets["long_term_context_price_weak"])
        self.assertEqual(buckets["avoid_now"][0]["id"], "fixture_theme")

    def test_weak_dynamic_definition_is_preserved_and_classified(self):
        config, _, observations, _, _ = synthetic_inputs()
        members = ["BANK1", "BANK2", "BANK3", "BANK4"]
        config["dynamic_industries"] = {"regional_banks": {"label": "地方銀行", "etf": "KRE", "members": members}}
        observations["KRE"] = {**observations["SPY"], "return_4w": -0.02}
        for ticker in members:
            observations[ticker] = {**observations["SPY"], "return_1w": -0.01, "return_4w": -0.02, "return_13w": -0.03, "above_50dma": False}
        dynamic = discover_dynamic_industries(config, observations, observations["SPY"])
        self.assertEqual(dynamic["candidate_ids"], [])
        self.assertIn("regional_banks", dynamic["candidates"])
        self.assertFalse(dynamic["candidates"]["regional_banks"]["eligible"])
        buckets = build_candidate_buckets({}, dynamic)
        self.assertEqual(buckets["avoid_now"][0]["id"], "regional_banks")

    def test_research_lens_priority_ticker_then_theme_then_role_then_global(self):
        config = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))
        _, source = _research_lens(config, "regional_banks", "RF", "core", "representative")
        self.assertEqual(source, "ticker:RF")
        _, source = _research_lens(config, "regional_banks", "CFG", "core", "representative")
        self.assertEqual(source, "theme:regional_banks:representative")
        role_config = {"role_research_lenses": config["role_research_lenses"]}
        _, source = _research_lens(role_config, "unknown", "XYZ", "beneficiary", "representative")
        self.assertEqual(source, "role:beneficiary")
        _, source = _research_lens({}, "unknown", "XYZ", "core", "breadth_check")
        self.assertEqual(source, "global_fallback")

    def test_known_configured_theme_cannot_downgrade_to_global_lens(self):
        snapshot = build_synthetic()
        theme = snapshot["themes"].pop("fixture_theme")
        theme["theme_id"] = "ai_semis"
        snapshot["themes"]["ai_semis"] = theme
        snapshot["theme_shortlist"]["selected_theme_ids"] = ["ai_semis" if value == "fixture_theme" else value for value in snapshot["theme_shortlist"]["selected_theme_ids"]]
        for name in BUCKET_NAMES:
            for item in snapshot["candidate_buckets"][name]:
                if item["id"] == "fixture_theme":
                    item["id"] = "ai_semis"
        config = load_json(ROOT / "config" / "universe.json")
        snapshot["company_candidates"] = select_companies(snapshot["themes"], snapshot["dynamic_discovery"], snapshot["candidate_buckets"], config)
        snapshot["user_view"] = build_user_view(
            regime=snapshot["market_regime"], style_factor=snapshot["style_factor"], sectors=snapshot["sectors"], industries=snapshot["industries"],
            themes=snapshot["themes"], dynamic=snapshot["dynamic_discovery"], buckets=snapshot["candidate_buckets"], companies=snapshot["company_candidates"], history_weeks=theme["quality"]["history_weeks"],
        )
        snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)
        validate_latest_semantics(snapshot, verify_source_hash=True)
        for item in snapshot["company_candidates"]:
            lens, _ = _research_lens({}, item["theme_id"], item["ticker"], "core", item["selection_role"])
            item.update(lens, research_lens_source="global_fallback")
        snapshot["user_view"] = build_user_view(
            regime=snapshot["market_regime"], style_factor=snapshot["style_factor"], sectors=snapshot["sectors"], industries=snapshot["industries"],
            themes=snapshot["themes"], dynamic=snapshot["dynamic_discovery"], buckets=snapshot["candidate_buckets"], companies=snapshot["company_candidates"], history_weeks=theme["quality"]["history_weeks"],
        )
        snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)
        with self.assertRaisesRegex(ContractError, "research lens"):
            validate_latest_semantics(snapshot, verify_source_hash=True)

    def test_legacy_three_bucket_projection_never_infers_structural_context(self):
        legacy = {"selection_version": "2.0", "max_research_items": 5, "research_now": [], "watch_recovery": [], "avoid_now": [{"id": "x", "label": "X", "source": "fixed_theme"}]}
        current = migrate_candidate_buckets_2_to_3(legacy)
        self.assertEqual(current["selection_version"], "3.0")
        self.assertEqual(current["long_term_context_price_weak"], [])
        self.assertEqual(current["avoid_now"][0]["classification_reason"], "avoid_now")

    def test_schema_1_1_additive_snapshot_remains_read_only_compatible(self):
        legacy = build_synthetic()
        legacy["meta"].update(schema_version="1.1", methodology_version="1.1.0")
        legacy["candidate_buckets"]["selection_version"] = "2.0"
        legacy["candidate_buckets"].pop("long_term_context_price_weak")
        for name in ("research_now", "watch_recovery", "avoid_now"):
            for item in legacy["candidate_buckets"][name]:
                item.pop("classification_reason", None)
        legacy["dynamic_discovery"] = {"discovery_version": "1.0", "thresholds": legacy["dynamic_discovery"]["thresholds"], "candidate_ids": [], "candidates": {}, "rejected": {}}
        for item in legacy["company_candidates"]:
            item.pop("research_lens_source", None)
        legacy["user_view"]["presentation_version"] = "1.0"
        legacy["meta"]["source_sha256"] = snapshot_source_hash(legacy)
        validate_schema(legacy, load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"), "legacy additive")
        validate_latest_semantics(legacy, verify_source_hash=True)

    def test_phase_four_and_six_always_name_all_four_buckets(self):
        snapshot = build_synthetic()
        self.assertEqual(snapshot["user_view"]["presentation_version"], "1.2")
        for phase in (4, 6):
            rendered = render_phase(snapshot["user_view"], phase)
            for label in ("個別企業を調べる", "回復条件を監視する", "長期材料はあるが、現在の株価は弱い", "現在は避ける"):
                self.assertIn(label, rendered)
            self.assertIn("該当なし", rendered)

    def test_presentation_1_1_remains_read_only_compatible(self):
        legacy = build_synthetic()
        legacy["user_view"] = build_user_view(
            regime=legacy["market_regime"], style_factor=legacy["style_factor"],
            sectors=legacy["sectors"], industries=legacy["industries"], themes=legacy["themes"],
            dynamic=legacy["dynamic_discovery"], buckets=legacy["candidate_buckets"],
            companies=legacy["company_candidates"],
            history_weeks=min(theme["quality"]["history_weeks"] for theme in legacy["themes"].values()),
            presentation_version="1.1",
        )
        legacy["meta"]["source_sha256"] = snapshot_source_hash(legacy)
        validate_schema(legacy, load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"), "presentation 1.1")
        validate_latest_semantics(legacy, verify_source_hash=True)
        self.assertNotIn("長期材料はあるが、現在の株価は弱い", render_phase(legacy["user_view"], 4))

    def test_semantic_validator_rejects_four_bucket_and_display_corruption(self):
        base = build_synthetic()
        mutations = {}
        value = copy.deepcopy(base); value["candidate_buckets"].pop("long_term_context_price_weak"); mutations["missing fourth bucket"] = value
        value = copy.deepcopy(base); value["candidate_buckets"]["avoid_now"].append(copy.deepcopy(value["candidate_buckets"]["research_now"][0])); mutations["duplicate membership"] = value
        value = copy.deepcopy(base); value["candidate_buckets"]["avoid_now"].append({"id": "unknown", "label": "未知", "source": "fixed_theme", "classification_reason": "avoid_now"}); mutations["unknown candidate"] = value
        value = copy.deepcopy(base); item = value["candidate_buckets"]["research_now"].pop(); item["classification_reason"] = "long_term_context_price_weak"; value["candidate_buckets"]["long_term_context_price_weak"].append(item); mutations["unsupported long term"] = value
        value = copy.deepcopy(base); value["company_candidates"][0].pop("key_check"); mutations["missing company lens"] = value
        value = copy.deepcopy(base); value["user_view"]["phases"][3]["conclusion"] = "classification_eligible"; mutations["internal field leak"] = value
        if len(base["company_candidates"]) > 1:
            value = copy.deepcopy(base)
            for item in value["company_candidates"][1:]:
                item["key_check"] = value["company_candidates"][0]["key_check"]
                item["counter_evidence"] = value["company_candidates"][0]["counter_evidence"]
            mutations["identical company text"] = value
        for name, value in mutations.items():
            value["meta"]["source_sha256"] = snapshot_source_hash(value)
            with self.subTest(name=name), self.assertRaises(ContractError):
                validate_latest_semantics(value, verify_source_hash=True)

    def test_eight_required_display_fixtures_are_registered(self):
        value = json.loads((ROOT / "tests" / "fixtures" / "user_display_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {case["id"] for case in value["cases"]},
            {"weak_market", "strong_fixed_theme", "strong_dynamic_industry", "single_name_concentration", "initial_observation", "semantic_stop", "zero_research_candidates", "long_term_but_price_weak"},
        )

    def test_all_six_normal_phases_hide_internal_language(self):
        snapshot = build_synthetic()
        for phase in range(1, 7):
            rendered = render_phase(snapshot["user_view"], phase)
            self.assertTrue(rendered.startswith("今回わかったこと:"))
            self.assertIn("投資判断への意味", rendered)
            self.assertIn("注意点", rendered)
            self.assertIn("次に確認すること", rendered)
            for token in FORBIDDEN:
                self.assertNotIn(token, rendered)

    def test_update_and_five_next_commands_complete_six_phases(self):
        session = ConversationSession(build_synthetic())
        outputs = [session.handle("更新")] + [session.handle("次") for _ in range(5)]
        self.assertEqual(session.phase, 6)
        self.assertEqual(len(outputs), 6)
        self.assertIn("個別企業", outputs[-1])

    def test_initial_observation_blocks_trend_claims(self):
        config, master, observations, _, previous = synthetic_inputs()
        from rotation.pipeline import build_snapshot
        import datetime as dt
        snapshot = build_snapshot(config=config, theme_master=master, observations=observations, history=[], previous_judgments=previous, generated_at=dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc), data_date="2026-07-10", source_commit="a" * 40)
        self.assertEqual(snapshot["user_view"]["analysis_mode"], "initial_observation")
        self.assertTrue(snapshot["candidate_buckets"]["research_now"])
        self.assertTrue(snapshot["company_candidates"])
        rendered = "\n".join(render_phase(snapshot["user_view"], phase) for phase in range(1, 7))
        self.assertIn("あと2週分", rendered)
        for token in ("初動", "拡散", "失速", "悪化", "反転", "流入継続", "流出継続", "加速", "減速"):
            self.assertNotIn(token, rendered)

    def test_dynamic_industry_requires_company_breadth_and_flows_downstream(self):
        config, _, observations, _, _ = synthetic_inputs()
        config["dynamic_industries"] = {"regional_banks": {"label": "地方銀行", "etf": "KRE", "members": ["BANK1", "BANK2", "BANK3", "BANK4"]}}
        observations["KRE"] = {**observations["SMH"], "return_4w": 0.08}
        for index, ticker in enumerate(config["dynamic_industries"]["regional_banks"]["members"]):
            observations[ticker] = {**observations["SMH"], "return_1w": 0.02 + index * 0.001, "return_4w": 0.07 + index * 0.005, "market_cap": None}
        dynamic = discover_dynamic_industries(config, observations, observations["SPY"])
        self.assertEqual(dynamic["candidate_ids"], ["regional_banks"])
        snapshot = build_synthetic()
        buckets = build_candidate_buckets(snapshot["themes"], dynamic)
        self.assertTrue(any(item["id"] == "regional_banks" for item in buckets["research_now"]))
        companies = select_companies(snapshot["themes"], dynamic, buckets)
        self.assertTrue(any(item["theme_id"] == "regional_banks" for item in companies))

    def test_concentrated_or_weak_theme_cannot_enter_research_queue(self):
        snapshot = build_synthetic()
        theme = snapshot["themes"]["fixture_theme"]
        theme["metrics"]["single_name_concentrated"] = True
        theme["condition_flags"]["broad_concentration_pass"] = False
        buckets = build_candidate_buckets(snapshot["themes"], {"candidate_ids": [], "candidates": {}})
        self.assertFalse(buckets["research_now"])
        self.assertTrue(buckets["avoid_now"])

    def test_price_preference_never_claims_direct_flow(self):
        theme = build_synthetic()["themes"]["fixture_theme"]
        self.assertEqual(theme["decision"]["price_preference"], "positive")
        self.assertEqual(theme["decision"]["direct_flow_confirmation"], "unavailable")

    def test_company_selection_is_max_two_per_item_and_globally_unique(self):
        snapshot = build_synthetic()
        selected = snapshot["company_candidates"]
        self.assertLessEqual(len(selected), 2 * len(snapshot["candidate_buckets"]["research_now"]))
        self.assertEqual(len({item["ticker"] for item in selected}), len(selected))

    def test_robust_metrics_distinguish_broad_strength_from_one_outlier(self):
        rows = [
            {"ticker": ticker, "return_1w": value / 4, "return_4w": value, "return_13w": value, "above_50dma": value > 0, "within_5pct_52w_high": False, "volume_ratio_20d_60d": 1.0, "market_cap": None, "dollar_volume_20d": 100.0}
            for ticker, value in zip("ABCDEF", (0.50, -0.02, -0.02, -0.02, -0.02, -0.02))
        ]
        metrics, _ = aggregate_theme(rows, {"1w": 0.01, "4w": 0.02, "13w": 0.04})
        self.assertGreater(metrics["equal_weight_rel_spy_4w"], 0)
        self.assertLess(metrics["median_rel_spy_4w"], 0)
        self.assertTrue(metrics["single_name_concentrated"])

    def test_non_overlapping_time_windows_are_distinct(self):
        index = pd.date_range("2026-01-01", periods=80, freq="B", tz="UTC")
        close = pd.Series([100 + value for value in range(80)], index=index)
        frame = pd.DataFrame({"Close": close, "Volume": 1000.0}, index=index)
        observed = ticker_observation(frame)
        self.assertIsNotNone(observed["return_1w"])
        self.assertIsNotNone(observed["return_previous_3w"])
        self.assertIsNotNone(observed["return_previous_9w"])
        self.assertNotEqual(observed["return_1w"], observed["return_previous_3w"])

    def test_semantic_validation_rejects_candidate_bucket_tampering(self):
        snapshot = build_synthetic()
        snapshot["candidate_buckets"]["research_now"] = []
        snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)
        with self.assertRaisesRegex(ContractError, "candidate_buckets"):
            validate_latest_semantics(snapshot, verify_source_hash=True)

    def test_publication_placeholder_is_clean_but_legacy_json_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            (output / "archive").mkdir(parents=True)
            (output / "archive" / ".gitkeep").touch()
            self.assertEqual(classify_publication_start_state(output).kind, "clean")
            (output / "archive" / "2026-07-10.json").write_text("{}", encoding="utf-8")
            self.assertEqual(classify_publication_start_state(output).kind, "partial_legacy")


if __name__ == "__main__":
    unittest.main()
