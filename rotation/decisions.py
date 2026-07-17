"""Decision-layer projections for research queues and company handoff."""
from __future__ import annotations

from .metrics import finite


BUCKET_NAMES = ("research_now", "watch_recovery", "long_term_context_price_weak", "avoid_now")


def _price_weak(metrics: dict) -> bool:
    rel4 = finite(metrics.get("equal_weight_rel_spy_4w"))
    advance = finite(metrics.get("advance_ratio_4w"))
    above50 = finite(metrics.get("pct_above_50dma"))
    observed_weakness = []
    if rel4 is not None:
        observed_weakness.append(rel4 <= 0)
    if advance is not None:
        observed_weakness.append(advance < 0.60)
    if above50 is not None:
        observed_weakness.append(above50 < 0.50)
    return any(observed_weakness)


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
    context = theme.get("structural_context", {})
    if context.get("status") == "supported" and _price_weak(metrics):
        return "long_term_context_price_weak"
    return "avoid_now"


def build_candidate_buckets(themes: dict[str, dict], dynamic: dict) -> dict:
    buckets = {name: [] for name in BUCKET_NAMES}
    for theme_id in sorted(themes):
        bucket = _fixed_bucket(themes[theme_id])
        buckets[bucket].append({"id": theme_id, "label": themes[theme_id]["label"], "source": "fixed_theme", "classification_reason": bucket})
    for candidate_id in sorted(dynamic.get("candidates", {})):
        candidate = dynamic["candidates"][candidate_id]
        if candidate.get("eligible") is True:
            bucket = "research_now"
        else:
            metrics = candidate.get("metrics", {})
            long_term_positive = finite(metrics.get("equal_weight_rel_spy_13w")) is not None and metrics["equal_weight_rel_spy_13w"] > 0
            recently_weak = finite(metrics.get("equal_weight_rel_spy_4w")) is not None and metrics["equal_weight_rel_spy_4w"] <= 0
            if long_term_positive and recently_weak:
                bucket = "watch_recovery"
            elif candidate.get("structural_context", {}).get("status") == "supported" and _price_weak(metrics):
                bucket = "long_term_context_price_weak"
            else:
                bucket = "avoid_now"
        buckets[bucket].append({"id": candidate_id, "label": candidate["label"], "source": "dynamic_industry", "classification_reason": bucket})
    def strength(item):
        source = themes[item["id"]]["metrics"] if item["source"] == "fixed_theme" else dynamic["candidates"][item["id"]]["metrics"]
        value = source.get("equal_weight_rel_spy_4w")
        return (finite(value) is None, -(value or 0), item["id"])
    ranked_research = sorted(buckets["research_now"], key=strength)
    buckets["research_now"] = ranked_research[:5]
    for item in ranked_research[5:]:
        item["classification_reason"] = "research_capacity_limit"
        buckets["avoid_now"].append(item)
    for name in BUCKET_NAMES:
        if name != "research_now":
            buckets[name] = sorted(buckets[name], key=lambda item: (item["source"], item["id"]))
    return {"selection_version": "3.0", "max_research_items": 5, **buckets}


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


def _research_lens(config: dict, item_id: str, ticker: str, role: str, selection_role: str) -> tuple[dict, str]:
    override = config.get("company_research_overrides", {}).get(ticker)
    if override:
        return override, f"ticker:{ticker}"
    theme_lens = config.get("research_lenses", {}).get(item_id, {}).get(selection_role)
    if theme_lens:
        return theme_lens, f"theme:{item_id}:{selection_role}"
    role_lens = config.get("role_research_lenses", {}).get(role)
    if role_lens:
        return role_lens, f"role:{role}"
    configured = config.get("global_research_lens")
    if configured:
        return configured, "global_fallback"
    if selection_role == "breadth_check":
        return {
            "key_check": "同じ対象の別企業にも売上・利益の改善が広がっているか",
            "counter_evidence": "代表企業だけが強く、同業他社の業績が追随しないこと",
        }, "global_fallback"
    return {
        "key_check": "次回決算と会社見通しが現在の株価の強さを裏付けるか",
        "counter_evidence": "業績の裏付けがないままテーマの相対的な強さが失われること",
    }, "global_fallback"


def select_companies(themes: dict[str, dict], dynamic: dict, buckets: dict, config: dict | None = None) -> list[dict]:
    """Select at most two companies per research item without duplicates."""
    selected, used, config = [], set(), config or {}
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
            selection_role = "representative" if index == 0 else "breadth_check"
            lens, lens_source = _research_lens(config, item["id"], row["ticker"], row.get("role", "core"), selection_role)
            used.add(row["ticker"])
            selected.append({
                "theme_id": item["id"], "theme_label": item["label"], "source": item["source"], "ticker": row["ticker"],
                "selection_role": selection_role,
                "why": f"{item['label']}の{'代表企業として中心的な強さ' if index == 0 else '別企業にも及ぶ上昇の広がり'}を確認するためです。",
                "key_check": lens["key_check"],
                "counter_evidence": lens["counter_evidence"],
                "research_lens_source": lens_source,
            })
    return selected
