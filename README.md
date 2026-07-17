# US Market Rotation & Theme Flow v1.2 user experience

Versions: data schema `1.2`（旧1.1は読み取り互換）、decision contract `3.0`、presentation `1.1`、Custom GPT instruction `1.3.0`、publication contract `1.0`。

米国株を市場環境→スタイル→セクター・業種→テーマ→個別企業→最終判断の6段階で調べる週次データ基盤です。内部では再現可能な監査情報を保持し、通常回答では結論・意味・注意点・次の確認だけを平易な日本語で表示します。週次preflight、commit、repository validatorは同一の厳密なpublication file inventoryを使用し、unknown file、invalid current、lock/staging残骸を取得・commit前に拒否します。

## 1.2 user experience の主要変更

- データ層、判断層、表示層を分離し、通常表示専用の `user_view` を追加
- 固定テーマ外の強い業種を、ETF信号＋最低3社の企業breadthで動的発見
- 候補を「個別企業を調べる」「回復条件を監視する」「長期材料はあるが、現在の株価は弱い」「現在は避ける」の相互排他的な4分類へ変更
- 固定テーマと動的業種へ、株価から推測しないversion付き構造的背景を追加
- 企業調査観点をティッカー上書き、テーマ別役割、構成上の役割、全体既定値の順で具体化
- 調査対象は0〜5件。弱い候補で枠を埋めない
- 価格上の選好と実際の資金フロー確認を別fieldに分離
- 履歴3週未満は初期観測モードとし、変化・反転・加速を断定しない
- 中央値、winsorized、流動性加重、寄与HHI、実効寄与企業数を追加
- 企業候補は1対象最大2社、全体でticker重複なし
- `更新` と5回の `次` だけで全6段階を完了

通常利用は [Custom GPT正本指示 1.3.0](docs/custom_gpt_instructions_current.md)（[GitHub raw正本](https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/main/docs/custom_gpt_instructions_current.md)）、完成形は [6段階の表示サンプル](docs/display_samples_v1.2.md)、方法は [Methodology 1.2](docs/methodology_v1.2.md)、fieldは [Data Dictionary 1.2](docs/data_dictionary_v1.2.md) を参照してください。

数値計算、欠損処理、market regime、theme判定、動的発見、4分類候補、企業候補、表示文はコードが決定します。Custom GPTは `user_view` を順番に提示し、結果を変更しません。価格上昇を直接的な資金流入とは扱いません。

Theme membershipはsnapshotのdata dateに対する`active/valid_from/valid_to`でpoint-in-time選択します。同一tickerの非重複・隣接期間は履歴として許可し、重複期間、逆転期間、異常日付は拒否します。50DMA breadthは実測countをweekly historyへ保存し、旧履歴にcountがなければ推定しません。`equal_weight_led`はmethodologyに既存定義があり、1.1の正式なcode-side fieldとして採用しました。

## 1.1監査基盤（継続）

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
output/generations/<generation_id>/ 同一世代のlatest/archive/history/judgment index/manifest
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
checks are the eight non-overlapping categories in that document, including
`production-orchestration-e2e` and transactional publication; all use offline
synthetic data and fixed source identities.

Linux/macOSでは`.venv/bin/python`を使用します。PR必須checkは架空データだけを使い、networkと実時刻に依存しません。feature branchではpull request eventだけが8 required checksを生成し、push eventは`main`に限定します。live取得はschedule/manualのweekly workflowだけです。workflowは保護された`main`へpushせず、初回だけ`main`から専用`publication`ブランチをbootstrapし、以後はcheckout時のremote SHA一致とancestor関係を確認して通常のfast-forward pushだけを許可します。競合またはremote先行時は公開せず停止します。

## 週次生成

```bash
python scripts/generate_weekly.py --dry-run
python scripts/generate_weekly.py
```

data date、raw input、theme master、各version、source commit、quantitative contentからclock非依存のanalysis identityを作り、実行時刻を含むgeneration identityを別に作ります。`output/.staging-*`へ全componentを生成し、各strict Schema・semantic・finite・hash・identity・versionを検証します。完成directoryを`output/generations/<generation_id>/`へrenameし、検証済みpointerだけをatomic replaceします。同一analysisの再実行はno-op、現在世代を直接の親とする同一analysisのvalid orphanだけを決定的に再利用します。通常publishでdata dateを後退させず、後退は明示的rollbackに限定します。同一data dateでも異なるanalysisは新世代として明示公開します。

汎用semantic validatorは診断用の`status=failed`も原因付きで検証できますが、公開validatorは`status=success`、`failure_reason=null`、`critical_missing=[]`、source hash一致を必須とします。固定互換パス`output/latest.json`が存在する場合にも同じ公開validatorを適用します。

`meta.valid_until`は生成から10日、`hard_stop_after`は14日です。unsupported version、`status=failed`、critical missing、source hash不一致は分析停止です。

## priorityとテーマ市場状態

priority precedenceは`P0 → P1 → P2 → P5 → P4 → P3 → fallback`です。P1はselected phaseがdiffusion、P2はselected phaseがprice_overheatかつdiffusion flag=trueであり相互排他的です。P1/P2/P3は`evidence.direction=inflow`を必須とします。

theme-state precedenceは`T0 → T1 → T2 → T3 → T4 → fallback`です。schema fieldは`timing_status`ですが、表示名は「テーマ市場状態」であり、個別銘柄のentry timingではありません。

shortlist対象は`dd_priority|dd_candidate|watch`だけです。priority→evidence direction→phase→direction→concentration→relative rank→theme_idの辞書式順序で最大5件を選びます。3件未満でも`low_priority`や`unclassifiable`で穴埋めしません。

## judgmentとlegacy

新規判断は`schemas/judgment_record.schema.json`に準拠して`output/judgments/*.json`へ保存し、既存byteを変更しません。PR CIはbase branch、通常のweekly publicationは取得済みの正確な`origin/publication` SHAと比較し、既存recordの変更・削除・renameをpush前に拒否します。source latestとのtheme集合、全code-side classification、evidence、quality、condition IDs、shortlist採否・連番rank、固定metrics、version・hashが完全一致したrecordだけをindexへ含めます。撤回条件は同じthemeの実在field、Schema上の型と互換なoperator/value、一意condition IDを必須とし、source値が`null`でも型検証を省略しません。旧prediction/verificationは意味が異なるため自動変換・削除しません。

Market Rotation 1.0はdefaultで拒否します。`scripts/migrate_1_0_to_1_1.py --explicit`は推測を行わない非publishable reportだけを生成します。完全な1.1はsource observationから再生成してください。詳細は[Migration](docs/migration_v1.1.md)と[Rollback](docs/rollback_v1.1.md)を参照してください。

## 限界

- direct ETF/fund flow、earnings revisions、short/options positioningは未実装
- market capはpoint-in-time保証がない間は補助fieldで、coverage不足時は`null`
- `role=core`はtheme中心性だけで、品質、収益性、moat、valuation、投資魅力度を意味しない
- 固定theme masterは四半期review対象。別枠の動的業種発見は設定済み企業basketの範囲に限る
- 閾値は未較正の暫定値で、履歴へ合わせて事後最適化しない

現状監査は[CURRENT_STATE](docs/CURRENT_STATE.md)、schema拡張は[Schema 1.2](docs/schema_v1.2.md)、実装は[Implementation Notes](docs/implementation_notes_v1.2.md)、テストは[Test Specification](docs/test_specification_v1.2.md)、運用は[Operations Guide](docs/operations_guide_v1.2.md)、移行は[Migration 1.2](docs/migration_v1.2.md)、公開契約は[Public Artifact 1.2](docs/public_artifact_v1.2.md)を参照してください。
## Publication contract 1.0

`publication`ブランチの`output/current.json`が唯一のauthoritative generation pointerです。Manifests and pointers carry `publication_contract_version=1.0`. `analysis_id` identifies deterministic inputs and logic without the clock; `generation_id` identifies one execution. `output/consumer/latest.json`は同一workflowでcurrentから生成・Schema検証・remote再取得比較まで完了した派生consumer exportであり、authoritative pointerの代替ではありません。ローカルでは次のcommandで同じexportを再生成できます。

```bash
python scripts/export_current_latest.py exported/latest.json
```

Custom GPTのGitHub sourceは`publication`ブランチの`output/consumer/latest.json`へ固定します。公開URLは`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/latest.json`です。初期設定後の日常操作は「更新」「次」だけで、週次のbranch作成、PR、Actions承認、merge、file添付を要求しません。A legacy fixed publication is migrated explicitly with `python scripts/migrate_publication_v1.py --explicit`; scheduled generation stops safely until migration. Inspect a lock with `python scripts/publication_lock.py inspect`; recover only an expired, non-live lock with `python scripts/publication_lock.py recover --stale-after-hours 6`.

This public repository protects `main` with pull requests, strict up-to-date required checks, resolved review conversations, and blocked force pushes and branch deletion. The eight required checks and the supplementary human release procedure are documented in the [Manual merge gate](docs/manual_merge_gate.md). No approving review is required by configuration, and repository administrators retain an emergency bypass path. A Draft PR remains Draft until final independent review is complete and must never be merged directly.
