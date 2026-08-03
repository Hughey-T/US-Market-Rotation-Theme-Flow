from __future__ import annotations

import copy
import unittest
from pathlib import Path

from rotation.ai_contracts import (
    outcome_maturity,
    reconcile_rankings,
    summarize_ledger,
    validate_ai_theme_assessment,
)
from rotation.consumer_v4 import _price_confirmation, build_consumer_v4_packages
from rotation.provenance import stable_hash
from rotation.validation import ContractError, load_json

ROOT = Path(__file__).resolve().parents[1]


class AIContractsV4Tests(unittest.TestCase):
    def setUp(self):
        snapshot = load_json(ROOT / "tests" / "fixtures" / "latest_normal.json")
        self.packages = build_consumer_v4_packages(snapshot)
        blind = self.packages["blind"]
        self.assessment = {
            "assessment_contract_version": "1.0",
            "generation_id": blind["generation_id"],
            "analysis_id": blind["analysis_id"],
            "blind_projection_sha256": stable_hash(blind),
            "theme_set_identity": blind["theme_set_identity"],
            "evidence_cutoff": blind["data_date"],
            "assessment_mode": "session_local",
            "themes": [{
                "theme_id": theme_id, "assessment_status": "assessed",
                "independent_ai_rank": rank, "confidence": 0.5, "evidence_refs": [],
            } for rank, theme_id in enumerate(blind["theme_ids"], 1)],
        }

    def test_rank_coverage_is_unique_and_contiguous(self):
        blind = copy.deepcopy(self.packages["blind"])
        theme_ids = list(blind["theme_ids"])
        if len(theme_ids) < 2:
            theme_ids.append("synthetic_theme")
        blind["theme_ids"] = sorted(theme_ids)
        blind["theme_set_identity"] = stable_hash(blind["theme_ids"])
        assessment = {
            "assessment_contract_version": "1.0",
            "generation_id": blind["generation_id"],
            "analysis_id": blind["analysis_id"],
            "blind_projection_sha256": stable_hash(blind),
            "theme_set_identity": blind["theme_set_identity"],
            "evidence_cutoff": blind["data_date"],
            "assessment_mode": "session_local",
            "themes": [{
                "theme_id": theme_id,
                "assessment_status": "assessed",
                "independent_ai_rank": rank,
                "confidence": 0.5,
                "evidence_refs": [],
            } for rank, theme_id in enumerate(blind["theme_ids"], 1)],
        }
        validate_ai_theme_assessment(assessment, blind)
        duplicate = copy.deepcopy(assessment)
        duplicate["themes"][1]["independent_ai_rank"] = 1
        with self.assertRaisesRegex(ContractError, "unique"):
            validate_ai_theme_assessment(duplicate, blind)
        gap = copy.deepcopy(assessment)
        gap["themes"][-1]["independent_ai_rank"] += 1
        with self.assertRaisesRegex(ContractError, "contiguous"):
            validate_ai_theme_assessment(gap, blind)

    def test_future_evidence_is_rejected(self):
        future = copy.deepcopy(self.assessment)
        future["evidence_cutoff"] = "2999-01-01"
        with self.assertRaisesRegex(ContractError, "future evidence"):
            validate_ai_theme_assessment(future, self.packages["blind"])

    def test_hard_exclusion_cannot_be_overridden(self):
        mechanical = copy.deepcopy(self.packages["mechanical"])
        for signal in mechanical["signals"]:
            signal["hard_exclusion"] = True
            signal["hard_exclusion_reason"] = "test"
            signal["selection_eligible"] = False
            signal["selection_gate_reasons"] = ["HARD_EXCLUSION"]
        result = reconcile_rankings(mechanical, self.assessment)
        self.assertEqual(result["decision"], "NO_SELECTION")
        self.assertTrue(all(row["integrated_rank"] is None for row in result["themes"]))

    def test_non_excluded_but_ineligible_theme_is_not_selected(self):
        mechanical = copy.deepcopy(self.packages["mechanical"])
        for signal in mechanical["signals"]:
            signal["hard_exclusion"] = False
            signal["hard_exclusion_reason"] = None
            signal["selection_eligible"] = False
            signal["selection_gate_status"] = "fail"
            signal["selection_gate_reasons"] = ["RELATIVE_RELATIVE_BELOW_THRESHOLD"]
        result = reconcile_rankings(mechanical, self.assessment)
        self.assertEqual(result["decision"], "NO_SELECTION")
        self.assertTrue(all(row["agreement_status"] == "INELIGIBLE" for row in result["themes"]))

    def test_relative_gate_explains_positive_but_below_five_percent(self):
        result = _price_confirmation({
            "metrics": {
                "equal_weight_rel_spy_4w": 0.039,
                "advance_ratio_4w": 0.70,
                "pct_above_50dma": 0.60,
            },
            "quality": {"classification_eligible": True},
        })
        gate = result["relative_gate"]
        self.assertEqual(gate["status"], "fail")
        self.assertEqual(gate["required_value"], 0.05)
        self.assertAlmostEqual(gate["difference"], -0.011)
        self.assertEqual(gate["reason_code"], "RELATIVE_BELOW_THRESHOLD")

    def test_missing_gate_data_is_not_evaluable_not_fail(self):
        result = _price_confirmation({"metrics": {}, "quality": {}})
        self.assertEqual(result["relative_gate"]["status"], "not_evaluable")
        self.assertEqual(result["breadth_gate"]["status"], "not_evaluable")
        self.assertEqual(result["quality_gate"]["status"], "not_evaluable")

    def test_exploratory_company_candidates_are_not_ranking_eligible(self):
        exploratory = [
            row for row in self.packages["companies"]["companies"]
            if row.get("handoff_scope") == "exploratory_only"
        ]
        for row in exploratory:
            self.assertEqual(row["candidate_origin"], "exploratory_company_candidate")
            self.assertFalse(row["ranking_eligible"])
            self.assertFalse(row["formal_dynamic_industry_present"])

    def test_outcome_maturity(self):
        self.assertEqual(outcome_maturity("2026-01-01", "2026-01-07", 1), "not_matured")
        self.assertEqual(outcome_maturity("2026-01-01", "2026-01-08", 1), "matured")

    def test_ledger_sample_gate(self):
        result = summarize_ledger([{
            "evaluation_mode": "integrated", "maturity_status": "matured",
            "excess_return": 0.1,
        }], minimum_sample=5)
        self.assertEqual(result["integrated"]["status"], "insufficient_sample")
        self.assertIsNone(result["integrated"]["average_excess_return"])


if __name__ == "__main__":
    unittest.main()
