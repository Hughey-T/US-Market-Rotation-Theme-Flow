# Public Artifact Contract 1.2

authoritative source は publication branch の `output/current.json` が指す generation です。Custom GPT は同一workflowでexport・検証された `output/consumer/latest.json` を取得します。

通常表示は `user_view`、調査対象は `candidate_buckets`、企業は `company_candidates` を正本とします。監査用の `themes`、condition、reason、identityは `詳細` のときだけ使用します。consumer exportは current generation とbyte-equivalentでなければrepository validationに失敗します。
