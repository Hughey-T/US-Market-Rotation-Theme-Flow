"""Pure metric and concentration calculations.

Missing observations remain ``None``.  No function in this module converts a
missing value to zero or emits non-finite JSON numbers.
"""
from __future__ import annotations

from .thresholds import equal_weight_led, market_cap_led, weighting_divergence

import math
from statistics import fmean
from typing import Iterable


def finite(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def mean(values: Iterable[float | None]) -> float | None:
    usable = [float(value) for value in values if finite(value) is not None]
    return fmean(usable) if usable else None


def ratio_true(values: Iterable[bool | None]) -> float | None:
    usable = [value for value in values if isinstance(value, bool)]
    return sum(usable) / len(usable) if usable else None


def relative(value: float | None, benchmark: float | None) -> float | None:
    return None if finite(value) is None or finite(benchmark) is None else float(value) - float(benchmark)


def positive_concentration(values: Iterable[float | None]) -> tuple[float | None, float | None, list[float | None]]:
    raw = list(values)
    positive = [max(float(value), 0.0) if finite(value) is not None else None for value in raw]
    total = sum(value for value in positive if value is not None)
    if total <= 0:
        return None, None, [None for _ in raw]
    shares = [None if value is None else value / total for value in positive]
    ranked = sorted((value for value in shares if value is not None), reverse=True)
    return ranked[0], sum(ranked[:3]), shares


def market_cap_weighted_relative(
    relatives: Iterable[float | None], market_caps: Iterable[float | None], minimum_coverage: float = 0.75
) -> tuple[float | None, float]:
    pairs = list(zip(relatives, market_caps))
    rel_valid = [pair for pair in pairs if finite(pair[0]) is not None]
    if not rel_valid:
        return None, 0.0
    weighted = [(float(rel), float(cap)) for rel, cap in rel_valid if finite(cap) is not None and float(cap) > 0]
    coverage = len(weighted) / len(rel_valid)
    denominator = sum(cap for _, cap in weighted)
    if coverage < minimum_coverage or denominator <= 0:
        return None, coverage
    return sum(rel * cap for rel, cap in weighted) / denominator, coverage


def aggregate_theme(constituents: list[dict], spy_returns: dict[str, float | None]) -> tuple[dict, list[dict]]:
    """Aggregate normalized constituent observations into schema 1.1 metrics."""
    returns = {h: [row.get(f"return_{h}") for row in constituents] for h in ("1w", "4w", "13w")}
    eq_returns = {h: mean(values) for h, values in returns.items()}
    relatives = [relative(row.get("return_4w"), spy_returns.get("4w")) for row in constituents]
    top1, top3, shares = positive_concentration(relatives)
    cap_rel, cap_coverage = market_cap_weighted_relative(relatives, [row.get("market_cap") for row in constituents])
    valid_4w = [value for value in returns["4w"] if finite(value) is not None]
    eq_rel4 = relative(eq_returns["4w"], spy_returns.get("4w"))
    divergence = weighting_divergence(cap_rel, eq_rel4)
    metrics = {
        "equal_weight_return_1w": eq_returns["1w"],
        "equal_weight_return_4w": eq_returns["4w"],
        "equal_weight_return_13w": eq_returns["13w"],
        "equal_weight_rel_spy_1w": relative(eq_returns["1w"], spy_returns.get("1w")),
        "equal_weight_rel_spy_4w": eq_rel4,
        "equal_weight_rel_spy_13w": relative(eq_returns["13w"], spy_returns.get("13w")),
        "market_cap_weight_rel_spy_4w": cap_rel,
        "weighting_divergence_4w": divergence,
        "advance_count_4w": sum(value > 0 for value in valid_4w) if valid_4w else None,
        "advance_ratio_4w": sum(value > 0 for value in valid_4w) / len(valid_4w) if valid_4w else None,
        "above_50dma_count": sum(row.get("above_50dma") is True for row in constituents) if any(isinstance(row.get("above_50dma"), bool) for row in constituents) else None,
        "pct_above_50dma": ratio_true(row.get("above_50dma") for row in constituents),
        "pct_within_5pct_52w_high": ratio_true(row.get("within_5pct_52w_high") for row in constituents),
        "volume_ratio_20d_60d": mean(row.get("volume_ratio_20d_60d") for row in constituents),
        "top1_contribution_ratio": top1,
        "top3_contribution_ratio": top3,
        "single_name_concentrated": None if top1 is None else top1 > 0.60,
        "market_cap_led": market_cap_led(divergence),
        "equal_weight_led": equal_weight_led(divergence),
    }
    updated = []
    for row, rel4, share in zip(constituents, relatives, shares):
        updated.append({**row, "rel_spy_4w": rel4, "positive_contribution_ratio": share})
    metrics["_market_cap_coverage"] = cap_coverage
    return metrics, updated


def role_aggregates(constituents: list[dict], spy_4w: float | None) -> tuple[dict, dict[str, int]]:
    output, counts = {}, {}
    for role in ("core", "beneficiary", "peripheral"):
        rows = [row for row in constituents if row.get("role") == role and finite(row.get("return_4w")) is not None]
        counts[role] = len(rows)
        if len(rows) < 2:
            output[role] = None
            continue
        avg = mean(row["return_4w"] for row in rows)
        output[role] = {
            "valid_count": len(rows),
            "equal_weight_rel_spy_4w": relative(avg, spy_4w),
            "advance_ratio_4w": sum(row["return_4w"] > 0 for row in rows) / len(rows),
        }
    return output, counts
