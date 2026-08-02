"""Semantic contracts and session-local runtime for consumer v4 AI analysis."""
from __future__ import annotations

import copy
import datetime as dt
from dataclasses import dataclass

from .consumer_v4 import BLIND_PACKAGES, RECONCILIATION_PACKAGES
from .provenance import stable_hash
from .validation import ContractError

AI_ASSESSMENT_VERSION = "1.0"
PHASE_COUNT = 10
OUTCOME_HORIZONS_WEEKS = (1, 4, 12, 26)


def _parse_date(value: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ContractError(f"{label} must be an ISO date") from error


def _theme_ids(blind: dict) -> list[str]:
    values = blind.get("theme_ids")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ContractError("blind projection theme_ids are invalid")
    if values != sorted(set(values)):
        raise ContractError("blind projection theme_ids must be unique and sorted")
    return values


def _assessment_rows(assessment: dict) -> list[dict]:
    rows = assessment.get("themes")
    if not isinstance(rows, list):
        raise ContractError("AI assessment themes must be an array")
    return rows


def validate_ai_theme_assessment(assessment: dict, blind: dict) -> str:
    if assessment.get("assessment_contract_version") != AI_ASSESSMENT_VERSION:
        raise ContractError("AI assessment contract version mismatch")
    for field in (
        "generation_id", "analysis_id", "blind_projection_sha256",
        "theme_set_identity", "evidence_cutoff",
    ):
        if field not in assessment:
            raise ContractError(f"AI assessment missing {field}")
    if assessment["generation_id"] != blind.get("generation_id"):
        raise ContractError("AI assessment generation mismatch")
    if assessment["analysis_id"] != blind.get("analysis_id"):
        raise ContractError("AI assessment analysis mismatch")
    if assessment["blind_projection_sha256"] != stable_hash(blind):
        raise ContractError("AI assessment blind projection hash mismatch")
    if assessment["theme_set_identity"] != blind.get("theme_set_identity"):
        raise ContractError("AI assessment theme set mismatch")
    data_date = _parse_date(str(blind.get("data_date")), "blind data_date")
    evidence_cutoff = _parse_date(assessment["evidence_cutoff"], "evidence_cutoff")
    if evidence_cutoff > data_date:
        raise ContractError("AI assessment future evidence is forbidden")
    expected, observed, ranks = set(_theme_ids(blind)), set(), []
    for row in _assessment_rows(assessment):
        if not isinstance(row, dict):
            raise ContractError("AI assessment theme row must be an object")
        theme_id = row.get("theme_id")
        if theme_id not in expected:
            raise ContractError(f"AI assessment unknown theme: {theme_id}")
        if theme_id in observed:
            raise ContractError(f"AI assessment duplicate theme: {theme_id}")
        observed.add(theme_id)
        status = row.get("assessment_status")
        if status not in {
            "assessed", "partially_assessed", "insufficient_evidence",
            "not_assessed", "not_applicable",
        }:
            raise ContractError(f"AI assessment invalid status: {theme_id}")
        confidence = row.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool) or not 0 <= confidence <= 1
        ):
            raise ContractError(f"AI assessment confidence out of range: {theme_id}")
        rank = row.get("independent_ai_rank")
        rankable = status in {"assessed", "partially_assessed"}
        if rankable:
            if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
                raise ContractError(f"AI assessment rank required: {theme_id}")
            ranks.append(rank)
        elif rank is not None:
            raise ContractError(f"AI assessment rank forbidden for unassessed theme: {theme_id}")
        for reference in row.get("evidence_refs", []):
            if not isinstance(reference, dict):
                raise ContractError("evidence reference must be an object")
            as_of = reference.get("as_of")
            if as_of and _parse_date(as_of, "evidence ref as_of") > evidence_cutoff:
                raise ContractError("AI assessment evidence after cutoff is forbidden")
    if observed != expected:
        raise ContractError(f"AI assessment missing themes: {sorted(expected - observed)}")
    if len(ranks) != len(set(ranks)):
        raise ContractError("AI assessment ranks must be unique")
    if sorted(ranks) != list(range(1, len(ranks) + 1)):
        raise ContractError("AI assessment ranks must be contiguous")
    return stable_hash(assessment)


def validate_counter_thesis(counter: dict, assessment: dict) -> str:
    if counter.get("artifact_type") != "COUNTER_THESIS":
        raise ContractError("counter-thesis artifact type mismatch")
    if counter.get("generation_id") != assessment["generation_id"]:
        raise ContractError("counter-thesis generation mismatch")
    if counter.get("analysis_id") != assessment["analysis_id"]:
        raise ContractError("counter-thesis analysis mismatch")
    if counter.get("ai_assessment_sha256") != stable_hash(assessment):
        raise ContractError("counter-thesis assessment hash mismatch")
    if not isinstance(counter.get("themes"), list):
        raise ContractError("counter-thesis themes must be an array")
    return stable_hash(counter)


def reconcile_rankings(mechanical: dict, assessment: dict) -> dict:
    signals = mechanical.get("signals")
    if not isinstance(signals, list):
        raise ContractError("mechanical signals are invalid")
    ai_rows = {row["theme_id"]: row for row in _assessment_rows(assessment)}
    candidates, output = [], []
    for signal in signals:
        theme_id, ai = signal["theme_id"], ai_rows[signal["theme_id"]]
        mechanical_rank, ai_rank = signal["mechanical_rank"], ai.get("independent_ai_rank")
        hard = signal.get("hard_exclusion") is True
        if hard:
            status, score = "REJECT", None
        elif ai_rank is None:
            status, score = "UNRESOLVED", float(mechanical_rank)
            candidates.append((score, theme_id))
        else:
            score = (float(mechanical_rank) + float(ai_rank)) / 2
            candidates.append((score, theme_id))
            status = (
                "AGREE" if mechanical_rank == ai_rank
                else "PARTIALLY_AGREE" if abs(mechanical_rank - ai_rank) == 1
                else "DISAGREE"
            )
        output.append({
            "theme_id": theme_id, "mechanical_rank": mechanical_rank,
            "independent_ai_rank": ai_rank, "integrated_rank": None,
            "agreement_status": status,
            "rank_difference": None if ai_rank is None else ai_rank - mechanical_rank,
            "hard_exclusion": hard,
            "hard_exclusion_reason": signal.get("hard_exclusion_reason"),
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
        "reconciliation_contract_version": "1.0",
        "generation_id": mechanical["generation_id"],
        "analysis_id": mechanical["analysis_id"],
        "mechanical_artifact_sha256": stable_hash(mechanical),
        "ai_assessment_sha256": stable_hash(assessment),
        "themes": output,
        "decision": "NO_SELECTION" if not integrated else "SELECTION_AVAILABLE",
    }


def integrated_theme_decision(reconciliation: dict) -> dict:
    eligible = sorted(
        [row for row in reconciliation["themes"] if row["integrated_rank"] is not None and not row["hard_exclusion"]],
        key=lambda row: row["integrated_rank"],
    )
    return {
        "artifact_type": "INTEGRATED_THEME_DECISION",
        "decision_contract_version": "1.0",
        "generation_id": reconciliation["generation_id"],
        "analysis_id": reconciliation["analysis_id"],
        "reconciliation_sha256": stable_hash(reconciliation),
        "decision": "NO_SELECTION" if not eligible else "RESEARCH_PRIORITIES",
        "priorities": [{
            "theme_id": row["theme_id"], "integrated_rank": row["integrated_rank"],
            "status": "research",
        } for row in eligible],
        "rejected": [{
            "theme_id": row["theme_id"],
            "reason": row["hard_exclusion_reason"] or "unresolved_conflict",
        } for row in reconciliation["themes"] if row["hard_exclusion"]],
    }


@dataclass
class SessionState:
    generation_id: str
    manifest_sha256: str
    phase: int = 0
    ai_assessment_sha256: str | None = None
    counter_thesis_sha256: str | None = None
    assessment_fixed: bool = False
    completed: bool = False


class SessionLocalRuntime:
    """One-session orchestration with a hard blind/reconciliation boundary."""

    def __init__(self, loaded_consumer: dict):
        self.pointer = copy.deepcopy(loaded_consumer["pointer"])
        self.manifest = copy.deepcopy(loaded_consumer["manifest"])
        self.packages = copy.deepcopy(loaded_consumer["packages"])
        self.state = SessionState(
            generation_id=self.pointer["generation_id"],
            manifest_sha256=self.pointer["generation_manifest_sha256"],
        )
        self._assessment = None
        self._counter = None
        self._reconciliation = None
        self._integrated = None

    def blind_inputs(self) -> dict:
        return {name: copy.deepcopy(self.packages[name]) for name in BLIND_PACKAGES}

    def reconciliation_inputs(self) -> dict:
        if not self.state.assessment_fixed:
            raise ContractError("reconciliation disclosure before AI assessment fixation")
        return {name: copy.deepcopy(self.packages[name]) for name in RECONCILIATION_PACKAGES}

    def fix_ai_assessment(self, assessment: dict) -> str:
        digest = validate_ai_theme_assessment(assessment, self.packages["blind"])
        if self._assessment is not None and stable_hash(self._assessment) != digest:
            raise ContractError("fixed AI assessment is immutable")
        self._assessment = copy.deepcopy(assessment)
        self.state.ai_assessment_sha256 = digest
        self.state.assessment_fixed = True
        return digest

    def fix_counter_thesis(self, counter: dict) -> str:
        if self._assessment is None:
            raise ContractError("counter-thesis requires fixed AI assessment")
        digest = validate_counter_thesis(counter, self._assessment)
        if self._counter is not None and stable_hash(self._counter) != digest:
            raise ContractError("fixed counter-thesis is immutable")
        self._counter = copy.deepcopy(counter)
        self.state.counter_thesis_sha256 = digest
        return digest

    def reconcile(self) -> dict:
        if self._assessment is None:
            raise ContractError("reconciliation requires fixed AI assessment")
        self.reconciliation_inputs()
        self._reconciliation = reconcile_rankings(self.packages["mechanical"], self._assessment)
        self._integrated = integrated_theme_decision(self._reconciliation)
        return copy.deepcopy(self._reconciliation)

    def _phase_payload(self, phase: int) -> dict:
        if phase == 1:
            return {"phase": 1, "title": "記録固定・データ品質・Blind AI初期化",
                    "facts": self.packages["facts"],
                    "blind_projection_sha256": stable_hash(self.packages["blind"]),
                    "assessment_mode": "session_local", "runtime_available": False}
        if phase == 2:
            return {"phase": 2, "title": "市場環境とスタイルローテーション",
                    "market_context": self.packages["blind"].get("market_context")}
        if phase in {3, 4, 5}:
            titles = {3: "固定コアテーマの観測事実", 4: "持続性・拡散・過熱の観測", 5: "テーマ重複・独立性"}
            return {"phase": phase, "title": titles[phase], "themes": self.packages["blind"].get("themes")}
        if phase == 6:
            return {"phase": 6, "title": "動的業種と候補宇宙",
                    "dynamic_industries": self.packages["blind"].get("dynamic_industries"),
                    "companies": self.packages["companies"].get("companies")}
        if phase == 7:
            if self._assessment is None: raise ContractError("Phase 7 requires fixed AI assessment")
            return {"phase": 7, "title": "AI独立テーマ解釈", "ai_assessment": copy.deepcopy(self._assessment)}
        if phase == 8:
            if self._counter is None: raise ContractError("Phase 8 requires fixed counter-thesis")
            return {"phase": 8, "title": "反対仮説・AI自己批判・探索テーマ", "counter_thesis": copy.deepcopy(self._counter)}
        if phase == 9:
            if self._reconciliation is None: self.reconcile()
            return {"phase": 9, "title": "機械判断とAI判断の照合", "reconciliation": copy.deepcopy(self._reconciliation)}
        if phase == 10:
            if self._integrated is None: self.reconcile()
            return {
                "phase": 10, "title": "企業調査仕様・handoff・最終統合",
                "integrated_decision": copy.deepcopy(self._integrated),
                "blind_handoff": copy.deepcopy(self.packages["blind-handoff"]),
                "reconciliation_handoff": copy.deepcopy(self.packages["reconciliation-handoff"]),
                "ledger_status": "not_persisted_session_local", "runtime_available": False,
            }
        raise ContractError(f"invalid Phase: {phase}")

    def advance(self, command: str) -> dict:
        if command not in {"更新", "次"}:
            raise ContractError("only exact 更新 or 次 advances the session")
        if self.state.completed:
            raise ContractError("session is complete after Phase 10")
        if self.state.phase == 0:
            if command != "更新": raise ContractError("session must start with 更新")
            target = 1
        else:
            if command != "次": raise ContractError("an active session advances only with 次")
            target = self.state.phase + 1
        payload = self._phase_payload(target)
        self.state.phase = target
        if target == PHASE_COUNT: self.state.completed = True
        return payload


def outcome_maturity(decision_date: str, evaluation_date: str, horizon_weeks: int) -> str:
    if horizon_weeks not in OUTCOME_HORIZONS_WEEKS:
        raise ContractError("unsupported outcome horizon")
    start = _parse_date(decision_date, "decision_date")
    evaluated = _parse_date(evaluation_date, "evaluation_date")
    return "matured" if evaluated >= start + dt.timedelta(weeks=horizon_weeks) else "not_matured"


def summarize_ledger(records: list[dict], minimum_sample: int = 5) -> dict:
    modes = ("mechanical_only", "ai_only", "integrated", "override", "rejected", "no_selection")
    output = {}
    for mode in modes:
        values = [
            row.get("excess_return") for row in records
            if row.get("evaluation_mode") == mode and row.get("maturity_status") == "matured"
            and isinstance(row.get("excess_return"), (int, float))
            and not isinstance(row.get("excess_return"), bool)
        ]
        if len(values) < minimum_sample:
            output[mode] = {"status": "insufficient_sample", "sample_size": len(values),
                            "average_excess_return": None, "hit_rate": None}
        else:
            output[mode] = {"status": "available", "sample_size": len(values),
                            "average_excess_return": sum(values) / len(values),
                            "hit_rate": sum(value > 0 for value in values) / len(values)}
    return output
