from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = ROOT / "docs" / "custom_gpt_instructions_current.md"


def _phase7_section() -> str:
    text = INSTRUCTIONS.read_text(encoding="utf-8")
    marker = "## Phase 7表示契約\n"
    if marker not in text:
        raise AssertionError("Phase 7 display contract section is missing")
    section = text.split(marker, 1)[1]
    return section.split("\n## ", 1)[0]


class CustomGptPhase7DisplayContractTests(unittest.TestCase):
    def test_phase7_discloses_fixed_assessment_and_ai_fields(self) -> None:
        section = _phase7_section()
        for required in (
            "固定済み同一hash",
            "AI順位表",
            "共通評価軸2〜3点",
            "上位3テーマの順位差",
            "正式選定順位ではない注意",
            "Phase8案内",
        ):
            with self.subTest(required=required):
                self.assertIn(required, section)

    def test_phase7_limits_observation_references(self) -> None:
        section = _phase7_section()
        for required in (
            "上位3テーマだけ",
            "1テーマにつき決定的な観測事実は最大1件",
            "因果解釈に不可欠な場合だけ",
            "Phase3で確認した相対強度と広がり",
            "下位5テーマは個別の価格指標を列挙せず",
        ):
            with self.subTest(required=required):
                self.assertIn(required, section)

    def test_phase7_forbids_rebuilding_phase3_output(self) -> None:
        section = _phase7_section()
        for forbidden_rule in (
            "Phase3のテーマ別数値表の再作成",
            "全8テーマのSPY対比・breadth・50日線・集中度の再掲",
            "下位5テーマの価格指標の個別説明",
            "順位表と本文での同一理由の反復",
            "AI因果解釈をPhase3の数値再掲で代替してはならない",
        ):
            with self.subTest(forbidden_rule=forbidden_rule):
                self.assertIn(forbidden_rule, section)

    def test_phase7_has_a_compact_body_budget(self) -> None:
        section = _phase7_section()
        self.assertIn("状態行を除き1,400文字以内", section)

    def test_canonical_instructions_remain_within_limit(self) -> None:
        text = INSTRUCTIONS.read_text(encoding="utf-8")
        self.assertLessEqual(len(text), 8_000)


if __name__ == "__main__":
    unittest.main()
