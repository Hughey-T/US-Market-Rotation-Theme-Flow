# Data Dictionary 1.2 Addendum

| Field | 意味 |
| --- | --- |
| `dynamic_discovery` | 固定テーマ外の業種候補、閾値、却下理由。監査用。 |
| `candidate_buckets.research_now` | 個別企業調査へ進める0〜5対象。 |
| `candidate_buckets.watch_recovery` | 長期相対強度を残し、直近の価格回復条件を監視する対象。 |
| `candidate_buckets.long_term_context_price_weak` | version付き構造的背景はsupportedだが現在の価格・breadthが弱い対象。 |
| `candidate_buckets.avoid_now` | 現在は避ける対象。 |
| `themes.*.decision.price_preference` | 価格とbreadthによる選好。positive/negative/mixed/unavailable。 |
| `themes.*.decision.direct_flow_confirmation` | 実フロー確認。未取得時はunavailable。 |
| `themes.*.decision.analysis_mode` | initial_observation / trend。 |
| `themes.*.decision.time_profile` | 非重複の直近1週・前3週・前9週の整合。 |
| `company_candidates` | 重複なし、1対象最大2社の調査引継ぎ。 |
| `user_view.phases` | 通常表示専用の6段階。内部コードを含めない。 |
| `median_rel_spy_4w` | 構成企業4週SPY比の中央値。 |
| `winsorized_equal_weight_rel_spy_4w` | 外れ値の影響を抑えた4週SPY比。 |
| `liquidity_weight_rel_spy_4w` | 売買代金が利用可能な場合の流動性加重。 |
| `contribution_hhi` | 正の寄与の集中度。 |
| `effective_contributor_count` | 1/HHI。実質的な寄与企業数。 |

旧 `evidence.direction=inflow/outflow` と `theme_shortlist` は immutable judgment 互換の監査フィールドです。通常表示に使用しません。
