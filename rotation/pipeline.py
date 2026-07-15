"""Offline-capable schema 1.1 snapshot assembly."""
from __future__ import annotations

import datetime as dt

from . import DATA_SCHEMA_VERSION, METHODOLOGY_VERSION
from .classification import classify_theme
from .metrics import aggregate_theme, role_aggregates
from .provenance import snapshot_source_hash, stable_hash
from .quality import assess_quality
from .regime import classify_market_regime
from .shortlist import apply_shortlist
from .trends import compute_theme_trends, contiguous_history


def _etf_metric(label, row, spy):
    row = row or {}
    return {
        "label": label,
        "return_1w": row.get("return_1w"), "return_4w": row.get("return_4w"), "return_13w": row.get("return_13w"),
        "rel_spy_1w": None if row.get("return_1w") is None or spy.get("return_1w") is None else row["return_1w"] - spy["return_1w"],
        "rel_spy_4w": None if row.get("return_4w") is None or spy.get("return_4w") is None else row["return_4w"] - spy["return_4w"],
        "rel_spy_13w": None if row.get("return_13w") is None or spy.get("return_13w") is None else row["return_13w"] - spy["return_13w"],
        "above_50dma": row.get("above_50dma"), "above_200dma": row.get("above_200dma"),
        "within_5pct_52w_high": row.get("within_5pct_52w_high"), "volume_ratio_20d_60d": row.get("volume_ratio_20d_60d"), "last_date": row.get("last_date"),
    }


def _group(config, name, observations, spy):
    etfs = {ticker: _etf_metric(label, observations.get(ticker), spy) for ticker, label in config.get(name, {}).items()}
    rank = sorted((ticker for ticker, value in etfs.items() if value["rel_spy_4w"] is not None), key=lambda ticker: (-etfs[ticker]["rel_spy_4w"], ticker))
    return {"etfs": etfs, "rank_by_rel_spy_4w": rank}


def _mean_relative(tickers, observations, spy4):
    values = [observations.get(ticker, {}).get("return_4w") for ticker in tickers]
    values = [value for value in values if value is not None]
    return None if len(values) < 3 or spy4 is None else sum(values) / len(values) - spy4


def regime_inputs(config, observations):
    spy4 = observations.get("SPY", {}).get("return_4w")
    def rel(ticker):
        value = observations.get(ticker, {}).get("return_4w")
        return None if value is None or spy4 is None else value - spy4
    sector_values = [rel(ticker) for ticker in config.get("sectors", {})]
    sector_values = [value for value in sector_values if value is not None]
    vix = observations.get(config.get("vix", "^VIX"), {})
    return {
        "spy_r_4w": spy4, "qqq_rel_spy_4w": rel("QQQ"), "rsp_minus_spy_4w": rel("RSP"), "iwm_minus_spy_4w": rel("IWM"),
        "sector_advance_ratio_4w": None if not sector_values else sum(value > 0 for value in sector_values) / len(sector_values),
        "defensive_basket_rel_spy_4w": _mean_relative(["XLP", "XLV", "XLU"], observations, spy4),
        "cyclical_basket_rel_spy_4w": _mean_relative(["XLY", "XLI", "XLF", "XLB"], observations, spy4),
        "dbc_rel_spy_4w": rel("DBC"), "gld_rel_spy_4w": rel("GLD"), "xle_rel_spy_4w": rel("XLE"),
        "hyg_minus_lqd_4w": None if observations.get("HYG", {}).get("return_4w") is None or observations.get("LQD", {}).get("return_4w") is None else observations["HYG"]["return_4w"] - observations["LQD"]["return_4w"],
        "vix_change_4w": vix.get("change_4w"), "uup_r_4w": observations.get("UUP", {}).get("return_4w"),
    }


def build_snapshot(
    *, config: dict, theme_master: dict, observations: dict[str, dict], history: list[dict], previous_judgments: dict,
    generated_at: dt.datetime, data_date: str, source_commit: str,
) -> dict:
    spy = observations["SPY"]
    master_version = theme_master["theme_master_version"]
    compatible = contiguous_history(history, data_date, DATA_SCHEMA_VERSION, METHODOLOGY_VERSION, master_version)
    active_membership: dict[str, int] = {}
    for theme in theme_master["themes"]:
        for member in theme["members"]:
            if member["active"]:
                active_membership[member["ticker"]] = active_membership.get(member["ticker"], 0) + 1
    themes = {}
    for definition in theme_master["themes"]:
        rows = []
        for member in definition["members"]:
            if not member["active"]:
                continue
            observed = observations.get(member["ticker"], {})
            rows.append({**observed, **member, "valid": observed.get("return_1w") is not None and observed.get("return_4w") is not None, "overlap_theme_count": active_membership[member["ticker"]]})
        metrics, rows = aggregate_theme(rows, {h: spy.get(f"return_{h}") for h in ("1w", "4w", "13w")})
        cap_coverage = metrics.pop("_market_cap_coverage")
        by_role, _ = role_aggregates(rows, spy.get("return_4w"))
        current_history = {"equal_weight_rel_spy_4w": metrics["equal_weight_rel_spy_4w"], "advance_count_4w": metrics["advance_count_4w"], "above_50dma_count": None, "pct_above_50dma": metrics["pct_above_50dma"], "volume_ratio_20d_60d": metrics["volume_ratio_20d_60d"]}
        trends = compute_theme_trends(compatible, definition["theme_id"], current_history)
        quality = assess_quality(rows, len(compatible) + 1, cap_coverage)
        flags, classifications = classify_theme(metrics, trends, quality, by_role)
        constituents = [{key: row.get(key) for key in ("ticker", "role", "valid", "return_4w", "rel_spy_4w", "market_cap", "positive_contribution_ratio", "overlap_theme_count")} for row in rows]
        themes[definition["theme_id"]] = {"theme_id": definition["theme_id"], "label": definition["label"], "quality": quality, "metrics": metrics, "trends": trends, "condition_flags": flags, "classifications": classifications, "relative_strength_rank_4w": None, "selected_for_deep_dive": False, "shortlist_rank": None, "shortlist_reason_codes": [], "by_role": by_role, "constituents": constituents}
    themes, shortlist = apply_shortlist(themes)
    now = generated_at.astimezone(dt.timezone.utc)
    universe_hash = stable_hash(theme_master)
    quantitative = {"regime": regime_inputs(config, observations), "themes": themes, "data_date": data_date}
    run_id = f"{data_date}-{stable_hash(quantitative)[:12]}"
    snapshot = {
        "meta": {
            "schema_version": DATA_SCHEMA_VERSION, "methodology_version": METHODOLOGY_VERSION,
            "generated_at": now.isoformat().replace("+00:00", "Z"), "data_date": data_date,
            "valid_until": (now + dt.timedelta(days=10)).isoformat().replace("+00:00", "Z"),
            "hard_stop_after": (now + dt.timedelta(days=14)).isoformat().replace("+00:00", "Z"),
            "run_id": run_id, "source_commit": source_commit, "source_snapshot": f"output/archive/{data_date}__{run_id.rsplit('-',1)[-1]}.json", "source_sha256": "0" * 64,
            "status": "success", "failure_reason": None,
            "universe_definition": {"theme_master_schema_version": "1.0", "theme_master_version": master_version, "universe_hash": universe_hash, "theme_count": len(themes), "unique_constituent_count": len(active_membership), "overlap_policy": "allow_with_warning"},
            "periods": {"1w": 5, "4w": 21, "13w": 63},
            "global_quality": {"requested_ticker_count": len(observations), "usable_ticker_count": sum(row.get("return_4w") is not None for row in observations.values()), "coverage_ratio": sum(row.get("return_4w") is not None for row in observations.values()) / len(observations), "critical_missing": [] if spy.get("return_4w") is not None else ["SPY"], "missing_tickers": sorted(ticker for ticker, row in observations.items() if row.get("return_4w") is None), "warnings": sorted(f"OVERLAP:{ticker}" for ticker,count in active_membership.items() if count > 1)},
        },
        "not_implemented": ["direct_etf_flow", "earnings_revision", "positioning", "point_in_time_market_cap"],
        "market_regime": classify_market_regime(regime_inputs(config, observations)),
        "style_factor": _group(config, "style_factor", observations, spy)["etfs"],
        "sectors": _group(config, "sectors", observations, spy), "industries": _group(config, "industries", observations, spy),
        "themes": themes, "theme_shortlist": shortlist, "history_weekly": compatible[-12:], "previous_judgments": previous_judgments,
    }
    snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)
    return snapshot

