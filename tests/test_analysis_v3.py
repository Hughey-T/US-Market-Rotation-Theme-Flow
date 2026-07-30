import copy, unittest
from pathlib import Path
from rotation.analysis_v3 import (build_authoritative_v3, display_percent,
    fundamental_confirmation, selection_stability, overlap_clusters,
    persistence_statistics, risk_adjusted_metrics, threshold_assessment)
from rotation.consumer_v3 import build_consumer_v3, validate_consumer_v3
from tests.test_publication_contract import generation
from rotation.fundamentals import load_point_in_time_fundamentals
from rotation.analysis_v3 import price_signal

class AnalysisV3Tests(unittest.TestCase):
    def test_threshold_display_and_confidence_are_deterministic(self):
        value=threshold_assessment(.2273157873932899,.05)
        self.assertAlmostEqual(value["margin"],.1773157873932899)
        self.assertEqual(value["signal_confidence"],"high")
        shown=display_percent(.2273157873932899,rank=1,threshold=.05)
        self.assertEqual(shown["display_value"],"+22.7%")
        self.assertEqual(shown["margin_to_threshold_display"],"+17.7pt")

    def test_risk_adjustment_and_minimum_observation_missingness(self):
        points=lambda values:[{"date":f"2026-06-{i+1:02d}","return":v} for i,v in enumerate(values)]
        self.assertEqual(risk_adjusted_metrics(points([.01]*19),points([.005]*19))["status"],"not_available")
        result=risk_adjusted_metrics(points([i/1000 for i in range(30)]),points([i/2000 for i in range(30)]))
        self.assertEqual(result["status"],"available")
        self.assertAlmostEqual(result["market_beta"],2)
        shifted=[{"date":f"2026-07-{i+1:02d}","theme_realized_return":.02,"benchmark_realized_return":.01,"forward_excess_return":.01,"constituents_hash":"a"*64,"availability":"available"} for i in range(20)]
        mismatch=risk_adjusted_metrics(points([.01]*19),shifted)
        self.assertEqual(mismatch["observation_count"],0)
        zero=risk_adjusted_metrics(points([.01+i*.001 for i in range(20)]),points([.005]*20))
        self.assertIsNone(zero["market_beta"])

    def test_multiple_comparison_penalty_and_forward_sample(self):
        samples=[{"prediction_date":"2026-01-01","outcome_date":f"2026-0{i+2}-01","theme_realized_return":.02,"benchmark_realized_return":.01,"forward_excess_return":.01,"constituents_hash":"a"*64,"availability":"available"} for i in range(5)]
        result=selection_stability(.4,[.1,.2,.3,.4],1,.8,samples,"2026-07-17")
        self.assertEqual(result["single_week_penalty"],.15)
        self.assertEqual(result["forward_return"]["status"],"available")

    def test_classification_persistence_and_churn(self):
        history=[{"data_date":"2026-07-03","classification_version":"candidate_bucket_v3","candidate_bucket":"watch_recovery","value":.01},{"data_date":"2026-07-10","classification_version":"candidate_bucket_v3","candidate_bucket":"research_now","value":.04}]
        result=persistence_statistics("research_now",.06,history)
        self.assertEqual(result["analysis_mode"],"trend"); self.assertEqual(result["signal_persistence_weeks"],2)
        self.assertAlmostEqual(result["prior_generation_delta"],.02); self.assertAlmostEqual(result["classification_churn"],.5)
        four=[{"data_date":f"2026-07-{i:02d}","classification_version":"candidate_bucket_v3","candidate_bucket":bucket,"value":i/100}
              for i,bucket in enumerate(("research_now","watch_recovery","long_term_context_price_weak"),1)]
        changed=persistence_statistics("avoid_now",.0,four)
        self.assertEqual(changed["signal_persistence_weeks"],1); self.assertEqual(changed["classification_churn"],1)

    def test_fundamental_statuses_and_field_missingness(self):
        self.assertEqual(fundamental_confirmation(None,True)["status"],"price_only")
        record={"revenue_growth":{"status":"available","value":.2,"source":"fixture","as_of":"2026-07-17","confirmation":True}}
        self.assertEqual(fundamental_confirmation(record,True)["status"],"price_and_fundamentals")
        self.assertEqual(fundamental_confirmation(record,False)["status"],"fundamentals_only")
        loaded=load_point_in_time_fundamentals(Path("tests/fixtures/fundamentals_v1.json"),"2026-07-17")
        self.assertEqual(loaded["fixture_theme"]["earnings_growth"]["status"],"not_available")

    def test_price_confirmation_is_not_data_availability(self):
        base={"metrics":{"equal_weight_rel_spy_4w":.06,"advance_ratio_4w":.7,"pct_above_50dma":.6},
              "quality":{"classification_eligible":True},"decision":{"candidate_bucket":"research_now"}}
        self.assertTrue(price_signal(base)["confirmed"])
        cases=[]
        for mutate in (
            lambda x:x["metrics"].__setitem__("equal_weight_rel_spy_4w",-.01),
            lambda x:x["metrics"].__setitem__("equal_weight_rel_spy_4w",.04),
            lambda x:x["metrics"].__setitem__("advance_ratio_4w",.4),
            lambda x:x["quality"].__setitem__("classification_eligible",False),
            lambda x:x["metrics"].__setitem__("equal_weight_rel_spy_4w",None),
        ):
            value=copy.deepcopy(base); mutate(value); cases.append(price_signal(value))
        self.assertTrue(all(not x["confirmed"] for x in cases)); self.assertFalse(cases[-1]["data_available"])

    def test_overlap_cluster_is_order_independent(self):
        snapshot=generation("2026-07-17","overlap-v3")
        snapshot["themes"]={"b":{"constituents":[{"ticker":"A"},{"ticker":"B"}],"metrics":{}},"a":{"constituents":[{"ticker":"A"},{"ticker":"B"}],"metrics":{}}}
        points=[{"date":f"2026-06-{i+1:02d}","return":i*.001} for i in range(20)]
        snapshot["v3_inputs"]={"themes":{"a":{"theme_returns":points,"factor_exposures":["growth"]},"b":{"theme_returns":points,"factor_exposures":["growth"]}}}
        first=overlap_clusters(snapshot); snapshot["themes"]={k:snapshot["themes"][k] for k in reversed(snapshot["themes"])}
        self.assertEqual(first,overlap_clusters(snapshot)); self.assertTrue(first[0]["breadth_overstatement_warning"])
        self.assertEqual(first[0]["theme_return_correlation"]["status"],"available"); self.assertEqual(first[0]["common_factor_exposure"],["growth"])

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
