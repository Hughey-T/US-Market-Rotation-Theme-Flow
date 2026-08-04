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
        self.assertIn("データ確認と評価固定を実行中・実行済みとして自然に表現", text)
        self.assertIn("実行中・実行済みとして自然に表現", text)
        self.assertIn("`Phase 1を開始できます`を使わない", text)
        self.assertIn("開示予定Phase7", text)
        self.assertIn("assessment hash", text)
        self.assertIn("mechanical取得前固定だけ", text)
        self.assertIn("independent AI rank、theme別confidence、theme別理由", text)
        self.assertIn("AI上位・下位テーマ、assessment要約はPhase7より前に表示しない", text)
        self.assertIn("AI評価状態：固定済み・未開示", text)

    def test_sealed_assessment_and_v4_package_safety_rules_are_preserved(self) -> None:
        text = _instructions()
        self.assertIn(
            "assessment、counter-thesis、integrated decision、ledgerをGitHubへ永続保存済みと表現しない",
            text,
        )
        self.assertIn("current/future outcomeを含めない", text)
        self.assertIn("巨大JSON・stack traceは非表示", text)
        self.assertIn("blind projection hash", text)
        self.assertIn("0〜1外confidence", text)
        for integrity_term in (
            "generation/analysis identity", "package inventory", "part sequence",
            "raw byte length", "canonical reconstruction hash",
        ):
            with self.subTest(integrity_term=integrity_term):
                self.assertIn(integrity_term, text)

    def test_selection_and_rank_distinctions_do_not_regress(self) -> None:
        text = _instructions()
        self.assertIn("hard exclusionなしだけでは選定しない", text)
        self.assertIn(
            "mechanical rank、independent AI rank、integrated rank、formal selection eligibilityは別物",
            text,
        )

    def test_user_facing_internal_terms_are_localized(self) -> None:
        text = _instructions()
        for localized in (
            "固定済み・未開示", "探索企業候補", "探索専用", "機械側",
            "正式選定なし", "回復監視", "現時点では見送り", "判定不能",
            "正式な動的業種", "候補の由来", "テーマ所属", "順位付け対象", "引き継ぎ範囲",
            "正式な動的業種の有無",
        ):
            with self.subTest(localized=localized):
                self.assertIn(localized, text)
        self.assertIn(
            "`candidate_origin=exploratory_company_candidate`の場合だけ「候補の由来：探索企業候補」",
            text,
        )
        self.assertIn(
            "`正式結果=NO_SELECTION`の場合だけ「機械側の正式結果は『正式選定なし』でした。」",
            text,
        )
        self.assertIn("正式選定ありは「正式選定」", text)
        self.assertIn("`formal_dynamic_industry_present`は直接表示せず正式な動的業種の有無", text)

    def test_relative_gate_and_common_notice_wording_is_precise(self) -> None:
        text = _instructions()
        self.assertIn("relative gate=過去4週間の等ウェイトSPY対比`>= +5.0%`", text)
        self.assertIn(
            "+3.9%はプラスだが+5.0%基準に1.1ポイント不足で`RELATIVE_BELOW_THRESHOLD`",
            text,
        )
        for notice in (
            "今回が最初の記録で継続性未確認", "direct flowなし",
            "価格変化を資金流入・流出と断定しない", "session_local",
            "自動売買・証券連携・注文執行なし",
        ):
            with self.subTest(notice=notice):
                self.assertIn(notice, text)

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
            "品質・事業確認",
            "重大な除外理由",
            "現在の扱い",
            "正式選定",
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
        self.assertIn("あり：履歴3週未満／時価総額データのカバレッジ不足", text)
        self.assertIn("あり：理由詳細は機械側データに未収録", text)
        self.assertIn("重大な除外がなければ`なし`", text)
        self.assertIn("| テーマ | 機械順位 | AI順位 | 現在の扱い | 正式選定 |", text)
        self.assertIn("| テーマ | SPYに対する相対強度 | 上昇の広がり | 品質・事業確認 | 重大な除外理由 |", text)
        self.assertIn("品質：通過／事業：判定不能", text)
        self.assertIn("品質：未通過／事業：通過", text)
        self.assertIn("横長10列表は禁止", text)
        self.assertIn("1表あたり最大5列", text)
        self.assertIn("#### 順位と最終的な扱い", text)
        self.assertIn("#### 条件確認", text)
        self.assertIn("両表に全8テーマを同じ順序で掲載", text)
        self.assertIn("正式選定0件でも全8テーマを省略しない", text)
        self.assertIn("mechanical rank／independent AI rank", text)
        self.assertIn("正式選定列は「正式選定」または「正式選定なし」", text)
        self.assertIn("全8テーマを再説明しない", text)
        self.assertIn("`NO_SELECTION`は正常結果", text)
        self.assertIn(
            "表後は正式結果、基準に近い1〜2テーマ、非除外だが未選定の重要例、"
            "重要なAI順位差、回復監視の意味だけとし、全8テーマを再説明しない",
            text,
        )

    def test_restored_phase_ownership_and_reconciliation_rules_are_exact(self) -> None:
        text = _instructions()
        for ownership_rule in (
            "identity、data quality、critical missing、sealed状態だけ",
            "formal dynamic industryの有無を示す",
            "AI固有の因果解釈、共通評価軸を初公開する",
        ):
            with self.subTest(ownership_rule=ownership_rule):
                self.assertIn(ownership_rule, text)
        for reconciliation_rule in (
            "critical data quality failureとhard exclusionはAIが相殺できない",
            "AI上方変更には追加根拠",
            "下方変更には反対証拠",
            "不一致は追加調査へ残す",
            "counter-thesisは元assessmentを書き換えない",
            "exploratory theme/companyを正式set、ranking、handoffへ混ぜない",
        ):
            with self.subTest(reconciliation_rule=reconciliation_rule):
                self.assertIn(reconciliation_rule, text)

    def test_exploratory_candidates_remain_optional(self) -> None:
        text = _instructions()
        self.assertIn("formal dynamic industryが空でも探索企業候補は存在し得る", text)

    def test_phase7_character_limit_has_no_obsolete_duplicate(self) -> None:
        text = _instructions()
        self.assertIn("監査情報行を除き1,400文字以内", text)
        self.assertNotIn("状態行を除き1,400文字以内", text)

    def test_phase7_and_phase10_use_unambiguous_user_facing_terms(self) -> None:
        text = _instructions()
        self.assertIn("7. 固定済み同一hash、independent AI rank", text)
        self.assertIn("通常表示は正式引き継ぎ／回復監視／探索専用", text)
        self.assertIn("監査情報行を除き1,400文字以内", text)
        self.assertIn("AI固有の因果解釈", text)
        phase7 = text.split("## Phase 7表示契約\n", 1)[1].split("\n## ", 1)[0]
        ordered = (
            "固定済み同一hashの確認",
            "independent AI順位表",
            "共通評価軸2〜3点",
            "上位3テーマの順位差とAI固有の因果解釈",
            "正式選定順位ではない注意",
            "Phase8案内",
        )
        positions = [phase7.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_instruction_identity_and_size(self) -> None:
        text = _instructions()
        self.assertTrue(text.startswith("# US Market Rotation & Theme Flow — Custom GPT 正本指示 2.0.3"))
        self.assertEqual(len(text), 8_000)

    def test_audit_information_is_one_trailing_line(self) -> None:
        text = _instructions()
        audit = "監査情報（通常は読み飛ばせます）：mode=v4 / phase=<番号> / generation_id=<値> / contract=4.0 / manifest_sha256=<値> / assessment_sha256=<値>"
        self.assertIn(f"`{audit}`の1行", text)
        for scope_rule in (
            "consumer v4正常回答末尾（Phase 1〜10）",
            "本文とは空行で分離",
            "エラー回答には適用しない",
            "v1〜v3 fallbackには適用しない",
            "改名・削除不可、各1回だけ表示",
        ):
            with self.subTest(scope_rule=scope_rule):
                self.assertIn(scope_rule, text)
        self.assertIn("payloadを会話内に固定保持しない", text)

    def test_fetch_urls_use_explicit_base_and_relative_paths(self) -> None:
        text = _instructions()
        for url_rule in (
            "取得base=`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/`",
            "current=`current.json`",
            "v4=`consumer/v4/manifest.json`",
            "v3=`consumer/v3/manifest.json`",
            "v2=`consumer/v2/manifest.json`",
            "v1=`consumer/v1/latest.json`",
            "legacy=`consumer/latest.json`",
            "取得baseと対応する相対pathを連結",
        ):
            with self.subTest(url_rule=url_rule):
                self.assertIn(url_rule, text)
        self.assertNotIn("base+current.json", text)

    def test_phase1_common_notices_are_state_dependent(self) -> None:
        text = _instructions()
        conditional_rule = (
            "共通注意文は反復しない。`initial_observation`の場合だけ"
            "「今回が最初の記録で継続性未確認」、direct flowがない場合だけ"
            "「direct flowなし」とPhase1で表示し、direct flowが存在する場合に"
            "「direct flowなし」と表示しない。"
        )
        self.assertIn(conditional_rule, text)
        self.assertIn("永続化状態はPhase10で再確認", text)
        self.assertNotIn("Phase1で1回だけ表示:今回が最初の記録", text)

    def test_producer_and_ai_ownership_boundary_is_explicit(self) -> None:
        text = _instructions()
        for boundary_rule in (
            "FACTS・MECHANICAL_SIGNALSは機械側",
            "AI_THEME_ASSESSMENTはCustom GPT",
            "AIの出力をFACTSと混同しない",
            "機械側の数値、機械順位、機械分類、候補identity、hard exclusion、data quality、"
            "selection eligibilityは変更・再計算・欠損補完しない",
            "mechanical rank、independent AI rank、integrated rank、formal selection eligibilityは別物",
        ):
            with self.subTest(boundary_rule=boundary_rule):
                self.assertIn(boundary_rule, text)
        self.assertIn("hash不一致は一時障害扱いしない", text)


if __name__ == "__main__":
    unittest.main()
