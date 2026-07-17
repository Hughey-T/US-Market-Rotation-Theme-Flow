# Current State Audit

## 結論

2026-07-17 時点の main (`03af8cc`) は、再現可能な詳細分析と安全な publication を備える一方、固定テーマ中心、監査用語中心の表示、旧 shortlist と価格シグナルの flow 表現が利用者向け用途に不向きでした。本変更は監査層を維持し、判断層と表示層を追加します。

## 3層

- データ層: 取得、欠損、指標、履歴、条件、schema、source identity、atomic publication。
- 判断層: 動的業種発見、3分類候補、価格上の選好、初期観測、企業選定。
- 表示層: `user_view` の6段階。通常表示と `詳細` を分離。

## 解消したギャップ

- 固定テーマ外の業種を複数企業の breadth で確認し、後段へ渡す。
- 調査候補を0〜5件とし、弱いテーマで埋めない。
- 実フローと株価上の選好を別契約にする。
- 履歴3週未満を初期観測モードにする。
- 中央値、winsorized、流動性加重、HHI、effective contributor を追加する。
- 企業を1対象最大2社、重複なしで選ぶ。

## 既知の限界

直接的な fund flow、point-in-time market cap、決算直前判定、過去時点の業種構成は未取得です。利用不能値は推測せず `unavailable` とします。
