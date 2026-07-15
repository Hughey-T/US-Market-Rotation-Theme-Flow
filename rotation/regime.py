"""Deterministic market-regime candidate table."""
from __future__ import annotations

from .metrics import finite


def _candidate(inputs, conditions, contrary):
    eligible = all(finite(inputs.get(field)) is not None for field, _, _ in conditions)
    matched, unmatched = [], []
    if eligible:
        for field, identifier, predicate in conditions:
            (matched if predicate(inputs[field]) else unmatched).append(identifier)
    contrary_ids = [identifier for field, identifier, predicate in contrary if finite(inputs.get(field)) is not None and predicate(inputs[field])]
    return {"eligible": eligible, "full_match": None if not eligible else not unmatched, "matched_conditions": matched, "unmatched_conditions": unmatched, "contrary_evidence": contrary_ids}


def classify_market_regime(inputs: dict) -> dict:
    definitions = {
        "broad_risk_on": ([('spy_r_4w','R_BROAD_SPY_POS',lambda v:v>0),('rsp_minus_spy_4w','R_BROAD_RSP_NONNEG',lambda v:v>=0),('iwm_minus_spy_4w','R_BROAD_IWM_NONNEG',lambda v:v>=0),('sector_advance_ratio_4w','R_BROAD_SECTORS_7_OF_11',lambda v:v>=7/11)], [('vix_change_4w','R_BROAD_VIX_CONTRARY',lambda v:v>=3),('hyg_minus_lqd_4w','R_BROAD_CREDIT_CONTRARY',lambda v:v<0)]),
        "large_growth_concentration": ([('spy_r_4w','R_LG_SPY_POS',lambda v:v>0),('qqq_rel_spy_4w','R_LG_QQQ_POS',lambda v:v>0),('rsp_minus_spy_4w','R_LG_RSP_NEG2',lambda v:v<=-0.02),('iwm_minus_spy_4w','R_LG_IWM_NEG',lambda v:v<0),('sector_advance_ratio_4w','R_LG_SECTORS_5',lambda v:v<=5/11)], []),
        "defensive_shift": ([('defensive_basket_rel_spy_4w','R_DEF_REL2',lambda v:v>=0.02),('cyclical_basket_rel_spy_4w','R_DEF_CYCLICAL_NONPOS',lambda v:v<=0),('vix_change_4w','R_DEF_VIX_POS',lambda v:v>0)], [('iwm_minus_spy_4w','R_DEF_IWM_CONTRARY',lambda v:v>=0.02)]),
        "real_asset_leadership": ([('dbc_rel_spy_4w','R_REAL_DBC2',lambda v:v>=0.02),('gld_rel_spy_4w','R_REAL_GLD_NONNEG',lambda v:v>=0)], []),
        "cyclical_recovery_expectation": ([('iwm_minus_spy_4w','R_CYCLE_IWM2',lambda v:v>=0.02),('cyclical_basket_rel_spy_4w','R_CYCLE_BASKET2',lambda v:v>=0.02),('hyg_minus_lqd_4w','R_CYCLE_CREDIT_NONNEG',lambda v:v>=0)], [('vix_change_4w','R_CYCLE_VIX_CONTRARY',lambda v:v>=3)]),
        "liquidity_contraction": ([('spy_r_4w','R_LIQ_SPY_NEG',lambda v:v<0),('hyg_minus_lqd_4w','R_LIQ_CREDIT_NEG1',lambda v:v<=-0.01),('vix_change_4w','R_LIQ_VIX3',lambda v:v>=3),('uup_r_4w','R_LIQ_UUP_POS',lambda v:v>0)], [('sector_advance_ratio_4w','R_LIQ_SECTORS_CONTRARY',lambda v:v>=7/11)]),
    }
    # Real assets accepts GLD or XLE. Rewrite its second condition with a synthetic value.
    work = dict(inputs)
    gld, xle = inputs.get("gld_rel_spy_4w"), inputs.get("xle_rel_spy_4w")
    work["gld_rel_spy_4w"] = None if finite(gld) is None and finite(xle) is None else max(value for value in (gld, xle) if finite(value) is not None)
    candidates = {name: _candidate(work, conditions, contrary) for name, (conditions, contrary) in definitions.items()}
    null_ratio = sum(finite(value) is None for value in inputs.values()) / len(inputs) if inputs else 1.0
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

