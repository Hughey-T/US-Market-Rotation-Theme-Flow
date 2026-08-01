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

    def test_instructions_hide_transport_and_explain_results_for_people(self):
        text = (ROOT / "docs" / "custom_gpt_instructions_current.md").read_text(
            encoding="utf-8"
        )
        self.assertLessEqual(len(text), 8000)
        for required in (
            "正本指示 1.8.0",
            "検証用データをそのまま並べることは目的ではない",
            "要約、平易な言い換え、重要度に応じた取捨選択",
            "### 結論",
            "### なぜそう言えるか",
            "### 投資家としてどう見るか",
            "内部IDは原則表示しない",
            "長いused_dates配列は省略する",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "Phase6は専用summaryを再要約しない",
            "Phase1〜5は「今回わかったこと／根拠と詳細／投資判断への意味／注意点／次に確認すること」を省略せず",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
