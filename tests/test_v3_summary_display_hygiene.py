import unittest
from pathlib import Path

from rotation.analysis_v3 import build_authoritative_v3
from tests.test_publication_contract import generation


ROOT = Path(__file__).resolve().parents[1]


class V3SummaryDisplayHygieneTests(unittest.TestCase):
    def test_research_priorities_are_unique_by_theme_in_first_seen_order(self):
        snapshot = generation("2026-07-17", "summary-theme-dedup")
        theme_id = next(iter(snapshot["themes"]))
        theme_label = snapshot["themes"][theme_id].get("label", theme_id)
        snapshot["company_candidates"] = [
            {
                "theme_id": theme_id,
                "theme_label": theme_label,
                "ticker": "AAA",
                "company_name": None,
                "selection_role": "representative",
                "why": "representative check",
                "key_check": "primary check",
                "counter_evidence": "counter evidence",
            },
            {
                "theme_id": theme_id,
                "theme_label": theme_label,
                "ticker": "BBB",
                "company_name": None,
                "selection_role": "breadth_check",
                "why": "breadth check",
                "key_check": "secondary check",
                "counter_evidence": "secondary counter evidence",
            },
        ]
        priorities = build_authoritative_v3(snapshot)["phases"][6]["research_priorities"]
        self.assertEqual(priorities, [theme_id])
        self.assertEqual(len(priorities), len(set(priorities)))
        self.assertLessEqual(len(priorities), 3)

    def test_instructions_hide_transport_and_long_trace_values_by_default(self):
        text = (ROOT / "docs" / "custom_gpt_instructions_current.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text), 8000)
        for required in (
            "正本指示 1.7.3",
            "内部検証・追跡値を表示しない",
            "長いused_dates配列は省略する",
            "利用者が検証方法を質問した場合だけ簡潔に説明する",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
