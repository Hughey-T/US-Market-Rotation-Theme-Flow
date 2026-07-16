"""Canonical, deterministic audit condition IDs for theme classification."""
from __future__ import annotations

import math


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def positioning_predicate(rel1, top1, volume, advance) -> bool | None:
    """The single predicate used for both the hypothesis and its audit ID."""
    if not all(_number(value) for value in (rel1, top1, volume, advance)):
        return None
    return (abs(rel1) >= 0.08 and top1 > 0.60) or (volume >= 1.80 and advance < 0.40)


def canonical_condition_ids(
    metrics: dict,
    trends: dict,
    quality: dict,
    by_role: dict,
    flags: dict,
    classification: dict,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return matched, unmatched, contrary, and evidence condition IDs.

    Null inputs are deliberately absent from both matched and unmatched lists.
    The order below is the public audit contract and must not depend on mapping
    insertion order.
    """
    if not quality.get("classification_eligible"):
        contrary = []
        if quality.get("missing_required_fields"):
            contrary.append("Q_REQUIRED_FIELD_NULL")
        if quality.get("history_weeks", 0) < 3:
            contrary.append("Q_HISTORY_BELOW_3")
        if not contrary:
            contrary.extend(quality.get("quality_reasons", []))
        return [], [], contrary, []

    matched: list[str] = []
    unmatched: list[str] = []
    contrary: list[str] = []
    rel1 = metrics.get("equal_weight_rel_spy_1w")
    rel4 = metrics.get("equal_weight_rel_spy_4w")
    rel13 = metrics.get("equal_weight_rel_spy_13w")
    advance = metrics.get("advance_ratio_4w")
    above50 = metrics.get("pct_above_50dma")
    high = metrics.get("pct_within_5pct_52w_high")
    volume = metrics.get("volume_ratio_20d_60d")
    top1 = metrics.get("top1_contribution_ratio")
    top3 = metrics.get("top3_contribution_ratio")

    # Initial audit is relevant when the breadth band is initial-like.
    if _number(advance) and 0.25 <= advance < 0.60 and _number(rel1) and rel1 > 0 and _number(rel4) and rel4 > 0:
        if _number(rel1):
            (matched if rel1 > 0 else unmatched).append("PH_INITIAL_REL1_POS")
        if _number(rel4):
            (matched if rel4 > 0 else unmatched).append("PH_INITIAL_REL4_POS")
        if _number(top1) and top1 > 0.60:
            unmatched.append("PH_INITIAL_CONCENTRATION_GATE")

    if flags.get("phase_diffusion") is True:
        matched.extend(("PH_DIFF_REL_POS", "PH_DIFF_ADVANCE_60", "PH_DIFF_ABOVE50_60", "PH_DIFF_CONCENTRATION_PASS"))
    elif flags.get("phase_diffusion") is False:
        if _number(rel4) and rel4 <= 0:
            unmatched.append("PH_DIFF_REL_POS")
        if _number(advance) and advance < 0.60:
            unmatched.append("PH_DIFF_ADVANCE_60")
        if _number(rel4) and rel4 > 0 and _number(above50) and above50 < 0.60:
            unmatched.append("PH_DIFF_ABOVE50_60")

    if flags.get("phase_price_overheat") is True:
        matched.extend(("PH_OVERHEAT_REL13_15", "PH_OVERHEAT_HIGH_50"))
        peripheral = by_role.get("peripheral") if isinstance(by_role, dict) else None
        peripheral_advance = peripheral.get("advance_ratio_4w") if isinstance(peripheral, dict) else None
        if _number(volume) and volume >= 1.30:
            matched.append("PH_OVERHEAT_VOLUME_130")
        elif _number(peripheral_advance) and peripheral_advance >= 0.67:
            matched.append("PH_OVERHEAT_PERIPHERAL_ADVANCE_67")
    elif flags.get("phase_price_overheat") is False and _number(rel13) and rel13 < 0.15 and not (_number(top1) and top1 > 0.60):
        unmatched.append("PH_OVERHEAT_REL13_15")

    direction = classification.get("direction")
    rel_trend = trends.get("rel_spy_4w_trend_3w")
    advance_trend = trends.get("advance_breadth_trend_3w")
    above_trend = trends.get("above_50dma_breadth_trend_3w")
    if direction == "improving":
        if rel_trend == "improving":
            matched.append("DIR_REL_IMPROVING")
        if "improving" in {advance_trend, above_trend} and not (_number(top1) and top1 > 0.60):
            matched.append("DIR_BREADTH_IMPROVING")
    elif direction in {"worsening", "outflow_signal"}:
        if rel_trend == "worsening":
            matched.append("DIR_REL_WORSENING")
        if "worsening" in {advance_trend, above_trend}:
            matched.append("DIR_BREADTH_WORSENING")
    if direction == "outflow_signal":
        if _number(rel4) and rel4 < 0:
            matched.append("DIR_OUTFLOW_REL_NEG")
        if _number(volume) and volume >= 1.20:
            matched.append("DIR_OUTFLOW_VOLUME_120")

    rels = [metrics.get(f"equal_weight_rel_spy_{h}") for h in ("1w", "4w", "13w")]
    all_nonpositive = all(_number(value) and value <= 0 for value in rels)
    if all_nonpositive:
        matched.append("P5_REL_ALL_NONPOSITIVE")
    if _number(top1) and top1 > 0.60:
        matched.append("CONCENTRATION_TOP1_GT_60")
        contrary.append("CONCENTRATION_SINGLE_NAME")
    if metrics.get("market_cap_led") is True:
        matched.append("WEIGHTING_MARKET_CAP_LED")
    core = by_role.get("core") if isinstance(by_role, dict) else None
    if _number(top1) and top1 > 0.60 and isinstance(core, dict) and _number(core.get("advance_ratio_4w")) and core["advance_ratio_4w"] < 0.50:
        contrary.append("ROLE_CORE_NOT_ADVANCING")
    if classification.get("phase") == "price_overheat" and direction == "outflow_signal":
        contrary.append("EVIDENCE_DIRECT_FLOW_UNAVAILABLE")

    evidence = classification.get("evidence", {})
    evidence_ids: list[str] = []
    if evidence.get("level") == "insufficient":
        pass
    elif evidence.get("direction") == "inflow":
        if _number(rel4) and rel4 > 0:
            evidence_ids.append("EV_REL_POS")
        if direction == "improving":
            evidence_ids.append("EV_DIRECTION_IMPROVING")
        if _number(volume) and volume >= 1.10:
            evidence_ids.append("EV_VOLUME_110")
        if _number(advance) and advance >= 0.60:
            evidence_ids.append("EV_ADVANCE_60")
        elif evidence.get("level") == "relative_preference_suggested" and _number(advance) and advance >= 0.25:
            evidence_ids.append("EV_ADVANCE_25")
        if _number(top1) and top1 <= 0.50:
            evidence_ids.append("EV_TOP1_50")
    elif evidence.get("direction") == "outflow":
        if all_nonpositive:
            evidence_ids.append("EV_REL_ALL_NONPOSITIVE")
            if _number(advance) and advance < 0.50:
                evidence_ids.append("EV_BREADTH_WEAK")
            evidence_ids.append("EV_DIRECTION_OUTFLOW")
        else:
            evidence_ids.append("EV_DIRECTION_OUTFLOW")
            if _number(volume) and volume >= 1.20:
                evidence_ids.append("EV_VOLUME_120")
            if "worsening" in {advance_trend, above_trend}:
                evidence_ids.append("EV_BREADTH_WORSENING")
    else:
        if _number(rel4) and rel4 > 0:
            evidence_ids.append("EV_REL_POS")
        if _number(top1) and top1 > 0.60:
            evidence_ids.append("CONCENTRATION_TOP1_GT_60")
        if positioning_predicate(rel1, top1, volume, advance) is True:
            evidence_ids.append("POSITIONING_REL1_OR_VOLUME_SPIKE")
    return matched, unmatched, contrary, evidence_ids
