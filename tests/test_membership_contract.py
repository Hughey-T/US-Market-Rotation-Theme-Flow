import copy
import datetime as dt
import unittest
from pathlib import Path

from rotation.membership import member_is_effective
from rotation.pipeline import build_snapshot
from rotation.validation import ContractError, load_json, validate_schema, validate_theme_master_semantics
from tests.test_pipeline_contract import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEMA = load_json(ROOT / "schemas" / "theme_master.schema.json")


def generated(master, observations, history, previous):
    config, _, _, _, _ = synthetic_inputs()
    return build_snapshot(
        config=config,
        theme_master=master,
        observations=observations,
        history=history,
        previous_judgments=previous,
        generated_at=dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc),
        data_date="2026-07-10",
        source_commit="a" * 40,
    )


class MembershipContractTests(unittest.TestCase):
    def test_zero_and_one_active_member_are_p0_without_zero_division(self):
        _, master, observations, history, previous = synthetic_inputs()
        active_theme = copy.deepcopy(master["themes"][0])
        active_theme["theme_id"] = "supporting_theme"
        master["themes"].append(active_theme)
        for row in history:
            row["themes"]["supporting_theme"] = copy.deepcopy(row["themes"]["fixture_theme"])
        for member in master["themes"][0]["members"]:
            member["active"] = False
        zero = generated(master, observations, history, previous)["themes"]["fixture_theme"]
        self.assertEqual((zero["quality"]["constituent_count"], zero["quality"]["coverage_ratio"]), (0, 0.0))
        self.assertEqual(zero["classifications"]["research_priority_rule"], "P0")
        self.assertEqual(zero["condition_flags"]["matched_conditions"], [])
        self.assertEqual(zero["condition_flags"]["unmatched_conditions"], [])
        self.assertEqual(zero["classifications"]["evidence"]["matched_conditions"], [])
        master["themes"][0]["members"][0]["active"] = True
        one = generated(master, observations, history, previous)["themes"]["fixture_theme"]
        self.assertEqual(one["quality"]["constituent_count"], 1)
        self.assertEqual(one["classifications"]["research_priority_rule"], "P0")

    def test_global_zero_active_constituents_is_explicit_failure(self):
        _, master, observations, history, previous = synthetic_inputs()
        for member in master["themes"][0]["members"]:
            member["active"] = False
        with self.assertRaisesRegex(ValueError, "global active constituent count is zero"):
            generated(master, observations, history, previous)

    def test_malformed_dates_fail_schema_and_runtime_predicate(self):
        _, master, _, _, _ = synthetic_inputs()
        for field in ("valid_from", "valid_to"):
            value = copy.deepcopy(master)
            value["themes"][0]["members"][0][field] = "not-a-date"
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_schema(value, MASTER_SCHEMA, "malformed master")
        member = copy.deepcopy(master["themes"][0]["members"][0])
        member["valid_from"] = "not-a-date"
        with self.assertRaises(ValueError):
            member_is_effective(member, "2026-07-10")
        with self.assertRaises(ValueError):
            member_is_effective(master["themes"][0]["members"][0], "not-a-date")

    def test_valid_from_after_valid_to_is_rejected(self):
        _, master, _, _, _ = synthetic_inputs()
        member = master["themes"][0]["members"][0]
        member.update(valid_from="2026-07-11", valid_to="2026-07-10")
        with self.assertRaisesRegex(ContractError, "after valid_to"):
            validate_theme_master_semantics(master)
        with self.assertRaisesRegex(ValueError, "after valid_to"):
            member_is_effective(member, "2026-07-10")

    def test_duplicate_and_overlapping_periods_are_rejected(self):
        _, master, _, _, _ = synthetic_inputs()
        duplicate = copy.deepcopy(master["themes"][0]["members"][0])
        master["themes"][0]["members"].append(duplicate)
        with self.assertRaisesRegex(ContractError, "duplicate membership period|overlapping"):
            validate_theme_master_semantics(master)
        master["themes"][0]["members"][-1].update(valid_from="2026-06-01", valid_to="2026-12-31")
        with self.assertRaisesRegex(ContractError, "overlapping membership periods"):
            validate_theme_master_semantics(master)

    def test_adjacent_periods_for_same_ticker_are_valid(self):
        _, master, _, _, _ = synthetic_inputs()
        first = master["themes"][0]["members"][0]
        first["valid_from"] = "2026-01-01"
        first["valid_to"] = "2026-06-30"
        second = copy.deepcopy(first)
        second.update(valid_from="2026-07-01", valid_to=None)
        master["themes"][0]["members"].append(second)
        validate_schema(master, MASTER_SCHEMA, "adjacent membership master")
        validate_theme_master_semantics(master)
        self.assertFalse(member_is_effective(first, "2026-07-01"))
        self.assertTrue(member_is_effective(second, "2026-07-01"))


if __name__ == "__main__":
    unittest.main()
