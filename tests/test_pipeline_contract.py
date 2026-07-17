import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from rotation.judgments import build_index, project_previous_judgments, verify_index
from rotation.legacy import UnsupportedLegacyVersion, read_legacy_snapshot
from rotation.pipeline import build_snapshot
from rotation.provenance import atomic_write_json
from rotation.validation import ContractError, load_json, validate_latest_semantics, validate_schema

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def synthetic_inputs():
    sectors = {ticker: ticker for ticker in ("XLP", "XLV", "XLU", "XLY", "XLI", "XLF", "XLB", "XLK", "XLC", "XLE", "XLRE")}
    config = {
        "config_version": "1.1.0", "vix": "^VIX",
        "regime_assets": {ticker: ticker for ticker in ("SPY", "QQQ", "RSP", "IWM", "DBC", "GLD", "HYG", "LQD", "UUP")},
        "style_factor": {"QQQ": "growth"}, "sectors": sectors, "industries": {"SMH": "semis"},
    }
    master = load_json(FIXTURES / "theme_master.json")
    observations = {}
    all_tickers = set(config["regime_assets"]) | set(sectors) | {"^VIX", "SMH", "AAA", "BBB", "CCC", "DDD", "EEE", "FFF"}
    for ticker in all_tickers:
        observations[ticker] = {
            "return_1w": 0.02, "return_4w": 0.04, "return_13w": 0.08,
            "above_50dma": True, "above_200dma": True, "within_5pct_52w_high": True,
            "volume_ratio_20d_60d": 1.2, "market_cap": None, "last_date": "2026-07-10", "change_4w": 0.0,
        }
    observations["SPY"].update(return_1w=0.01, return_4w=0.02, return_13w=0.04)
    observations["RSP"]["return_4w"] = 0.03
    observations["IWM"]["return_4w"] = 0.04
    observations["QQQ"]["return_4w"] = 0.03
    observations["^VIX"]["change_4w"] = -2.0
    for ticker, value in zip(("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"), (0.12, 0.10, 0.08, 0.07, 0.06, -0.01)):
        observations[ticker].update(return_1w=value / 4, return_4w=value, return_13w=value + 0.04)
    history = []
    for date, rel, advance in (("2026-06-19", 0.01, 3), ("2026-06-26", 0.02, 4), ("2026-07-03", 0.03, 4)):
        history.append({
            "data_date": date, "schema_version": "1.1", "methodology_version": "1.1.0", "theme_master_version": "fixture-1",
            "themes": {"fixture_theme": {"equal_weight_rel_spy_4w": rel, "advance_count_4w": advance, "above_50dma_count": advance, "pct_above_50dma": advance / 6, "volume_ratio_20d_60d": 1.0}},
        })
    previous = {"source": "output/judgments/index.json", "available": False, "latest_data_date": None, "records": []}
    return config, master, observations, history, previous


def build_synthetic(observations_order=None):
    config, master, observations, history, previous = synthetic_inputs()
    if observations_order == "reverse":
        observations = dict(reversed(list(observations.items())))
    return build_snapshot(
        config=config, theme_master=master, observations=observations, history=history, previous_judgments=previous,
        generated_at=dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc), data_date="2026-07-10", source_commit="a" * 40,
    )


class PipelineContractTests(unittest.TestCase):
    def test_offline_synthetic_end_to_end(self):
        value = build_synthetic()
        validate_schema(value, load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"))
        validate_latest_semantics(value, verify_source_hash=True)
        self.assertEqual(value["meta"]["schema_version"], "1.1")
        self.assertEqual(value["meta"]["methodology_version"], "1.1.0")

    def test_fixed_input_clock_source_is_reproducible(self):
        first = build_synthetic()
        self.assertEqual(first, build_synthetic())
        config, master, observations, history, previous = synthetic_inputs()
        changed_commit = build_snapshot(
            config=config, theme_master=master, observations=observations, history=history, previous_judgments=previous,
            generated_at=dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc), data_date="2026-07-10", source_commit="b" * 40,
        )
        changed_observations = copy.deepcopy(observations); changed_observations["AAA"]["return_4w"] += 0.001
        changed_input = build_snapshot(
            config=config, theme_master=master, observations=changed_observations, history=history, previous_judgments=previous,
            generated_at=dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc), data_date="2026-07-10", source_commit="a" * 40,
        )
        self.assertNotEqual(first["meta"]["run_id"], changed_commit["meta"]["run_id"])
        self.assertNotEqual(first["meta"]["run_id"], changed_input["meta"]["run_id"])

    def test_observation_input_order_is_irrelevant(self):
        self.assertEqual(build_synthetic(), build_synthetic("reverse"))

    def test_pipeline_keeps_phase_and_direction_separate(self):
        classifications = build_synthetic()["themes"]["fixture_theme"]["classifications"]
        self.assertIn(classifications["phase"], {"initial", "diffusion", "price_overheat", "unclassifiable"})
        self.assertIn(classifications["direction"], {"improving", "flat", "worsening", "outflow_signal", "unclassifiable"})

    def test_atomic_write_replaces_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            atomic_write_json(path, {"status": "old"})
            atomic_write_json(path, {"status": "new"})
            self.assertEqual(load_json(path), {"status": "new"})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_failed_validation_does_not_overwrite_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            atomic_write_json(path, {"status": "success"})
            invalid = build_synthetic()
            invalid["meta"]["schema_version"] = "2.0"
            with self.assertRaises(ContractError):
                validate_schema(invalid, load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"))
            self.assertEqual(load_json(path), {"status": "success"})

    def test_judgment_index_and_projection(self):
        schema = load_json(ROOT / "schemas" / "judgment_record.schema.json")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "judgment.json"
            target.write_bytes((FIXTURES / "judgment_record.json").read_bytes())
            source = load_json(FIXTURES / "latest_normal.json")
            index = build_index(Path(directory), schema, lambda _: source)
            current = load_json(FIXTURES / "latest_normal.json")
            current["themes"]["fixture_theme"]["metrics"]["equal_weight_rel_spy_4w"] = -0.02
            current["history_weekly"][-1]["themes"]["fixture_theme"]["equal_weight_rel_spy_4w"] = -0.01
            projection = project_previous_judgments(index, current, current["history_weekly"])
            self.assertTrue(projection["available"])
            self.assertEqual(projection["records"][0]["research_priority_rule"], "P1")
            self.assertEqual(
                projection["records"][0]["withdrawal_evaluations"][0],
                {"condition_id": "W_FIXTURE_REL4_NEG_2W", "status": "triggered", "observed_weeks": 2},
            )

    def test_judgment_byte_change_breaks_index(self):
        schema = load_json(ROOT / "schemas" / "judgment_record.schema.json")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "judgment.json"
            target.write_bytes((FIXTURES / "judgment_record.json").read_bytes())
            source = load_json(FIXTURES / "latest_normal.json")
            index = build_index(Path(directory), schema, lambda _: source)
            value = load_json(target)
            value["theme_judgments"][0]["one_line"] += " changed"
            target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ContractError):
                verify_index(Path(directory), index, schema, lambda _: source)

    def test_legacy_is_rejected_by_default(self):
        legacy = {"meta": {"schema_version": "1.0"}, "themes": {}}
        with self.assertRaises(UnsupportedLegacyVersion):
            read_legacy_snapshot(legacy)

    def test_explicit_legacy_outflow_mapping_does_not_guess_phase(self):
        legacy = {"meta": {"schema_version": "1.0"}, "themes": {"x": {"phase_assessment": {"phase": "流出"}}}}
        report = read_legacy_snapshot(legacy, explicit=True)
        mapping = report["theme_mappings"][0]
        self.assertEqual((mapping["phase"], mapping["direction"]), ("unclassifiable", "outflow_signal"))
        self.assertFalse(report["publishable"])

    def test_latest_rejects_unknown_property(self):
        value = load_json(FIXTURES / "latest_normal.json")
        value["unexpected"] = True
        with self.assertRaises(ContractError):
            validate_schema(value, load_json(ROOT / "schemas" / "rotation_snapshot.schema.json"))

    def test_judgment_rejects_future_outcome(self):
        value = load_json(FIXTURES / "judgment_record.json")
        value["future_outcome"] = 1.0
        with self.assertRaises(ContractError):
            validate_schema(value, load_json(ROOT / "schemas" / "judgment_record.schema.json"))

    def test_custom_gpt_instruction_contract(self):
        text = (ROOT / "docs" / "custom_gpt_instructions_v1.2.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text), 8000)
        for required in ("更新", "次", "詳細", "用語", "再評価", "user_view.phases", "candidate_buckets", "initial_observation", "資金流入・流出を断定しない"):
            self.assertIn(required, text)

    def test_daily_screen_contract_is_not_present(self):
        current = (ROOT / "schemas" / "rotation_snapshot.schema.json").read_text(encoding="utf-8")
        self.assertNotIn('"1.3"', current)


if __name__ == "__main__":
    unittest.main()
