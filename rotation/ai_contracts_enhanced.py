"""Compatibility enhancements for consumer v4 session disclosure and selection."""
from __future__ import annotations

import copy
from typing import Any

from .provenance import stable_hash
from .validation import ContractError


def install(module: Any) -> None:
    """Patch the session runtime without changing the transport contract."""
    original_init = module.SessionLocalRuntime.__init__
    original_fix = module.SessionLocalRuntime.fix_ai_assessment
    original_phase_payload = module.SessionLocalRuntime._phase_payload

    def reconcile_rankings(mechanical: dict, assessment: dict) -> dict:
        signals = mechanical.get("signals")
        if not isinstance(signals, list):
            raise ContractError("mechanical signals are invalid")
        ai_rows = {row["theme_id"]: row for row in module._assessment_rows(assessment)}
        candidates: list[tuple[float, str]] = []
        output = []
        for signal in signals:
            theme_id = signal["theme_id"]
            ai = ai_rows[theme_id]
            mechanical_rank = signal["mechanical_rank"]
            ai_rank = ai.get("independent_ai_rank")
            hard = signal.get("hard_exclusion") is True
            eligible = signal.get("selection_eligible") is True
            if hard:
                status = "REJECT"
            elif not eligible:
                status = "INELIGIBLE"
            elif ai_rank is None:
                status = "UNRESOLVED"
            else:
                candidates.append(((float(mechanical_rank) + float(ai_rank)) / 2, theme_id))
                status = (
                    "AGREE" if mechanical_rank == ai_rank
                    else "PARTIALLY_AGREE" if abs(mechanical_rank - ai_rank) == 1
                    else "DISAGREE"
                )
            output.append({
                "theme_id": theme_id,
                "mechanical_rank": mechanical_rank,
                "independent_ai_rank": ai_rank,
                "integrated_rank": None,
                "agreement_status": status,
                "rank_difference": None if ai_rank is None else ai_rank - mechanical_rank,
                "hard_exclusion": hard,
                "hard_exclusion_reason": signal.get("hard_exclusion_reason"),
                "selection_eligible": eligible,
                "selection_gate_status": signal.get("selection_gate_status"),
                "selection_gate_reasons": copy.deepcopy(signal.get("selection_gate_reasons") or []),
                "monitoring_status": signal.get("monitoring_status"),
                "price_confirmation": copy.deepcopy(signal.get("price_confirmation")),
                "fundamental_gate": copy.deepcopy(signal.get("fundamental_gate")),
                "unresolved_conflict": status in {"DISAGREE", "UNRESOLVED"},
            })
        integrated = {
            theme_id: rank
            for rank, (_, theme_id) in enumerate(sorted(candidates, key=lambda row: (row[0], row[1])), 1)
        }
        for row in output:
            row["integrated_rank"] = integrated.get(row["theme_id"])
        return {
            "artifact_type": "RECONCILIATION_ARTIFACT",
            "reconciliation_contract_version": "1.1",
            "generation_id": mechanical["generation_id"],
            "analysis_id": mechanical["analysis_id"],
            "mechanical_artifact_sha256": stable_hash(mechanical),
            "ai_assessment_sha256": stable_hash(assessment),
            "themes": output,
            "decision": "NO_SELECTION" if not integrated else "SELECTION_AVAILABLE",
        }

    def integrated_theme_decision(reconciliation: dict) -> dict:
        eligible = sorted(
            [
                row for row in reconciliation["themes"]
                if row.get("selection_eligible") is True and row.get("integrated_rank") is not None
            ],
            key=lambda row: row["integrated_rank"],
        )
        return {
            "artifact_type": "INTEGRATED_THEME_DECISION",
            "decision_contract_version": "1.1",
            "generation_id": reconciliation["generation_id"],
            "analysis_id": reconciliation["analysis_id"],
            "reconciliation_sha256": stable_hash(reconciliation),
            "decision": "NO_SELECTION" if not eligible else "RESEARCH_PRIORITIES",
            "priorities": [
                {
                    "theme_id": row["theme_id"],
                    "integrated_rank": row["integrated_rank"],
                    "status": "research",
                }
                for row in eligible
            ],
            "rejected": [
                {
                    "theme_id": row["theme_id"],
                    "reason": (
                        row.get("hard_exclusion_reason")
                        or ",".join(row.get("selection_gate_reasons") or [])
                        or "not_selection_eligible"
                    ),
                }
                for row in reconciliation["themes"]
                if row.get("selection_eligible") is not True
            ],
        }

    def init(self: Any, loaded_consumer: dict) -> None:
        original_init(self, loaded_consumer)
        self.state.assessment_status = "not_fixed"
        self.state.assessment_disclosure_phase = 7
        self.state.assessment_content_disclosed = False

    def fix_ai_assessment(self: Any, assessment: dict) -> str:
        digest = original_fix(self, assessment)
        self.state.assessment_status = "fixed_hidden"
        self.state.assessment_disclosure_phase = 7
        self.state.assessment_content_disclosed = False
        return digest

    def _handoffs(self: Any) -> dict:
        if self._integrated is None:
            self.reconcile()
        formal_theme_ids = {
            row["theme_id"] for row in self._integrated.get("priorities", [])
        }
        signals = self.packages["mechanical"].get("signals") or []
        recovery = [
            {
                "theme_id": row["theme_id"],
                "selection_gate_reasons": copy.deepcopy(row.get("selection_gate_reasons") or []),
            }
            for row in signals
            if row.get("monitoring_status") == "recovery_monitoring"
        ]
        companies = self.packages["companies"].get("companies") or []
        formal_companies = [
            copy.deepcopy(row)
            for row in companies
            if row.get("theme_id") in formal_theme_ids and row.get("handoff_scope") != "exploratory_only"
        ]
        exploratory = [
            copy.deepcopy(row) for row in companies if row.get("handoff_scope") == "exploratory_only"
        ]
        return {
            "formal": {
                "themes": sorted(formal_theme_ids),
                "companies": formal_companies,
            },
            "recovery_monitoring": recovery,
            "exploratory": exploratory,
        }

    def phase_payload(self: Any, phase: int) -> dict:
        if phase == 1:
            if self._assessment is None or not self.state.assessment_fixed:
                raise ContractError("Phase 1 response requires fixed AI assessment")
            facts = self.packages["facts"]
            return {
                "phase": 1,
                "title": "記録固定・データ品質・Blind AI初期化",
                "generation_id": facts.get("generation_id"),
                "analysis_id": facts.get("analysis_id"),
                "data_date": facts.get("data_date"),
                "generated_at": facts.get("generated_at"),
                "data_quality": copy.deepcopy(facts.get("data_quality")),
                "blind_projection_sha256": stable_hash(self.packages["blind"]),
                "assessment_mode": "session_local",
                "assessment_status": "fixed_hidden",
                "assessment_disclosure_phase": 7,
                "assessment_content_disclosed": False,
                "ai_assessment_sha256": self.state.ai_assessment_sha256,
                "assessment_fixed_before_mechanical_disclosure": True,
                "runtime_available": False,
            }
        if phase == 4:
            payload = original_phase_payload(self, phase)
            payload["formal_dynamic_industry_present"] = bool(
                self.packages["blind"].get("dynamic_industries")
            )
            payload["exploratory_company_candidates_may_exist"] = any(
                row.get("handoff_scope") == "exploratory_only"
                for row in self.packages["companies"].get("companies") or []
            )
            return payload
        if phase == 6:
            payload = original_phase_payload(self, phase)
            companies = payload.get("companies") or []
            payload["candidate_scope_summary"] = {
                "formal_dynamic_industry_present": bool(payload.get("dynamic_industries")),
                "formal_candidates": sum(row.get("handoff_scope") != "exploratory_only" for row in companies),
                "exploratory_only_candidates": sum(row.get("handoff_scope") == "exploratory_only" for row in companies),
            }
            return payload
        if phase == 7:
            if self._assessment is None:
                raise ContractError("Phase 7 requires fixed AI assessment")
            self.state.assessment_status = "fixed_disclosed"
            self.state.assessment_content_disclosed = True
            return {
                "phase": 7,
                "title": "固定済みAI独立テーマ解釈",
                "assessment_disclosure": "fixed_in_phase_1_disclosed_now",
                "ai_assessment_sha256": self.state.ai_assessment_sha256,
                "ai_assessment": copy.deepcopy(self._assessment),
            }
        if phase == 9:
            if self._reconciliation is None:
                self.reconcile()
            return {
                "phase": 9,
                "title": "機械判断とAI判断の照合",
                "mechanical_signals": copy.deepcopy(self.packages["mechanical"].get("signals") or []),
                "reconciliation": copy.deepcopy(self._reconciliation),
                "integrated_decision": copy.deepcopy(self._integrated),
            }
        if phase == 10:
            if self._integrated is None:
                self.reconcile()
            return {
                "phase": 10,
                "title": "企業調査仕様・handoff・最終統合",
                "final_decision": self._integrated.get("decision"),
                "handoffs": _handoffs(self),
                "next_update_focus": [
                    "relative threshold",
                    "breadth recovery",
                    "quality and fundamental confirmation",
                    "multi-company diffusion",
                ],
                "ledger_status": "not_persisted_session_local",
                "runtime_available": False,
            }
        return original_phase_payload(self, phase)

    module.reconcile_rankings = reconcile_rankings
    module.integrated_theme_decision = integrated_theme_decision
    module.SessionLocalRuntime.__init__ = init
    module.SessionLocalRuntime.fix_ai_assessment = fix_ai_assessment
    module.SessionLocalRuntime._phase_payload = phase_payload
