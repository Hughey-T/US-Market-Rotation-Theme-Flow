"""Decision-layer projections for research queues and company handoff."""
from __future__ import annotations

from .metrics import finite


def _fixed_bucket(theme: dict) -> str:
    metrics = theme["metrics"]
    quality = theme["quality"]
    classification = theme["classifications"]
    broad = theme["condition_flags"].get("broad_concentration_pass") is True
    research = (
        quality.get("classification_eligible") is True
        and (
            classification.get("research_priority") in {"dd_priority", "dd_candidate"}
            or quality.get("history_weeks", 0) < 3
        )
        and finite(metrics.get("equal_weight_rel_spy_4w")) is not None
        and metrics["equal_weight_rel_spy_4w"] > 0
        and finite(metrics.get("advance_ratio_4w")) is not None
        and metrics["advance_ratio_4w"] >= 0.60
        and finite(metrics.get("pct_above_50dma")) is not None
        and metrics["pct_above_50dma"] >= 0.50
        and broad
    )
    if research:
        return "research_now"
    long_term_positive = finite(metrics.get("equal_weight_rel_spy_13w")) is not None and metrics["equal_weight_rel_spy_13w"] > 0
    recently_weak = finite(metrics.get("equal_weight_rel_spy_4w")) is not None and metrics["equal_weight_rel_spy_4w"] <= 0
    if long_term_positive and (recently_weak or classification.get("direction") in {"worsening", "outflow_signal"}):
        return "watch_recovery"
    return "avoid_now"


def build_candidate_buckets(themes: dict[str, dict], dynamic: dict) -> dict:
    buckets = {"research_now": [], "watch_recovery": [], "avoid_now": []}
    for theme_id in sorted(themes):
        buckets[_fixed_bucket(themes[theme_id])].append({"id": theme_id, "label": themes[theme_id]["label"], "source": "fixed_theme"})
    for candidate_id in dynamic.get("candidate_ids", []):
        candidate = dynamic["candidates"][candidate_id]
        buckets["research_now"].append({"id": candidate_id, "label": candidate["label"], "source": "dynamic_industry"})
    def strength(item):
        source = themes[item["id"]]["metrics"] if item["source"] == "fixed_theme" else dynamic["candidates"][item["id"]]["metrics"]
        value = source.get("equal_weight_rel_spy_4w")
        return (finite(value) is None, -(value or 0), item["id"])
    ranked_research = sorted(buckets["research_now"], key=strength)
    buckets["research_now"] = ranked_research[:5]
    buckets["watch_recovery"].extend(ranked_research[5:])
    return {"selection_version": "2.0", "max_research_items": 5, **buckets}


def build_theme_decision(theme: dict, bucket: str) -> dict:
    metrics = theme["metrics"]
    rel4 = metrics.get("equal_weight_rel_spy_4w")
    windows = [metrics.get(key) for key in ("equal_weight_rel_spy_1w", "equal_weight_rel_spy_previous_3w", "equal_weight_rel_spy_previous_9w")]
    if any(value is None for value in windows):
        time_profile = "unavailable"
    elif windows[0] > windows[1] > windows[2]:
        time_profile = "strengthening"
    elif windows[0] < windows[1] < windows[2]:
        time_profile = "weakening"
    else:
        time_profile = "mixed"
    history_weeks = theme["quality"]["history_weeks"]
    return {
        "candidate_bucket": bucket,
        "price_preference": "unavailable" if rel4 is None else "positive" if rel4 > 0 else "negative" if rel4 < 0 else "mixed",
        "direct_flow_confirmation": "unavailable",
        "analysis_mode": "initial_observation" if history_weeks < 3 else "trend",
        "weeks_until_trend": max(0, 3 - history_weeks),
        "time_profile": time_profile,
    }


def select_companies(themes: dict[str, dict], dynamic: dict, buckets: dict) -> list[dict]:
    """Select at most two companies per research item without duplicates."""
    selected, used = [], set()
    for item in buckets["research_now"]:
        source = themes[item["id"]] if item["source"] == "fixed_theme" else dynamic["candidates"][item["id"]]
        rows = [
            row for row in source.get("constituents", [])
            if row.get("ticker") not in used
            and finite(row.get("rel_spy_4w")) is not None
            and (finite(row.get("dollar_volume_20d")) is None or row["dollar_volume_20d"] >= 5_000_000)
        ]
        if item["source"] == "fixed_theme":
            core = sorted((row for row in rows if row.get("role") == "core"), key=lambda row: (-row["rel_spy_4w"], row["ticker"]))
            first = core[0] if core else (sorted(rows, key=lambda row: (-row["rel_spy_4w"], row["ticker"]))[0] if rows else None)
        else:
            first = sorted(rows, key=lambda row: (-row["rel_spy_4w"], row["ticker"]))[0] if rows else None
        picks = [first] if first else []
        remaining = [row for row in rows if first is None or row["ticker"] != first["ticker"]]
        if remaining:
            median_like = min(remaining, key=lambda row: (abs(row["rel_spy_4w"] - source["metrics"].get("median_rel_spy_4w", 0)), row["ticker"]))
            picks.append(median_like)
        for index, row in enumerate(picks[:2]):
            used.add(row["ticker"])
            selected.append({
                "theme_id": item["id"], "theme_label": item["label"], "source": item["source"], "ticker": row["ticker"],
                "selection_role": "representative" if index == 0 else "breadth_check",
                "why": f"{item['label']}の{'中心的な強さ' if index == 0 else '上昇の広がり'}を確認するためです。",
                "key_check": "次回決算と業績見通しが現在の株価の強さを裏付けるか",
                "counter_evidence": "テーマの相対的な強さが失われる、または50日移動平均線を下回ること",
            })
    return selected
