# Methodology 1.2 — Decision and Presentation Addendum

既存 methodology 1.1.0 の監査計算を保持し、次を追加する非破壊拡張です。

## 動的業種発見

業種ETFの4週SPY比が+3%以上で、設定済み企業が最低3社、企業中央値の4週SPY比が正、50日線上比率が50%以上、一社集中でない場合だけ候補化します。ETFは発見信号であり、企業 breadth が確認できない業種は後段へ渡しません。

## 候補分類

- `research_now`: 相対強度が正、advance ratio 60%以上、50日線上比率50%以上、広範上昇、品質十分。最大5件。
- `watch_recovery`: 長期相対強度は正だが、直近が弱い、または研究枠外。
- `avoid_now`: 上記を満たさない。0件を含む件数は正常。

旧 `theme_shortlist` は監査互換として deprecated。正式な利用者向け契約は `candidate_buckets` です。

## 指標

equal-weight に加え、中央値、10% winsorized mean、利用可能時の流動性加重、top1/top3、寄与HHI、effective contributor countを使用します。point-in-time market cap がない限り現在時価総額を過去へ適用しません。

## 初期観測

互換履歴を含む観測が3週未満なら `initial_observation`。現在断面だけを表示し、変化語を禁止します。非重複窓は今後の source observation に保存可能ですが、過去構成を再現できない backfill は正式履歴に混ぜません。

初期観測でも、現在の4週相対強度、breadth、50日線上比率、集中度、データ品質がすべて基準を満たせば、現在断面に限った企業調査候補を選べます。継続・改善・反転は主張しません。

通常の時間比較には直近1週、その前の3週、さらに前の9週という非重複窓を使い、`time_profile` を strengthening / weakening / mixed / unavailable にまとめます。従来の1週・4週・13週は水準確認と監査互換に残します。

## 企業選定

1対象最大2社。固定テーマでは中心企業を先に、次にテーマ中央値付近の広がり確認企業を選びます。動的業種では相対強度上位と中央値付近を選びます。同一tickerは全対象で一度だけです。条件を満たさない場合は0社です。

20日平均売買代金が取得でき、500万ドル未満の場合は候補から除外します。売買代金や決算日程が取得不能な場合は推測せず、利用者向け注意点で未確認とします。
