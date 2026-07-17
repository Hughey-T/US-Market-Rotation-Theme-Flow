import copy
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from rotation.consumer import build_consumer_details, build_consumer_snapshot
from rotation.judgments import evaluate_withdrawal
from rotation.provenance import canonical_bytes, snapshot_source_hash
from rotation.publication import load_current_generation, publish_generation
from rotation.regime import classify_market_regime
from rotation.validation import ContractError, load_json, validate_latest_semantics, validate_public_latest, validate_schema
from scripts import generate_weekly
from scripts import validate_repository as repository_validator
from scripts.commit_weekly_outputs import commit_weekly_outputs
from scripts.export_current_latest import export_current
from scripts.export_consumer_projection import export_consumer_projection
from scripts.export_consumer_details import export_consumer_details
from scripts.validate_repository import validate_public_outputs
from tests.test_pipeline_contract import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
LATEST_SCHEMA = load_json(ROOT / "schemas" / "rotation_snapshot.schema.json")
DATES = pd.bdate_range(end="2026-07-10", periods=253)


def export_consumers(output):
    export_current(output, output / "consumer/latest.json")
    export_consumer_projection(output, output / "consumer/v1/latest.json")
    export_consumer_details(output, output / "consumer/v1/details")


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


def run_main(master, profile, history, *, reverse=False, omit_spy=False, output=None, mutate_frames=None):
    config, frames = raw_inputs(master, profile, reverse=reverse, omit_spy=omit_spy)
    if mutate_frames:
        mutate_frames(frames, config)
    temporary = tempfile.TemporaryDirectory() if output is None else None
    root = Path(temporary.name) if temporary else output.parent
    output = output or root / "output"
    config_path, master_path = root / "config.json", root / "themes.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    master_path.write_text(json.dumps(master), encoding="utf-8")
    (output / "judgments").mkdir(parents=True, exist_ok=True)
    judgment_index = output / "judgments" / "index.json"
    if not judgment_index.exists():
        judgment_index.write_text('{"index_version":"1.0","records":[]}\n', encoding="utf-8")

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
        stack.enter_context(mock.patch.object(generate_weekly, "load_history", return_value=history))
        stack.enter_context(mock.patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}))
        result = generate_weekly.main([])
    current = load_current_generation(output)
    latest = current[3] if current else None
    return result, latest, output, temporary


class ProductionOrchestrationE2E(unittest.TestCase):
    def test_main_placeholder_shape_bootstraps_publication_remote(self):
        _, master, _, _, _ = synthetic_inputs()
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (3, 4, 5))
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            checkout = temporary / "checkout"
            work = temporary / "work"
            remote = temporary / "publication.git"
            verified = temporary / "verified"
            shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"))
            shutil.copytree(checkout, work)
            subprocess.run(["git", "init", "-b", "main"], cwd=work, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "baseline"],
                cwd=work, check=True, capture_output=True,
            )
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=work, check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "main:main"], cwd=work, check=True, capture_output=True)
            main_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=work, check=True, capture_output=True, text=True,
            ).stdout.strip()
            output = work / "output"
            self.assertFalse((output / "current.json").exists())
            self.assertFalse((output / "latest.json").exists())
            self.assertEqual(
                [path.relative_to(output).as_posix() for path in sorted((output / "archive").iterdir())],
                ["archive/.gitkeep"],
            )
            self.assertEqual(generate_weekly.classify_publication_start_state(output).kind, "clean")

            for relative in ("judgments/secret.txt", "generations/secret.txt"):
                injected = output / relative
                injected.parent.mkdir(parents=True, exist_ok=True)
                injected.write_text("sensitive body", encoding="utf-8")
                acquisition = mock.Mock(side_effect=AssertionError("acquisition must not start"))
                with mock.patch.object(generate_weekly, "OUTPUT", output), mock.patch.object(
                    generate_weekly, "download_observations", acquisition,
                ):
                    with self.assertRaises(RuntimeError):
                        generate_weekly.main([])
                acquisition.assert_not_called()
                self.assertFalse((output / "current.json").exists())
                injected.unlink()
                if injected.parent.name == "generations":
                    injected.parent.rmdir()

            result, latest, _, _ = run_main(master, "p1", history, output=output)
            self.assertEqual(result, 0)
            validate_schema(latest, LATEST_SCHEMA, "main-shaped bootstrap latest")
            validate_public_latest(latest, verify_source_hash=True)
            export_consumers(output)
            subprocess.run(["git", "switch", "-c", "publication"], cwd=work, check=True, capture_output=True)
            current = load_current_generation(output)
            for injected in (output / "judgments/secret.txt", current[1] / "secret.txt"):
                injected.write_text("sensitive body", encoding="utf-8")
                with self.assertRaises(ContractError):
                    commit_weekly_outputs(work, push=True, bootstrap=True)
                self.assertEqual(
                    subprocess.run(
                        ["git", "ls-remote", "--heads", "origin", "refs/heads/publication"],
                        cwd=work, check=True, capture_output=True, text=True,
                    ).stdout.strip(),
                    "",
                )
                injected.unlink()
            self.assertTrue(commit_weekly_outputs(work, push=True, bootstrap=True))

            self.assertEqual(
                subprocess.run(
                    ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
                    check=True, capture_output=True, text=True,
                ).stdout.strip(),
                main_sha,
            )
            changed = subprocess.run(
                ["git", "diff", "--name-only", "main..publication"],
                cwd=work, check=True, capture_output=True, text=True,
            ).stdout.splitlines()
            self.assertTrue(changed)
            self.assertTrue(all(
                path == "output/current.json" or path.startswith("output/consumer/")
                or path.startswith("output/generations/")
                or path.startswith("output/judgments/")
                for path in changed
            ), changed)

            subprocess.run(
                ["git", "clone", "--branch", "publication", str(remote), str(verified)],
                check=True, capture_output=True,
            )
            with mock.patch.object(repository_validator, "ROOT", verified):
                self.assertEqual(repository_validator.main(), 0)
                unknown = verified / "output/generations/secret.txt"
                unknown.write_text("remote tamper", encoding="utf-8")
                self.assertEqual(repository_validator.main(), 1)
                unknown.unlink()
                self.assertEqual(repository_validator.main(), 0)
            current = load_current_generation(verified / "output")
            self.assertIsNotNone(current)
            regenerated = temporary / "consumer-latest.json"
            export_current(verified / "output", regenerated)
            self.assertEqual((verified / "output" / "consumer" / "latest.json").read_bytes(), regenerated.read_bytes())
            regenerated_projection = temporary / "consumer-v1-latest.json"
            export_consumer_projection(verified / "output", regenerated_projection)
            self.assertEqual((verified / "output/consumer/v1/latest.json").read_bytes(), regenerated_projection.read_bytes())

    def test_raw_dataframe_regime_or_and_trend_contrary_evidence(self):
        _, master, _, _, _ = synthetic_inputs()
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5))

        def set_return(frame, oldest, middle, current):
            frame = frame.copy()
            for denominator in (-32, -27, -22):
                frame.iloc[denominator, frame.columns.get_loc("Close")] = 100.0
            for endpoint, value in zip((-11, -6, -1), (oldest, middle, current)):
                frame.iloc[endpoint, frame.columns.get_loc("Close")] = value
            return frame

        def regime_profiles(frames, config):
            frames["SPY"] = set_return(frames["SPY"], 101.0, 101.0, 101.0)
            frames["QQQ"] = set_return(frames["QQQ"], 104.0, 104.0, 104.0)
            frames["RSP"] = set_return(frames["RSP"], 94.0, 96.0, 98.0)
            frames["IWM"] = set_return(frames["IWM"], 94.0, 96.0, 98.0)
            for ticker in config["sectors"]:
                frames[ticker] = set_return(frames[ticker], 99.0, 99.0, 99.0)
            frames["XLE"] = set_return(frames["XLE"], 101.0, 101.0, 101.0)
            frames["GLD"] = set_return(frames["GLD"], 99.0, 99.0, 99.0)
            frames["DBC"] = set_return(frames["DBC"], 108.0, 106.0, 104.0)

        result, latest, _, temporary = run_main(master, "p1", history, mutate_frames=regime_profiles)
        try:
            self.assertEqual(result, 0)
            regime = latest["market_regime"]
            self.assertEqual(regime["inputs"]["rsp_minus_spy_4w_trend_3w"], "improving")
            self.assertEqual(regime["inputs"]["dbc_rel_spy_4w_trend_3w"], "worsening")
            self.assertEqual(
                regime["candidate_flags"]["real_asset_leadership"]["matched_conditions"],
                ["R_REAL_DBC2", "R_REAL_GLD_OR_XLE_NONNEG"],
            )
            self.assertIn("R_LG_RSP_OR_IWM_IMPROVING_CONTRARY", regime["classification"]["contrary_evidence"])
            self.assertIn("R_REAL_DBC_WORSENING_CONTRARY", regime["classification"]["contrary_evidence"])
        finally:
            temporary.cleanup()

    def test_main_different_clock_retry_recovers_orphan_after_rename(self):
        _, master, _, _, _ = synthetic_inputs()
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            original_publish = generate_weekly.publish
            def failed_publish(snapshot, index):
                return original_publish(snapshot, index, lambda step: (_ for _ in ()).throw(OSError("after rename")) if step == "generation_rename" else None)
            class FirstClock(dt.datetime):
                @classmethod
                def now(cls, tz=None): return cls(2026, 7, 11, tzinfo=tz)
            with mock.patch.object(generate_weekly, "publish", side_effect=failed_publish), mock.patch.object(generate_weekly.dt, "datetime", FirstClock):
                with self.assertRaisesRegex(OSError, "after rename"):
                    run_main(master, "p1", history, output=output)
            self.assertFalse((output / "current.json").exists())
            class RetryClock(dt.datetime):
                @classmethod
                def now(cls, tz=None): return cls(2026, 7, 12, tzinfo=tz)
            with mock.patch.object(generate_weekly.dt, "datetime", RetryClock):
                result, latest, _, _ = run_main(master, "p1", history, output=output)
            self.assertEqual(result, 0)
            self.assertEqual(latest["meta"]["generated_at"], "2026-07-11T00:00:00Z")
            self.assertEqual(len(list((output / "generations").iterdir())), 1)
            self.assertEqual(len(generate_weekly.committed_history(output)), 1)
            self.assertEqual(load_current_generation(output)[5]["records"], [])
            self.assertEqual(list(output.glob(".staging-*")), [])
            self.assertFalse((output / ".publish.lock").exists())
    def test_market_data_edge_normalization_and_missingness_contract(self):
        _, master, _, _, _ = synthetic_inputs()
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5))
        members = [member["ticker"] for member in master["themes"][0]["members"]]

        def run_case(label, mutator):
            result, latest, _, temporary = run_main(master, "p1", history, mutate_frames=mutator)
            try:
                self.assertEqual(result, 0, label)
                self.assertEqual(latest["meta"]["status"], "success", label)
                return latest
            finally:
                temporary.cleanup()

        normalizers = {
            "missing trading day": lambda frames, _: frames.update({ticker: frame.drop(frame.index[-30]) for ticker, frame in frames.items()}),
            "weekend return window": lambda frames, _: None,
            "duplicated date index": lambda frames, _: frames.update({ticker: pd.concat([frame, frame.iloc[[-1]]]) for ticker, frame in frames.items()}),
            "unsorted date index": lambda frames, _: frames.update({ticker: frame.iloc[::-1] for ticker, frame in frames.items()}),
            "timezone index": lambda frames, _: frames.update({ticker: frame.set_axis(frame.index.tz_localize("America/New_York")) for ticker, frame in frames.items()}),
            "different ticker starts": lambda frames, _: [frames.__setitem__(ticker, frames[ticker].iloc[index * 10:]) for index, ticker in enumerate(members)],
        }
        for label, mutator in normalizers.items():
            with self.subTest(label=label):
                run_case(label, mutator)

        def all_members(transform):
            return lambda frames, _: [frames.__setitem__(ticker, transform(frames[ticker].copy())) for ticker in members]
        missing_cases = {
            "constituent calendar skew": all_members(lambda frame: frame.iloc[:-1]),
            "Close NaN": all_members(lambda frame: frame.assign(Close=frame["Close"].mask(frame.index == frame.index[-1]))),
            "Volume NaN": all_members(lambda frame: frame.assign(Volume=np.nan)),
            "60-day volume mean zero": all_members(lambda frame: frame.assign(Volume=0.0)),
            "volume zero": all_members(lambda frame: frame.assign(Volume=np.r_[frame["Volume"].iloc[:-20], np.zeros(20)])),
            "insufficient 50DMA": all_members(lambda frame: frame.iloc[-40:]),
            "insufficient 13-week": all_members(lambda frame: frame.iloc[-62:]),
            "empty DataFrame": lambda frames, _: [frames.__setitem__(ticker, pd.DataFrame(columns=["Close", "Volume"])) for ticker in members],
        }
        for label, mutator in missing_cases.items():
            with self.subTest(label=label):
                latest = run_case(label, mutator)
                theme = latest["themes"]["fixture_theme"]
                if label in {"constituent calendar skew", "Close NaN", "empty DataFrame"}:
                    self.assertEqual(theme["classifications"]["research_priority_rule"], "P0", label)
                if label == "insufficient 50DMA":
                    self.assertIsNone(theme["metrics"]["pct_above_50dma"])
                if label in {"Volume NaN", "60-day volume mean zero"}:
                    self.assertIsNone(theme["metrics"]["volume_ratio_20d_60d"], label)
                if label == "volume zero":
                    self.assertEqual(theme["metrics"]["volume_ratio_20d_60d"], 0.0)
                if label == "insufficient 13-week":
                    self.assertIsNone(theme["metrics"]["equal_weight_rel_spy_13w"])

    def test_benchmark_calendar_skew_stops_publish_and_preserves_current(self):
        _, master, _, _, _ = synthetic_inputs()
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5))
        _, _, output, temporary = run_main(master, "p1", history)
        pointer = load_current_generation(output)[0]
        try:
            def skew(frames, _config):
                frames["RSP"] = frames["RSP"].iloc[:-1]
            with self.assertRaisesRegex(RuntimeError, "critical market inputs unavailable"):
                run_main(master, "p1", history, output=output, mutate_frames=skew)
            self.assertEqual(load_current_generation(output)[0], pointer)
        finally:
            temporary.cleanup()
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
            self.assertEqual(latest["market_regime"], classify_market_regime(latest["market_regime"]["inputs"]))
            validate_schema(latest, LATEST_SCHEMA, "production-generated latest")
            validate_latest_semantics(latest, verify_source_hash=True)
            export_consumers(output)
            consumer = output / "consumer" / "v1" / "latest.json"
            self.assertEqual(validate_public_outputs(output.parent, LATEST_SCHEMA), 2)
            projected = load_json(consumer)
            self.assertNotIn("market_regime", projected)
            self.assertEqual(projected["user_view"], latest["user_view"])
            root = output.parent
            shutil.copytree(ROOT / "schemas", root / "schemas")
            shutil.copytree(ROOT / "docs", root / "docs")
            shutil.copytree(ROOT / "tests" / "fixtures", root / "tests" / "fixtures")
            (root / "data").mkdir()
            (root / "data" / "themes.json").write_text(json.dumps(master), encoding="utf-8")
            with mock.patch.object(repository_validator, "ROOT", root):
                self.assertEqual(repository_validator.main(), 0)
            with tempfile.TemporaryDirectory() as remote_directory, tempfile.TemporaryDirectory() as clone_directory:
                remote = Path(remote_directory) / "publication.git"
                subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
                subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
                subprocess.run(
                    ["git", "add", "config.json", "themes.json", "schemas", "docs", "tests", "data"],
                    cwd=root, check=True, capture_output=True,
                )
                subprocess.run(
                    ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "baseline"],
                    cwd=root, check=True, capture_output=True,
                )
                main_sha = subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
                ).stdout.strip()
                subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True, capture_output=True)
                subprocess.run(["git", "push", "origin", "main:main"], cwd=root, check=True, capture_output=True)
                subprocess.run(["git", "switch", "-c", "publication"], cwd=root, check=True, capture_output=True)
                self.assertTrue(commit_weekly_outputs(root, push=True, bootstrap=True))
                self.assertEqual(
                    subprocess.run(
                        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
                        check=True, capture_output=True, text=True,
                    ).stdout.strip(),
                    main_sha,
                )
                remote_clone = Path(clone_directory) / "publication"
                subprocess.run(
                    ["git", "clone", "--branch", "publication", str(remote), str(remote_clone)],
                    check=True, capture_output=True,
                )
                remote_current = load_current_generation(remote_clone / "output")
                self.assertIsNotNone(remote_current)
                validate_schema(remote_current[3], LATEST_SCHEMA, "remote publication latest")
                validate_public_latest(remote_current[3], verify_source_hash=True)
                self.assertEqual(
                    canonical_bytes(load_json(remote_clone / "output" / "consumer" / "latest.json")),
                    canonical_bytes(remote_current[3]),
                )
                self.assertEqual(
                    canonical_bytes(load_json(remote_clone / "output/consumer/v1/latest.json")),
                    canonical_bytes(build_consumer_snapshot(remote_current[3])),
                )
                self.assertEqual(
                    [canonical_bytes(load_json(remote_clone / f"output/consumer/v1/details/phase-{phase}.json")) for phase in range(1, 7)],
                    [canonical_bytes(item) for item in build_consumer_details(remote_current[3])],
                )
        finally:
            temporary.cleanup()

    def test_schema_valid_regime_tamper_cannot_publish_or_replace_consumer(self):
        _, master, _, _, _ = synthetic_inputs()
        history = history_for(master, (0.00, 0.01, 0.02), (4, 5, 5), (3, 4, 5))
        _, latest, output, temporary = run_main(master, "p1", history)
        try:
            consumer = output / "consumer" / "latest.json"
            export_consumers(output)
            pointer_before = (output / "current.json").read_bytes()
            consumer_before = consumer.read_bytes()
            generations_before = sorted(path.name for path in (output / "generations").iterdir())

            tampered = copy.deepcopy(latest)
            stored_confidence = tampered["market_regime"]["classification"]["confidence"]
            tampered["market_regime"]["classification"]["confidence"] = "high" if stored_confidence != "high" else "low"
            tampered["meta"]["source_sha256"] = snapshot_source_hash(tampered)
            validate_schema(tampered, LATEST_SCHEMA, "schema-valid regime tamper")
            with self.assertRaisesRegex(ContractError, "market_regime.classification.confidence"):
                publish_generation(
                    output,
                    tampered,
                    generate_weekly.history_item(tampered),
                    {"index_version": "1.0", "records": []},
                )

            self.assertEqual((output / "current.json").read_bytes(), pointer_before)
            self.assertEqual(consumer.read_bytes(), consumer_before)
            self.assertEqual(sorted(path.name for path in (output / "generations").iterdir()), generations_before)
        finally:
            temporary.cleanup()

    def test_raw_dataframe_reaches_p3_with_initial_breadth(self):
        _, master, _, _, _ = synthetic_inputs()
        members = [member["ticker"] for member in master["themes"][0]["members"]]
        history = history_for(master, (-0.03, -0.02, -0.01), (1, 1, 2), (1, 1, 2))

        def half_flat(frames, _config):
            for ticker in members[3:]:
                frame = frames[ticker].copy()
                frame["Close"] = 100.0
                frame["Volume"] = 100.0
                frames[ticker] = frame

        result, latest, _, temporary = run_main(master, "p1", history, mutate_frames=half_flat)
        try:
            self.assertEqual(result, 0)
            theme = latest["themes"]["fixture_theme"]
            classifications = theme["classifications"]
            self.assertEqual(theme["metrics"]["advance_ratio_4w"], 0.50)
            self.assertEqual(
                (classifications["phase"], classifications["direction"]),
                ("initial", "improving"),
            )
            self.assertEqual(
                (classifications["evidence"]["level"], classifications["evidence"]["direction"]),
                ("relative_preference_suggested", "inflow"),
            )
            self.assertEqual(
                (classifications["research_priority_rule"], classifications["timing_rule"]),
                ("P3", "T3"),
            )
            self.assertIn("EV_ADVANCE_25", classifications["evidence"]["matched_conditions"])
            self.assertNotIn("EV_ADVANCE_60", classifications["evidence"]["matched_conditions"])
        finally:
            temporary.cleanup()

    def test_raw_dataframe_reaches_p2_p5_and_overheat_outflow(self):
        cases = (
            ("p2", (0.00, 0.01, 0.02), (4, 5, 5), (4, 5, 5), "P2", "price_overheat", "flat"),
            ("p5", (0.03, -0.01, -0.02), (3, 2, 1), (3, 2, 1), "P5", "unclassifiable", "outflow_signal"),
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
                    if profile == "p5":
                        condition = {
                            "condition_id": "W_PRODUCTION_REL4_NEG_2W",
                            "field_path": "themes.fixture_theme.metrics.equal_weight_rel_spy_4w",
                            "operator": "<", "value": 0, "persistence_weeks": 2,
                        }
                        self.assertEqual(
                            evaluate_withdrawal(condition, latest, latest["history_weekly"]),
                            {"condition_id": "W_PRODUCTION_REL4_NEG_2W", "status": "triggered", "observed_weeks": 2},
                        )
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
