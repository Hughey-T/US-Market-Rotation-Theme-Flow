#!/usr/bin/env python3
"""Validate consumer v4 schemas, fixture transport, and optional publication."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rotation.consumer_v4 import export_consumer_v4, load_and_validate_consumer_v4
from rotation.validation import ContractError, load_json


def validate_v4_schemas() -> int:
    root = ROOT / "schemas" / "v4"
    paths = sorted(root.glob("*.schema.json"))
    if len(paths) < 18:
        raise ContractError(f"consumer v4 schema inventory is incomplete: {len(paths)}")
    for path in paths:
        schema = load_json(path)
        Draft202012Validator.check_schema(schema)
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ContractError(f"consumer v4 schema must be a closed object: {path.name}")
    return len(paths)


def main() -> int:
    try:
        count = validate_v4_schemas()
        fixture = load_json(ROOT / "tests" / "fixtures" / "latest_normal.json")
        with tempfile.TemporaryDirectory(prefix="consumer-v4-validate-") as directory:
            root = Path(directory) / "v4"
            export_consumer_v4(fixture, root)
            load_and_validate_consumer_v4(root)
        published = ROOT / "output" / "consumer" / "v4"
        if published.exists():
            load_and_validate_consumer_v4(published)
        instructions = (ROOT / "docs" / "custom_gpt_instructions_current.md").read_text(encoding="utf-8")
        if len(instructions) != 8000:
            raise ContractError(f"Custom GPT instructions must contain exactly 8,000 characters: {len(instructions)}")
        required = (
            "正本指示 2.0.3", "consumer/v4/manifest.json", "全10 Phase",
            "# Phase X / 全10 Phase — <日本語の内容名>",
            "blind-handoff", "reconciliation-handoff", "session_local",
            "runtime_available=false", "mechanical rank", "independent AI rank",
            "integrated rank", "exact 404", "1 tool callにつき1 URL",
            "fixed_hidden", "Phase7", "pass／fail／not_evaluable",
            "RELATIVE_BELOW_THRESHOLD", "selection_eligible=true",
            "exploratory_only", "Phase10はPhase9より短く",
            "理由詳細は機械側データに未収録", "重大な除外理由", "正式選定なし",
            "| テーマ | 機械順位 | AI順位 | 現在の扱い | 正式選定 |",
            "| テーマ | SPYに対する相対強度 | 上昇の広がり | 品質・事業確認 | 重大な除外理由 |",
            "1表あたり最大5列", "監査情報（通常は読み飛ばせます）",
            "AI評価状態：固定済み・未開示",
            "candidate_origin=exploratory_company_candidate`の場合だけ",
            "候補の由来：探索企業候補",
            "正式結果=NO_SELECTION`の場合だけ",
            "機械側の正式結果は『正式選定なし』でした。",
            "正式選定ありは「正式選定」",
            "あり：理由詳細は機械側データに未収録",
            "巨大JSON・stack traceは非表示", "current/future outcome",
            "hard exclusionなしだけでは選定しない",
            "consumer v4正常回答末尾", "エラー回答には適用しない",
            "v1〜v3 fallbackには適用しない", "各1回", "本文とは空行で分離",
            "順位と最終的な扱い", "条件確認", "両表に全8テーマ",
            "同じ順序", "正式選定0件でも",
            "formal_dynamic_industry_present", "正式な動的業種の有無",
            "mechanical rank、independent AI rank、integrated rank、formal selection eligibilityは別物",
            "過去4週間の等ウェイトSPY対比", "blind projection hash",
            "payloadを会話内に固定保持しない",
            "generation/analysis identity", "package inventory", "part sequence",
            "raw byte length", "canonical reconstruction hash",
            "mechanical rank／independent AI rank",
            "正式選定列は「正式選定」または「正式選定なし」",
            "監査情報行を除き1,400文字以内", "AI固有の因果解釈",
            "0〜1外confidence", "independent AI順位表",
            "上位3テーマの順位差とAI固有の因果解釈",
            "formal dynamic industryが空でも探索企業候補は存在し得る",
            "+3.9%はプラスだが+5.0%基準に1.1ポイント不足で`RELATIVE_BELOW_THRESHOLD`",
            "Phase1ではデータ確認と評価固定を実行中・実行済み",
            "data quality、critical missing",
            "formal dynamic industryの有無",
            "AI固有の因果解釈、共通評価軸",
            "表後は正式結果、基準に近い1〜2テーマ、非除外だが未選定の重要例、重要なAI順位差、回復監視の意味だけ",
            "critical data quality failureとhard exclusionはAIが相殺できない",
            "AI上方変更には追加根拠", "下方変更には反対証拠",
            "不一致は追加調査へ残す",
            "counter-thesisは元assessmentを書き換えない",
            "exploratory theme/companyを正式set、ranking、handoffへ混ぜない",
            "取得base=`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/`",
            "current=`current.json`", "v4=`consumer/v4/manifest.json`",
            "v3=`consumer/v3/manifest.json`", "v2=`consumer/v2/manifest.json`",
            "v1=`consumer/v1/latest.json`", "legacy=`consumer/latest.json`",
            "取得baseと対応する相対pathを連結",
            "`initial_observation`の場合だけ",
            "direct flowがない場合だけ",
            "direct flowが存在する場合に「direct flowなし」と表示しない",
            "共通注意文は反復しない", "永続化状態はPhase10で再確認",
            "変更・再計算・欠損補完しない",
            "FACTS・MECHANICAL_SIGNALSは機械側",
            "AI_THEME_ASSESSMENTはCustom GPT",
            "AIの出力をFACTSと混同しない",
            "hash不一致は一時障害扱いしない",
        )
        missing = [term for term in required if term not in instructions]
        if missing:
            raise ContractError(f"Custom GPT instructions missing v4 terms: {missing}")
        if "Phase1〜8で`【機械判定】`を使わない" not in instructions:
            raise ContractError("Custom GPT instructions do not reserve machine-decision labeling for Phase 9")
        if "base+current.json" in instructions:
            raise ContractError("Custom GPT instructions contain an ambiguous base URL expression")
        print(f"consumer v4 validation passed: {count} closed schemas")
        return 0
    except (ContractError, OSError, ValueError) as error:
        print(f"consumer v4 validation failed:\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
