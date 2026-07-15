#!/usr/bin/env python3
"""Generate the weekly US market-rotation data package.

The script owns every numerical calculation and deterministic classification.
The Custom GPT is expected to explain and challenge the supplied results, not
to recompute them.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "universe.json"
THEMES_PATH = ROOT / "data" / "themes.json"
OUT_DIR = ROOT / "output"
HIST_DIR = OUT_DIR / "history"
ARCHIVE_DIR = OUT_DIR / "archive"
PRED_DIR = OUT_DIR / "predictions"

ROTATION_SCHEMA_VERSION = "1.0"
PREDICTION_SCHEMA_VERSION = "1.0"
RULE_VERSION = "phase-1.0"
TD = {"1w": 5, "4w": 21, "13w": 63}
HISTORY_WEEKS = 12
PREDICTIONS_EMBED = 3
STALE_DAYS = 7
MIN_THEME_COVERAGE = 0.75
ALLOWED_ROLES = {"core", "beneficiary", "peripheral"}


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rnd(x, nd=4):
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(x), nd)


def validate_configuration(universe: dict, themes_cfg: dict) -> None:
    required_groups = ("regime_assets", "style_factor", "sectors", "industries")
    errors = []
    for group in required_groups:
        if not isinstance(universe.get(group), dict) or not universe[group]:
            errors.append(f"config/universe.json: {group} must be a non-empty object")
    if "SPY" not in universe.get("regime_assets", {}):
        errors.append("config/universe.json: regime_assets must contain SPY")
    themes = themes_cfg.get("themes")
    if not isinstance(themes, dict) or not themes:
        errors.append("data/themes.json: themes must be a non-empty object")
    else:
        for theme_id, theme in themes.items():
            members = theme.get("members")
            if not isinstance(members, dict) or not members:
                errors.append(f"theme {theme_id}: members must be a non-empty object")
                continue
            bad_roles = sorted(set(members.values()) - ALLOWED_ROLES)
            if bad_roles:
                errors.append(f"theme {theme_id}: invalid roles {bad_roles}")
            if len(members) < 6:
                errors.append(f"theme {theme_id}: at least 6 members are required")
    if errors:
        raise ValueError("\n".join(errors))


def get_frame(data: pd.DataFrame, ticker: str):
    """Extract one ticker from yfinance's grouped MultiIndex result."""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            df = data[ticker]
        else:
            df = data
    except (KeyError, TypeError):
        return None
    if df is None or df.empty or "Close" not in df.columns or "Volume" not in df.columns:
        return None
    df = df[["Close", "Volume"]].dropna(subset=["Close"])
    return df if len(df) >= 30 else None


def align_to_market_date(df: pd.DataFrame, data_date: dt.date) -> pd.DataFrame:
    """Remove weekend/future observations (notably crypto) after SPY's date."""
    mask = [timestamp.date() <= data_date for timestamp in df.index]
    return df.loc[mask]


def ret_n(close: pd.Series, n: int):
    if len(close) <= n:
        return None
    previous, last = close.iloc[-1 - n], close.iloc[-1]
    if pd.isna(previous) or pd.isna(last) or previous == 0:
        return None
    return last / previous - 1.0


def ticker_metrics(df: pd.DataFrame) -> dict:
    close, volume = df["Close"], df["Volume"]
    metrics = {f"r_{key}": ret_n(close, n) for key, n in TD.items()}
    last = close.iloc[-1]
    for n, key in ((20, "above_20dma"), (50, "above_50dma"), (200, "above_200dma")):
        ma = close.rolling(n).mean().iloc[-1] if len(close) >= n else None
        metrics[key] = bool(last > ma) if ma is not None and not pd.isna(ma) else None
    if len(close) >= 252:
        high_52w = close.iloc[-252:].max()
        metrics["within_5pct_52w_high"] = bool(last >= 0.95 * high_52w)
        metrics["new_52w_high_4w"] = bool(close.iloc[-21:].max() >= high_52w * 0.999)
    else:
        metrics["within_5pct_52w_high"] = None
        metrics["new_52w_high_4w"] = None
    if len(volume) >= 80:
        baseline = volume.iloc[-60:].mean()
        metrics["volume_ratio_20d_60d"] = (
            float(volume.iloc[-20:].mean() / baseline) if baseline and baseline > 0 else None
        )
    else:
        metrics["volume_ratio_20d_60d"] = None
    metrics["last_date"] = str(close.index[-1].date())
    return metrics


def _vals(members: list[dict], key: str):
    return [member[key] for member in members if member.get(key) is not None]


def aggregate(members: list[dict]) -> dict:
    def mean_of(key):
        values = _vals(members, key)
        return sum(values) / len(values) if values else None

    def share_true(key):
        values = _vals(members, key)
        return sum(bool(value) for value in values) / len(values) if values else None

    r4 = _vals(members, "r_4w")
    result = {
        "n_members_with_data": len(members),
        "eq_r_1w": rnd(mean_of("r_1w")),
        "eq_r_4w": rnd(mean_of("r_4w")),
        "eq_r_13w": rnd(mean_of("r_13w")),
        "median_r_4w": rnd(statistics.median(r4)) if r4 else None,
        "advance_ratio_4w": rnd(sum(value > 0 for value in r4) / len(r4), 3) if r4 else None,
        "pct_above_20dma": rnd(share_true("above_20dma"), 3),
        "pct_above_50dma": rnd(share_true("above_50dma"), 3),
        "pct_above_200dma": rnd(share_true("above_200dma"), 3),
        "pct_within_5pct_52w_high": rnd(share_true("within_5pct_52w_high"), 3),
        "new_52w_high_ratio_4w": rnd(share_true("new_52w_high_4w"), 3),
        "volume_ratio_20d_60d": rnd(mean_of("volume_ratio_20d_60d"), 3),
    }
    result["dispersion_4w_top_minus_median"] = (
        rnd(max(r4) - result["median_r_4w"]) if r4 and result["median_r_4w"] is not None else None
    )
    return result


def rel(a, b):
    return None if a is None or b is None else rnd(a - b)


def _delta(current, previous):
    return None if current is None or previous is None else rnd(current - previous)


def trend_vs_previous(metrics: dict, previous: dict | None) -> dict:
    if not previous:
        return {"available": False, "label": "比較不能", "reason": "過去の週次スナップショットなし"}
    fields = ("rel_spy_4w", "advance_ratio_4w", "pct_above_50dma", "volume_ratio_20d_60d")
    deltas = {f"{field}_delta": _delta(metrics.get(field), previous.get(field)) for field in fields}
    rel_delta = deltas["rel_spy_4w_delta"]
    breadth_delta = deltas["advance_ratio_4w_delta"]
    if rel_delta is None or breadth_delta is None:
        label = "比較不能"
    elif rel_delta > 0 and breadth_delta >= 0:
        label = "改善"
    elif rel_delta < 0 and breadth_delta <= 0:
        label = "悪化"
    else:
        label = "混在"
    return {"available": True, "label": label, **deltas}


def classify_phase(metrics: dict, by_role: dict, trend: dict) -> dict:
    """Deterministic v1 classification; precedence is outflow > overheat > diffusion > start."""
    rel1, rel4, rel13 = (metrics.get("rel_spy_1w"), metrics.get("rel_spy_4w"), metrics.get("rel_spy_13w"))
    advance = metrics.get("advance_ratio_4w")
    above50 = metrics.get("pct_above_50dma")
    near_high = metrics.get("pct_within_5pct_52w_high")
    volume = metrics.get("volume_ratio_20d_60d")
    peripheral = by_role.get("peripheral", {})
    improving = trend.get("label") == "改善"
    weakening = trend.get("label") == "悪化"
    broad = advance is not None and above50 is not None and advance >= 0.6 and above50 >= 0.6
    narrow = advance is not None and above50 is not None and (advance < 0.5 or above50 < 0.6)
    peripheral_spread = peripheral.get("advance_ratio_4w") is not None and peripheral["advance_ratio_4w"] >= 0.5
    rules = {
        "positive_rel_1w": None if rel1 is None else rel1 > 0,
        "positive_rel_4w": None if rel4 is None else rel4 > 0,
        "broad_participation": broad if advance is not None and above50 is not None else None,
        "narrow_participation": narrow if advance is not None and above50 is not None else None,
        "same_horizon_trend_improving": improving if trend.get("available") else None,
        "same_horizon_trend_weakening": weakening if trend.get("available") else None,
        "overheat_13w": None if rel13 is None else rel13 >= 0.15,
        "overheat_near_high": None if near_high is None else near_high >= 0.5,
        "overheat_volume": None if volume is None else volume >= 1.3,
        "peripheral_participation": peripheral_spread if peripheral else None,
    }
    outflow = rel4 is not None and rel4 < 0 and (
        weakening or (metrics.get("eq_r_4w") is not None and metrics["eq_r_4w"] < 0 and volume is not None and volume >= 1.2)
    )
    overheat = all((rel13 is not None and rel13 >= 0.15, near_high is not None and near_high >= 0.5,
                    volume is not None and volume >= 1.3, peripheral_spread))
    diffusion = rel4 is not None and rel4 > 0 and broad and improving
    start = rel1 is not None and rel1 > 0 and rel4 is not None and rel4 > 0 and narrow
    if outflow:
        phase = "流出"
    elif overheat:
        phase = "過熱"
    elif diffusion:
        phase = "拡散"
    elif start:
        phase = "初動"
    else:
        phase = "判定不能"
    return {"phase": phase, "rule_version": RULE_VERSION, "rule_results": rules}


def classify_flow_evidence(metrics: dict, phase: str) -> dict:
    rel4 = metrics.get("rel_spy_4w")
    volume = metrics.get("volume_ratio_20d_60d")
    broad = (metrics.get("advance_ratio_4w") is not None and metrics.get("pct_above_50dma") is not None
             and metrics["advance_ratio_4w"] >= 0.6 and metrics["pct_above_50dma"] >= 0.6)
    if phase == "流出" and volume is not None and volume >= 1.2:
        return {"level": "間接証拠", "direction": "流出示唆", "direct_flow_data": False}
    if rel4 is not None and rel4 > 0 and broad and volume is not None and volume >= 1.1:
        return {"level": "間接証拠", "direction": "流入示唆", "direct_flow_data": False}
    if rel4 is not None and rel4 != 0:
        return {"level": "価格のみ", "direction": "上昇" if rel4 > 0 else "下落", "direct_flow_data": False}
    return {"level": "証拠不足", "direction": "不明", "direct_flow_data": False}


def classify_move_hypothesis(metrics: dict, phase: str) -> str:
    if phase == "流出":
        return "分配・流出の可能性"
    if metrics.get("rel_spy_4w") is not None and metrics["rel_spy_4w"] > 0:
        advance = metrics.get("advance_ratio_4w")
        if advance is not None and advance >= 0.6:
            return "広範上昇"
        return "リーダー集中"
    rel13 = metrics.get("rel_spy_13w")
    if metrics.get("rel_spy_1w") is not None and metrics["rel_spy_1w"] > 0 and rel13 is not None and rel13 < 0:
        return "反発の可能性（ショートカバーは判定不能）"
    return "不明"


def load_prior_history(data_date: dt.date) -> list[dict]:
    history = []
    for path in sorted(HIST_DIR.glob("*.json")):
        try:
            item = load_json(path)
            if dt.date.fromisoformat(item["data_date"]) < data_date:
                history.append(item)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return history[-HISTORY_WEEKS:]


def minimally_valid_prediction(value: dict) -> bool:
    return (
        value.get("prediction_schema_version") == PREDICTION_SCHEMA_VERSION
        and isinstance(value.get("data_date"), str)
        and isinstance(value.get("run_id"), str)
        and isinstance(value.get("predictions"), list)
    )


def load_previous_predictions() -> tuple[list[dict], list[str]]:
    values, warnings = [], []
    for path in sorted(PRED_DIR.glob("*.json"))[-PREDICTIONS_EMBED:]:
        try:
            value = load_json(path)
            if not minimally_valid_prediction(value):
                raise ValueError("必須フィールドまたはschema versionが不正")
            values.append({"file": path.name, "content": value})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"prediction {path.name}: {exc}")
    return values, warnings


def main() -> None:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit("yfinance is required; run: pip install -r requirements.txt") from exc

    universe, themes_cfg = load_json(CONFIG_PATH), load_json(THEMES_PATH)
    validate_configuration(universe, themes_cfg)
    vix_ticker = universe.get("vix", "^VIX")
    groups = ("regime_assets", "style_factor", "sectors", "industries")
    etf_tickers = set().union(*(set(universe.get(group, {})) for group in groups))
    theme_tickers = set().union(*(set(theme["members"]) for theme in themes_cfg["themes"].values()))
    tickers = sorted(etf_tickers | theme_tickers | {vix_ticker, "SPY"})

    print(f"downloading {len(tickers)} tickers ...")
    data = yf.download(tickers, period="2y", auto_adjust=True, group_by="ticker", progress=False, threads=True)
    raw_frames = {ticker: get_frame(data, ticker) for ticker in tickers}
    if raw_frames.get("SPY") is None:
        raise SystemExit("SPY（基準指数）の取得に失敗したため中止します。")
    data_date = raw_frames["SPY"].index[-1].date()

    frames, missing = {}, []
    for ticker, raw in raw_frames.items():
        if raw is None:
            missing.append({"ticker": ticker, "reason": "取得失敗またはデータ不足"})
            continue
        frame = align_to_market_date(raw, data_date)
        if frame.empty:
            missing.append({"ticker": ticker, "reason": "基準日以前のデータなし"})
            continue
        gap = (data_date - frame.index[-1].date()).days
        if gap > STALE_DAYS:
            missing.append({"ticker": ticker, "reason": f"データが古い（最終 {frame.index[-1].date()}）"})
            continue
        frames[ticker] = frame

    metrics_by_ticker = {ticker: ticker_metrics(frame) for ticker, frame in frames.items()}
    spy = metrics_by_ticker["SPY"]

    def etf_block(group_key: str) -> dict:
        block = {}
        for ticker, label in universe.get(group_key, {}).items():
            if ticker not in metrics_by_ticker:
                block[ticker] = {"label": label, "data": None}
                continue
            metrics = metrics_by_ticker[ticker]
            block[ticker] = {
                "label": label,
                "r_1w": rnd(metrics["r_1w"]), "r_4w": rnd(metrics["r_4w"]), "r_13w": rnd(metrics["r_13w"]),
                "rel_spy_1w": rel(metrics["r_1w"], spy["r_1w"]),
                "rel_spy_4w": rel(metrics["r_4w"], spy["r_4w"]),
                "rel_spy_13w": rel(metrics["r_13w"], spy["r_13w"]),
                "above_50dma": metrics["above_50dma"], "above_200dma": metrics["above_200dma"],
                "within_5pct_52w_high": metrics["within_5pct_52w_high"],
                "volume_ratio_20d_60d": rnd(metrics["volume_ratio_20d_60d"], 3),
                "last_date": metrics["last_date"],
            }
        return block

    sectors = etf_block("sectors")
    sector_rel4 = {ticker: value["rel_spy_4w"] for ticker, value in sectors.items()
                   if value.get("rel_spy_4w") is not None}
    market_breadth = {
        "rsp_minus_spy_4w": rel(metrics_by_ticker.get("RSP", {}).get("r_4w"), spy["r_4w"]),
        "iwm_minus_spy_4w": rel(metrics_by_ticker.get("IWM", {}).get("r_4w"), spy["r_4w"]),
        "sector_advance_ratio_4w": rnd(sum(value > 0 for value in sector_rel4.values()) / len(sector_rel4), 3)
        if sector_rel4 else None,
        "vix_level": rnd(frames[vix_ticker]["Close"].iloc[-1], 2) if vix_ticker in frames else None,
        "vix_4w_ago": rnd(frames[vix_ticker]["Close"].iloc[-1 - TD["4w"]], 2)
        if vix_ticker in frames and len(frames[vix_ticker]) > TD["4w"] else None,
    }

    prior_history = load_prior_history(data_date)
    previous_themes = prior_history[-1].get("themes", {}) if prior_history else {}
    themes_out = {}
    for theme_id, theme in themes_cfg["themes"].items():
        member_rows = []
        for ticker, role in theme["members"].items():
            if ticker in metrics_by_ticker:
                row = dict(metrics_by_ticker[ticker])
                row.update({"ticker": ticker, "role": role})
                member_rows.append(row)
        aggregate_all = aggregate(member_rows)
        by_role = {}
        for role in sorted(ALLOWED_ROLES):
            subset = [member for member in member_rows if member["role"] == role]
            if subset:
                role_agg = aggregate(subset)
                by_role[role] = {
                    "n": role_agg["n_members_with_data"], "eq_r_4w": role_agg["eq_r_4w"],
                    "rel_spy_4w": rel(role_agg["eq_r_4w"], rnd(spy["r_4w"])),
                    "advance_ratio_4w": role_agg["advance_ratio_4w"],
                    "pct_above_50dma": role_agg["pct_above_50dma"],
                }
        theme_metrics = {
            **aggregate_all,
            "rel_spy_1w": rel(aggregate_all["eq_r_1w"], rnd(spy["r_1w"])),
            "rel_spy_4w": rel(aggregate_all["eq_r_4w"], rnd(spy["r_4w"])),
            "rel_spy_13w": rel(aggregate_all["eq_r_13w"], rnd(spy["r_13w"])),
        }
        trend = trend_vs_previous(theme_metrics, previous_themes.get(theme_id))
        phase = classify_phase(theme_metrics, by_role, trend)
        ranked = sorted((member for member in member_rows if member.get("r_4w") is not None),
                        key=lambda member: -member["r_4w"])

        def brief(member):
            return {"ticker": member["ticker"], "role": member["role"], "r_4w": rnd(member["r_4w"]),
                    "within_5pct_52w_high": member["within_5pct_52w_high"]}

        n_defined = len(theme["members"])
        coverage_ratio = len(member_rows) / n_defined
        themes_out[theme_id] = {
            "label": theme["label"],
            "reference_etfs": theme.get("reference_etfs", []),
            "coverage": {"n_defined": n_defined, "n_with_data": len(member_rows),
                         "ratio": rnd(coverage_ratio, 3), "analysis_ready": coverage_ratio >= MIN_THEME_COVERAGE},
            "metrics": theme_metrics,
            "trend_vs_previous": trend,
            "phase_assessment": phase,
            "flow_evidence": classify_flow_evidence(theme_metrics, phase["phase"]),
            "move_hypothesis": classify_move_hypothesis(theme_metrics, phase["phase"]),
            "by_role": by_role,
            "leaders_4w": [brief(member) for member in ranked[:2]],
            "laggards_4w": [brief(member) for member in ranked[-2:]] if len(ranked) >= 2 else [],
        }

    snapshot = {
        "data_date": str(data_date),
        "market": {"spy_r_4w": rnd(spy["r_4w"]), **market_breadth},
        "themes": {
            theme_id: {**{field: theme["metrics"].get(field) for field in
                          ("rel_spy_1w", "rel_spy_4w", "rel_spy_13w", "advance_ratio_4w",
                           "pct_above_50dma", "volume_ratio_20d_60d")},
                       "phase": theme["phase_assessment"]["phase"]}
            for theme_id, theme in themes_out.items()
        },
    }
    write_json(HIST_DIR / f"{data_date}.json", snapshot)

    previous_predictions, prediction_warnings = load_previous_predictions()
    critical = {"SPY", "RSP", "IWM", vix_ticker, *universe.get("sectors", {}).keys()}
    missing_tickers = {item["ticker"] for item in missing}
    critical_missing = sorted(critical & missing_tickers)
    industries = etf_block("industries")
    mapped_reference_etfs = sorted({ticker for theme in themes_cfg["themes"].values()
                                    for ticker in theme.get("reference_etfs", [])})
    unmapped_industry_signals = [
        {"ticker": ticker, "label": value["label"], "rel_spy_4w": value["rel_spy_4w"]}
        for ticker, value in industries.items()
        if ticker not in mapped_reference_etfs and value.get("rel_spy_4w") is not None
        and value["rel_spy_4w"] > 0
    ]
    unmapped_industry_signals.sort(key=lambda item: item["rel_spy_4w"], reverse=True)
    quantitative = {
        "market_regime_inputs": {"assets": etf_block("regime_assets"), "breadth": market_breadth},
        "style_factor": etf_block("style_factor"),
        "sectors": {"etfs": sectors, "rank_by_rel_spy_4w": sorted(sector_rel4, key=sector_rel4.get, reverse=True)},
        "industries": industries,
        "theme_universe_coverage": {
            "configured_theme_count": len(themes_cfg["themes"]),
            "mapped_reference_etfs": mapped_reference_etfs,
            "unmapped_positive_industry_signals": unmapped_industry_signals
        },
        "themes": themes_out,
    }
    run_id = f"{data_date}-{stable_hash(quantitative)[:12]}"
    archive_file = f"output/archive/{data_date}__{run_id.rsplit('-', 1)[-1]}.json"
    latest = {
        "meta": {
            "schema_version": ROTATION_SCHEMA_VERSION,
            "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
            "status": "success",
            "analysis_ready": not critical_missing,
            "data_date": str(data_date),
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id,
            "archive_file": archive_file,
            "rule_version": RULE_VERSION,
            "config_sha256": sha256_file(CONFIG_PATH),
            "themes_sha256": sha256_file(THEMES_PATH),
            "coverage": {"requested_tickers": len(tickers), "usable_tickers": len(frames),
                         "ratio": rnd(len(frames) / len(tickers), 4), "critical_missing": critical_missing,
                         "themes_ready": sum(theme["coverage"]["analysis_ready"] for theme in themes_out.values()),
                         "themes_total": len(themes_out)},
            "missing": missing,
            "warnings": prediction_warnings,
            "periods": {"1w": "5営業日", "4w": "21営業日", "13w": "63営業日"},
        },
        "not_implemented": {
            "earnings_revisions": "業績予想修正・受注・ガイダンス（第2期）",
            "direct_etf_flows": "ETF設定・解約等の直接フロー（第3期）",
            "positioning": "空売り残高・オプション・センチメント（第3期）",
        },
        **quantitative,
        "history_weekly": prior_history,
        "previous_predictions": previous_predictions,
    }
    write_json(OUT_DIR / "latest.json", latest)
    archive_path = ROOT / archive_file
    if not archive_path.exists():
        write_json(archive_path, latest)
    print(f"data_date={data_date} run_id={run_id} usable={len(frames)}/{len(tickers)} missing={len(missing)}")
    print(f"wrote {OUT_DIR / 'latest.json'}, {archive_path}, and {HIST_DIR / f'{data_date}.json'}")


if __name__ == "__main__":
    main()
