import copy, datetime as dt, tempfile, unittest
from pathlib import Path

from rotation.pipeline import build_snapshot
from rotation.analysis_v3 import build_authoritative_v3
from rotation.consumer_v3 import build_consumer_v3, load_and_validate_consumer_v3
from rotation.publication import publish_generation
from scripts.export_consumer_v3 import export_consumer_v3
from scripts.generate_weekly import history_item
from tests.test_pipeline_contract import synthetic_inputs


class V3ProductionE2E(unittest.TestCase):
    def production_snapshot(self):
        config,master,observations,history,previous=synthetic_inputs()
        dates=["2026-05-08","2026-05-15","2026-05-22","2026-05-29","2026-06-05","2026-06-12","2026-06-19","2026-06-26","2026-07-03"]
        template=history[0]
        history=[]
        for index,date in enumerate(dates):
            item=copy.deepcopy(template); item["data_date"]=date
            item["themes"]["fixture_theme"]["equal_weight_rel_spy_4w"]=.01+index*.005
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
        self.assertNotIn("companies",projection["phases"][6]); self.assertEqual(len(projection["phases"][4]["classification_summary"]),4)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); publish_generation(root/"output",snapshot,history_item(snapshot),{"index_version":"1.0","records":[]})
            destination=root/"consumer"/"v3"; export_consumer_v3(root/"output",destination)
            pointer,manifest,phases,details,handoffs=load_and_validate_consumer_v3(destination)
            self.assertEqual(pointer["identity"],manifest["identity"]); self.assertEqual(manifest["presentation"]["analysis_mode"],"trend")
            export_consumer_v3(root/"output",destination)
            part=destination/pointer["generation_manifest_path"].replace("manifest.json","phases/phase-1/part-1.json")
            part.write_bytes(part.read_bytes().replace(b"theme_assessments",b"themeXassessments",1))
            with self.assertRaises(Exception): load_and_validate_consumer_v3(destination)

    def test_future_forward_outcome_is_rejected(self):
        snapshot=self.production_snapshot()
        snapshot["v3_inputs"]["themes"]["fixture_theme"]["forward_samples"].append(
            {"prediction_date":"2026-07-03","outcome_date":"2026-08-01","return":.1})
        with self.assertRaisesRegex(ValueError,"future"): build_authoritative_v3(snapshot)

if __name__=="__main__": unittest.main()
