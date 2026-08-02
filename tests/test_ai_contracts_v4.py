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
from rotation.consumer_v4 import build_consumer_v4_packages
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
        validate_ai_theme_assessment(self.assessment, self.packages["blind"])
        duplicate = copy.deepcopy(self.assessment)
        duplicate["themes"][1]["independent_ai_rank"] = 1
        with self.assertRaisesRegex(ContractError, "unique"):
            validate_ai_theme_assessment(duplicate, self.packages["blind"])
        gap = copy.deepcopy(self.assessment)
        gap["themes"][-1]["independent_ai_rank"] += 1
        with self.assertRaisesRegex(ContractError, "contiguous"):
            validate_ai_theme_assessment(gap, self.packages["blind"])

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
        result = reconcile_rankings(mechanical, self.assessment)
        self.assertEqual(result["decision"], "NO_SELECTION")
        self.assertTrue(all(row["integrated_rank"] is None for row in result["themes"]))

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
