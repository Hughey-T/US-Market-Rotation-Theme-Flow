# US Market Rotation & Theme Flow v2

米国株を「市場環境→スタイル→セクター・業種→テーマ→銘柄群」の順に調べる、週次の定量データ基盤です。価格上昇を資金流入と同一視せず、数値計算と暫定局面判定をコード側、解釈・反証・定性調査をCustom GPT側へ分離します。

## v1案からの主要修正

- 古いデータを欠損表示するだけで計算に残していた問題を修正
- SPY基準日後の暗号資産の週末データを除外し、比較日を統一
- 1週・4週・13週の大小を加速・減速と誤認せず、同じ4週指標の前週差を使用
- 局面ルールをコード側で決定的に適用し、GPTは再分類しない
- 「証拠水準」と「値動きの原因仮説」を別フィールドに分離
- テーマ別カバレッジ、schema version、run_id、archive、critical missingを追加
- 予測と事後検証を別スキーマ・別フォルダに分離
- 固定テーマ外で相対的に強い業種ETFをcoverage gapとして出力
- 単体テスト、設定・出力検証、CIを追加

## 構成

```text
config/universe.json                ETF・指数定義
data/themes.json                    テーマ構成と役割（暫定、要レビュー）
scripts/generate_weekly.py          週次データ生成
scripts/validate_repository.py      設定・出力・記録の検証
schemas/rotation_snapshot.schema.json
schemas/prediction_record.schema.json
schemas/verification_record.schema.json
output/latest.json                  最新run
output/archive/                     run固定用の完全JSON
output/history/                     過去12週比較用の縮約データ
output/predictions/                 その時点の予測（後から変更しない）
output/verifications/               将来の事後検証（予測へ追記しない）
docs/custom_gpt_instructions_v2.md  Custom GPT貼り付け用
docs/indicator_inventory.md         指標定義と限界
tests/                              単体テスト
```

## セットアップ

1. GitHubに新規リポジトリを作り、このフォルダの中身をpushする。
2. Settings → Actions → General → Workflow permissionsを`Read and write permissions`にする。
3. `data/themes.json`をレビューする。現在の構成はETF保有銘柄を自動同期したものではなく、参照ETFを手掛かりに作った暫定allowlistである。役割分類も投資判断ではない。
4. Actions → `test`を実行し、成功を確認する。
5. Actions → `weekly-data` → Run workflowを実行する。
6. `output/latest.json`で`meta.status=success`、`analysis_ready=true`、`critical_missing=[]`、テーマ別coverageを確認する。
7. `docs/custom_gpt_instructions_v2.md`の指示本文をCustom GPTへ貼る。

## 週次運用

1. 毎週土曜08:00 JSTに自動生成される。
2. `output/latest.json`をCustom GPTへ添付して「更新」と送る。
3. 段階7の予測JSONを`output/predictions/YYYY-MM-DD.json`へ保存する。同じ予測を後から書き換えない。
4. `python scripts/validate_repository.py`で検証してcommitする。
5. 4・13・26・52週後の結果は`output/verifications/`へ別ファイルで保存する。予測ファイルの空欄埋めや上書きはしない。

`latest.json`には直近3回の予測を同梱するため、Custom GPTに会話をまたぐ記憶がなくても撤回条件と前回差分を確認できます。`history_weekly`は現在週を含めず、直前までの最大12週です。

## データと判断の限界

- 第1期はYahoo Finance由来の価格・出来高をyfinance経由で取得する非公式基盤です。取得失敗や仕様変更はあり得ます。
- 第1期に直接フロー、業績予想修正、空売り、オプションはありません。「資金流入確認」は使用できません。
- `core/beneficiary/peripheral`はテーマ内の便宜的役割で、利益感応度や企業品質を証明しません。
- 固定リストは市場の全テーマを覆いません。未登録テーマを弱いとみなさず、`unmapped_positive_industry_signals`を追加調査候補として扱います。
- 初期の局面閾値は仮説です。半年〜1年の履歴がたまる前に収益率で最適化すると過学習しやすいため、先に再現性と撤回規律を検証します。

## ローカル確認

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/validate_repository.py
python scripts/generate_weekly.py
```

テーマ構成の見直しは四半期ごと、コード・依存関係・取得成否の確認は毎週行います。
