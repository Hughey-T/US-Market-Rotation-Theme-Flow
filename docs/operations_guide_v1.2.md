# Operations Guide 1.2

## 利用者

1. `更新` で公開データを取得し段階1を読む。
2. `次` を5回送り段階6まで進む。
3. 必要な段階だけ `詳細` または `用語` を使う。

## 運用者

週次workflowはmainからpublication branchを更新し、全テスト、完全snapshot生成、repository validation、軽量consumer projection、remote再取得比較を行います。consumerはauthoritative currentから再生成され、canonical/fileの32 KiB上限、source identity、完全な`user_view`一致を満たさなければcommitしません。失敗時はcurrent pointerを更新しません。

公開URL: `https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/latest.json`

Custom GPT指示の正本: [`custom_gpt_instructions_current.md`](custom_gpt_instructions_current.md) / `https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/main/docs/custom_gpt_instructions_current.md`

Custom GPT UIを自動更新できない場合の唯一の手作業: 「Custom GPT編集画面の「指示」欄を開き、正本指示文の全文へ置き換えて保存する。」

直接フロー、過去時価総額、決算日程がない場合は停止せず、該当判断だけ unavailable にします。SPY等critical input欠損、schema不整合、source hash不一致は公開停止です。

## 検証責任

- Repository: 完全snapshot、全semantic、hash、generation chain、judgment、lock、TOCTOU、consumer再生成一致。
- Custom GPT: HTTP/完全JSON、consumer 1.0、source identity、success、critical missing、validity、presentation 1.2、6 phases。
- 利用者: 日常操作は`更新`と`次`だけ。file添付、URL入力、Actions操作は不要です。
