# Public Artifact Contract 1.2 / Consumer Contract 1.0

authoritative sourceはpublication branchの`output/current.json`が指すgenerationです。generation内のlatest/archive、history、judgment index、manifestが分析・監査の正本であり、縮小しません。

`output/consumer/latest.json`はCustom GPT表示専用の決定的projectionです。`consumer_contract_version`、`source_identity`、必要なmeta/quality/validity、authoritative snapshotと完全一致する`user_view`だけを含みます。`themes`、market inputs、condition、reason、history、judgments等の監査fieldは複製しません。

repository側は完全snapshotのschema・semantic・source hash・generation chain・manifest・immutable judgment・TOCTOUを検証した後、同じauthoritative snapshotからconsumerを再生成し、source generation ID、analysis ID、run ID、source SHA-256、source commit、`user_view`、canonical bytesを比較します。canonical JSONと配信fileは32 KiB以下でなければ公開を拒否します。

Custom GPT側はHTTP/完全JSON、consumer contract version、source identity、status、critical missing、validity dates、presentation version、6 phasesを検証します。consumerは分析の正本ではなく、publication時に検証済みの表示用派生物です。
