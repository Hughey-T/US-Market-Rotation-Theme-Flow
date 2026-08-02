# US Market Rotation & Theme Flow

週次の米国市場データから、市場環境、スタイル、セクター・業種、テーマ、企業調査候補を決定論的に生成し、Custom GPTが独立した因果解釈と反証を行う調査基盤です。自動売買、証券会社連携、注文執行は行いません。

## Version matrix

| Layer | Version |
|---|---|
| data schema | 1.2 |
| mechanical decision | 3.0 |
| presentation | 1.2 |
| publication core | 1.1 |
| preferred consumer | 4.0 |
| supported fallback | 3.0、2.0、1.0、legacy |
| AI assessment | 1.0 |
| handoff | 2.0 |
| Custom GPT instruction | 2.0.0 |

## Machine/AI boundary

Producerはmarket data、point-in-time membership、数値、機械分類・順位、hard exclusion、company candidate identity、immutable publicationを所有します。Custom GPTはblind状態で因果仮説、structural/cyclical評価、independent AI rank、counter-thesis、exploratory proposalを生成します。

AIはproducerの数値、機械順位、候補identity、hard exclusionを変更しません。mechanical rank、independent AI rank、integrated rankは別fieldです。不一致は隠さず、`NO_SELECTION`を正式結果として維持します。

## Consumer v4

```text
output/consumer/v4/manifest.json
output/consumer/v4/generations/{generation_id}/manifest.json
output/consumer/v4/generations/{generation_id}/facts/part-{n}.json
output/consumer/v4/generations/{generation_id}/blind/part-{n}.json
output/consumer/v4/generations/{generation_id}/companies/part-{n}.json
output/consumer/v4/generations/{generation_id}/blind-handoff/part-{n}.json
output/consumer/v4/generations/{generation_id}/mechanical/part-{n}.json
output/consumer/v4/generations/{generation_id}/reconciliation-handoff/part-{n}.json
```

Blind packageはmechanical rank、candidate bucket、integrated rank、過去AI判断、AI confidence、current/future outcomeを再帰的に拒否します。AI assessmentをcanonical hashへ固定するまでreconciliation packageは開示されません。

## 10 Phase

1. 記録固定・データ品質・blind AI初期化
2. 市場環境とスタイルローテーション
3. 固定コアテーマの機械観測
4. 持続性・拡散・過熱
5. 重複・独立性
6. 動的業種と候補宇宙
7. 固定済みAI独立解釈
8. 反対仮説・自己批判・探索提案
9. 機械・AI・統合順位の照合
10. 企業調査仕様・二段階handoff・最終統合

進行操作は正確な`更新`と`次`だけです。1操作1 Phaseで、1回の応答内に対象Phaseを完了します。

## Persistence

既定は`session_local`です。AI assessment、counter-thesis、reconciliation、integrated decisionは会話内だけで保持され、GitHubへ永続保存済みとは表示しません。`runtime_persisted`はwrite-capable runtimeが実際に利用可能な場合だけ使用します。現状は`runtime_available=false`です。

既存のconsumer v1〜v3、immutable publication、point-in-time membership、dynamic industry discovery、selection stability、overlap analysis、matured four-week outcomesは維持します。未実装の直接fund flow、point-in-time market cap、short/options positioningは推測せず`not_available`として扱います。

## Validation

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/validate_repository.py
python scripts/validate_consumer_v4.py
python scripts/export_consumer_v4.py --snapshot tests/fixtures/latest_normal.json --destination /tmp/consumer-v4
python -m compileall -q rotation scripts tests
```

詳細は[consumer v4 architecture](docs/architecture_v4.md)、[current state](docs/CURRENT_STATE.md)、[Custom GPT正本指示](docs/custom_gpt_instructions_current.md)を参照してください。
