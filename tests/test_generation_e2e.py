import copy
import datetime as dt
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rotation.membership import member_is_effective
from rotation.pipeline import build_snapshot
from rotation.validation import ContractError, load_json, validate_judgment_semantics, validate_latest_semantics, validate_schema
from scripts import generate_weekly
from scripts.generate_weekly import configured_tickers
from tests.test_pipeline_contract import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
LATEST_SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")
NOW = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
DATA_DATE = "2026-07-10"


def generate(config, master, observations, history, previous=None):
    previous = previous or {"source": "output/judgments/index.json", "available": False, "latest_data_date": None, "records": []}
    value = build_snapshot(
        config=config, theme_master=master, observations=observations, history=history,
        previous_judgments=previous, generated_at=NOW, data_date=DATA_DATE, source_commit="a" * 40,
    )
    validate_schema(value, LATEST_SCHEMA, "raw generated latest")
    validate_latest_semantics(value, verify_source_hash=True)
    return value


def judgment_from_source(source):
    record = load_json(FIXTURES / "judgment_record.json")
    meta = source["meta"]
    for field in ("run_id", "data_date", "source_commit", "source_snapshot", "source_sha256"):
        record[field] = meta[field]
    record["regime"] = copy.deepcopy(source["market_regime"]["classification"])
    source_theme = source["themes"]["fixture_theme"]
    theme = record["theme_judgments"][0]
    classifications = source_theme["classifications"]
    for field in ("phase", "direction", "research_priority", "research_priority_rule", "timing_status", "timing_rule"):
        theme[field] = classifications[field]
    theme["evidence"] = copy.deepcopy(classifications["evidence"])
    theme["selected_for_deep_dive"] = source_theme["selected_for_deep_dive"]
    theme["shortlist_rank"] = source_theme["shortlist_rank"]
    theme["shortlist_reason_codes"] = copy.deepcopy(source_theme["shortlist_reason_codes"])
    quality = source_theme["quality"]
    theme["data_quality"] = {
        "classification_eligible": quality["classification_eligible"],
        "coverage_ratio": quality["coverage_ratio"],
        "valid_constituent_count": quality["valid_constituent_count"],
        "history_weeks": quality["history_weeks"],
        "missing_required_fields": copy.deepcopy(quality["missing_required_fields"]),
        "quality_reasons": copy.deepcopy(quality["quality_reasons"]),
    }
    theme["matched_conditions"] = copy.deepcopy(source_theme["condition_flags"]["matched_conditions"])
    theme["unmatched_conditions"] = copy.deepcopy(source_theme["condition_flags"]["unmatched_conditions"])
    for field in theme["key_metrics"]:
        theme["key_metrics"][field] = source_theme["metrics"][field]
    return record


class RawGenerationE2E(unittest.TestCase):
    def test_T50_50dma_only_breadth_improvement_drives_direction(self):
        config, master, observations, history, previous = synthetic_inputs()
        latest = generate(config, master, observations, history, previous)
        theme = latest["themes"]["fixture_theme"]
        self.assertEqual(theme["trends"]["advance_breadth_trend_3w"], "flat")
        self.assertEqual(theme["trends"]["above_50dma_breadth_trend_3w"], "improving")
        self.assertEqual(theme["classifications"]["direction"], "improving")

    def test_T51_50dma_only_breadth_worsening_drives_direction(self):
        config, master, observations, history, previous = synthetic_inputs()
        members = {member["ticker"] for member in master["themes"][0]["members"]}
        for ticker in members:
            observations[ticker].update(return_4w=0.04, above_50dma=False)
        for item, rel, advance, above in zip(history, (0.08, 0.06, 0.04), (5, 5, 5), (6, 5, 4)):
            row = item["themes"]["fixture_theme"]
            row.update(equal_weight_rel_spy_4w=rel, advance_count_4w=advance, above_50dma_count=above, pct_above_50dma=above / 6)
        latest = generate(config, master, observations, history, previous)
        theme = latest["themes"]["fixture_theme"]
        self.assertEqual(theme["trends"]["advance_breadth_trend_3w"], "flat")
        self.assertEqual(theme["trends"]["above_50dma_breadth_trend_3w"], "worsening")
        self.assertEqual(theme["classifications"]["direction"], "worsening")

    def test_T52_point_in_time_membership_boundaries_and_acquisition_scope(self):
        config, master, observations, history, previous = synthetic_inputs()
        members = master["themes"][0]["members"]
        members[0].update(valid_from="2026-07-11", valid_to=None, active=True)
        members[1].update(valid_from="2026-07-10", valid_to=None, active=True)
        members[2].update(valid_from="2026-01-01", valid_to="2026-07-10", active=True)
        members[3].update(valid_from="2026-01-01", valid_to="2026-07-09", active=True)
        members[4].update(valid_from="2026-01-01", valid_to=None, active=True)
        members[5].update(valid_from="2026-01-01", valid_to=None, active=False)
        self.assertEqual([member_is_effective(member, DATA_DATE) for member in members], [False, True, True, False, True, False])
        requested = set(configured_tickers(config, master, DATA_DATE))
        self.assertEqual(requested.intersection({member["ticker"] for member in members}), {members[index]["ticker"] for index in (1, 2, 4)})
        latest = generate(config, master, observations, history, previous)
        theme = latest["themes"]["fixture_theme"]
        self.assertEqual(theme["quality"]["constituent_count"], 3)
        self.assertFalse(theme["quality"]["classification_eligible"])

    def test_T65_raw_generation_reaches_P1_P2_P5_and_projects_judgment(self):
        config, master, observations, history, previous = synthetic_inputs()
        p1 = generate(config, master, observations, history, previous)
        self.assertEqual(p1["themes"]["fixture_theme"]["classifications"]["research_priority_rule"], "P1")
        validate_judgment_semantics(judgment_from_source(p1), p1)

        config, master, observations, history, previous = synthetic_inputs()
        members = {member["ticker"] for member in master["themes"][0]["members"]}
        for ticker in members:
            observations[ticker].update(return_13w=0.25, volume_ratio_20d_60d=1.30, within_5pct_52w_high=True)
        p2 = generate(config, master, observations, history, previous)
        self.assertEqual((p2["themes"]["fixture_theme"]["classifications"]["phase"], p2["themes"]["fixture_theme"]["classifications"]["research_priority_rule"]), ("price_overheat", "P2"))

        config, master, observations, history, previous = synthetic_inputs()
        members = {member["ticker"] for member in master["themes"][0]["members"]}
        for ticker in members:
            observations[ticker].update(return_1w=-0.01, return_4w=-0.01, return_13w=-0.02, above_50dma=False, within_5pct_52w_high=False, volume_ratio_20d_60d=1.20)
        for item, rel, count in zip(history, (0.08, 0.04, 0.00), (3, 2, 1)):
            item["themes"]["fixture_theme"].update(equal_weight_rel_spy_4w=rel, advance_count_4w=count, above_50dma_count=count, pct_above_50dma=count / 6)
        p5 = generate(config, master, observations, history, previous)
        self.assertEqual(p5["themes"]["fixture_theme"]["classifications"]["research_priority_rule"], "P5")

    def test_T66_raw_generation_preserves_price_overheat_and_outflow(self):
        config, master, observations, history, previous = synthetic_inputs()
        members = {member["ticker"] for member in master["themes"][0]["members"]}
        for ticker in members:
            observations[ticker].update(return_4w=-0.01, return_13w=0.25, above_50dma=False, within_5pct_52w_high=True, volume_ratio_20d_60d=1.40)
        for item, rel, count in zip(history, (0.03, 0.01, -0.01), (4, 3, 2)):
            item["themes"]["fixture_theme"].update(equal_weight_rel_spy_4w=rel, advance_count_4w=count, above_50dma_count=count, pct_above_50dma=count / 6)
        latest = generate(config, master, observations, history, previous)
        classification = latest["themes"]["fixture_theme"]["classifications"]
        self.assertEqual((classification["phase"], classification["direction"], classification["timing_rule"]), ("price_overheat", "outflow_signal", "T1"))

    def test_T67_raw_shortlist_tie_break_no_backfill_and_input_order(self):
        config, base_master, observations, _, previous = synthetic_inputs()
        template = base_master["themes"][0]
        themes = []
        history = []
        for date, rel, count in (("2026-06-19", 0.01, 3), ("2026-06-26", 0.02, 4), ("2026-07-03", 0.03, 4)):
            history.append({"data_date": date, "schema_version": "1.1", "methodology_version": "1.1.0", "theme_master_version": "fixture-1", "themes": {}})
        for theme_id in "gfedcba":
            definition = copy.deepcopy(template)
            definition["theme_id"] = theme_id
            for index, member in enumerate(definition["members"]):
                member["ticker"] = f"{theme_id.upper()}{index}"
                observations[member["ticker"]] = {"return_1w": 0.02, "return_4w": 0.07, "return_13w": 0.11, "above_50dma": True, "above_200dma": True, "within_5pct_52w_high": True, "volume_ratio_20d_60d": 1.2, "market_cap": None, "last_date": DATA_DATE, "change_4w": 0.0}
            themes.append(definition)
            for row, rel, count in zip(history, (0.01, 0.02, 0.03), (3, 4, 4)):
                row["themes"][theme_id] = {"equal_weight_rel_spy_4w": rel, "advance_count_4w": count, "above_50dma_count": count, "pct_above_50dma": count / 6, "volume_ratio_20d_60d": 1.0}
        master = dict(base_master, themes=themes)
        first = generate(config, master, observations, history, previous)
        reversed_value = generate(config, dict(master, themes=list(reversed(themes))), dict(reversed(list(observations.items()))), history, previous)
        self.assertEqual(first["theme_shortlist"]["selected_theme_ids"], ["a", "b", "c", "d", "e"])
        self.assertEqual(first["theme_shortlist"], reversed_value["theme_shortlist"])
        self.assertEqual(first["themes"]["f"]["shortlist_reason_codes"], ["SL_PRIORITY_DD_PRIORITY", "SL_EXCLUDED_TOP5_LIMIT"])

        two_theme_master = dict(master, themes=[theme for theme in themes if theme["theme_id"] in {"a", "b"}])
        two_theme = generate(config, two_theme_master, observations, history, previous)
        self.assertEqual(two_theme["theme_shortlist"]["selected_theme_ids"], ["a", "b"])
        self.assertIn("SHORTLIST_BELOW_MINIMUM_3", two_theme["theme_shortlist"]["quality_reasons"])

    def test_T68_raw_critical_missing_is_rejected_before_publish(self):
        config, master, observations, history, previous = synthetic_inputs()
        observations["SPY"]["return_4w"] = None
        snapshot = build_snapshot(
            config=config,
            theme_master=master,
            observations=observations,
            history=history,
            previous_judgments=previous,
            generated_at=NOW,
            data_date=DATA_DATE,
            source_commit="a" * 40,
        )
        self.assertEqual(snapshot["meta"]["global_quality"]["critical_missing"], ["SPY"])
        with self.assertRaisesRegex(ContractError, "critical_missing"):
            validate_latest_semantics(snapshot, verify_source_hash=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            latest_path = output / "latest.json"
            latest_path.write_bytes(b'{"status":"success"}\n')
            before = hashlib.sha256(latest_path.read_bytes()).hexdigest()
            with mock.patch.object(generate_weekly, "ROOT", root), mock.patch.object(generate_weekly, "OUTPUT", output), mock.patch.object(generate_weekly, "HISTORY", output / "history"), mock.patch.object(generate_weekly, "JUDGMENTS", output / "judgments"):
                with self.assertRaisesRegex(ContractError, "critical_missing"):
                    generate_weekly.publish(snapshot, {"index_version": "1.0", "records": []})
            self.assertEqual(hashlib.sha256(latest_path.read_bytes()).hexdigest(), before)

    def test_T69_raw_judgment_projection_mismatch_is_rejected(self):
        config, master, observations, history, previous = synthetic_inputs()
        source = generate(config, master, observations, history, previous)
        judgment = judgment_from_source(source)
        judgment["theme_judgments"][0]["research_priority_rule"] = "P5"
        with self.assertRaisesRegex(ContractError, "research_priority|source latest"):
            validate_judgment_semantics(judgment, source)

    def test_T70_old_history_without_50dma_count_is_not_inferred(self):
        config, master, observations, history, previous = synthetic_inputs()
        for item in history:
            del item["themes"]["fixture_theme"]["above_50dma_count"]
        latest = generate(config, master, observations, history, previous)
        theme = latest["themes"]["fixture_theme"]
        self.assertEqual(theme["trends"]["above_50dma_breadth_trend_3w"], "insufficient")
        self.assertIsNone(theme["trends"]["above_50dma_count_change_1w"])
        self.assertTrue(all("above_50dma_count" not in item["themes"]["fixture_theme"] for item in latest["history_weekly"]))
        generated_history = generate_weekly.history_item(latest)
        self.assertEqual(
            generated_history["themes"]["fixture_theme"]["above_50dma_count"],
            theme["metrics"]["above_50dma_count"],
        )


if __name__ == "__main__":
    unittest.main()
