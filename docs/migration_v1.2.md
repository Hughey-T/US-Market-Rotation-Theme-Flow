# Migration 1.1 → data/decision contract 1.2/3.0

3分類から4分類への必須key変更はbreaking contractです。新規生成物はdata schema 1.2、decision contract 3.0、presentation contract 1.2とします。presentation 1.1は公開更新時の読み取り互換として保持し、新規生成しません。既存1.1監査フィールド、履歴、immutable judgment recordは読み取り専用で保持します。

1. `dynamic_discovery`
2. `candidate_buckets`
3. `company_candidates`
4. `user_view`

`migrate_candidate_buckets_2_to_3` は旧3分類を明示的に投影しますが、構造的背景を推測しないため新bucketは空にします。正式公開は必ず現行generatorで再生成します。新 Custom GPT は4契約が揃わない旧artifactを通常表示に使用せず、更新待ちとします。旧 `theme_shortlist` と flow 系 evidence は監査互換のみで、通常表示へ出しません。rollbackはコードを戻しても既存immutable recordを変更しません。

空の `output/archive/.gitkeep` は repository placeholder であり legacy publication ではありません。JSONを含む archive や固定 `output/latest.json` がある場合だけ明示migrationを要求します。
