# Public Artifact Contract 1.2 / Consumer Contract 1.0

authoritative sourceはpublication branchの`output/current.json`が指すgenerationです。generation内のlatest/archive、history、judgment index、manifestが分析・監査の正本であり、縮小しません。

`output/consumer/latest.json`は既存Custom GPT 1.3.0用の互換URLであり、authoritative current full snapshotとcanonical完全一致します。32 KiB制限は適用せず、今回の移行では廃止・縮小しません。

`output/consumer/v1/latest.json`が新しい通常表示用の軽量projectionです。`consumer_contract_version`、`source_identity`、必要なmeta/quality/validity、authoritative snapshotと完全一致する`user_view`だけを含み、32 KiB以下です。`output/consumer/v1/details/phase-1.json`〜`phase-6.json`は現在phaseだけの人間可読な監査説明で、各fileが`details_contract_version=1.0`と同じanalysis/generation/run/source commit/source SHA/data dateを持ち、各32 KiB以下です。

repository側は完全snapshotのschema・semantic・source hash・generation chain・manifest・immutable judgment・TOCTOUを検証した後、旧full、新軽量、details 6件を再生成し、canonical bytesと厳密inventoryを比較します。unknown/missing/symlink/重複phase/identity不一致を拒否します。

Custom GPT側は新URLを先に検証し、HTTP 404の場合だけ旧fullへfallbackします。新URLが存在して無効ならfallbackしません。「詳細」では現在phaseの1 fileだけを取得し、固定consumerとidentityが一致しない場合はdetailsだけを停止します。
