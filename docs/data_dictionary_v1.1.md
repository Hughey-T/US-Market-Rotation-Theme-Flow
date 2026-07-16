# データ辞書

## Publication contract 1.0

This is versioned independently of data schema 1.1. `output/current.json` and each manifest carry `publication_contract_version=1.0`. A manifest stores `analysis_id`, `generation_id`, `generated_at`, `source_commit`, `previous_generation_id`, and hashes for all components. IDs are 64-character lowercase hexadecimal values. `meta.run_id` is the analysis identity; `meta.source_snapshot` is `output/generations/<generation_id>/archive.json`. Consumers obtain a validated copy through `scripts/export_current_latest.py`.

`dd_handoff` has at most five entries. Every theme must be selected in the source shortlist; every ticker must be an active source constituent and its role must match. Tickers and theme/ticker pairs are unique. Order is shortlist rank, source constituent order, then ticker. Empty is permitted when qualitative constraints leave no sound candidate, including when a selected theme exists; no backfill is allowed.

`R`=required、`O`=optional。単位`decimal`は0.01=1%。全数値は有限値だけを許可し、取得・計算不能はnullable fieldへ`null`を入れる。`NaN/Infinity`は禁止。

## 1. `latest.json` top/meta

| path | 型 | R/O | null | 定義・生成 | 段階 |
|---|---|---|---|---|---|
| `meta.schema_version` | string const `1.1` | R | no | data contract | 1 |
| `meta.methodology_version` | string const `1.1.0` | R | no | condition rules version | 1 |
| `meta.generated_at` | ISO datetime | R | no | workflow生成時UTC | 1 |
| `meta.data_date` | date | R | no | SPYの最新market session | 1 |
| `meta.valid_until` | datetime | R | no | generated_atから10暦日後 | 1 |
| `meta.hard_stop_after` | datetime | R | no | generated_atから14暦日後 | 1 |
| `meta.run_id` | 64hex | R | no | deterministic analysis identity | all |
| `meta.source_commit` | 40hex | R | no | workflow開始時`GITHUB_SHA` | 1/record |
| `meta.source_snapshot` | path | R | no | `output/generations/<generation_id>/archive.json` | all |
| `meta.source_sha256` | 64hex | R | no | archive quantitative payload hash | all/record |
| `meta.status` | success/failed | R | no | pipeline outcome | 1 |
| `meta.failure_reason` | string | R | yes | failed reason。success時null | 1 |
| `meta.universe_definition.theme_master_schema_version` | `1.0` | R | no | master structure version | 1 |
| `.theme_master_version` | string | R | no | membership content version | 1 |
| `.universe_hash` | 64hex | R | no | canonical master SHA-256 | 1 |
| `.theme_count` | integer | R | no | active theme数 | 1 |
| `.unique_constituent_count` | integer | R | no | active unique ticker数 | 1 |
| `.overlap_policy` | `allow_with_warning` | R | no | 重複所属方針 | 1 |
| `meta.periods.1w/4w/13w` | 5/21/63 | R | no | trading intervals | 1 |
| `meta.global_quality.requested_ticker_count` | integer | R | no | download対象数 | 1 |
| `.usable_ticker_count` | integer | R | no | date/price要件通過数 | 1 |
| `.coverage_ratio` | decimal [0,1] | R | no | usable/requested | 1 |
| `.critical_missing` | string[] | R | no | SPY等global必須ticker | 1 |
| `.missing_tickers` | string[] | R | no | 全欠損ticker | 1 |
| `.warnings` | string[] | R | no | overlap、optional欠損等 | 1 |
| `not_implemented[]` | string[] | R | no | `direct_etf_flow`, `earnings_revision`, `positioning`等 | all |

`status=failed`、unsupported schema/methodology、current time>`hard_stop_after`、source hash不一致、critical missingありは全分析停止。current time>`valid_until`かつ<=hard stopはwarningを表示して段階1のみ停止し、ユーザーに更新を求める。

## 2. market regime

| path | 型/単位 | R | null | 計算元 |
|---|---|---|---|---|
| `market_regime.inputs.spy_r_4w` | number/decimal | R | yes | SPY price return 21 intervals |
| `.qqq_rel_spy_4w` | number/decimal | R | yes | QQQ−SPY |
| `.rsp_minus_spy_4w` | number/decimal | R | yes | RSP−SPY |
| `.iwm_minus_spy_4w` | number/decimal | R | yes | IWM−SPY |
| `.sector_advance_ratio_4w` | number/[0,1] | R | yes | 11 sectorのSPY超過比率 |
| `.defensive_basket_rel_spy_4w` | number/decimal | R | yes | XLP/XLV/XLU equal-weight relative |
| `.cyclical_basket_rel_spy_4w` | number/decimal | R | yes | XLY/XLI/XLF/XLB equal-weight relative |
| `.dbc_rel_spy_4w` | number/decimal | R | yes | DBC−SPY |
| `.gld_rel_spy_4w` | number/decimal | R | yes | GLD−SPY |
| `.xle_rel_spy_4w` | number/decimal | R | yes | XLE−SPY |
| `.hyg_minus_lqd_4w` | number/decimal | R | yes | HYG−LQD |
| `.vix_change_4w` | number/index points | R | yes | current VIX−21 intervals ago |
| `.uup_r_4w` | number/decimal | R | yes | UUP return |
| `.rsp_minus_spy_4w_trend_3w` | trend enum | R | no | 5-session-spaced, same-horizon RSP-minus-SPY 4w trend |
| `.iwm_minus_spy_4w_trend_3w` | trend enum | R | no | 5-session-spaced, same-horizon IWM-minus-SPY 4w trend |
| `.dbc_rel_spy_4w_trend_3w` | trend enum | R | no | 5-session-spaced, same-horizon DBC-relative-SPY 4w trend |
| `market_regime.candidate_flags.<canonical candidate>.eligible` | boolean | R | no | all six canonical candidate IDs are required; mandatory input availability |
| `.full_match` | boolean | R | yes | eligible時condition all match |
| `.matched_conditions[]` | condition id[] | R | no | code-side truth |
| `.unmatched_conditions[]` | condition id[] | R | no | code-side false |
| `.contrary_evidence[]` | condition id[] | R | no | counter flags |
| `market_regime.classification.primary_regime` | enum | R | no | method table |
| `.secondary_regimes[]` | candidate enum[] | R | no | mixed/partial candidates in canonical ID order; unique, maximum 6 |
| `.confidence` | enum | R | no | high/medium/low/unclassifiable |
| `.matched_conditions[]` | id[] | R | no | primary/mixed evidence |
| `.contrary_evidence[]` | id[] | R | no | primary/mixed counterevidence |

## 3. ETF group common fields

`style_factor.<ticker>`, `sectors.etfs.<ticker>`, `industries.etfs.<ticker>`で共通。

| suffix | 型 | null | 定義 |
|---|---|---|---|
| `label` | string | no | human label |
| `return_1w/4w/13w` | number | yes | split-adjusted price return |
| `rel_spy_1w/4w/13w` | number | yes | ETF−SPY same horizon |
| `above_50dma/above_200dma` | boolean | yes | latest price>DMA |
| `within_5pct_52w_high` | boolean | yes | latest>=95% of 252-session high |
| `volume_ratio_20d_60d` | number | yes | latest20-day mean / latest60-day mean |
| `last_date` | date | yes | ticker latest aligned date |
| `sectors/industries.rank_by_rel_spy_4w[]` | ticker[] | no | null除外、descending、ticker tie-break |

## 4. theme quality

`themes.<theme_id>`のkeyと内部`theme_id`は一致必須。

| path suffix | 型 | null | 定義 |
|---|---|---|---|
| `theme_id`, `label` | string | no | master由来 |
| `quality.classification_eligible` | boolean | no | phase/directionを両方出せる |
| `.phase_initial_diffusion_eligible` | boolean | no | base current＋history条件 |
| `.phase_overheat_eligible` | boolean | no | 13週/high/volumeまたはperipheral条件 |
| `.direction_eligible` | boolean | no | 連続3週trend可 |
| `.evidence_eligible` | boolean | no | current relative/breadth/concentration可 |
| `.constituent_count` | integer | no | active defined members |
| `.valid_constituent_count` | integer | no | current 1/4週valid members |
| `.coverage_ratio` | number [0,1] | no | valid/defined |
| `.history_weeks` | integer | no | version一致した連続weekly observations（current含む） |
| `.role_valid_counts.core/beneficiary/peripheral` | integer | no | roleごとのvalid数 |
| `.metric_valid_counts.<metric>` | integer | no | metric固有denominator |
| `.missing_required_fields[]` | field path[] | no | required null/missing |
| `.quality_reasons[]` | reason id[] | no | `Q_TOO_FEW_MEMBERS`等 |

## 5. theme metrics/concentration

| suffix | 型/単位 | null | 計算 |
|---|---|---|---|
| `metrics.equal_weight_return_1w/4w/13w` | decimal | yes | valid constituent return mean |
| `.equal_weight_rel_spy_1w/4w/13w` | decimal | yes | equal-weight return−SPY |
| `.market_cap_weight_rel_spy_4w` | decimal | yes | current market-cap weighted return−SPY。coverage<0.75はnull |
| `.weighting_divergence_4w` | decimal | yes | market-cap-weight−equal-weight |
| `.advance_count_4w` | integer | yes | positive 4週return constituent count |
| `.advance_ratio_4w` | [0,1] | yes | advance/valid |
| `.above_50dma_count` | integer | yes | 50DMA超過constituent count。field-valid 5社未満はnull |
| `.pct_above_50dma` | [0,1] | yes | field-valid denominator |
| `.pct_within_5pct_52w_high` | [0,1] | yes | field-valid denominator |
| `.volume_ratio_20d_60d` | number | yes | constituent ratio mean |
| `.top1_contribution_ratio` | [0,1] | yes | largest positive relative contribution share |
| `.top3_contribution_ratio` | [0,1] | yes | top3 positive relative contribution share |
| `.single_name_concentrated` | boolean | yes | top1>0.60 |
| `.market_cap_led` | boolean | yes | weighting divergence>=0.03 |
| `.equal_weight_led` | boolean | yes | weighting divergence<=-0.03。market-cap input不足時はnull |

## 6. theme trends

| suffix | 型 | null | 定義 |
|---|---|---|---|
| `trends.rel_spy_4w_change_1w` | number | yes | current−previous same metric |
| `.rel_spy_4w_slope_3w/4w` | number/week | yes | OLS slope |
| `.rel_spy_4w_trend_3w/4w` | enum | no | improving/flat/worsening/insufficient |
| `.advance_count_change_1w/3w` | integer | yes | same universe count change |
| `.above_50dma_count_change_1w/3w` | integer | yes | count change |
| `.advance_breadth_trend_3w` | enum | no | count-based state |
| `.above_50dma_breadth_trend_3w` | enum | no | count-based state |
| `.volume_ratio_change_1w` | number | yes | current−previous |

## 7. condition/classification/role/constituent

| path suffix | 型 | null | 定義 |
|---|---|---|---|
| `condition_flags.phase_initial/diffusion/price_overheat` | boolean | yes | eligibility不足はnull |
| `.direction_improving/worsening/outflow_signal` | boolean | yes | eligibility不足はnull |
| `.broad_concentration_pass` | boolean | yes | top1<=0.50 and top3<=0.85 |
| `.overheat_breadth_weak` | boolean | yes | overheat flag=trueかつadvance ratio<0.60または50DMA超過率<0.60。必要field不足はnull |
| `.matched_conditions[]` | id[] | no | true flags |
| `.unmatched_conditions[]` | id[] | no | false flags |
| `.contrary_evidence[]` | id[] | no | counter flags |
| `classifications.phase` | enum | no | initial/diffusion/price_overheat/unclassifiable |
| `.direction` | enum | no | improving/flat/worsening/outflow_signal/unclassifiable |
| `.evidence.level` | enum | no | direct/flow/relative/price/insufficient |
| `.evidence.direction` | enum | no | inflow/outflow/up/down/unknown |
| `.evidence.positioning_hypothesis` | enum | no | possible/not_supported/not_assessable |
| `.evidence.direct_flow_data_available` | boolean | no | v1.1 false |
| `.evidence.matched_conditions[]` | id[] | no | evidence source flags |
| `classifications.research_priority` | enum | no | code-side P0〜P5/fallback結果 |
| `.research_priority_rule` | enum | no | `P0..P5/fallback` |
| `.timing_status` | enum | no | code-sideテーマ市場状態。個別銘柄entry timingではない |
| `.timing_rule` | enum | no | `T0..T4/fallback` |
| `relative_strength_rank_4w` | integer/null | yes | equal-weight rel 4週降順、null最後、theme_id tie-break |
| `selected_for_deep_dive` | boolean | no | code-side shortlist採否 |
| `shortlist_rank` | integer 1..5/null | yes | 選定順。非選定はnull |
| `shortlist_reason_codes[]` | id[] | no | priority/evidence/phase/concentration/除外理由 |
| `by_role.<role>` | object/null | yes | valid<2ならnull |
| `.valid_count` | integer>=2 | no | role valid denominator |
| `.equal_weight_rel_spy_4w` | number | yes | role mean−SPY |
| `.advance_ratio_4w` | [0,1] | yes | role positive share |
| `constituents[].ticker/role/valid` | string/enum/bool | no | master/current quality |
| `.return_4w`, `.rel_spy_4w` | number | yes | aligned price data |
| `.market_cap` | USD number | yes | current snapshot、point-in-time非保証 |
| `.positive_contribution_ratio` | [0,1] | yes | theme positive sum share |
| `.overlap_theme_count` | integer | no | active theme所属数 |

## 8. top-level shortlist・history・previous judgment

Withdrawalの`field_path`はcurrent snapshotの`themes.<id>.metrics.<field>`形式を正本とする。評価時は、同じ5指標を`themes.<id>.<field>`に圧縮して保存する`history_weekly`へ明示的に対応付ける。連続性・schema・methodology・theme masterが適合しない履歴はpersistence判定に使用しない。

| path | 型 | null | 定義 |
|---|---|---|---|
| `theme_shortlist.selection_version` | const `1.0` | no | shortlist rule contract |
| `.max_themes` | const 5 | no | 選定上限 |
| `.minimum_preferred_themes` | const 3 | no | 望ましい最低件数。穴埋め条件ではない |
| `.selected_theme_ids[]` | theme id[] | no | `shortlist_rank`順、最大5件 |
| `.quality_reasons[]` | reason id[] | no | 3件未満、eligibleなし等 |

| path | 型 | null | 定義 |
|---|---|---|---|
| `history_weekly[].data_date` | date | no | currentより前 |
| `.schema_version/methodology_version/theme_master_version` | string | no | continuity gate |
| `.themes.<id>.equal_weight_rel_spy_4w` | number | yes | trend input |
| `.advance_count_4w` | integer | yes | trend input |
| `.above_50dma_count` | integer | yes | count-based 50DMA breadth trend input。旧履歴にない場合は推定せずnull扱い |
| `.pct_above_50dma` | number | yes | trend input |
| `.volume_ratio_20d_60d` | number | yes | trend input |
| `previous_judgments.source` | const path | no | validated index |
| `.available` | boolean | no | valid prior exists |
| `.latest_data_date` | date | yes | none時null |
| `.records[].judgment_id/data_date/theme_id` | string/date | no | prior projection identity |
| `.phase/.direction/.research_priority/.timing_status` | enum | no | prior code-side values |
| `.research_priority_rule/.timing_rule` | enum | no | prior code-side rule ids |
| `.selected_for_deep_dive/.shortlist_rank` | bool/integer|null | rank yes | prior shortlist採否・順位 |
| `.shortlist_reason_codes[]` | id[] | no | prior selection理由 |
| `.withdrawal_evaluations[].condition_id` | string | no | prior condition |
| `.status` | enum | no | triggered/not_triggered/unknown |
| `.observed_weeks` | integer | no | consecutive evidence count |

## 9. `judgment_record.json`

### document metadata/regime

| path | 型 | null | 定義 |
|---|---|---|---|
| `judgment_schema_version` | const `1.0` | no | new record contract |
| `instruction_version` | const `1.1.1` | no | GPT instructions |
| `data_schema_version` | const `1.1` | no | source latest contract |
| `methodology_version` | const `1.1.0` | no | decision table |
| `judgment_id` | string | no | `judgment_<run_id>` |
| `run_id`, `data_date` | string/date | no | source identity |
| `generated_at` | datetime | no | judgment output time |
| `source_commit/source_snapshot/source_sha256` | string | no | immutable source provenance |
| `previous_judgment_date` | date | yes | none時null |
| `regime.primary_regime/secondary_regimes/confidence` | enum/array | no | latestから転記 |
| `regime.matched_conditions/contrary_evidence` | id[] | no | latestから転記 |

### `theme_judgments[]`

| suffix | 型 | null | 定義 |
|---|---|---|---|
| `theme_id` | string | no | source theme |
| `phase`, `direction`, `evidence` | object/enums | no | latestから変更せず転記 |
| `research_priority` | enum | no | latestのcode-side結果を転記 |
| `research_priority_rule` | P0..P5/fallback | no | latestのcode-side rule provenance |
| `timing_status` | enum | no | latestのテーマ市場状態を転記 |
| `timing_rule` | T0..T4/fallback | no | latestのcode-side rule provenance |
| `selected_for_deep_dive` | boolean | no | source shortlist採否を転記 |
| `shortlist_rank` | integer/null | yes | source shortlist順位を転記 |
| `shortlist_reason_codes[]` | id[] | no | source reason codeを転記 |
| `data_quality.classification_eligible` | bool | no | source quality |
| `.coverage_ratio` | number | yes | source quality |
| `.valid_constituent_count/history_weeks` | integer | no | source quality |
| `.missing_required_fields/quality_reasons` | string[] | no | source quality |
| `matched_conditions/unmatched_conditions` | id[] | no | source flags |
| `key_metrics.*` | number | yes | schema固定9 metrics、source転記 |
| `withdrawal_conditions[].condition_id` | string | no | unique in theme judgment |
| `.field_path` | JSON path string | no | same themeのfuture latestに存在するfield |
| `.operator` | enum | no | ordered comparisonはnumeric fieldだけ |
| `.value` | number/string/bool | no | source fieldと型互換のthreshold/category |
| `.persistence_weeks` | integer 1..12 | no | consecutive condition |
| `one_line` | string | no | 最重要一点 |
| `next_check[]` | string[] | no | next weekly checks |

### `dd_handoff[]`

`ticker`, `theme_id`, `role`, `selection_reason`, `dd_questions[]`。全document最大5銘柄。`role`は中心性だけであり、quality/valuationを示さない。

## 10. theme master

| path | 型 | null | 定義 |
|---|---|---|---|
| `theme_master_schema_version` | `1.0` | no | structure |
| `theme_master_version` | string | no | membership content |
| `effective_date` | date | no | point-in-time start |
| `review_cycle` | quarterly | no | fixed review cycle |
| `overlap_policy` | allow_with_warning | no | duplication |
| `themes[].theme_id/label/definition` | string | no | identity/scope |
| `.reference_etfs[]` | ticker[] | no | reference only、automatic membershipではない |
| `.members[].ticker/role/active` | string/enum/bool | no | membership。active=falseは常に除外 |
| `.valid_from/valid_to` | date/date|null | valid_to yes | `valid_from <= data_date <= valid_to`（nullは上限なし）のpoint-in-time membership |
| `.rationale` | string | no | role assignment reason |
`weighting_divergence_4w`はdecimal文字列表現で差を計算し、小数点以下10桁へround-half-evenで保存する。`market_cap_led`と`equal_weight_led`はこの保存値と同じdecimal threshold contractで判定する。

Theme memberの期間は両端を含む。同一theme/tickerの隣接期間は許可するが、同日を共有する重複、完全duplicate、`valid_from > valid_to`、不正日付は拒否する。
