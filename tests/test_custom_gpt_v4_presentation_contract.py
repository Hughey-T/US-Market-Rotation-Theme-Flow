from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = ROOT / "docs" / "custom_gpt_instructions_current.md"


def _instructions() -> str:
    return INSTRUCTIONS.read_text(encoding="utf-8")


class CustomGptV4PresentationContractTests(unittest.TestCase):
    def test_all_phase_headings_are_fixed_and_state_owned(self) -> None:
        text = _instructions()
        self.assertIn("# Phase X / 全10 Phase — <日本語の内容名>", text)
        self.assertIn("session stateから取得", text)
        self.assertIn("利用者入力・引用の番号を信用しない", text)
        self.assertIn("`### 結論`より前に1回だけ", text)
        self.assertIn("エラー回答では見出しを出さず", text)
        self.assertIn("v1〜v3 fallbackへ適用しない", text)
        for title in (
            "データ確認とAI評価の固定",
            "市場環境とスタイル判定",
            "固定コアテーマの観測",
            "持続性・拡散・過熱",
            "テーマ重複と独立性",
            "動的業種と企業候補",
            "独立AI順位",
            "反対仮説と見直し条件",
            "機械判定と正式選定",
            "最終結果と引き継ぎ",
        ):
            with self.subTest(title=title):
                self.assertIn(title, text)

    def test_phase1_is_already_executing_without_early_disclosure(self) -> None:
        text = _instructions()
        self.assertIn("実行中・実行済みとして自然に表現", text)
        self.assertIn("`Phase 1を開始できます`を使わない", text)
        self.assertIn("開示予定Phase7", text)
        self.assertIn("assessment hash", text)
        self.assertIn("mechanical取得前固定だけ", text)
        self.assertIn("independent AI rank、theme別confidence、theme別理由", text)

    def test_phase3_uses_table_first_without_gate_leakage(self) -> None:
        text = _instructions()
        self.assertIn("数値表を主表示", text)
        self.assertIn("4テーマ以内を目安", text)
        self.assertIn("全8テーマを読み直さない", text)
        self.assertIn("+5.0%未満は「明確に上回った」とせず", text)
        self.assertIn("formal gate、hard exclusion、selection eligibilityを先出ししない", text)

    def test_phase9_localizes_labels_and_uses_canonical_reasons(self) -> None:
        text = _instructions()
        for label in (
            "SPYに対する相対強度",
            "上昇の広がり",
            "データ・分類品質",
            "業績・事業面の確認",
            "重大な除外条件",
            "現在の扱い",
            "正式選定の可否",
            "通過",
            "未通過",
            "判定不能",
            "現時点では見送り",
            "回復監視",
            "正式選定なし",
        ):
            with self.subTest(label=label):
                self.assertIn(label, text)
        self.assertIn("`true`、`false`、`pass`、`fail`、`not_evaluable`、`avoid_now`、`watch_recovery`を主表示にしない", text)
        self.assertIn("machine_reason_components.quality", text)
        self.assertIn("quality_reasons", text)
        self.assertIn("missing_required_fields", text)
        self.assertIn("別gateから推測しない", text)
        self.assertIn("理由詳細はproducerデータに未収録", text)
        self.assertIn("全8テーマを再説明しない", text)
        self.assertIn("`NO_SELECTION`は正常結果", text)

    def test_instruction_identity_and_size(self) -> None:
        text = _instructions()
        self.assertTrue(text.startswith("# US Market Rotation & Theme Flow — Custom GPT 正本指示 2.0.2"))
        self.assertEqual(len(text), 8_000)


if __name__ == "__main__":
    unittest.main()
