# Operations Guide 1.2

## 利用者

1. 新しいセッションで`更新`と送信し、Phase1を読む。
2. `次`を5回送り、Phase6まで進む。
3. Phaseの内容や用語について質問する場合は、通常の文章で質問する。
4. 公開データのgenerationが途中で更新された場合や進行状態を確認できない場合は、新しいセッションで`更新`からやり直す。

日常の進行コマンドは`更新`と`次`だけです。`詳細`、`用語`、`再評価`は進行コマンドとして使用しません。

Phase1〜Phase5は通常データとdetailデータを合わせて詳しく表示します。Phase6だけを簡潔な全体まとめとして表示します。

## 運用者

週次workflowはmainからpublication branchを更新し、次を実行します。

- 全テスト
- 完全snapshot生成
- 旧full consumer生成
- consumer v1生成
- consumer v1 details生成
- consumer v2 manifest・通常chunk・detail chunk生成
- repository validation
- remote再取得比較

いずれかが失敗した場合は公開しません。

### consumer v2

manifest:

`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/v2/manifest.json`

通常Phase URL規約:

`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/v2/phases/phase-{n}/part-{p}.json`

detail URL規約:

`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/v2/details/phase-{n}/part-{p}.json`

各ファイルは4 KiB以下です。manifestはPhase1〜6の通常・detailそれぞれのpart数を持ちます。各chunkはmanifestと同一のanalysis ID、generation ID、run ID、source commit、source SHA-256、data dateを持つ必要があります。

Custom GPTは`更新`時に全Phaseを一括取得しません。Phase1に必要な通常chunkとdetail chunkだけを取得します。

各Phase末尾には、`mode`、現在のPhase番号、完全なgeneration IDだけを含む可視の進行状態行を表示します。

`次`ではmanifestを再取得し、manifestのgeneration IDが進行状態行と完全一致する場合だけ次のPhaseに必要なchunkを取得します。manifestとchunk間の全identityは毎回完全検証します。公開データが別generationへ更新された場合は停止し、新旧generationを混在させません。

### fallback

consumer v2 manifestがHTTP 404の場合だけconsumer v1を使用します。

consumer v1もHTTP 404の場合だけ旧full consumerを使用します。

存在する上位形式が不完全JSON、Schema不一致、identity不一致、status不正などで無効な場合は、下位形式へfallbackせずfail-closedで停止します。

旧互換URL:

`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/latest.json`

consumer v1 URL:

`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/v1/latest.json`

consumer v1 details URL規約:

`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/v1/details/phase-{n}.json`

## Custom GPT指示の更新

正本:

[`custom_gpt_instructions_current.md`](custom_gpt_instructions_current.md)

raw URL:

`https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/main/docs/custom_gpt_instructions_current.md`

Custom GPT UIを自動更新できない場合の手作業は次の1件だけです。

「Custom GPT編集画面の指示欄を開き、最新の正本指示全文へ置き換えて保存する。」

## 検証責任

### Repository

- 完全snapshot
- Schema・semantic validation
- source hash
- generation chain
- judgment
- lock
- TOCTOU
- 旧full consumer
- consumer v1
- consumer v1 details
- consumer v2 manifest・chunk
- deterministic regeneration
- canonical bytes
- exact inventory
- 4 KiB上限
- lossless reconstruction

### Custom GPT

- consumer v2優先
- HTTP 404の場合だけfallback
- 完全JSON
- contract version
- source identity
- success status
- critical missing
- validity
- presentation version
- part数・順序
- fragment復元
- 同一generationの再検証
- Phase1〜5の通常・detail統合表示
- Phase6の簡潔なまとめ

### 利用者

日常操作は`更新`と`次`だけです。ファイル添付、URL入力、GitHub操作、Actions実行は不要です。

直接フロー、過去時点の時価総額、決算日程がない場合は、該当判断だけを`unavailable`として扱います。SPY等のcritical input欠損、Schema不整合、source hash不一致は公開停止です。
