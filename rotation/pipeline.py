"""Offline-capable schema 1.1 snapshot assembly."""
from __future__ import annotations

import datetime as dt

from . import DATA_SCHEMA_VERSION, METHODOLOGY_VERSION
from .identity import analysis_identity, generation_identity
from .classification import classify_theme
from .decisions import build_candidate_buckets, build_theme_decision, select_companies
from .discovery import discover_dynamic_industries
from .metrics import aggregate_theme, role_aggregates
from .membership import member_is_effective
from .provenance import snapshot_source_hash, stable_hash
from .quality import assess_quality
from .regime import classify_market_regime
from .presentation import build_user_view
from .shortlist import apply_shortlist
from .trends import compute_theme_trends, contiguous_history, relative_trend


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
    spy_weekly = observations.get("SPY", {}).get("_return_4w_weekly_3w")
    def relative_state(ticker):
        asset_weekly = observations.get(ticker, {}).get("_return_4w_weekly_3w")
        if not isinstance(asset_weekly, list) or not isinstance(spy_weekly, list) or len(asset_weekly) != 3 or len(spy_weekly) != 3:
            return "insufficient"
        values = [None if asset is None or spy is None else asset - spy for asset, spy in zip(asset_weekly, spy_weekly)]
        return relative_trend(values)
    return {
        "spy_r_4w": spy4, "qqq_rel_spy_4w": rel("QQQ"), "rsp_minus_spy_4w": rel("RSP"), "iwm_minus_spy_4w": rel("IWM"),
        "sector_advance_ratio_4w": None if not sector_values else sum(value > 0 for value in sector_values) / len(sector_values),
        "defensive_basket_rel_spy_4w": _mean_relative(["XLP", "XLV", "XLU"], observations, spy4),
        "cyclical_basket_rel_spy_4w": _mean_relative(["XLY", "XLI", "XLF", "XLB"], observations, spy4),
        "dbc_rel_spy_4w": rel("DBC"), "gld_rel_spy_4w": rel("GLD"), "xle_rel_spy_4w": rel("XLE"),
        "hyg_minus_lqd_4w": None if observations.get("HYG", {}).get("return_4w") is None or observations.get("LQD", {}).get("return_4w") is None else observations["HYG"]["return_4w"] - observations["LQD"]["return_4w"],
        "vix_change_4w": vix.get("change_4w"), "uup_r_4w": observations.get("UUP", {}).get("return_4w"),
        "rsp_minus_spy_4w_trend_3w": relative_state("RSP"),
        "iwm_minus_spy_4w_trend_3w": relative_state("IWM"),
        "dbc_rel_spy_4w_trend_3w": relative_state("DBC"),
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
            if member_is_effective(member, data_date):
                active_membership[member["ticker"]] = active_membership.get(member["ticker"], 0) + 1
    if not active_membership:
        raise ValueError("global active constituent count is zero; success artifact cannot be generated")
    themes = {}
    for definition in theme_master["themes"]:
        rows = []
        for member in definition["members"]:
            if not member_is_effective(member, data_date):
                continue
            observed = observations.get(member["ticker"], {})
            rows.append({**observed, **member, "valid": observed.get("return_1w") is not None and observed.get("return_4w") is not None, "overlap_theme_count": active_membership[member["ticker"]]})
        metrics, rows = aggregate_theme(rows, {
            **{h: spy.get(f"return_{h}") for h in ("1w", "4w", "13w")},
            "previous_3w": spy.get("return_previous_3w"), "previous_9w": spy.get("return_previous_9w"),
        })
        cap_coverage = metrics.pop("_market_cap_coverage")
        metrics.pop("_liquidity_coverage")
        by_role, _ = role_aggregates(rows, spy.get("return_4w"))
        quality = assess_quality(rows, len(compatible) + 1, cap_coverage)
        if quality["metric_valid_counts"]["above_50dma"] < 5:
            metrics["above_50dma_count"] = None
            metrics["pct_above_50dma"] = None
        current_history = {"equal_weight_rel_spy_4w": metrics["equal_weight_rel_spy_4w"], "advance_count_4w": metrics["advance_count_4w"], "above_50dma_count": metrics["above_50dma_count"], "pct_above_50dma": metrics["pct_above_50dma"], "volume_ratio_20d_60d": metrics["volume_ratio_20d_60d"]}
        trends = compute_theme_trends(compatible, definition["theme_id"], current_history)
        flags, classifications = classify_theme(metrics, trends, quality, by_role)
        constituents = [{key: row.get(key) for key in ("ticker", "role", "valid", "return_4w", "rel_spy_4w", "market_cap", "dollar_volume_20d", "positive_contribution_ratio", "overlap_theme_count")} for row in rows]
        structural_context = config.get("structural_contexts", {}).get(definition["theme_id"], {
            "version": config.get("structural_context_version", "1.0"), "status": "not_assessed", "as_of": None,
            "summary": "構造的背景は未評価です。価格条件だけから長期材料を推測しません。", "source_category": [],
        })
        themes[definition["theme_id"]] = {"theme_id": definition["theme_id"], "label": definition["label"], "structural_context": structural_context, "quality": quality, "metrics": metrics, "trends": trends, "condition_flags": flags, "classifications": classifications, "relative_strength_rank_4w": None, "selected_for_deep_dive": False, "shortlist_rank": None, "shortlist_reason_codes": [], "by_role": by_role, "constituents": constituents}
    themes, shortlist = apply_shortlist(themes)
    dynamic = discover_dynamic_industries(config, observations, spy)
    candidate_buckets = build_candidate_buckets(themes, dynamic)
    company_candidates = select_companies(themes, dynamic, candidate_buckets, config)
    for theme_id, theme in themes.items():
        bucket = next(
            name for name in ("research_now", "watch_recovery", "long_term_context_price_weak", "avoid_now")
            if any(item["id"] == theme_id and item["source"] == "fixed_theme" for item in candidate_buckets[name])
        )
        theme["decision"] = build_theme_decision(theme, bucket)
    now = generated_at.astimezone(dt.timezone.utc)
    universe_hash = stable_hash(theme_master)
    quantitative = {"regime": regime_inputs(config, observations), "themes": themes, "data_date": data_date}
    generated_at_text = now.isoformat().replace("+00:00", "Z")
    run_id = analysis_identity(
        data_date=data_date, observations=observations, theme_master=theme_master,
        config=config, source_commit=source_commit, quantitative=quantitative,
    )
    generation_id = generation_identity(run_id, generated_at_text, source_commit)
    classified_regime = classify_market_regime(regime_inputs(config, observations))
    style_factor = _group(config, "style_factor", observations, spy)["etfs"]
    sectors = _group(config, "sectors", observations, spy)
    industries = _group(config, "industries", observations, spy)
    user_view = build_user_view(
        regime=classified_regime, style_factor=style_factor, sectors=sectors, industries=industries,
        themes=themes, dynamic=dynamic, buckets=candidate_buckets, companies=company_candidates,
        history_weeks=len(compatible) + 1,
    )
    snapshot = {
        "meta": {
            "schema_version": DATA_SCHEMA_VERSION, "methodology_version": METHODOLOGY_VERSION,
            "generated_at": generated_at_text, "data_date": data_date,
            "valid_until": (now + dt.timedelta(days=10)).isoformat().replace("+00:00", "Z"),
            "hard_stop_after": (now + dt.timedelta(days=14)).isoformat().replace("+00:00", "Z"),
            "run_id": run_id, "source_commit": source_commit, "source_snapshot": f"output/generations/{generation_id}/archive.json", "source_sha256": "0" * 64,
            "status": "success", "failure_reason": None,
            "universe_definition": {"theme_master_schema_version": "1.0", "theme_master_version": master_version, "universe_hash": universe_hash, "theme_count": len(themes), "unique_constituent_count": len(active_membership), "overlap_policy": "allow_with_warning"},
            "periods": {"1w": 5, "4w": 21, "13w": 63},
            "global_quality": {"requested_ticker_count": len(observations), "usable_ticker_count": sum(row.get("return_4w") is not None for row in observations.values()), "coverage_ratio": sum(row.get("return_4w") is not None for row in observations.values()) / len(observations), "critical_missing": [] if spy.get("return_4w") is not None else ["SPY"], "missing_tickers": sorted(ticker for ticker, row in observations.items() if row.get("return_4w") is None), "warnings": sorted(f"OVERLAP:{ticker}" for ticker,count in active_membership.items() if count > 1)},
        },
        "not_implemented": ["direct_etf_flow", "earnings_revision", "positioning", "point_in_time_market_cap"],
        "market_regime": classified_regime,
        "style_factor": style_factor,
        "sectors": sectors, "industries": industries,
        "themes": themes, "theme_shortlist": shortlist,
        "dynamic_discovery": dynamic, "candidate_buckets": candidate_buckets,
        "company_candidates": company_candidates, "user_view": user_view,
        "history_weekly": compatible[-12:], "previous_judgments": previous_judgments,
    }
    snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)
    return snapshot
