# Operations Guide 1.2

## 利用者

1. `更新` で公開データを取得し段階1を読む。
2. `次` を5回送り段階6まで進む。
3. 必要な段階だけ `詳細` または `用語` を使う。

## 運用者

週次 workflow は main から publication branch を更新し、全テスト、repository validation、生成、consumer export、remote再取得比較を行います。失敗時は current pointer を更新しません。

公開URL: `https://raw.githubusercontent.com/Hughey-T/US-Market-Rotation-Theme-Flow/publication/output/consumer/latest.json`

直接フロー、過去時価総額、決算日程がない場合は停止せず、該当判断だけ unavailable にします。SPY等critical input欠損、schema不整合、source hash不一致は公開停止です。
