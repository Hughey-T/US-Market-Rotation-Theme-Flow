import copy
import unittest

from rotation.analysis_v3 import build_authoritative_v3
from rotation.consumer_v3 import build_consumer_v3
from rotation.provenance import snapshot_source_hash
from tests.test_v3_production_e2e import V3ProductionE2E


class DynamicIndustryV3HandoffTests(unittest.TestCase):
    def dynamic_snapshot(self):
        snapshot = V3ProductionE2E().production_snapshot()
        dynamic_id = "oil_gas_exploration"
        metrics = copy.deepcopy(
            snapshot["themes"]["fixture_theme"]["metrics"]
        )
        metrics.update(
            equal_weight_rel_spy_4w=0.08,
            advance_ratio_4w=0.75,
            pct_above_50dma=0.75,
        )

        discovery = copy.deepcopy(snapshot["dynamic_discovery"])
        discovery["candidate_ids"] = [dynamic_id]
        discovery["candidates"][dynamic_id] = {
            "candidate_id": dynamic_id,
            "label": "Oil & Gas Exploration",
            "source": "dynamic_industry",
            "reference_etf": "XOP",
            "reference_etf_rel_spy_4w": 0.09,
            "eligible": True,
            "rejection_reasons": [],
            "structural_context": {
                "version": "1.0",
                "status": "not_assessed",
                "as_of": None,
                "summary": "not assessed",
                "source_category": [],
            },
            "metrics": metrics,
            "constituents": [
                {
                    "ticker": "DYN",
                    "return_4w": 0.12,
                    "rel_spy_4w": 0.10,
                    "above_50dma": True,
                    "positive_contribution_ratio": 0.5,
                    "dollar_volume_20d": 10_000_000,
                }
            ],
        }
        discovery["rejected"].pop(dynamic_id, None)
        snapshot["dynamic_discovery"] = discovery
        snapshot["candidate_buckets"]["research_now"].append(
            {
                "id": dynamic_id,
                "label": "Oil & Gas Exploration",
                "source": "dynamic_industry",
                "classification_reason": "research_now",
            }
        )
        snapshot["company_candidates"] = [
            {
                "theme_id": dynamic_id,
                "theme_label": "Oil & Gas Exploration",
                "source": "dynamic_industry",
                "ticker": "DYN",
                "company_name": "Dynamic Energy",
                "company_name_source": "test",
                "selection_role": "representative",
                "why": "dynamic industry breadth",
                "key_check": "check",
                "counter_evidence": "counter",
                "research_lens_source": "test",
            }
        ]
        snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)
        return snapshot, dynamic_id

    def test_dynamic_candidate_gets_authoritative_handoff(self):
        snapshot, dynamic_id = self.dynamic_snapshot()
        projection = build_authoritative_v3(snapshot)
        handoff = projection["handoffs"][0]

        self.assertEqual(handoff["theme_id"], dynamic_id)
        self.assertEqual(handoff["candidate_bucket"], "research_now")
        self.assertTrue(handoff["price_data_available"])
        self.assertTrue(handoff["threshold_pass"])
        self.assertTrue(handoff["breadth_pass"])
        self.assertTrue(handoff["quality_pass"])
        self.assertEqual(handoff["price_signal_status"], "confirmed")
        self.assertEqual(
            projection["coverage"]["configured_theme_count"],
            len(snapshot["themes"]),
        )

        pointer, manifest, phases, details, handoffs = build_consumer_v3(
            snapshot
        )
        self.assertEqual(pointer["identity"], manifest["identity"])
        self.assertTrue(phases)
        self.assertTrue(details)
        self.assertTrue(handoffs)

    def test_unowned_dynamic_candidate_fails_closed(self):
        snapshot, dynamic_id = self.dynamic_snapshot()
        snapshot["dynamic_discovery"]["candidates"].pop(dynamic_id)
        with self.assertRaisesRegex(
            ValueError, "dynamic industry candidate is missing"
        ):
            build_authoritative_v3(snapshot)


if __name__ == "__main__":
    unittest.main()
