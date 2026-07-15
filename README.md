# US Market Rotation & Theme Flow v1.1

米国株を市場環境→スタイル→セクター・業種→テーマ→個別DDの順に調べる週次データ基盤です。data schema `1.1`、methodology `1.1.0`、Custom GPT instruction `1.1.0`を使用します。

数値計算、欠損処理、market regime、phase、direction、evidence、research priority、テーマ市場状態、shortlistはコードが決定します。Custom GPTは結果を変更せず、説明、反対証拠、定性補足、個別DD引継ぎを担当します。価格上昇を直接的な資金流入とは扱いません。

Theme membershipはsnapshotのdata dateに対する`active/valid_from/valid_to`でpoint-in-time選択します。同一tickerの非重複・隣接期間は履歴として許可し、重複期間、逆転期間、異常日付は拒否します。50DMA breadthは実測countをweekly historyへ保存し、旧履歴にcountがなければ推定しません。`equal_weight_led`はmethodologyに既存定義があり、1.1の正式なcode-side fieldとして採用しました。

## 1.1の主要変更

- `phase=initial|diffusion|price_overheat|unclassifiable`と`direction=improving|flat|worsening|outflow_signal|unclassifiable`を分離
- `price_overheat + outflow_signal`を同時保持
- 同じ4週relative指標の前週差、3週・4週OLS slope/stateを生成
- defined 6社、valid 5社、coverage 75%、role valid 2社、連続historyを機械判定
- top1/top3 positive contributionとnullable market-cap weighting divergenceを実装
- P0〜P5/fallbackとT0〜T4/fallbackをcode-side決定
- `overheat_breadth_weak`をcode-side flag化
- 総合スコアを使わない辞書式shortlistを最大5テーマまで生成
- immutable judgment 1.0と検証済み`previous_judgments` projectionを追加
- strict Draft 2020-12 JSON Schemaとsemantic再計算validatorを追加
- phase/direction/evidenceのcanonical condition IDをproductionで生成・再検証
- generation全体をstagingし、atomic `current.json` pointerで公開世代を切替

## 主要構成

```text
rotation/                          純粋なmetric・trend・quality・分類・shortlist処理
config/universe.json               ETF・指数定義 1.1.0
data/themes.json                   theme master schema 1.0 / content 2026-Q3-r1
data/legacy/                       移行前の暫定master（read-only）
scripts/generate_weekly.py         週次生成・検証・atomic publish
scripts/validate_repository.py     strict schema＋semantic検証
scripts/migrate_1_0_to_1_1.py      明示的なread-only migration report
scripts/migrate_theme_master.py    暫定masterからmaster 1.0への明示migration
schemas/rotation_snapshot.schema.json  latest data 1.1
schemas/judgment_record.schema.json    immutable judgment 1.0
schemas/theme_master.schema.json       theme master 1.0
schemas/legacy/                    latest 1.0 schemaの保存
tests/fixtures/                    架空fixture
output/judgments/                  immutable judgmentと再生成index
output/generations/<run_id>/       同一世代のlatest/archive/history/judgment index/manifest
output/current.json                検証済み公開世代を指すatomic pointer
output/predictions/                legacy prediction 1.0（read-only）
output/verifications/              legacy verification 1.0（read-only）
```

## セットアップと検証

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python scripts/validate_repository.py
.venv/Scripts/python scripts/generate_weekly.py --fixture tests/fixtures/latest_normal.json --dry-run
```

Test ownership and stable specification IDs are documented in
[`tests/TEST_CLASSIFICATION.md`](tests/TEST_CLASSIFICATION.md). The required PR
checks are the six non-overlapping categories in that document, including
`production-orchestration-e2e` and transactional publication; all use offline
synthetic data and fixed source identities.

Linux/macOSでは`.venv/bin/python`を使用します。PR必須checkは架空データだけを使い、networkと実時刻に依存しません。live取得はschedule/manualのweekly workflowだけです。

## 週次生成

```bash
python scripts/generate_weekly.py --dry-run
python scripts/generate_weekly.py
```

生成開始時のcommit SHA、data date、固定clockからrun identityを作ります。`output/.staging-*`へarchive、history、judgment index、latest、manifestを全生成し、Schema・semantic・hash・run ID・data dateを照合します。完成したdirectoryを`output/generations/<run_id>/`へrenameした後、small pointer `output/current.json`だけをatomic replaceします。consumerはpointerが指す同一世代だけを読み、orphan staging/generationを参照しません。同一run再実行はidempotent、同一data dateの異内容は明示拒否です。

汎用semantic validatorは診断用の`status=failed`も原因付きで検証できますが、公開validatorは`status=success`、`failure_reason=null`、`critical_missing=[]`、source hash一致を必須とします。固定互換パス`output/latest.json`が存在する場合にも同じ公開validatorを適用します。

`meta.valid_until`は生成から10日、`hard_stop_after`は14日です。unsupported version、`status=failed`、critical missing、source hash不一致は分析停止です。

## priorityとテーマ市場状態

priority precedenceは`P0 → P1 → P2 → P5 → P4 → P3 → fallback`です。P1はselected phaseがdiffusion、P2はselected phaseがprice_overheatかつdiffusion flag=trueであり相互排他的です。P1/P2/P3は`evidence.direction=inflow`を必須とします。

theme-state precedenceは`T0 → T1 → T2 → T3 → T4 → fallback`です。schema fieldは`timing_status`ですが、表示名は「テーマ市場状態」であり、個別銘柄のentry timingではありません。

shortlist対象は`dd_priority|dd_candidate|watch`だけです。priority→evidence direction→phase→direction→concentration→relative rank→theme_idの辞書式順序で最大5件を選びます。3件未満でも`low_priority`や`unclassifiable`で穴埋めしません。

## judgmentとlegacy

新規判断は`schemas/judgment_record.schema.json`に準拠して`output/judgments/*.json`へ保存し、既存byteを変更しません。source latestとのtheme集合、全code-side classification、evidence、quality、condition IDs、shortlist採否・連番rank、固定metrics、version・hashが完全一致したrecordだけをindexへ含めます。旧prediction/verificationは意味が異なるため自動変換・削除しません。

Market Rotation 1.0はdefaultで拒否します。`scripts/migrate_1_0_to_1_1.py --explicit`は推測を行わない非publishable reportだけを生成します。完全な1.1はsource observationから再生成してください。詳細は[Migration](docs/migration_v1.1.md)と[Rollback](docs/rollback_v1.1.md)を参照してください。

## 限界

- direct ETF/fund flow、earnings revisions、short/options positioningは未実装
- market capはpoint-in-time保証がない間は補助fieldで、coverage不足時は`null`
- `role=core`はtheme中心性だけで、品質、収益性、moat、valuation、投資魅力度を意味しない
- theme masterは市場全体の自動発見ではなく、四半期review対象
- 閾値は未較正の暫定値で、履歴へ合わせて事後最適化しない

方法論は[Methodology 1.1.0](docs/methodology_v1.1.md)、field定義は[Data Dictionary](docs/data_dictionary_v1.1.md)、Custom GPT契約は[Instructions 1.1.0](docs/custom_gpt_instructions_v1.1.md)が正本です。
