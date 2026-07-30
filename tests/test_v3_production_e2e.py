import copy, datetime as dt, tempfile, unittest
from pathlib import Path

from rotation.pipeline import build_snapshot
from rotation.analysis_v3 import build_authoritative_v3
from rotation.consumer_v3 import build_consumer_v3, load_and_validate_consumer_v3, reconstruct_fragments
from rotation.publication import publish_generation
from scripts.export_consumer_v3 import export_consumer_v3
from scripts.generate_weekly import history_item
from tests.test_pipeline_contract import synthetic_inputs
from rotation.provenance import stable_hash


class V3ProductionE2E(unittest.TestCase):
    def production_snapshot(self):
        config,master,observations,history,previous=synthetic_inputs()
        dates=["2026-05-08","2026-05-15","2026-05-22","2026-05-29","2026-06-05","2026-06-12","2026-06-19","2026-06-26","2026-07-03"]
        template=history[0]
        history=[]
        for index,date in enumerate(dates):
            item=copy.deepcopy(template); item["data_date"]=date
            item["themes"]["fixture_theme"]["equal_weight_rel_spy_4w"]=.01+index*.005
            row=item["themes"]["fixture_theme"]; row.update(theme_return_4w=.03+index*.01,spy_return_4w=.01+index*.002,
                candidate_bucket="research_now" if index>=4 else "watch_recovery",classification_version="candidate_bucket_v3",
                price_signal={"confirmed":index>=4},quality_status="eligible",constituents_hash=stable_hash({"date":date}))
            history.append(item)
        daily_dates=[(dt.date(2026,5,29)+dt.timedelta(days=i)).isoformat() for i in range(42) if (dt.date(2026,5,29)+dt.timedelta(days=i)).weekday()<5]
        for ticker,row in observations.items():
            scale=.001 if ticker=="SPY" else .0015
            row["_daily_returns"]=[{"date":date,"return":scale*(i%5-2)} for i,date in enumerate(daily_dates)]
        fundamental={"adapter_version":"1.0","as_of":"2026-07-10","source":"data/fundamentals/2026-07-10.json","source_sha256":"a"*64,
            "themes":{"fixture_theme":{"revenue_growth":{"status":"available","value":.2,"source":"public_filing","as_of":"2026-07-10","confirmation":True}}}}
        return build_snapshot(config=config,theme_master=master,observations=observations,history=history,previous_judgments=previous,
            generated_at=dt.datetime(2026,7,11,tzinfo=dt.timezone.utc),data_date="2026-07-10",source_commit="a"*40,fundamentals_bundle=fundamental)

    def test_production_shape_to_remote_disk_validation(self):
        snapshot=self.production_snapshot(); projection=build_authoritative_v3(snapshot)
        assessment=projection["phases"][1]["theme_assessments"][0]
        self.assertEqual(projection["analysis_mode"],"trend")
        self.assertEqual(assessment["risk_adjustment"]["status"],"available")
        self.assertFalse(assessment["persistence"]["history_insufficient"])
        self.assertEqual(assessment["fundamental_confirmation"]["status"],"price_and_fundamentals")
        self.assertEqual(assessment["selection_stability"]["forward_return"]["status"],"available")
        handoff=projection["handoffs"][0]; signal=assessment["price_signal"]
        self.assertEqual(handoff["price_signal_status"],"confirmed")
        self.assertEqual({k:handoff[k] for k in ("price_data_available","threshold_pass","breadth_pass","quality_pass","candidate_bucket")},
                         {"price_data_available":signal["data_available"],"threshold_pass":signal["threshold_pass"],
                          "breadth_pass":signal["breadth_pass"],"quality_pass":signal["quality_pass"],"candidate_bucket":signal["candidate_bucket"]})
        sample=snapshot["v3_inputs"]["themes"]["fixture_theme"]["forward_samples"][0]
        self.assertAlmostEqual(sample["theme_realized_return"],.07); self.assertAlmostEqual(sample["forward_excess_return"],.052)
        self.assertNotIn("companies",projection["phases"][6]); self.assertEqual(len(projection["phases"][4]["classification_summary"]),4)
        constituents=projection["phases"][3]["point_in_time_constituents"][0]
        self.assertNotEqual(constituents["theme_master_version"],"unknown"); self.assertTrue(constituents["universe_hash"])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); publish_generation(root/"output",snapshot,history_item(snapshot),{"index_version":"1.0","records":[]})
            destination=root/"consumer"/"v3"; export_consumer_v3(root/"output",destination)
            pointer,manifest,phases,details,handoffs=load_and_validate_consumer_v3(destination)
            self.assertEqual(pointer["identity"],manifest["identity"]); self.assertEqual(manifest["presentation"]["analysis_mode"],"trend")
            restored_handoff=reconstruct_fragments([fragment for chunk in handoffs for fragment in chunk["fragments"]])["handoffs"][0]
            self.assertEqual(restored_handoff["price_signal_status"],handoff["price_signal_status"])
            self.assertEqual(restored_handoff["threshold_pass"],handoff["threshold_pass"])
            export_consumer_v3(root/"output",destination)
            part=destination/pointer["generation_manifest_path"].replace("manifest.json","phases/phase-1/part-1.json")
            part.write_bytes(part.read_bytes().replace(b"theme_assessments",b"themeXassessments",1))
            with self.assertRaises(Exception): load_and_validate_consumer_v3(destination)

    def test_handoff_price_signal_unconfirmed_and_missing(self):
        snapshot=self.production_snapshot(); theme=snapshot["themes"]["fixture_theme"]
        theme["metrics"]["equal_weight_rel_spy_4w"]=.04
        unconfirmed=build_authoritative_v3(snapshot)["handoffs"][0]
        self.assertEqual(unconfirmed["price_signal_status"],"unconfirmed")
        self.assertFalse(unconfirmed["threshold_pass"])
        snapshot=self.production_snapshot(); snapshot["themes"]["fixture_theme"]["metrics"]["equal_weight_rel_spy_4w"]=None
        missing=build_authoritative_v3(snapshot)["handoffs"][0]
        self.assertEqual(missing["price_signal_status"],"not_available")
        self.assertFalse(missing["price_data_available"])

    def test_future_forward_outcome_is_rejected(self):
        snapshot=self.production_snapshot()
        snapshot["v3_inputs"]["themes"]["fixture_theme"]["forward_samples"].append(
            {"prediction_date":"2026-07-03","outcome_date":"2026-08-01","theme_realized_return":.2,"benchmark_realized_return":.1,
             "forward_excess_return":.1,"constituents_hash":"a"*64,"availability":"available"})
        with self.assertRaisesRegex(ValueError,"future"): build_authoritative_v3(snapshot)
        snapshot=self.production_snapshot(); snapshot["v3_inputs"]["fundamentals"]["themes"]["fixture_theme"]["revenue_growth"]["as_of"]="2026-08-01"
        with self.assertRaisesRegex(ValueError,"future fundamental"): build_authoritative_v3(snapshot)

    def test_success_generation_requires_universe_identity(self):
        snapshot=self.production_snapshot(); snapshot["meta"]["universe_definition"].pop("universe_hash")
        with self.assertRaisesRegex(ValueError,"universe identity"): build_authoritative_v3(snapshot)

    def test_unconfigured_optional_inputs_warn_but_do_not_make_core_critical(self):
        config,master,observations,history,previous=synthetic_inputs()
        snapshot=build_snapshot(config=config,theme_master=master,observations=observations,history=history,previous_judgments=previous,
            generated_at=dt.datetime(2026,7,11,tzinfo=dt.timezone.utc),data_date="2026-07-10",source_commit="a"*40)
        coverage=build_authoritative_v3(snapshot)["coverage"]
        self.assertEqual(coverage["optional_input_status"],"not_assessed_or_partial")
        self.assertEqual(coverage["status"],"warning")

    def test_constituent_exclusion_missing_and_unavailable_are_distinct(self):
        snapshot=self.production_snapshot(); membership=snapshot["v3_inputs"]["themes"]["fixture_theme"]["membership"]
        membership[0].update(active=False,effective=False,reason="inactive")
        membership[1].update(effective=True,data_available=False)
        membership.append({"ticker":"MISSING","active":True,"effective":True,"reason":"included","data_available":False})
        item=build_authoritative_v3(snapshot)["constituent_snapshots"][0]
        self.assertIn({"ticker":membership[0]["ticker"],"reason":"inactive"},item["exclusion_reasons"])
        self.assertIn(membership[1]["ticker"],item["unavailable_tickers"])
        self.assertIn("MISSING",item["missing_tickers"])

if __name__=="__main__": unittest.main()
