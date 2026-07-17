"""Deterministic discovery of strong industries outside the fixed theme master."""
from __future__ import annotations

from .metrics import aggregate_theme, finite


def discover_dynamic_industries(config: dict, observations: dict[str, dict], spy: dict) -> dict:
    """Build quality-gated candidates from configured industry baskets.

    The ETF is a discovery signal only.  A candidate is promoted only when at
    least three configured companies provide usable observations and their
    median and breadth confirm the ETF move.
    """
    definitions = config.get("dynamic_industries", {})
    candidates: dict[str, dict] = {}
    rejected: dict[str, list[str]] = {}
    for candidate_id in sorted(definitions):
        definition = definitions[candidate_id]
        rows = []
        for ticker in definition.get("members", []):
            observed = observations.get(ticker, {})
            rows.append({
                **observed,
                "ticker": ticker,
                "role": "core",
                "valid": finite(observed.get("return_4w")) is not None,
                "overlap_theme_count": 1,
            })
        metrics, rows = aggregate_theme(rows, {
            **{h: spy.get(f"return_{h}") for h in ("1w", "4w", "13w")},
            "previous_3w": spy.get("return_previous_3w"), "previous_9w": spy.get("return_previous_9w"),
        })
        metrics.pop("_market_cap_coverage", None)
        metrics.pop("_liquidity_coverage", None)
        valid = [row for row in rows if row.get("valid")]
        etf = observations.get(definition.get("etf"), {})
        etf_rel4 = None if finite(etf.get("return_4w")) is None or finite(spy.get("return_4w")) is None else etf["return_4w"] - spy["return_4w"]
        reasons = []
        if len(valid) < 3:
            reasons.append("fewer_than_three_usable_companies")
        if finite(etf_rel4) is None or etf_rel4 < 0.03:
            reasons.append("industry_etf_relative_strength_below_3pct")
        if finite(metrics.get("equal_weight_rel_spy_1w")) is None or finite(metrics.get("equal_weight_rel_spy_4w")) is None or not (metrics["equal_weight_rel_spy_1w"] > 0 or metrics["equal_weight_rel_spy_4w"] > 0):
            reasons.append("recent_company_strength_not_positive")
        if finite(metrics.get("pct_above_50dma")) is None or metrics["pct_above_50dma"] < 0.50:
            reasons.append("fewer_than_half_above_50dma")
        if finite(metrics.get("median_rel_spy_4w")) is None or metrics["median_rel_spy_4w"] <= 0:
            reasons.append("median_company_not_above_market")
        if metrics.get("single_name_concentrated") is not False:
            reasons.append("single_company_concentration_or_unknown")
        if reasons:
            rejected[candidate_id] = reasons
        candidates[candidate_id] = {
            "candidate_id": candidate_id,
            "label": definition["label"],
            "source": "dynamic_industry",
            "reference_etf": definition["etf"],
            "reference_etf_rel_spy_4w": etf_rel4,
            "eligible": not reasons,
            "rejection_reasons": reasons,
            "structural_context": config.get("structural_contexts", {}).get(candidate_id, {
                "version": config.get("structural_context_version", "1.0"),
                "status": "not_assessed", "as_of": None,
                "summary": "構造的背景は未評価です。価格条件だけから長期材料を推測しません。",
                "source_category": [],
            }),
            "metrics": metrics,
            "constituents": [
                {key: row.get(key) for key in ("ticker", "return_4w", "rel_spy_4w", "above_50dma", "positive_contribution_ratio", "dollar_volume_20d")}
                for row in rows
            ],
        }
    ordered = sorted(
        (key for key, candidate in candidates.items() if candidate["eligible"]),
        key=lambda key: (-candidates[key]["metrics"]["equal_weight_rel_spy_4w"], key),
    )
    return {
        "discovery_version": "2.0",
        "thresholds": {"etf_rel_spy_4w_min": 0.03, "minimum_companies": 3, "pct_above_50dma_min": 0.50, "median_rel_spy_4w_min_exclusive": 0.0},
        "candidate_ids": ordered,
        "candidates": {key: candidates[key] for key in sorted(candidates)},
        "rejected": rejected,
    }
