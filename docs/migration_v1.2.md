# Migration 1.1 → additive decision contract 1.2

破壊的なdata schema変更は行いません。既存1.1監査フィールドとjudgment recordは保持します。新規生成時に4契約を追加します。

1. `dynamic_discovery`
2. `candidate_buckets`
3. `company_candidates`
4. `user_view`

旧 consumer は従来fieldを継続利用できます。新 Custom GPT は4契約が揃わない旧artifactを通常表示に使用せず、更新待ちとします。旧 `theme_shortlist` と flow 系 evidence は監査互換のみで、通常表示へ出しません。rollbackはコードを戻しても既存immutable recordを変更しません。

空の `output/archive/.gitkeep` は repository placeholder であり legacy publication ではありません。JSONを含む archive や固定 `output/latest.json` がある場合だけ明示migrationを要求します。
