import copy
import unittest
from pathlib import Path

from rotation.provenance import snapshot_source_hash
from rotation.judgments import evaluate_withdrawal
from rotation.decisions import build_candidate_buckets, build_theme_decision, select_companies
from rotation.presentation import build_user_view
from rotation.shortlist import apply_shortlist
from rotation.validation import ContractError, load_json, validate_judgment_semantics, validate_schema
from tests.test_pipeline_contract import build_synthetic


ROOT = Path(__file__).resolve().parents[1]
JUDGMENT_SCHEMA = load_json(ROOT / "schemas" / "judgment_record.schema.json")
TEMPLATE = load_json(ROOT / "tests" / "fixtures" / "judgment_record.json")


def two_theme_source():
    source = build_synthetic()
    second = copy.deepcopy(load_json(ROOT / "tests" / "fixtures" / "latest_p5_low_priority.json")["themes"]["fixture_theme"])
    second["theme_id"] = "second_theme"
    second["label"] = "架空全面弱化theme"
    second["structural_context"] = {"version": "1.0", "status": "not_assessed", "as_of": "2026-07-10", "summary": "test context", "source_category": []}
    for index, constituent in enumerate(second["constituents"]):
        constituent["ticker"] = f"SECOND{index}"
    source["themes"]["second_theme"] = second
    source["themes"], source["theme_shortlist"] = apply_shortlist(source["themes"])
    source["candidate_buckets"] = build_candidate_buckets(source["themes"], source["dynamic_discovery"])
    source["company_candidates"] = select_companies(source["themes"], source["dynamic_discovery"], source["candidate_buckets"])
    for theme_id, theme in source["themes"].items():
        bucket = next(name for name in ("research_now", "watch_recovery", "long_term_context_price_weak", "avoid_now") if any(item["id"] == theme_id and item["source"] == "fixed_theme" for item in source["candidate_buckets"][name]))
        theme["decision"] = build_theme_decision(theme, bucket)
    source["user_view"] = build_user_view(regime=source["market_regime"], style_factor=source["style_factor"], sectors=source["sectors"], industries=source["industries"], themes=source["themes"], dynamic=source["dynamic_discovery"], buckets=source["candidate_buckets"], companies=source["company_candidates"], history_weeks=min(theme["quality"]["history_weeks"] for theme in source["themes"].values()))
    source["meta"]["universe_definition"]["theme_count"] = 2
    source["meta"]["source_sha256"] = snapshot_source_hash(source)
    return source


def complete_projection(source):
    record = copy.deepcopy(TEMPLATE)
    meta = source["meta"]
    record.update(
        run_id=meta["run_id"],
        data_date=meta["data_date"],
        source_commit=meta["source_commit"],
        source_snapshot=meta["source_snapshot"],
        source_sha256=meta["source_sha256"],
        data_schema_version=meta["schema_version"],
        methodology_version=meta["methodology_version"],
        instruction_version="1.3.0" if meta["schema_version"] == "1.2" else "1.1.1",
    )
    record["regime"] = copy.deepcopy(source["market_regime"]["classification"])
    template = record["theme_judgments"][0]
    judgments = []
    for theme_id, source_theme in source["themes"].items():
        theme = copy.deepcopy(template)
        cls = source_theme["classifications"]
        quality = source_theme["quality"]
        theme["theme_id"] = theme_id
        for field in ("phase", "direction", "research_priority", "research_priority_rule", "timing_status", "timing_rule"):
            theme[field] = cls[field]
        theme["evidence"] = {key: copy.deepcopy(cls["evidence"][key]) for key in ("level", "direction", "positioning_hypothesis", "matched_conditions")}
        theme["selected_for_deep_dive"] = source_theme["selected_for_deep_dive"]
        theme["shortlist_rank"] = source_theme["shortlist_rank"]
        theme["shortlist_reason_codes"] = copy.deepcopy(source_theme["shortlist_reason_codes"])
        theme["data_quality"] = {
            "classification_eligible": quality["classification_eligible"],
            "coverage_ratio": quality["coverage_ratio"],
            "valid_constituent_count": quality["valid_constituent_count"],
            "history_weeks": quality["history_weeks"],
            "missing_required_fields": copy.deepcopy(quality["missing_required_fields"]),
            "quality_reasons": copy.deepcopy(quality["quality_reasons"]),
        }
        theme["matched_conditions"] = copy.deepcopy(source_theme["condition_flags"]["matched_conditions"])
        theme["unmatched_conditions"] = copy.deepcopy(source_theme["condition_flags"]["unmatched_conditions"])
        for condition in theme["withdrawal_conditions"]:
            condition["field_path"] = condition["field_path"].replace("themes.fixture_theme.", f"themes.{theme_id}.", 1)
        for field in theme["key_metrics"]:
            theme["key_metrics"][field] = source_theme["metrics"][field]
        judgments.append(theme)
    record["theme_judgments"] = judgments
    selected = source["theme_shortlist"]["selected_theme_ids"]
    if selected:
        theme_id = selected[0]
        constituent = source["themes"][theme_id]["constituents"][0]
        record["dd_handoff"] = [{
            "ticker": constituent["ticker"], "theme_id": theme_id, "role": constituent["role"],
            "selection_reason": "source-aligned candidate", "dd_questions": ["verify fundamentals"],
        }]
    else:
        record["dd_handoff"] = []
    return record


class CompleteJudgmentProjectionTests(unittest.TestCase):
    def test_non_orderable_withdrawal_comparison_returns_unknown_instead_of_crashing(self):
        condition = {
            "condition_id": "TYPE_SAFE", "field_path": "themes.fixture_theme.classifications.phase",
            "operator": "<", "value": 1, "persistence_weeks": 1,
        }
        source = load_json(ROOT / "tests" / "fixtures" / "latest_normal.json")
        self.assertEqual(evaluate_withdrawal(condition, source, [])["status"], "unknown")
        equality = {**condition, "operator": "==", "value": 1}
        self.assertEqual(evaluate_withdrawal(equality, source, [])["status"], "unknown")

    def test_complete_projection_is_valid(self):
        sources = (
            two_theme_source(),
            load_json(ROOT / "tests" / "fixtures" / "latest_p2_overheat_diffusion.json"),
            load_json(ROOT / "tests" / "fixtures" / "latest_p5_low_priority.json"),
        )
        for source in sources:
            with self.subTest(rule=next(iter(source["themes"].values()))["classifications"]["research_priority_rule"]):
                record = complete_projection(source)
                validate_schema(record, JUDGMENT_SCHEMA, "complete judgment")
                validate_judgment_semantics(record, source)

    def test_eighteen_projection_and_handoff_mutations_are_rejected(self):
        source = two_theme_source()
        base = complete_projection(source)
        mutations = {}
        value = copy.deepcopy(base); value["theme_judgments"].pop(); mutations["source theme omitted"] = (value, source)
        value = copy.deepcopy(base); extra = copy.deepcopy(value["theme_judgments"][0]); extra["theme_id"] = "unknown_theme"; value["theme_judgments"].append(extra); mutations["unknown theme added"] = (value, source)
        value = copy.deepcopy(base); value["theme_judgments"][0]["evidence"]["positioning_hypothesis"] = "not_assessable"; mutations["positioning changed"] = (value, source)
        value = copy.deepcopy(base); value["theme_judgments"][0]["evidence"]["matched_conditions"] = ["EV_CORRUPTED"]; mutations["evidence conditions changed"] = (value, source)
        value = copy.deepcopy(base); value["theme_judgments"][0]["data_quality"]["coverage_ratio"] = 0.01; mutations["quality changed"] = (value, source)
        value = copy.deepcopy(base); value["theme_judgments"][0]["matched_conditions"] = ["PH_CORRUPTED"]; mutations["matched changed"] = (value, source)
        value = copy.deepcopy(base); value["theme_judgments"][0]["unmatched_conditions"] = ["PH_CORRUPTED"]; mutations["unmatched changed"] = (value, source)
        value = copy.deepcopy(base); value["theme_judgments"][1]["shortlist_rank"] = 3; mutations["rank gap"] = (value, source)
        value = copy.deepcopy(base); value["theme_judgments"][1]["shortlist_rank"] = 1; mutations["rank duplicate"] = (value, source)
        changed_source = copy.deepcopy(source); changed_source["themes"]["fixture_theme"]["metrics"]["advance_ratio_4w"] = 0.01; changed_source["meta"]["source_sha256"] = snapshot_source_hash(changed_source)
        value = copy.deepcopy(base); value["source_sha256"] = changed_source["meta"]["source_sha256"]; mutations["hash updated but source content changed"] = (value, changed_source)
        value = copy.deepcopy(base); value["dd_handoff"][0]["theme_id"] = "unknown_theme"; mutations["handoff unknown theme"] = (value, source)
        value = copy.deepcopy(base); value["dd_handoff"][0]["theme_id"] = "second_theme"; mutations["handoff unselected theme"] = (value, source)
        value = copy.deepcopy(base); value["dd_handoff"][0]["ticker"] = "UNKNOWN"; mutations["handoff unknown ticker"] = (value, source)
        value = copy.deepcopy(base); value["dd_handoff"][0]["ticker"] = source["themes"]["second_theme"]["constituents"][0]["ticker"]; mutations["handoff cross-theme ticker"] = (value, source)
        value = copy.deepcopy(base); value["dd_handoff"][0]["role"] = "peripheral"; mutations["handoff role changed"] = (value, source)
        value = copy.deepcopy(base); value["dd_handoff"].append(copy.deepcopy(value["dd_handoff"][0])); mutations["handoff duplicate pair"] = (value, source)
        value = copy.deepcopy(base); value["dd_handoff"] = [copy.deepcopy(value["dd_handoff"][0]) for _ in range(6)]; mutations["handoff over five"] = (value, source)
        changed_source = copy.deepcopy(source); changed_source["themes"]["fixture_theme"]["constituents"].pop(0); changed_source["meta"]["source_sha256"] = snapshot_source_hash(changed_source)
        value = copy.deepcopy(base); value["source_sha256"] = changed_source["meta"]["source_sha256"]; mutations["handoff source constituent removed"] = (value, changed_source)
        self.assertEqual(len(mutations), 18)
        for label, (record, source_value) in mutations.items():
            with self.subTest(label=label), self.assertRaises(ContractError):
                validate_judgment_semantics(record, source_value)


if __name__ == "__main__":
    unittest.main()
