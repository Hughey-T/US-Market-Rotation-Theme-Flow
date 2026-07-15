import copy
import json
import os
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from rotation.publication import load_current_generation
from rotation.validation import load_json
from scripts import generate_weekly
from scripts import validate_repository as repository_validator
from scripts.validate_repository import validate_public_outputs
from tests.test_pipeline_contract import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
LATEST_SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")
DATES = pd.bdate_range(end="2026-07-10", periods=253)


def raw_frame(profile="market", volume_tail=130.0):
    if profile == "p1":
        close = np.r_[np.full(189, 100.0), np.linspace(100.0, 112.0, 64)]
    elif profile == "p2":
        close = np.r_[np.full(189, 100.0), np.linspace(100.0, 125.0, 64)]
    elif profile == "p5":
        close = np.r_[np.full(189, 100.0), np.linspace(100.0, 90.0, 64)]
    elif profile == "overheat_outflow":
        close = np.r_[np.full(189, 100.0), np.linspace(100.0, 124.0, 14), np.full(28, 124.0), np.linspace(124.0, 120.0, 22)]
    elif profile == "below50_positive4w":
        close = np.r_[np.full(193, 120.0), np.linspace(120.0, 90.0, 39), np.linspace(90.0, 95.0, 21)]
    else:
        close = np.r_[np.full(189, 100.0), np.linspace(100.0, 104.0, 64)]
    volume = np.full(253, 100.0)
    volume[-20:] = volume_tail
    return pd.DataFrame({"Close": close, "Volume": volume}, index=DATES)


def raw_inputs(master, profile, *, reverse=False, omit_spy=False):
    config, _, _, _, _ = synthetic_inputs()
    market = generate_weekly.configured_market_tickers(config)
    members = [member["ticker"] for theme in master["themes"] for member in theme["members"]]
    frames = {ticker: raw_frame("market", 110.0) for ticker in market}
    frames["SPY"] = raw_frame("market", 100.0)
    tail = 180.0 if profile in {"p2", "overheat_outflow"} else 140.0 if profile == "p5" else 130.0
    for ticker in members:
        frames[ticker] = raw_frame(profile, tail)
    if omit_spy:
        frames.pop("SPY", None)
    if reverse:
        frames = dict(reversed(list(frames.items())))
    return config, frames


def history_for(master, rels, advances, above_counts):
    values = []
    for data_date, rel, advance, above in zip(("2026-06-19", "2026-06-26", "2026-07-03"), rels, advances, above_counts):
        values.append({
            "data_date": data_date,
            "schema_version": "1.1",
            "methodology_version": "1.1.0",
            "theme_master_version": master["theme_master_version"],
            "themes": {
                theme["theme_id"]: {
                    "equal_weight_rel_spy_4w": rel,
                    "advance_count_4w": advance,
                    "above_50dma_count": above,
                    "pct_above_50dma": above / max(1, len(theme["members"])),
                    "volume_ratio_20d_60d": 1.0,
                }
                for theme in master["themes"]
            },
        })
    return values


def run_main(master, profile, history, *, reverse=False, omit_spy=False, output=None):
    config, frames = raw_inputs(master, profile, reverse=reverse, omit_spy=omit_spy)
    temporary = tempfile.TemporaryDirectory() if output is None else None
    root = Path(temporary.name) if temporary else output.parent
    output = output or root / "output"
    config_path, master_path = root / "config.json", root / "themes.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    master_path.write_text(json.dumps(master), encoding="utf-8")
    legacy_history = output / "history"
    legacy_history.mkdir(parents=True, exist_ok=True)
    for row in history:
        (legacy_history / f"{row['data_date']}.json").write_text(json.dumps(row), encoding="utf-8")
    (output / "judgments").mkdir(parents=True, exist_ok=True)

    def download(tickers, **_kwargs):
        requested = list(tickers) if not isinstance(tickers, str) else [tickers]
        selected = {ticker: frames[ticker] for ticker in requested if ticker in frames}
        return pd.concat(selected, axis=1) if selected else pd.DataFrame()

    with ExitStack() as stack:
        stack.enter_context(mock.patch("yfinance.download", side_effect=download))
        stack.enter_context(mock.patch.object(generate_weekly, "ROOT", root))
        stack.enter_context(mock.patch.object(generate_weekly, "CONFIG", config_path))
        stack.enter_context(mock.patch.object(generate_weekly, "MASTER", master_path))
        stack.enter_context(mock.patch.object(generate_weekly, "OUTPUT", output))
        stack.enter_context(mock.patch.object(generate_weekly, "HISTORY", output / "history"))
        stack.enter_context(mock.patch.object(generate_weekly, "JUDGMENTS", output / "judgments"))
        stack.enter_context(mock.patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}))
        result = generate_weekly.main([])
    current = load_current_generation(output)
    latest = current[3] if current else None
    return result, latest, output, temporary


class ProductionOrchestrationE2E(unittest.TestCase):
    def test_raw_dataframe_p1_success_publish_membership_and_repository_validation(self):
        _, master, _, _, _ = synthetic_inputs()
        future = copy.deepcopy(master["themes"][0]["members"][0]); future.update(ticker="FUTURE", valid_from="2026-07-11")
        expired = copy.deepcopy(master["themes"][0]["members"][1]); expired.update(ticker="EXPIRED", valid_from="2026-01-01", valid_to="2026-07-09")
        master["themes"][0]["members"].extend((future, expired))
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (3, 4, 5))
        result, latest, output, temporary = run_main(master, "p1", history)
        try:
            self.assertEqual(result, 0)
            theme = latest["themes"]["fixture_theme"]
            self.assertEqual(theme["classifications"]["research_priority_rule"], "P1")
            self.assertTrue(all(row["ticker"] not in {"FUTURE", "EXPIRED"} for row in theme["constituents"]))
            self.assertTrue(theme["metrics"]["pct_above_50dma"] >= 0.60)
            self.assertTrue(theme["metrics"]["volume_ratio_20d_60d"] >= 1.10)
            self.assertEqual(validate_public_outputs(output.parent, LATEST_SCHEMA), 1)
            root = output.parent
            shutil.copytree(ROOT / "schemas", root / "schemas")
            shutil.copytree(ROOT / "docs", root / "docs")
            shutil.copytree(ROOT / "tests" / "fixtures", root / "tests" / "fixtures")
            (root / "data").mkdir()
            (root / "data" / "themes.json").write_text(json.dumps(master), encoding="utf-8")
            with mock.patch.object(repository_validator, "ROOT", root):
                self.assertEqual(repository_validator.main(), 0)
        finally:
            temporary.cleanup()

    def test_raw_dataframe_reaches_p2_p5_and_overheat_outflow(self):
        cases = (
            ("p2", (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5), "P2", "price_overheat", "flat"),
            ("p5", (0.08, 0.04, 0.00), (3, 2, 1), (3, 2, 1), "P5", "unclassifiable", "outflow_signal"),
            ("overheat_outflow", (0.08, 0.04, 0.00), (4, 3, 2), (4, 3, 2), "P4", "price_overheat", "outflow_signal"),
        )
        for profile, rels, advances, above, rule, phase, direction in cases:
            with self.subTest(profile=profile):
                _, master, _, _, _ = synthetic_inputs()
                result, latest, _, temporary = run_main(master, profile, history_for(master, rels, advances, above))
                try:
                    classification = latest["themes"]["fixture_theme"]["classifications"]
                    self.assertEqual(result, 0)
                    self.assertEqual((classification["research_priority_rule"], classification["phase"], classification["direction"]), (rule, phase, direction))
                finally:
                    temporary.cleanup()

    def test_raw_close_50dma_only_improving_and_worsening(self):
        for profile, rels, above, expected in (
            ("p1", (0.00, 0.01, 0.02), (3, 4, 5), "improving"),
            ("below50_positive4w", (0.08, 0.06, 0.04), (6, 5, 4), "worsening"),
        ):
            with self.subTest(expected=expected):
                _, master, _, _, _ = synthetic_inputs()
                history = history_for(master, rels, (6, 6, 6), above)
                _, latest, _, temporary = run_main(master, profile, history)
                try:
                    theme = latest["themes"]["fixture_theme"]
                    self.assertEqual(theme["trends"]["advance_breadth_trend_3w"], "flat")
                    self.assertEqual(theme["trends"]["above_50dma_breadth_trend_3w"], expected)
                    self.assertEqual(theme["classifications"]["direction"], expected)
                finally:
                    temporary.cleanup()

    def test_raw_input_order_tie_break_max_five_and_no_backfill(self):
        _, base, _, _, _ = synthetic_inputs()
        template = base["themes"][0]
        themes = []
        for theme_id in "gfedcba":
            theme = copy.deepcopy(template); theme["theme_id"] = theme_id
            for index, member in enumerate(theme["members"]):
                member["ticker"] = f"{theme_id.upper()}{index}"
            themes.append(theme)
        master = dict(base, themes=themes)
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5))
        _, first, _, temp1 = run_main(master, "p1", history)
        _, second, _, temp2 = run_main(dict(master, themes=list(reversed(themes))), "p1", history, reverse=True)
        try:
            self.assertEqual(first["theme_shortlist"]["selected_theme_ids"], ["a", "b", "c", "d", "e"])
            self.assertEqual(first["theme_shortlist"], second["theme_shortlist"])
        finally:
            temp1.cleanup(); temp2.cleanup()
        two = dict(master, themes=[theme for theme in themes if theme["theme_id"] in {"a", "b"}])
        _, latest, _, temporary = run_main(two, "p1", history_for(two, (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5)))
        try:
            self.assertEqual(latest["theme_shortlist"]["selected_theme_ids"], ["a", "b"])
        finally:
            temporary.cleanup()

    def test_raw_critical_missing_rejects_publish_and_preserves_current(self):
        _, master, _, _, _ = synthetic_inputs()
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5))
        _, original, output, temporary = run_main(master, "p1", history)
        pointer = load_current_generation(output)[0]
        try:
            with self.assertRaisesRegex(RuntimeError, "SPY is unavailable"):
                run_main(master, "p1", history, omit_spy=True, output=output)
            self.assertEqual(load_current_generation(output)[0], pointer)
            self.assertEqual(load_current_generation(output)[3], original)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
