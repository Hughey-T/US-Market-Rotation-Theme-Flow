# Schema 1.2 Breaking Decision Contract

`rotation_snapshot.schema.json` の現行identityはdata schema 1.2です。必須3分類を4分類へ変更したためbreakingです。過去1.1 snapshot/history/judgmentは読み取り互換として保持し、現行公開物には使用しません。

新規生成物は `dynamic_discovery`、`candidate_buckets`、`company_candidates`、`user_view` を一組で必ず生成します。semantic validator は4つの一部欠落、分類改ざん、動的候補の消失、弱い候補の昇格、企業重複、通常表示への内部語露出を拒否します。過去1.1 fixture は移行検証のため引き続き読めます。
