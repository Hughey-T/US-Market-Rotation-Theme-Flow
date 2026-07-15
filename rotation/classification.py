"""Deterministic phase, direction, evidence, priority, and theme-state rules."""
from __future__ import annotations

from .metrics import finite
from .condition_audit import canonical_condition_ids, positioning_predicate

DD_LEVELS = {"direct_flow_confirmed", "flow_suggested", "relative_preference_suggested"}


def _tri_all(*conditions: bool | None) -> bool | None:
    if any(condition is None for condition in conditions):
        return None
    return all(conditions)


def _finite_condition(value, predicate) -> bool | None:
    return None if finite(value) is None else bool(predicate(value))


def _tri_or(*conditions: bool | None) -> bool | None:
    if any(condition is True for condition in conditions):
        return True
    if all(condition is False for condition in conditions):
        return False
    return None


def overheat_breadth_weak(overheat, advance, above50):
    if overheat is None:
        return None
    if not overheat:
        return False
    if finite(advance) is None or finite(above50) is None:
        return None
    return advance < 0.60 or above50 < 0.60


def priority_matches(theme: dict) -> dict[str, bool]:
    q, m, f, c = theme["quality"], theme["metrics"], theme["condition_flags"], theme["classifications"]
    phase, direction, evidence = c["phase"], c["direction"], c["evidence"]
    inflow_dd = evidence["level"] in DD_LEVELS and evidence["direction"] == "inflow"
    concentration = f.get("broad_concentration_pass") is True
    rels = [m.get(f"equal_weight_rel_spy_{h}") for h in ("1w", "4w", "13w")]
    p0 = not q.get("classification_eligible", False)
    p1 = phase == "diffusion" and direction in {"improving", "flat"} and inflow_dd and concentration
    p2 = phase == "price_overheat" and f.get("phase_diffusion") is True and direction in {"improving", "flat"} and inflow_dd and concentration
    p4 = m.get("single_name_concentrated") is True or direction in {"worsening", "outflow_signal"} or f.get("overheat_breadth_weak") is True
    p5 = all(finite(value) is not None and value <= 0 for value in rels) and direction in {"worsening", "outflow_signal"} and evidence["direction"] in {"outflow", "down", "unknown"}
    p3_base = phase in {"initial", "diffusion", "price_overheat"} and direction in {"improving", "flat"} and inflow_dd
    p3 = p3_base and not any((p1, p2, p4, p5))
    return {"P0": p0, "P1": p1, "P2": p2, "P3": p3, "P4": p4, "P5": p5, "fallback": True}


def evaluate_priority(theme: dict) -> tuple[str, str, list[str]]:
    matches = priority_matches(theme)
    mapping = {
        "P0": "unclassifiable", "P1": "dd_priority", "P2": "dd_priority", "P5": "low_priority",
        "P4": "watch", "P3": "dd_candidate", "fallback": "watch",
    }
    for rule in ("P0", "P1", "P2", "P5", "P4", "P3", "fallback"):
        if matches[rule]:
            return mapping[rule], rule, [key for key, matched in matches.items() if key != "fallback" and matched]
    raise AssertionError("fallback must match")


def timing_matches(theme: dict) -> dict[str, bool]:
    q, c = theme["quality"], theme["classifications"]
    return {
        "T0": not q.get("classification_eligible", False),
        "T1": c["phase"] == "price_overheat",
        "T2": c["direction"] in {"worsening", "outflow_signal"},
        "T3": c["phase"] == "initial",
        "T4": c["phase"] == "diffusion" and c["direction"] in {"improving", "flat"},
        "fallback": True,
    }


def evaluate_timing(theme: dict) -> tuple[str, str, list[str]]:
    matches = timing_matches(theme)
    mapping = {"T0": "unclassifiable", "T1": "price_overheat", "T2": "deteriorating", "T3": "early_unconfirmed", "T4": "favorable", "fallback": "unclassifiable"}
    for rule in ("T0", "T1", "T2", "T3", "T4", "fallback"):
        if matches[rule]:
            return mapping[rule], rule, [key for key, matched in matches.items() if key != "fallback" and matched]
    raise AssertionError("fallback must match")


def classify_theme(metrics: dict, trends: dict, quality: dict, by_role: dict) -> tuple[dict, dict]:
    if not quality.get("classification_eligible"):
        flags = {key: None for key in ("phase_initial", "phase_diffusion", "phase_price_overheat", "direction_improving", "direction_worsening", "direction_outflow_signal", "broad_concentration_pass", "overheat_breadth_weak")}
        flags.update({"matched_conditions": [], "unmatched_conditions": [], "contrary_evidence": []})
        classification = {
            "phase": "unclassifiable", "direction": "unclassifiable",
            "evidence": {"level": "insufficient", "direction": "unknown", "positioning_hypothesis": "not_assessable", "direct_flow_data_available": False, "matched_conditions": []},
        }
        matched, unmatched, contrary, evidence_ids = canonical_condition_ids(metrics, trends, quality, by_role, flags, classification)
        flags.update(matched_conditions=matched, unmatched_conditions=unmatched, contrary_evidence=contrary)
        classification["evidence"]["matched_conditions"] = evidence_ids
        theme = {"quality": quality, "metrics": metrics, "condition_flags": flags, "classifications": classification}
        classification["research_priority"], classification["research_priority_rule"], _ = evaluate_priority(theme)
        classification["timing_status"], classification["timing_rule"], _ = evaluate_timing(theme)
        return flags, classification

    rel4 = metrics.get("equal_weight_rel_spy_4w")
    reltrend = trends.get("rel_spy_4w_trend_3w")
    advtrend = trends.get("advance_breadth_trend_3w")
    abovetrend = trends.get("above_50dma_breadth_trend_3w")
    if not quality.get("direction_eligible"):
        improving = worsening = None
    else:
        breadth_known = advtrend != "insufficient" or abovetrend != "insufficient"
        improving = _tri_all(
            None if reltrend == "insufficient" else reltrend == "improving",
            None if not breadth_known else advtrend == "improving" or abovetrend == "improving",
            advtrend != "worsening", abovetrend != "worsening",
        )
        worsening = _tri_all(
            None if reltrend == "insufficient" else reltrend == "worsening",
            None if not breadth_known else advtrend == "worsening" or abovetrend == "worsening",
            advtrend != "improving", abovetrend != "improving",
        )
    if worsening is None:
        outflow = None
    elif not worsening:
        outflow = False
    else:
        negative_rel = _finite_condition(rel4, lambda value: value < 0)
        volume = _finite_condition(metrics.get("volume_ratio_20d_60d"), lambda value: value >= 1.20)
        absolute = _finite_condition(metrics.get("equal_weight_return_4w"), lambda value: value < 0)
        outflow = _tri_all(negative_rel, _tri_or(volume, absolute))
    if not quality.get("direction_eligible"):
        direction = "unclassifiable"
    elif outflow is True:
        direction = "outflow_signal"
    elif improving is True:
        direction = "improving"
    elif worsening is True:
        direction = "worsening"
    elif any(flag is None for flag in (improving, worsening, outflow)):
        direction = "unclassifiable"
    else:
        direction = "flat"

    top1, top3 = metrics.get("top1_contribution_ratio"), metrics.get("top3_contribution_ratio")
    concentration = None if finite(top1) is None or finite(top3) is None else top1 <= 0.50 and top3 <= 0.85
    initial = None
    diffusion = None
    if quality.get("phase_initial_diffusion_eligible"):
        initial = _tri_all(
            _finite_condition(metrics.get("equal_weight_rel_spy_1w"), lambda value: value > 0),
            _finite_condition(rel4, lambda value: value > 0), None if direction == "unclassifiable" else direction == "improving",
            _finite_condition(metrics.get("advance_ratio_4w"), lambda value: 0.25 <= value < 0.60),
            _finite_condition(top1, lambda value: value <= 0.60),
        )
        diffusion = _tri_all(
            _finite_condition(rel4, lambda value: value > 0),
            _finite_condition(metrics.get("advance_ratio_4w"), lambda value: value >= 0.60),
            _finite_condition(metrics.get("pct_above_50dma"), lambda value: value >= 0.60),
            _finite_condition(top1, lambda value: value <= 0.50),
            _finite_condition(top3, lambda value: value <= 0.85),
        )
    overheat = None
    if quality.get("phase_overheat_eligible"):
        peripheral = by_role.get("peripheral")
        peripheral_advance = peripheral.get("advance_ratio_4w") if isinstance(peripheral, dict) else None
        volume_or_peripheral = _tri_or(
            _finite_condition(metrics.get("volume_ratio_20d_60d"), lambda value: value >= 1.30),
            _finite_condition(peripheral_advance, lambda value: value >= 0.67),
        )
        overheat = _tri_all(
            _finite_condition(metrics.get("equal_weight_rel_spy_13w"), lambda value: value >= 0.15),
            _finite_condition(metrics.get("pct_within_5pct_52w_high"), lambda value: value >= 0.50),
            volume_or_peripheral,
        )
    phase = "price_overheat" if overheat is True else "diffusion" if diffusion is True else "initial" if initial is True else "unclassifiable"

    if not quality.get("evidence_eligible") or finite(rel4) is None:
        level, evidence_direction = "insufficient", "unknown"
    elif direction == "outflow_signal":
        level, evidence_direction = "flow_suggested", "outflow"
    elif rel4 > 0 and direction == "improving" and finite(metrics.get("volume_ratio_20d_60d")) is not None and metrics["volume_ratio_20d_60d"] >= 1.10 and finite(metrics.get("advance_ratio_4w")) is not None and metrics["advance_ratio_4w"] >= 0.60 and finite(top1) is not None and top1 <= 0.50:
        level, evidence_direction = "flow_suggested", "inflow"
    elif rel4 > 0 and finite(metrics.get("advance_ratio_4w")) is not None and metrics["advance_ratio_4w"] >= 0.60:
        level, evidence_direction = "relative_preference_suggested", "inflow"
    elif rel4 < 0 and finite(metrics.get("advance_ratio_4w")) is not None and metrics["advance_ratio_4w"] < 0.50:
        level, evidence_direction = "relative_preference_suggested", "outflow"
    else:
        level, evidence_direction = "price_only", "up" if rel4 > 0 else "down" if rel4 < 0 else "unknown"
    rel1, volume, advance = metrics.get("equal_weight_rel_spy_1w"), metrics.get("volume_ratio_20d_60d"), metrics.get("advance_ratio_4w")
    positioning_match = positioning_predicate(rel1, top1, volume, advance)
    if positioning_match is None:
        positioning = "not_assessable"
    elif positioning_match:
        positioning = "possible_short_term_adjustment"
    else:
        positioning = "not_supported"
    weak = overheat_breadth_weak(overheat, advance, metrics.get("pct_above_50dma"))
    flags = {
        "phase_initial": initial, "phase_diffusion": diffusion, "phase_price_overheat": overheat,
        "direction_improving": improving, "direction_worsening": worsening, "direction_outflow_signal": outflow,
        "broad_concentration_pass": concentration, "overheat_breadth_weak": weak,
        "matched_conditions": [], "unmatched_conditions": [], "contrary_evidence": [],
    }
    evidence = {"level": level, "direction": evidence_direction, "positioning_hypothesis": positioning, "direct_flow_data_available": False, "matched_conditions": []}
    classification = {"phase": phase, "direction": direction, "evidence": evidence}
    matched, unmatched, contrary, evidence_ids = canonical_condition_ids(metrics, trends, quality, by_role, flags, classification)
    flags.update(matched_conditions=matched, unmatched_conditions=unmatched, contrary_evidence=contrary)
    evidence["matched_conditions"] = evidence_ids
    theme = {"quality": quality, "metrics": metrics, "condition_flags": flags, "classifications": classification}
    classification["research_priority"], classification["research_priority_rule"], _ = evaluate_priority(theme)
    classification["timing_status"], classification["timing_rule"], _ = evaluate_timing(theme)
    return flags, classification
