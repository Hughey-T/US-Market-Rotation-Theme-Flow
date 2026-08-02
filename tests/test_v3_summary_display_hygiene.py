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
            "正本指示 1.8.4",
            "検証用データをそのまま並べることは目的ではない",
            "要約、平易な言い換え、重要度に応じた取捨選択",
            "### 結論",
            "### なぜそう言えるか",
            "### 投資家としてどう見るか",
            "内部IDは原則表示しない",
            "長いused_dates配列は省略する",
            "過去4週間の等ウェイトテーマ収益率のSPY対比",
            "単純なテーマ騰落率として",
            "相関値は表示専用に小数2桁",
            "Phase1〜3は固定コアテーマ、Phase4以降は動的に発見した業種を含む広い候補群",
            "Phase1の順位や全テーマ値を繰り返さない",
            "Phase4・5の全文を繰り返さない",
            "初回観測を「単週」や「初回generation」と表現しない",
            "現在PhaseのpayloadにないSPY対比、breadth、threshold、業績評価をPhase1〜3から流用・推測しない",
            "保存済みsummaryの一般的な`next_update_checks`を特定テーマ固有の数値条件へ変換しない",
            "moving v3 manifestの`generation_manifest_sha256`",
            "`output/current.json`の`manifest_sha256`や別contractのhashを使わない",
            "Phase1〜5では、本文の最後に単独行で正確に `「次」と送信してください。`",
            "Phase6ではこの案内を表示せず",
            "全6 Phaseの表示は完了しました。",
            "鮮度コードは通常表示へ出さない",
            "`fresh`は「有効期間内」",
            "生成日時は日本時間へ換算する",
            "`generation`は通常文では「記録」または「更新回」と言い換える",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "Phase6は専用summaryを再要約しない",
            "Phase1〜5は「今回わかったこと／根拠と詳細／投資判断への意味／注意点／次に確認すること」を省略せず",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
