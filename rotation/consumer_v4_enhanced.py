"""Compatibility enhancements for consumer v4 explainability and selection gates."""
from __future__ import annotations

from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _scalar_gate(
    observed: Any,
    *,
    operator: str,
    required: float,
    missing_field: str,
    fail_reason: str,
) -> dict:
    if not _is_number(observed):
        return {
            "status": "not_evaluable",
            "observed_value": None,
            "required_operator": operator,
            "required_value": required,
            "difference": None,
            "reason_code": "MISSING_REQUIRED_VALUE",
            "missing_fields": [missing_field],
        }
    passed = observed >= required
    return {
        "status": "pass" if passed else "fail",
        "observed_value": observed,
        "required_operator": operator,
        "required_value": required,
        "difference": observed - required,
        "reason_code": "PASS" if passed else fail_reason,
        "missing_fields": [],
    }


def _breadth_gate(advance: Any, above: Any) -> dict:
    missing = []
    if not _is_number(advance):
        missing.append("advance_ratio_4w")
    if not _is_number(above):
        missing.append("pct_above_50dma")
    if missing:
        return {
            "status": "not_evaluable",
            "observed_values": {"advance_ratio_4w": advance, "pct_above_50dma": above},
            "required_values": {"advance_ratio_4w": 0.60, "pct_above_50dma": 0.50},
            "required_operator": ">= for both",
            "reason_code": "BREADTH_DATA_MISSING",
            "missing_fields": missing,
        }
    passed = advance >= 0.60 and above >= 0.50
    return {
        "status": "pass" if passed else "fail",
        "observed_values": {"advance_ratio_4w": advance, "pct_above_50dma": above},
        "required_values": {"advance_ratio_4w": 0.60, "pct_above_50dma": 0.50},
        "required_operator": ">= for both",
        "reason_code": "PASS" if passed else "BREADTH_BELOW_THRESHOLD",
        "missing_fields": [],
    }


def _quality_gate(value: Any) -> dict:
    if value is None:
        return {
            "status": "not_evaluable",
            "observed_value": None,
            "required_value": True,
            "required_operator": "is",
            "reason_code": "QUALITY_STATUS_MISSING",
            "missing_fields": ["classification_eligible"],
        }
    passed = value is True
    return {
        "status": "pass" if passed else "fail",
        "observed_value": value,
        "required_value": True,
        "required_operator": "is",
        "reason_code": "PASS" if passed else "QUALITY_INELIGIBLE",
        "missing_fields": [],
    }


def _fundamental_gate(value: Any) -> dict:
    if not isinstance(value, dict) or not value:
        return {
            "status": "not_evaluable",
            "reason_code": "FUNDAMENTAL_CONFIRMATION_MISSING",
            "missing_fields": ["fundamental_confirmation"],
        }
    status = value.get("status")
    confirmed = value.get("confirmed") is True or status in {"pass", "confirmed"}
    if confirmed:
        return {"status": "pass", "reason_code": "PASS", "missing_fields": []}
    if status in {"fail", "rejected"} or value.get("confirmed") is False:
        return {"status": "fail", "reason_code": "FUNDAMENTAL_CONFIRMATION_FAILED", "missing_fields": []}
    return {
        "status": "not_evaluable",
        "reason_code": "FUNDAMENTAL_CONFIRMATION_INCOMPLETE",
        "missing_fields": ["fundamental_confirmation.status"],
    }


def install(module: Any) -> None:
    """Install a narrow compatibility layer over the immutable v4 transport."""
    original_dynamic = module._dynamic_industry_facts
    original_company = module._company_facts
    original_mechanical = module._mechanical_signals

    def price_confirmation(theme: dict) -> dict:
        metrics = theme.get("metrics") or {}
        quality = theme.get("quality") or {}
        relative = _scalar_gate(
            metrics.get("equal_weight_rel_spy_4w"),
            operator=">=",
            required=0.05,
            missing_field="equal_weight_rel_spy_4w",
            fail_reason="RELATIVE_BELOW_THRESHOLD",
        )
        breadth = _breadth_gate(metrics.get("advance_ratio_4w"), metrics.get("pct_above_50dma"))
        quality_gate = _quality_gate(quality.get("classification_eligible"))
        statuses = {relative["status"], breadth["status"], quality_gate["status"]}
        overall = "fail" if "fail" in statuses else "not_evaluable" if "not_evaluable" in statuses else "pass"
        return {
            "data_available": relative["status"] != "not_evaluable" and breadth["status"] != "not_evaluable",
            "relative_threshold_pass": relative["status"] == "pass",
            "breadth_pass": breadth["status"] == "pass",
            "quality_pass": quality_gate["status"] == "pass",
            "status": overall,
            "relative_gate": relative,
            "breadth_gate": breadth,
            "quality_gate": quality_gate,
            "missing_fields": sorted({
                field
                for gate in (relative, breadth, quality_gate)
                for field in gate.get("missing_fields", [])
            }),
        }

    def company_facts(snapshot: dict) -> list[dict]:
        rows = original_company(snapshot)
        fixed_ids = set((snapshot.get("themes") or {}).keys())
        formal_dynamic_ids = {
            row.get("industry_id")
            for row in original_dynamic(snapshot)
            if isinstance(row, dict) and row.get("industry_id")
        }
        for row in rows:
            theme_id = row.get("theme_id")
            if theme_id in fixed_ids:
                origin = "fixed_theme_candidate"
                membership = "fixed_theme_set"
                formal_dynamic = False
                ranking_eligible = True
                scope = "formal_candidate"
            elif theme_id in formal_dynamic_ids:
                origin = "formal_dynamic_industry_candidate"
                membership = "formal_dynamic_industry"
                formal_dynamic = True
                ranking_eligible = True
                scope = "formal_candidate"
            else:
                origin = "exploratory_company_candidate"
                membership = "outside_fixed_theme_set"
                formal_dynamic = False
                ranking_eligible = False
                scope = "exploratory_only"
            row.update({
                "candidate_origin": origin,
                "theme_membership": membership,
                "formal_dynamic_industry_present": formal_dynamic,
                "ranking_eligible": ranking_eligible,
                "handoff_scope": scope,
            })
            theme = (snapshot.get("themes") or {}).get(theme_id, {})
            row["price_confirmation"] = price_confirmation(theme)
        return rows

    def mechanical_signals(snapshot: dict) -> list[dict]:
        signals = original_mechanical(snapshot)
        for signal in signals:
            theme_id = signal["theme_id"]
            theme = (snapshot.get("themes") or {}).get(theme_id, {})
            signal["price_confirmation"] = price_confirmation(theme)
            fundamental = _fundamental_gate(signal.get("fundamental_confirmation"))
            signal["fundamental_gate"] = fundamental
            reasons: list[str] = []
            hard = signal.get("hard_exclusion") is True
            if hard:
                reasons.append("HARD_EXCLUSION")
            gate_values = (
                ("RELATIVE", signal["price_confirmation"]["relative_gate"]),
                ("BREADTH", signal["price_confirmation"]["breadth_gate"]),
                ("QUALITY", signal["price_confirmation"]["quality_gate"]),
                ("FUNDAMENTAL", fundamental),
            )
            for gate_name, gate in gate_values:
                if gate["status"] != "pass":
                    reasons.append(f"{gate_name}_{gate['reason_code']}")
            bucket = signal.get("candidate_bucket")
            if bucket == "watch_recovery":
                reasons.append("WATCH_RECOVERY")
            elif bucket in {"avoid_now", "unavailable"}:
                reasons.append(f"CANDIDATE_BUCKET_{str(bucket).upper()}")
            eligible = not reasons
            any_failed = any(gate["status"] == "fail" for _, gate in gate_values)
            any_not_evaluable = any(gate["status"] == "not_evaluable" for _, gate in gate_values)
            if eligible:
                selection_status = "pass"
            elif hard or any_failed or bucket in {"avoid_now", "watch_recovery", "unavailable"}:
                selection_status = "fail"
            elif any_not_evaluable:
                selection_status = "not_evaluable"
            else:
                selection_status = "fail"
            signal.update({
                "selection_eligible": eligible,
                "selection_gate_status": selection_status,
                "selection_gate_reasons": reasons,
                "monitoring_status": (
                    "selected" if eligible
                    else "recovery_monitoring" if bucket == "watch_recovery"
                    else "excluded" if hard
                    else "not_selected"
                ),
            })
        return signals

    module._price_confirmation = price_confirmation
    module._company_facts = company_facts
    module._mechanical_signals = mechanical_signals
