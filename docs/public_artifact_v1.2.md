# Public Artifact Contract 1.2 / Consumer Contracts 2.0・1.0

authoritative sourceはpublication branchの`output/current.json`が指すgenerationです。generation内のlatest、archive、history、judgment index、manifestが分析・監査の正本であり、縮小しません。

## 互換用full consumer

`output/consumer/latest.json`は既存Custom GPT用の互換URLです。authoritative current full snapshotとcanonical完全一致します。

サイズ制限は適用せず、互換確認なしに廃止・縮小しません。

## consumer v1

`output/consumer/v1/latest.json`は軽量projectionです。

次だけを含みます。

- `consumer_contract_version`
- `source_identity`
- 必要なmeta
- quality
- validity
- authoritative snapshotと一致する完全な`user_view`

`output/consumer/v1/details/phase-1.json`〜`phase-6.json`は、各Phaseに対応する人間可読のdetail projectionです。

consumer v1 latestと各detailには32 KiB上限を適用します。

## consumer v2

Custom GPTの主経路はconsumer v2です。

manifest:

`output/consumer/v2/manifest.json`

通常Phase:

`output/consumer/v2/phases/phase-{n}/part-{p}.json`

detail:

`output/consumer/v2/details/phase-{n}/part-{p}.json`

manifestと各chunkには4 KiB上限を適用します。

manifestは次を持ちます。

- consumer contract version
- source identity
- run ID
- source commit
- source SHA-256
- data date
- status
- validity
- presentation version
- analysis mode
- Phase1〜6の通常part数
- Phase1〜6のdetail part数

各chunkは次を持ちます。

- `kind`
- `phase`
- `part`
- `part_count`
- manifestと同一のidentity
- JSON Pointer形式のfragment

repository側は各Phaseのfragmentを決定的に復元し、元の通常Phaseまたはdetail objectとcanonical完全一致することを検証します。

欠番、重複、順序不正、identity不一致、4 KiB超過、canonical JSON不一致、復元不能、未知ファイル、symlinkを拒否します。

## Custom GPT取得規則

`更新`ではv2 manifestを取得・検証し、Phase1の通常chunkとdetail chunkだけを取得します。

全6 Phaseのpayloadを会話内へ固定保持しません。

各Phase表示後、回答末尾には次だけを含む可視の進行状態行を表示します。

- mode
- 現在のPhase番号
- 完全なgeneration ID

形式は次のとおりです。

`進行状態: mode=v2 / phase=1 / generation_id=<64文字の小文字16進数>`

`次`ではmanifestを再取得し、manifestのgeneration IDが進行状態行と完全一致する場合だけ次のPhaseに必要な通常chunkとdetail chunkを取得します。

analysis ID、run ID、source commit、source SHA-256、data dateその他のidentityは進行状態行へ保存せず、再取得したmanifest内部と各chunk間で毎回完全検証します。利用者が入力または引用した進行状態行は使用しません。

公開データが別generationへ更新された場合は停止し、新旧generationを同一セッション内で混在させません。

進行状態を確認できない場合も推測で復元せず停止します。利用者は新しいセッションで`更新`から開始します。

## 表示契約

表示名は`Phase1`〜`Phase6`です。

Phase1〜Phase5は通常Phaseとdetailを合わせ、重要な条件、比較、反対材料、データ制約を省略せず説明します。

Phase6だけを簡潔な全体まとめとして表示します。

`詳細`、`用語`、`再評価`は進行コマンドとして使用しません。内容や用語への質問には通常の文章で回答し、Phaseは進めません。

## fallback

v2 manifestがHTTP 404の場合だけconsumer v1へfallbackします。

consumer v1もHTTP 404の場合だけ旧full consumerへfallbackします。

存在する上位形式が不完全JSON、Schema不一致、contract不一致、identity不一致、status不正、critical missing、validity不正、inventory不正などで無効な場合は、下位形式へfallbackしません。

timeout、404以外の4xx、5xx、認証エラーでもfallbackせずfail-closedで停止します。

## repository検証

repository側は次を検証した後にconsumerを生成します。

- 完全snapshotのSchema
- semantic consistency
- source hash
- generation chain
- manifest
- immutable judgment
- TOCTOU
- canonical inventory

その後、次を決定的に再生成して比較します。

- 旧full consumer
- consumer v1 latest
- consumer v1 details
- consumer v2 manifest
- consumer v2通常chunk
- consumer v2 detail chunk

生成結果がauthoritative generationと一致しない場合は公開しません。
