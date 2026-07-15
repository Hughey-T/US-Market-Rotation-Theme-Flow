"""Deterministic, score-free lexicographic theme shortlist."""
from __future__ import annotations

import copy

PRIORITY = {"dd_priority": 0, "dd_candidate": 1, "watch": 2}
EVIDENCE = {"inflow": 0, "up": 1, "unknown": 2, "down": 3, "outflow": 4}
PHASE = {"diffusion": 0, "initial": 1, "price_overheat": 2, "unclassifiable": 3}
DIRECTION = {"improving": 0, "flat": 1, "worsening": 2, "outflow_signal": 3, "unclassifiable": 4}


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
            reason = "SL_EXCLUDED_LOW_PRIORITY" if cls["research_priority"] == "low_priority" else "SL_EXCLUDED_CLASSIFICATION_INELIGIBLE"
            theme["shortlist_reason_codes"] = [reason]
            continue
        concentration = flags.get("broad_concentration_pass")
        key = (PRIORITY[cls["research_priority"]], EVIDENCE[cls["evidence"]["direction"]], PHASE[cls["phase"]], DIRECTION[cls["direction"]], 0 if concentration is True else 1 if concentration is False else 2, theme.get("relative_strength_rank_4w") or 10**9, theme_id)
        candidates.append((key, theme_id))
    selected = [theme_id for _, theme_id in sorted(candidates)[:5]]
    for rank, theme_id in enumerate(selected, 1):
        theme = result[theme_id]
        theme["selected_for_deep_dive"] = True
        theme["shortlist_rank"] = rank
        theme["shortlist_reason_codes"] = [f"SL_PRIORITY_{theme['classifications']['research_priority'].upper()}", f"SL_EVIDENCE_{theme['classifications']['evidence']['direction'].upper()}", f"SL_PHASE_{theme['classifications']['phase'].upper()}"]
        if theme["condition_flags"].get("broad_concentration_pass") is True:
            theme["shortlist_reason_codes"].append("SL_CONCENTRATION_PASS")
    reasons = []
    if not selected:
        reasons.append("SHORTLIST_NO_ELIGIBLE_THEME")
    if len(selected) < 3:
        reasons.append("SHORTLIST_BELOW_MINIMUM_3")
    return result, {"selection_version": "1.0", "max_themes": 5, "minimum_preferred_themes": 3, "selected_theme_ids": selected, "quality_reasons": reasons}

