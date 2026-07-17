# Test Specification 1.2

`tests/test_user_experience.py` は次を所有します。

- 8表示fixtureの登録
- 通常6段階から内部語を排除
- `更新` + `次`×5 の統合操作
- 初期観測時の変化語禁止
- 動的業種が企業breadthを通り後段へ残ること
- 弱い・一社集中テーマが調査対象へ入らないこと
- 価格上の選好と実フロー確認の分離
- 1対象最大2社、全体ticker重複なし
- robust metricが一社急騰を見抜くこと
- 3分類改ざんをsemantic validationが拒否すること

既存165テストはデータ層、rule、schema、publication、immutable judgment、production orchestration を継続検証します。
