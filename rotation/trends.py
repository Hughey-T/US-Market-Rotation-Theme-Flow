"""Same-horizon trend generation and history continuity gates."""
from __future__ import annotations

import datetime as dt

from .metrics import finite


def ols_slope(values: list[float | None]) -> float | None:
    if len(values) < 2 or any(finite(value) is None for value in values):
        return None
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(float(value) for value in values) / n
    denominator = sum((index - x_mean) ** 2 for index in range(n))
    return sum((index - x_mean) * (float(value) - y_mean) for index, value in enumerate(values)) / denominator


def relative_trend(values: list[float | None]) -> str:
    if len(values) < 3 or any(finite(value) is None for value in values):
        return "insufficient"
    current = values[-3:]
    slope = ols_slope(current)
    change = float(current[-1]) - float(current[0])
    if slope is not None and slope >= 0.005 and change >= 0.01:
        return "improving"
    if slope is not None and slope <= -0.005 and change <= -0.01:
        return "worsening"
    return "flat"


def breadth_trend(values: list[int | None]) -> str:
    if len(values) < 3 or any(value is None for value in values[-3:]):
        return "insufficient"
    change = int(values[-1]) - int(values[-3])
    if change >= 2:
        return "improving"
    if change <= -2:
        return "worsening"
    return "flat"


def contiguous_history(
    history: list[dict], current_date: str, schema_version: str, methodology_version: str, theme_master_version: str
) -> list[dict]:
    """Return the newest contiguous compatible chain, excluding current."""
    current = dt.date.fromisoformat(current_date)
    compatible = []
    for item in sorted(history, key=lambda row: row.get("data_date", ""), reverse=True):
        version_pair = (item.get("schema_version"), item.get("methodology_version"))
        accepted_pairs = {(schema_version, methodology_version)}
        if (schema_version, methodology_version) == ("1.2", "1.2.0"):
            # 1.2 changes the decision/presentation contract, not history metrics.
            accepted_pairs.add(("1.1", "1.1.0"))
        if version_pair not in accepted_pairs:
            continue
        if item.get("theme_master_version") != theme_master_version:
            continue
        try:
            date = dt.date.fromisoformat(item["data_date"])
        except (KeyError, TypeError, ValueError):
            continue
        gap = (current - date).days
        if not 4 <= gap <= 10:
            break
        compatible.append(item)
        current = date
    return list(reversed(compatible))


def compute_theme_trends(prior_history: list[dict], theme_id: str, current: dict) -> dict:
    rows = [item.get("themes", {}).get(theme_id, {}) for item in prior_history] + [current]
    rels = [row.get("equal_weight_rel_spy_4w") for row in rows]
    advances = [row.get("advance_count_4w") for row in rows]
    above_counts = [row.get("above_50dma_count") for row in rows]
    volumes = [row.get("volume_ratio_20d_60d") for row in rows]
    return {
        "rel_spy_4w_change_1w": None if len(rels) < 2 or finite(rels[-1]) is None or finite(rels[-2]) is None else rels[-1] - rels[-2],
        "rel_spy_4w_slope_3w": ols_slope(rels[-3:]) if len(rels) >= 3 else None,
        "rel_spy_4w_slope_4w": ols_slope(rels[-4:]) if len(rels) >= 4 else None,
        "rel_spy_4w_trend_3w": relative_trend(rels[-3:]),
        "rel_spy_4w_trend_4w": relative_trend(rels[-4:]) if len(rels) >= 4 else "insufficient",
        "advance_count_change_1w": None if len(advances) < 2 or advances[-1] is None or advances[-2] is None else advances[-1] - advances[-2],
        "advance_count_change_3w": None if len(advances) < 3 or advances[-1] is None or advances[-3] is None else advances[-1] - advances[-3],
        "above_50dma_count_change_1w": None if len(above_counts) < 2 or above_counts[-1] is None or above_counts[-2] is None else above_counts[-1] - above_counts[-2],
        "above_50dma_count_change_3w": None if len(above_counts) < 3 or above_counts[-1] is None or above_counts[-3] is None else above_counts[-1] - above_counts[-3],
        "advance_breadth_trend_3w": breadth_trend(advances[-3:]),
        "above_50dma_breadth_trend_3w": breadth_trend(above_counts[-3:]),
        "volume_ratio_change_1w": None if len(volumes) < 2 or finite(volumes[-1]) is None or finite(volumes[-2]) is None else volumes[-1] - volumes[-2],
    }
