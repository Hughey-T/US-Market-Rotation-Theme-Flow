"""Deterministic, score-free lexicographic theme shortlist."""
from __future__ import annotations

import copy

PRIORITY = {"dd_priority": 0, "dd_candidate": 1, "watch": 2}
EVIDENCE = {"inflow": 0, "up": 1, "unknown": 2, "down": 3, "outflow": 4}
PHASE = {"diffusion": 0, "initial": 1, "price_overheat": 2, "unclassifiable": 3}
DIRECTION = {"improving": 0, "flat": 1, "worsening": 2, "outflow_signal": 3, "unclassifiable": 4}


def canonical_shortlist_reason_codes(theme: dict, *, selected: bool, top5_excluded: bool = False) -> list[str]:
    """Build ordered audit codes from code-side values only."""
    cls, flags, metrics = theme["classifications"], theme["condition_flags"], theme["metrics"]
    priority, rule = cls["research_priority"], cls["research_priority_rule"]
    evidence, phase = cls["evidence"]["direction"], cls["phase"]
    if not theme["quality"].get("classification_eligible"):
        return ["SL_EXCLUDED_CLASSIFICATION_INELIGIBLE"]
    if priority == "low_priority":
        codes = ["SL_EXCLUDED_LOW_PRIORITY", f"SL_EVIDENCE_{evidence.upper()}"]
        rels = [metrics.get(f"equal_weight_rel_spy_{h}") for h in ("1w", "4w", "13w")]
        if all(value is not None and value <= 0 for value in rels):
            codes.append("SL_REL_ALL_NONPOSITIVE")
        return codes
    codes = [f"SL_PRIORITY_{priority.upper()}"]
    if top5_excluded:
        codes.append("SL_EXCLUDED_TOP5_LIMIT")
        return codes
    if rule == "P2":
        codes.append("SL_RULE_P2")
    if rule == "P4" and metrics.get("single_name_concentrated") is True:
        codes.append("SL_SINGLE_NAME_CONCENTRATION")
        if metrics.get("market_cap_led") is True:
            codes.append("SL_MARKET_CAP_LED")
        if flags.get("overheat_breadth_weak") is True:
            codes.append("SL_OVERHEAT_BREADTH_WEAK")
        return codes
    if rule == "P4" and phase == "price_overheat":
        codes.append("SL_PHASE_PRICE_OVERHEAT")
        if flags.get("overheat_breadth_weak") is True:
            codes.append("SL_OVERHEAT_BREADTH_WEAK")
        codes.append(f"SL_EVIDENCE_{evidence.upper()}")
        return codes
    codes.extend((f"SL_EVIDENCE_{evidence.upper()}", f"SL_PHASE_{phase.upper()}"))
    if rule == "P2" and flags.get("phase_diffusion") is True:
        codes.append("SL_DIFFUSION_FLAG_TRUE")
    concentration = flags.get("broad_concentration_pass")
    if concentration is True:
        codes.append("SL_CONCENTRATION_PASS")
    elif concentration is False:
        codes.append("SL_CONCENTRATION_FAIL")
    return codes


def apply_shortlist(themes: dict[str, dict]) -> tuple[dict[str, dict], dict]:
    result = copy.deepcopy(themes)
    strength = sorted(result, key=lambda theme_id: (result[theme_id]["metrics"].get("equal_weight_rel_spy_4w") is None, -(result[theme_id]["metrics"].get("equal_weight_rel_spy_4w") or 0), theme_id))
    for rank, theme_id in enumerate(strength, 1):
        result[theme_id]["relative_strength_rank_4w"] = rank if result[theme_id]["metrics"].get("equal_weight_rel_spy_4w") is not None else None
    candidates = []
    for theme_id, theme in result.items():
        cls, flags = theme["classifications"], theme["condition_flags"]
        eligible = theme["quality"].get("classification_eligible") and cls["research_priority"] in PRIORITY
        theme["selected_for_deep_dive"] = False
        theme["shortlist_rank"] = None
        if not eligible:
            theme["shortlist_reason_codes"] = canonical_shortlist_reason_codes(theme, selected=False)
            continue
        concentration = flags.get("broad_concentration_pass")
        key = (PRIORITY[cls["research_priority"]], EVIDENCE[cls["evidence"]["direction"]], PHASE[cls["phase"]], DIRECTION[cls["direction"]], 0 if concentration is True else 1 if concentration is False else 2, theme.get("relative_strength_rank_4w") or 10**9, theme_id)
        candidates.append((key, theme_id))
    selected = [theme_id for _, theme_id in sorted(candidates)[:5]]
    for rank, theme_id in enumerate(selected, 1):
        theme = result[theme_id]
        theme["selected_for_deep_dive"] = True
        theme["shortlist_rank"] = rank
        theme["shortlist_reason_codes"] = canonical_shortlist_reason_codes(theme, selected=True)
    for _, theme_id in sorted(candidates)[5:]:
        result[theme_id]["shortlist_reason_codes"] = canonical_shortlist_reason_codes(result[theme_id], selected=False, top5_excluded=True)
    reasons = []
    if not selected:
        reasons.append("SHORTLIST_NO_ELIGIBLE_THEME")
    if len(selected) < 3:
        reasons.append("SHORTLIST_BELOW_MINIMUM_3")
    return result, {"selection_version": "1.0", "max_themes": 5, "minimum_preferred_themes": 3, "selected_theme_ids": selected, "quality_reasons": reasons}
