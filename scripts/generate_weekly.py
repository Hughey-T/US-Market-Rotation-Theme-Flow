#!/usr/bin/env python3
"""Generate and atomically publish a validated Market Rotation 1.1 snapshot."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.judgments import build_index, project_previous_judgments
from rotation.membership import member_is_effective
from rotation.pipeline import build_snapshot
from rotation.provenance import snapshot_source_hash
from rotation.publication import committed_history, load_current_generation, publish_generation
from rotation.validation import load_json, validate_public_latest, validate_schema, validate_theme_master_semantics

CONFIG = ROOT / "config" / "universe.json"
MASTER = ROOT / "data" / "themes.json"
LATEST_SCHEMA = ROOT / "schemas" / "rotation_snapshot.schema.json"
JUDGMENT_SCHEMA = ROOT / "schemas" / "judgment_record.schema.json"
OUTPUT = ROOT / "output"
HISTORY = OUTPUT / "history"
JUDGMENTS = OUTPUT / "judgments"
PERIODS = {"1w": 5, "4w": 21, "13w": 63}
KNOWN_OUTPUT_DIRECTORIES = {
    "archive", "consumer", "generations", "history", "judgments", "predictions", "verifications",
}


@dataclass(frozen=True)
class PublicationStartState:
    kind: Literal["clean", "fixed_legacy", "partial_legacy", "ambiguous", "current"]
    path: str | None = None


def _output_path(output: Path, path: Path) -> str:
    if path == output:
        return "output"
    return f"output/{path.relative_to(output).as_posix()}"


def classify_publication_start_state(output: Path) -> PublicationStartState:
    """Classify existing publication state without changing disk or starting acquisition."""
    if not output.exists():
        return PublicationStartState("clean")
    if output.is_symlink() or not output.is_dir():
        return PublicationStartState("ambiguous", "output")

    current = output / "current.json"
    if current.is_symlink():
        return PublicationStartState("ambiguous", _output_path(output, current))
    if current.is_file():
        return PublicationStartState("current")
    if current.exists():
        return PublicationStartState("ambiguous", _output_path(output, current))

    latest = output / "latest.json"
    if latest.is_symlink():
        return PublicationStartState("ambiguous", _output_path(output, latest))
    if latest.is_file():
        return PublicationStartState("fixed_legacy", _output_path(output, latest))
    if latest.exists():
        return PublicationStartState("ambiguous", _output_path(output, latest))

    archive = output / "archive"
    if archive.is_symlink() or (archive.exists() and not archive.is_dir()):
        return PublicationStartState("ambiguous", _output_path(output, archive))
    if archive.is_dir():
        entries = sorted(archive.rglob("*"), key=lambda path: path.relative_to(output).as_posix())
        for entry in entries:
            if entry.is_symlink():
                return PublicationStartState("ambiguous", _output_path(output, entry))
        legacy_json = [entry for entry in entries if entry.is_file() and entry.suffix.lower() == ".json"]
        for entry in legacy_json:
            try:
                load_json(entry)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                return PublicationStartState("ambiguous", _output_path(output, entry))
        if legacy_json:
            return PublicationStartState("partial_legacy", _output_path(output, legacy_json[0]))
        for entry in entries:
            if entry == archive / ".gitkeep" and entry.is_file():
                continue
            return PublicationStartState("ambiguous", _output_path(output, entry))

    for entry in sorted(output.iterdir(), key=lambda path: path.name):
        if entry.name in {"archive", "current.json", "latest.json"}:
            continue
        if entry.name in KNOWN_OUTPUT_DIRECTORIES and entry.is_dir() and not entry.is_symlink():
            continue
        if entry.name == ".publish.lock" and entry.is_file() and not entry.is_symlink():
            continue
        if entry.name.startswith(".staging-") and entry.is_dir() and not entry.is_symlink():
            continue
        return PublicationStartState("ambiguous", _output_path(output, entry))
    return PublicationStartState("clean")


def enforce_publication_start_state(output: Path) -> PublicationStartState:
    state = classify_publication_start_state(output)
    if state.kind in {"clean", "current"}:
        return state
    if state.kind == "fixed_legacy":
        raise RuntimeError(
            "legacy fixed publication detected; "
            "run scripts/migrate_publication_v1.py --explicit before weekly publication"
        )
    if state.kind == "partial_legacy":
        raise RuntimeError(
            "partial legacy publication detected: "
            "archive data exists but output/latest.json is absent"
        )
    raise RuntimeError(f"ambiguous output state: unexpected path {state.path}")


def source_commit() -> str:
    value = os.environ.get("GITHUB_SHA")
    if value and len(value) == 40:
        return value.lower()
    result = subprocess.run(["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True)
    return result.stdout.strip().lower()


def get_frame(data: pd.DataFrame, ticker: str):
    try:
        frame = data[ticker] if isinstance(data.columns, pd.MultiIndex) else data
    except (KeyError, TypeError):
        return None
    if frame is None or frame.empty or "Close" not in frame or "Volume" not in frame:
        return None
    frame = frame[["Close", "Volume"]].copy()
    try:
        frame.index = pd.to_datetime(frame.index, utc=True)
    except (TypeError, ValueError):
        return None
    frame = frame.sort_index(kind="stable")
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.dropna(subset=["Close"])
    return frame if len(frame) >= 30 else None


def align_to_market_date(frame: pd.DataFrame, data_date: dt.date) -> pd.DataFrame:
    return frame.loc[[timestamp.date() <= data_date for timestamp in frame.index]]


def ret_n(close: pd.Series, periods: int):
    if len(close) <= periods:
        return None
    prior, current = close.iloc[-1 - periods], close.iloc[-1]
    if pd.isna(prior) or pd.isna(current) or prior == 0:
        return None
    return float(current / prior - 1)


def ticker_observation(frame: pd.DataFrame) -> dict:
    close, volume = frame["Close"], frame["Volume"]
    last = close.iloc[-1]
    result = {f"return_{horizon}": ret_n(close, periods) for horizon, periods in PERIODS.items()}
    result["_return_4w_weekly_3w"] = [ret_n(close.iloc[: len(close) - offset], PERIODS["4w"]) for offset in (10, 5, 0)]
    result["above_50dma"] = bool(last > close.iloc[-50:].mean()) if len(close) >= 50 else None
    result["above_200dma"] = bool(last > close.iloc[-200:].mean()) if len(close) >= 200 else None
    result["within_5pct_52w_high"] = bool(last >= close.iloc[-252:].max() * 0.95) if len(close) >= 252 else None
    volume60 = volume.iloc[-60:] if len(volume) >= 60 else None
    if volume60 is None or volume60.isna().any() or not pd.api.types.is_numeric_dtype(volume60):
        baseline = recent = None
    else:
        baseline, recent = volume60.mean(), volume.iloc[-20:].mean()
    result["volume_ratio_20d_60d"] = float(recent / baseline) if baseline is not None and recent is not None and pd.notna(recent) and baseline > 0 else None
    result["change_4w"] = float(last - close.iloc[-22]) if len(close) > 21 else None
    result["market_cap"] = None  # optional until a point-in-time source is implemented
    result["last_date"] = str(close.index[-1].date())
    return result


def configured_market_tickers(config: dict) -> list[str]:
    tickers = {config.get("vix", "^VIX"), "SPY"}
    for group in ("regime_assets", "style_factor", "sectors", "industries"):
        tickers.update(config.get(group, {}))
    return sorted(tickers)


def configured_tickers(config: dict, master: dict, data_date: str) -> list[str]:
    tickers = set(configured_market_tickers(config))
    for theme in master["themes"]:
        tickers.update(member["ticker"] for member in theme["members"] if member_is_effective(member, data_date))
    return sorted(tickers)


def download_observations(config: dict, master: dict) -> tuple[dict, str]:
    import yfinance as yf

    market_tickers = configured_market_tickers(config)
    print(f"downloading {len(market_tickers)} market tickers")
    market_data = yf.download(market_tickers, period="2y", auto_adjust=True, group_by="ticker", progress=False, threads=True)
    raw = {ticker: get_frame(market_data, ticker) for ticker in market_tickers}
    if raw.get("SPY") is None:
        raise RuntimeError("SPY is unavailable; publication stopped")
    date = raw["SPY"].index[-1].date()
    tickers = configured_tickers(config, master, str(date))
    theme_only = sorted(set(tickers) - set(market_tickers))
    if theme_only:
        print(f"downloading {len(theme_only)} effective theme tickers")
        theme_data = yf.download(theme_only, period="2y", auto_adjust=True, group_by="ticker", progress=False, threads=True)
        raw.update({ticker: get_frame(theme_data, ticker) for ticker in theme_only})
    observations = {}
    for ticker in tickers:
        frame = raw[ticker]
        if frame is None:
            observations[ticker] = {f"return_{horizon}": None for horizon in PERIODS}
            continue
        aligned = align_to_market_date(frame, date)
        # Never compare returns from different market sessions. A lagging ticker
        # remains missing; no weekend/calendar gap is converted to zero.
        if aligned.empty or aligned.index[-1].date() != date:
            observations[ticker] = {f"return_{horizon}": None for horizon in PERIODS}
            continue
        observations[ticker] = ticker_observation(aligned)
    critical = {"SPY", "RSP", "IWM", config.get("vix", "^VIX"), *config.get("sectors", {})}
    missing = sorted(ticker for ticker in critical if observations.get(ticker, {}).get("return_4w") is None)
    if missing:
        raise RuntimeError(f"critical market inputs unavailable: {', '.join(missing)}")
    return observations, str(date)


def load_history() -> list[dict]:
    committed = committed_history(OUTPUT)
    if committed:
        return committed
    values = []
    for path in sorted(HISTORY.glob("*.json")):
        try:
            values.append(load_json(path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return values[-12:]


def load_judgment_source(record: dict) -> dict:
    path = ROOT / record["source_snapshot"]
    if not path.is_file():
        raise RuntimeError(f"judgment source latest is unavailable: {path}")
    value = load_json(path)
    validate_schema(value, load_json(LATEST_SCHEMA), str(path))
    validate_public_latest(value, verify_source_hash=True)
    return value


def history_item(snapshot: dict) -> dict:
    return {
        "data_date": snapshot["meta"]["data_date"], "schema_version": "1.1", "methodology_version": "1.1.0",
        "theme_master_version": snapshot["meta"]["universe_definition"]["theme_master_version"],
        "themes": {
            theme_id: {
                "equal_weight_rel_spy_4w": theme["metrics"]["equal_weight_rel_spy_4w"],
                "advance_count_4w": theme["metrics"]["advance_count_4w"],
                "above_50dma_count": theme["metrics"]["above_50dma_count"],
                "pct_above_50dma": theme["metrics"]["pct_above_50dma"],
                "volume_ratio_20d_60d": theme["metrics"]["volume_ratio_20d_60d"],
            }
            for theme_id, theme in snapshot["themes"].items()
        },
    }


def publish(snapshot: dict, index: dict, failure_injector=None) -> dict:
    return publish_generation(OUTPUT, snapshot, history_item(snapshot), index, failure_injector)


def validate_fixture(path: Path) -> int:
    snapshot = load_json(path)
    validate_schema(snapshot, load_json(LATEST_SCHEMA), str(path))
    validate_public_latest(snapshot, verify_source_hash=False)
    print(f"offline fixture valid: {path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="generate and validate without publishing")
    parser.add_argument("--fixture", type=Path, help="validate an offline latest fixture; no network or writes")
    args = parser.parse_args(argv)
    if args.fixture:
        return validate_fixture(args.fixture)
    enforce_publication_start_state(OUTPUT)
    config, master = load_json(CONFIG), load_json(MASTER)
    validate_theme_master_semantics(master)
    observations, data_date = download_observations(config, master)
    history = load_history()
    judgment_schema = load_json(JUDGMENT_SCHEMA)
    index = build_index(JUDGMENTS, judgment_schema, load_judgment_source)
    empty_projection = {"source": "output/judgments/index.json", "available": False, "latest_data_date": None, "records": []}
    generated_at = dt.datetime.now(dt.timezone.utc)
    snapshot = build_snapshot(config=config, theme_master=master, observations=observations, history=history, previous_judgments=empty_projection, generated_at=generated_at, data_date=data_date, source_commit=source_commit())
    snapshot["previous_judgments"] = project_previous_judgments(index, snapshot, snapshot["history_weekly"])
    snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)
    validate_schema(snapshot, load_json(LATEST_SCHEMA), "generated latest")
    validate_public_latest(snapshot, verify_source_hash=True)
    if args.dry_run:
        print(f"dry-run valid: {snapshot['meta']['run_id']}")
    else:
        publish(snapshot, index)
        print(f"published {snapshot['meta']['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
