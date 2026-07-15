import datetime as dt
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_weekly.py"
SPEC = importlib.util.spec_from_file_location("generate_weekly", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MetricsTests(unittest.TestCase):
    def test_align_removes_weekend_observation(self):
        index = pd.to_datetime(["2026-07-10", "2026-07-11"])
        frame = pd.DataFrame({"Close": [100, 101], "Volume": [10, 20]}, index=index)
        aligned = MODULE.align_to_market_date(frame, dt.date(2026, 7, 10))
        self.assertEqual(list(aligned.index.date), [dt.date(2026, 7, 10)])

    def test_phase_requires_same_horizon_improvement_for_diffusion(self):
        metrics = {"rel_spy_1w": 0.02, "rel_spy_4w": 0.08, "rel_spy_13w": 0.10,
                   "eq_r_4w": 0.10, "advance_ratio_4w": 0.75, "pct_above_50dma": 0.75,
                   "pct_within_5pct_52w_high": 0.25, "volume_ratio_20d_60d": 1.1}
        no_history = MODULE.classify_phase(metrics, {}, {"available": False, "label": "比較不能"})
        improving = MODULE.classify_phase(metrics, {}, {"available": True, "label": "改善"})
        self.assertEqual(no_history["phase"], "判定不能")
        self.assertEqual(improving["phase"], "拡散")

    def test_evidence_and_cause_are_separate(self):
        metrics = {"rel_spy_4w": 0.05, "advance_ratio_4w": 0.25,
                   "pct_above_50dma": 0.4, "volume_ratio_20d_60d": 1.5}
        evidence = MODULE.classify_flow_evidence(metrics, "初動")
        cause = MODULE.classify_move_hypothesis(metrics, "初動")
        self.assertEqual(evidence["level"], "価格のみ")
        self.assertEqual(cause, "リーダー集中")

    def test_stable_hash_is_order_independent(self):
        self.assertEqual(MODULE.stable_hash({"a": 1, "b": 2}), MODULE.stable_hash({"b": 2, "a": 1}))

    def test_move_hypothesis_handles_missing_long_horizon(self):
        metrics = {"rel_spy_1w": 0.01, "rel_spy_4w": -0.01, "rel_spy_13w": None}
        self.assertEqual(MODULE.classify_move_hypothesis(metrics, "判定不能"), "不明")

    def test_full_pipeline_with_synthetic_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config" / "universe.json"
            themes = root / "data" / "themes.json"
            config.parent.mkdir(parents=True)
            themes.parent.mkdir(parents=True)
            universe = {
                "vix": "^VIX",
                "regime_assets": {"SPY": "S&P 500", "RSP": "Equal weight", "IWM": "Small"},
                "style_factor": {"IWF": "Growth"},
                "sectors": {"XLK": "Technology"},
                "industries": {"SMH": "Semiconductors"}
            }
            theme_config = {
                "version": "test",
                "themes": {"test_theme": {"label": "Test", "reference_etfs": ["SMH"],
                    "members": {"AAA": "core", "BBB": "core", "CCC": "beneficiary",
                                "DDD": "beneficiary", "EEE": "peripheral", "FFF": "peripheral"}}}
            }
            config.write_text(json.dumps(universe), encoding="utf-8")
            themes.write_text(json.dumps(theme_config), encoding="utf-8")

            tickers = {"SPY", "RSP", "IWM", "IWF", "XLK", "SMH", "^VIX", "AAA", "BBB", "CCC", "DDD", "EEE", "FFF"}
            index = pd.bdate_range("2025-01-01", periods=320)
            frames = {}
            for offset, ticker in enumerate(sorted(tickers)):
                close = pd.Series([100 + offset + i * (0.08 + offset * 0.002) for i in range(len(index))], index=index)
                frames[ticker] = pd.DataFrame({"Close": close, "Volume": 1_000_000 + offset * 1_000}, index=index)
            downloaded = pd.concat(frames, axis=1)
            fake_yf = types.SimpleNamespace(download=lambda *args, **kwargs: downloaded)

            with mock.patch.dict(sys.modules, {"yfinance": fake_yf}), \
                 mock.patch.object(MODULE, "ROOT", root), \
                 mock.patch.object(MODULE, "CONFIG_PATH", config), \
                 mock.patch.object(MODULE, "THEMES_PATH", themes), \
                 mock.patch.object(MODULE, "OUT_DIR", root / "output"), \
                 mock.patch.object(MODULE, "HIST_DIR", root / "output" / "history"), \
                 mock.patch.object(MODULE, "ARCHIVE_DIR", root / "output" / "archive"), \
                 mock.patch.object(MODULE, "PRED_DIR", root / "output" / "predictions"):
                MODULE.main()

            latest = json.loads((root / "output" / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["meta"]["status"], "success")
            self.assertTrue(latest["meta"]["analysis_ready"])
            self.assertEqual(latest["themes"]["test_theme"]["coverage"]["ratio"], 1.0)
            self.assertEqual(latest["history_weekly"], [])
            self.assertEqual(len(list((root / "output" / "archive").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
