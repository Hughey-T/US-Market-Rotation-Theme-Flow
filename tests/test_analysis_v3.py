import copy, unittest
from pathlib import Path
from rotation.analysis_v3 import (build_authoritative_v3, display_percent,
    fundamental_confirmation, multiple_comparison, overlap_clusters,
    persistence_statistics, risk_adjusted_metrics, threshold_assessment)
from rotation.consumer_v3 import build_consumer_v3, validate_consumer_v3
from tests.test_publication_contract import generation
from rotation.fundamentals import load_point_in_time_fundamentals

class AnalysisV3Tests(unittest.TestCase):
    def test_threshold_display_and_confidence_are_deterministic(self):
        value=threshold_assessment(.2273157873932899,.05)
        self.assertAlmostEqual(value["margin"],.1773157873932899)
        self.assertEqual(value["signal_confidence"],"high")
        shown=display_percent(.2273157873932899,rank=1,threshold=.05)
        self.assertEqual(shown["display_value"],"+22.7%")
        self.assertEqual(shown["margin_to_threshold_display"],"+17.7pt")

    def test_risk_adjustment_and_minimum_observation_missingness(self):
        self.assertEqual(risk_adjusted_metrics([.01]*19,[.005]*19)["status"],"not_available")
        result=risk_adjusted_metrics([i/1000 for i in range(30)],[i/2000 for i in range(30)])
        self.assertEqual(result["status"],"available")
        self.assertAlmostEqual(result["market_beta"],2)

    def test_multiple_comparison_penalty_and_forward_sample(self):
        result=multiple_comparison(.4,[.1,.2,.3,.4],1,.8,[.01]*5)
        self.assertEqual(result["single_week_penalty"],.15)
        self.assertEqual(result["forward_return"]["status"],"available")

    def test_classification_persistence_and_churn(self):
        history=[{"data_date":"2026-07-03","classification":"watch","value":.01},{"data_date":"2026-07-10","classification":"research","value":.04}]
        result=persistence_statistics("research",.06,history)
        self.assertEqual(result["analysis_mode"],"trend"); self.assertEqual(result["signal_persistence_weeks"],2)
        self.assertAlmostEqual(result["prior_generation_delta"],.02); self.assertAlmostEqual(result["classification_churn"],.5)

    def test_fundamental_statuses_and_field_missingness(self):
        self.assertEqual(fundamental_confirmation(None,True)["status"],"price_only")
        record={"revenue_growth":{"status":"available","value":.2,"source":"fixture","as_of":"2026-07-17","confirmation":True}}
        self.assertEqual(fundamental_confirmation(record,True)["status"],"price_and_fundamentals")
        self.assertEqual(fundamental_confirmation(record,False)["status"],"fundamentals_only")
        loaded=load_point_in_time_fundamentals(Path("tests/fixtures/fundamentals_v1.json"),"2026-07-17")
        self.assertEqual(loaded["fixture_theme"]["earnings_growth"]["status"],"not_available")

    def test_overlap_cluster_is_order_independent(self):
        snapshot=generation("2026-07-17","overlap-v3")
        snapshot["themes"]={"b":{"constituents":[{"ticker":"A"},{"ticker":"B"}],"metrics":{}},"a":{"constituents":[{"ticker":"A"},{"ticker":"B"}],"metrics":{}}}
        first=overlap_clusters(snapshot); snapshot["themes"]={k:snapshot["themes"][k] for k in reversed(snapshot["themes"])}
        self.assertEqual(first,overlap_clusters(snapshot)); self.assertTrue(first[0]["breadth_overstatement_warning"])

    def test_phase5_phase6_handoff_and_v3_e2e(self):
        snapshot=generation("2026-07-17","authoritative-v3")
        projection=build_authoritative_v3(snapshot)
        self.assertIsInstance(projection["phases"][5]["companies"],list)
        self.assertNotIn("companies",projection["phases"][6])
        self.assertNotEqual(projection["phases"][6],projection["phases"][5])
        pointer,manifest,phases,details,handoffs=build_consumer_v3(snapshot)
        validate_consumer_v3(pointer,manifest,phases,details,handoffs)
        self.assertIn("handoff_inventory",manifest)

if __name__ == "__main__": unittest.main()
