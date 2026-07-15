"""Theme and metric-level eligibility rules."""
from __future__ import annotations

from .metrics import finite


def assess_quality(members: list[dict], history_weeks: int, market_cap_coverage: float) -> dict:
    active = [row for row in members if row.get("active", True)]
    valid = [row for row in active if finite(row.get("return_1w")) is not None and finite(row.get("return_4w")) is not None]
    count, valid_count = len(active), len(valid)
    coverage = valid_count / count if count else 0.0
    metric_fields = {
        "return_4w": "return_4w",
        "return_13w": "return_13w",
        "above_50dma": "above_50dma",
        "within_5pct_52w_high": "within_5pct_52w_high",
        "market_cap": "market_cap",
    }
    metric_counts = {
        name: sum((isinstance(row.get(field), bool) if field.startswith(("above_", "within_")) else finite(row.get(field)) is not None) for row in active)
        for name, field in metric_fields.items()
    }
    role_counts = {role: sum(row.get("role") == role and row in valid for row in active) for role in ("core", "beneficiary", "peripheral")}
    reasons = []
    if count < 6:
        reasons.append("Q_TOO_FEW_MEMBERS")
    if valid_count < 5:
        reasons.append("Q_VALID_CONSTITUENTS_BELOW_5")
    if coverage < 0.75:
        reasons.append("Q_COVERAGE_BELOW_075")
    if history_weeks < 3:
        reasons.append("Q_HISTORY_BELOW_3")
    for role, role_count in role_counts.items():
        if role_count < 2:
            reasons.append(f"Q_ROLE_{role.upper()}_BELOW_2")
    if market_cap_coverage < 0.75:
        reasons.append("Q_MARKET_CAP_COVERAGE_BELOW_075")
    base = count >= 6 and valid_count >= 5 and coverage >= 0.75
    overheat = base and metric_counts["return_13w"] >= 5 and metric_counts["within_5pct_52w_high"] >= 5
    missing = []
    if not valid:
        missing.append("metrics.equal_weight_rel_spy_4w")
    return {
        "classification_eligible": base,
        "phase_initial_diffusion_eligible": base and history_weeks >= 3,
        "phase_overheat_eligible": overheat,
        "direction_eligible": base and history_weeks >= 3,
        "evidence_eligible": base,
        "constituent_count": count,
        "valid_constituent_count": valid_count,
        "coverage_ratio": coverage,
        "history_weeks": history_weeks,
        "role_valid_counts": role_counts,
        "metric_valid_counts": metric_counts,
        "missing_required_fields": missing,
        "quality_reasons": reasons,
    }

