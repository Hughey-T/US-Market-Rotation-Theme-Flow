# Schema 1.2 Additive Contract

`rotation_snapshot.schema.json` の data schema 1.1 identity は immutable judgment と publication の互換性のため維持します。本変更は新しい top-level object と theme fieldを追加する additive contract です。

新規生成物は `dynamic_discovery`、`candidate_buckets`、`company_candidates`、`user_view` を一組で必ず生成します。semantic validator は4つの一部欠落、分類改ざん、動的候補の消失、弱い候補の昇格、企業重複、通常表示への内部語露出を拒否します。過去1.1 fixture は移行検証のため引き続き読めます。
