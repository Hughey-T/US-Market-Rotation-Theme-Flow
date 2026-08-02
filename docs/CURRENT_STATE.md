# Current State Audit

## 結論

作業開始時点の`main`はconsumer v3、6 Phase、決定論的producerによるauthoritative presentationを使用していました。本変更は既存のdata schema 1.2、mechanical decision 3.0、publication core 1.1、consumer v1〜v3を維持したまま、consumer v4と10 Phaseのsession-local AI layerを追加します。

## Version matrix

| Contract | Current/added |
|---|---|
| data schema | 1.2（変更なし） |
| mechanical decision | 3.0（変更なし） |
| publication core | 1.1（変更なし） |
| preferred consumer | 4.0 |
| previous supported consumers | 3.0、2.0、1.0、legacy |
| AI assessment | 1.0 |
| handoff | 2.0 |
| Custom GPT | 2.0.0 |
| default AI persistence | session_local |
| write runtime | runtime_available=false |

## 境界

- FACTS、MECHANICAL_SIGNALS、blind projection、company/dynamic-industry factsはproducer所有。
- AI_THEME_ASSESSMENT、COUNTER_THESIS、exploratory proposalはCustom GPT所有。
- reconciliationとintegrated decisionはsession-local runtimeが構築する。
- hard exclusionとcritical data-quality gateはAIで相殺しない。
- blind packagesとreconciliation packagesは別directory・別URLで公開する。
- 過去generationのAI statusは`not_assessed`。現在の知識から再構築しない。

## 運用状態

consumer v4 codeとfixture E2EはPR CIで検証します。mainへmerge後、weekly workflowが成功して初めてpublication branchへ`output/consumer/v4`が公開されます。write-capable runtimeは未デプロイであり、AI artifactとledgerは永続保存済みと表示しません。
