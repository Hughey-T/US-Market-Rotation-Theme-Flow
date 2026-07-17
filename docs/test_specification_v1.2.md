# Test Specification 1.2

## Consumer contract 1.0

- schema適合、32 KiB canonical/file上限、`user_view`完全一致、大型監査field除外を検証する。
- 同一authoritative snapshotから同一canonical bytesを生成する。
- generation/analysis/run/source SHA identity改ざん、failed status、critical missing、unsupported version、phase数・表示field欠損を拒否する。
- repository validatorの再生成差分検出、旧full consumerからprojectionへの移行、publication 1.0 chain読取互換と1.1 transactional publicationを検証する。

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
- 4分類の欠落・重複・未知候補・不正な長期材料bucketをsemantic validationが拒否すること

既存165テストはデータ層、rule、schema、publication、immutable judgment、production orchestration を継続検証します。
