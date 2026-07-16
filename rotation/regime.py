"""Deterministic market-regime candidate table."""
from __future__ import annotations

from .metrics import finite


def _candidate(inputs, conditions, contrary):
    eligible = all(finite(inputs.get(field)) is not None for field, _, _ in conditions)
    matched, unmatched = [], []
    if eligible:
        for field, identifier, predicate in conditions:
            (matched if predicate(inputs[field]) else unmatched).append(identifier)
    contrary_ids = []
    for field, identifier, predicate in contrary:
        value = inputs.get(field)
        if (finite(value) is not None or isinstance(value, bool)) and predicate(value):
            contrary_ids.append(identifier)
    return {"eligible": eligible, "full_match": None if not eligible else not unmatched, "matched_conditions": matched, "unmatched_conditions": unmatched, "contrary_evidence": contrary_ids}


def classify_market_regime(inputs: dict) -> dict:
    definitions = {
        "broad_risk_on": ([('spy_r_4w','R_BROAD_SPY_POS',lambda v:v>0),('rsp_minus_spy_4w','R_BROAD_RSP_NONNEG',lambda v:v>=0),('iwm_minus_spy_4w','R_BROAD_IWM_NONNEG',lambda v:v>=0),('sector_advance_ratio_4w','R_BROAD_SECTORS_7_OF_11',lambda v:v>=7/11)], [('vix_change_4w','R_BROAD_VIX_CONTRARY',lambda v:v>=3),('hyg_minus_lqd_4w','R_BROAD_CREDIT_CONTRARY',lambda v:v<0)]),
        "large_growth_concentration": ([('spy_r_4w','R_LG_SPY_POS',lambda v:v>0),('qqq_rel_spy_4w','R_LG_QQQ_POS',lambda v:v>0),('rsp_minus_spy_4w','R_LG_RSP_NEG2',lambda v:v<=-0.02),('iwm_minus_spy_4w','R_LG_IWM_NEG',lambda v:v<0),('sector_advance_ratio_4w','R_LG_SECTORS_5',lambda v:v<=5/11)], [('_rsp_or_iwm_improving','R_LG_RSP_OR_IWM_IMPROVING_CONTRARY',lambda v:v is True)]),
        "defensive_shift": ([('defensive_basket_rel_spy_4w','R_DEF_REL2',lambda v:v>=0.02),('cyclical_basket_rel_spy_4w','R_DEF_CYCLICAL_NONPOS',lambda v:v<=0),('vix_change_4w','R_DEF_VIX_POS',lambda v:v>0)], [('iwm_minus_spy_4w','R_DEF_IWM_CONTRARY',lambda v:v>=0.02)]),
        "real_asset_leadership": ([('dbc_rel_spy_4w','R_REAL_DBC2',lambda v:v>=0.02),('_gld_or_xle_rel_spy_4w','R_REAL_GLD_OR_XLE_NONNEG',lambda v:v>=0)], [('_dbc_worsening','R_REAL_DBC_WORSENING_CONTRARY',lambda v:v is True)]),
        "cyclical_recovery_expectation": ([('iwm_minus_spy_4w','R_CYCLE_IWM2',lambda v:v>=0.02),('cyclical_basket_rel_spy_4w','R_CYCLE_BASKET2',lambda v:v>=0.02),('hyg_minus_lqd_4w','R_CYCLE_CREDIT_NONNEG',lambda v:v>=0)], [('vix_change_4w','R_CYCLE_VIX_CONTRARY',lambda v:v>=3)]),
        "liquidity_contraction": ([('spy_r_4w','R_LIQ_SPY_NEG',lambda v:v<0),('hyg_minus_lqd_4w','R_LIQ_CREDIT_NEG1',lambda v:v<=-0.01),('vix_change_4w','R_LIQ_VIX3',lambda v:v>=3),('uup_r_4w','R_LIQ_UUP_POS',lambda v:v>0)], [('sector_advance_ratio_4w','R_LIQ_SECTORS_CONTRARY',lambda v:v>=7/11)]),
    }
    # Synthetic values represent explicit OR predicates without falsely naming
    # one source asset when the other asset is the one that actually matched.
    work = dict(inputs)
    gld, xle = inputs.get("gld_rel_spy_4w"), inputs.get("xle_rel_spy_4w")
    work["_gld_or_xle_rel_spy_4w"] = None if finite(gld) is None and finite(xle) is None else max(value for value in (gld, xle) if finite(value) is not None)
    work["_rsp_or_iwm_improving"] = any(inputs.get(field) == "improving" for field in ("rsp_minus_spy_4w_trend_3w", "iwm_minus_spy_4w_trend_3w"))
    work["_dbc_worsening"] = inputs.get("dbc_rel_spy_4w_trend_3w") == "worsening"
    candidates = {name: _candidate(work, conditions, contrary) for name, (conditions, contrary) in definitions.items()}
    numeric_inputs = [
        "spy_r_4w", "qqq_rel_spy_4w", "rsp_minus_spy_4w", "iwm_minus_spy_4w",
        "sector_advance_ratio_4w", "defensive_basket_rel_spy_4w", "cyclical_basket_rel_spy_4w",
        "dbc_rel_spy_4w", "gld_rel_spy_4w", "xle_rel_spy_4w", "hyg_minus_lqd_4w",
        "vix_change_4w", "uup_r_4w",
    ]
    null_ratio = sum(finite(inputs.get(field)) is None for field in numeric_inputs) / len(numeric_inputs)
    full = [name for name, candidate in candidates.items() if candidate["full_match"] is True]
    if null_ratio >= 0.25:
        primary, secondary, confidence = "unclassifiable", [], "unclassifiable"
    elif len(full) > 1:
        primary, secondary, confidence = "mixed", sorted(full), "low"
    elif len(full) == 1:
        primary, secondary = full[0], []
        candidate = candidates[primary]
        confidence = "high" if len(candidate["matched_conditions"]) >= 4 and not candidate["contrary_evidence"] else "medium"
    else:
        primary, confidence = "directionless", "low"
        partial = [(len(c["matched_conditions"]) / (len(c["matched_conditions"])+len(c["unmatched_conditions"])), name) for name,c in candidates.items() if c["eligible"] and c["matched_conditions"]]
        secondary = [name for ratio, name in sorted(partial, key=lambda pair:(-pair[0],pair[1])) if ratio >= 0.75][:2]
    matched = sorted({item for name in full for item in candidates[name]["matched_conditions"]})
    contrary = sorted({item for name in full for item in candidates[name]["contrary_evidence"]})
    return {"inputs": inputs, "candidate_flags": candidates, "classification": {"primary_regime": primary, "secondary_regimes": secondary, "confidence": confidence, "matched_conditions": matched, "contrary_evidence": contrary}}
