# 方法論仕様書 1.1.0

すべての閾値は**未較正の暫定値**である。初期実装では再現性、欠損時停止、撤回規律を検証し、収益率へ合わせて変更しない。

## 1. 共通原則

- returnはsplit-adjusted price return、dividend除外。期間は1週=5、4週=21、13週=63 trading intervals。
- `null`は未取得・計算不能。0とは別。denominator 0も`null`。
- trendは同じfieldのweekly snapshotだけで計算する。1/4/13週returnの大小は方向整合性にしか使わない。
- theme重複所属は許可するが、overlap countとwarningを出す。重複銘柄を自動除外しない。
- price/volumeだけの段階ではdirect flowを確認しない。
- codeがquality、metric、trend、condition flag、phase、direction、evidence、research priority、theme market state、shortlistを決定する。GPTは変更・再計算しない。
- GPTはcode-side結果、反対証拠、theme間比較を説明し、qualitative evidenceと個別DDへの引継ぎを補足する。

## 2. trend生成

### 必要field

各themeについて次をcode-sideで生成する。

- `rel_spy_4w_change_1w`
- `rel_spy_4w_slope_3w`, `rel_spy_4w_slope_4w`
- `rel_spy_4w_trend_3w`, `rel_spy_4w_trend_4w`
- `advance_count_change_1w`, `advance_count_change_3w`
- `above_50dma_count_change_1w`, `above_50dma_count_change_3w`
- `advance_breadth_trend_3w`, `above_50dma_breadth_trend_3w`
- `volume_ratio_change_1w`

`slope_Nw`は等間隔weekly observationsのordinary least squares slope（週あたりdecimal return）。欠週、methodology/theme-master変更、N未満は`null`。50DMA breadth trendはcurrentと新規weekly historyへ保存する実測`above_50dma_count`だけを使い、旧履歴にfieldがなければ0補完・比率からの推定をせず`insufficient`とする。

### trend state（暫定）

| state | rel_spy_4w | breadth count |
|---|---|---|
| improving | `slope_3w >= 0.005`かつoldest→current `>=0.01` | 3週でvalid constituentが2社以上改善 |
| worsening | `slope_3w <= -0.005`かつoldest→current `<=-0.01` | 3週で2社以上悪化 |
| flat | eligibleだが上記外 | eligibleだが±1社以内 |
| insufficient | 3観測未満またはversion/欠週不整合 | 同左 |

3週stateを判定に使い、4週slopeは反対証拠と安定性確認に使う。

## 3. 市場レジーム決定表

### code-side input

`spy_r_4w`, `qqq_rel_spy_4w`, `rsp_minus_spy_4w`, `iwm_minus_spy_4w`, `sector_advance_ratio_4w`, `defensive_basket_rel_spy_4w`, `cyclical_basket_rel_spy_4w`, `dbc_rel_spy_4w`, `gld_rel_spy_4w`, `xle_rel_spy_4w`, `hyg_minus_lqd_4w`, `vix_change_4w`, `uup_r_4w`。

defensive basket=`XLP, XLV, XLU` equal-weight、cyclical basket=`XLY, XLI, XLF, XLB` equal-weight。3本未満ならbasketは`null`。

### candidate conditions

| condition id / 表示 | mandatory | contrary evidence | JSON value |
|---|---|---|---|
| `R_BROAD_RISK_ON` / 広範なリスクオン | `spy_r_4w>0`; `rsp_minus_spy_4w>=0`; `iwm_minus_spy_4w>=0`; sector advance `>=7/11` | VIX +3以上、HYG−LQD<0 | `broad_risk_on` |
| `R_LARGE_GROWTH_CONCENTRATION` / 大型グロース集中 | `spy_r_4w>0`; `qqq_rel_spy_4w>0`; `rsp_minus_spy_4w<=-0.02`; `iwm_minus_spy_4w<0`; sector advance `<=5/11` | RSP/IWM改善trend | `large_growth_concentration` |
| `R_DEFENSIVE_SHIFT` / ディフェンシブ移行 | defensive relative `>=0.02`; cyclical relative `<=0`; `vix_change_4w>0` | IWM relative>=0.02 | `defensive_shift` |
| `R_REAL_ASSET_LEADERSHIP` / 実物資産相対優位 | DBC relative `>=0.02`; GLDまたはXLE relative `>=0` | DBC trend worsening | `real_asset_leadership` |
| `R_CYCLICAL_RECOVERY_EXPECTATION` / 景気敏感優位（回復期待を示唆） | IWM relative `>=0.02`; cyclical relative `>=0.02`; HYG−LQD `>=0` | VIX +3以上 | `cyclical_recovery_expectation` |
| `R_LIQUIDITY_CONTRACTION` / 流動性縮小を示唆 | `spy_r_4w<0`; HYG−LQD `<=-0.01`; VIX +3以上; UUP 4週>0 | sector advance>=7/11 | `liquidity_contraction` |
| no full match | 上記full matchなし | — | `directionless` |

各candidateは`eligible`, `matched_conditions`, `unmatched_conditions`, `contrary_evidence`を保存する。

### primary/secondary/confidence

- full matchが1つ: それを`primary_regime`。mandatory 4個以上かつcontrary 0なら`high`、それ以外`medium`。
- full matchが複数: `primary_regime=mixed`、full match群を`secondary_regimes`、`confidence=low`。単一因果へ押し込まない。
- full matchなし: `primary_regime=directionless`。mandatoryの75%以上を満たす候補を最大2件`secondary_regimes`へ、`confidence=low`。
- 必須inputの25%以上がnull: `primary_regime=unclassifiable`, `confidence=unclassifiable`。

経済因果を断定せず、上記表示名称を使う。

## 4. theme data quality決定表

### threshold

| 項目 | 暫定条件 |
|---|---|
| defined constituent | 6社以上 |
| valid constituent（current 1/4週return） | 5社以上かつcoverage>=0.75 |
| 13週metric | valid 5社以上 |
| high/200DMA metric | valid 5社以上 |
| role aggregate | 当該role valid 2社以上。未満はrole metricを`null` |
| history | currentを含む連続3週でdirection eligible、4週で4週trend eligible |
| continuity | 各snapshot間4〜10暦日、schema/methodology/theme-master version一致 |
| market-cap weight | valid market cap coverage>=0.75。未満はnullable、他分類は継続可能 |

### output

`classification_eligible`, `phase_initial_diffusion_eligible`, `phase_overheat_eligible`, `direction_eligible`, `evidence_eligible`, `coverage_ratio`, `constituent_count`, `valid_constituent_count`, `history_weeks`, `role_valid_counts`, `metric_valid_counts`, `missing_required_fields`, `quality_reasons`。

### stop/partial rules

- global meta/schema/source integrity failure: 全段階停止。
- theme defined<6、valid<5、coverage<0.75: themeのphase/direction/evidence/research priority/theme market stateをすべて`unclassifiable`。current raw metricsは参考表示可、shortlist対象外。
- history<3: direction=`unclassifiable`、initial/diffusion phase=`unclassifiable`。current-only overheatは必要fieldが揃えば判定可。
- high/13週不足: overheat flag=`null`。initial/diffusionは継続可。
- role valid<2: そのrole比率だけ`null`。peripheral不足時はoverheatのperipheral conditionを使わず、volume conditionが必須になる。
- market cap不足: market-cap fields=`null`。equal-weight、top1/top3に基づく分類は継続可。
- condition flagはtri-stateで、必要データが揃って成立=`true`、揃って不成立=`false`、必須入力不足=`null`とする。

## 5. concentration定義

theme constituent `i`の4週SPY-relativeが正の場合だけ`positive_contribution_i=max(relative_i,0)`。分母は全valid constituentのpositive contribution合計。

- `top1_contribution_ratio = max(positive_contribution)/sum(positive_contribution)`
- `top3_contribution_ratio = top3 sum/sum(positive_contribution)`
- positive contribution合計0なら両方`null`
- `single_name_concentrated=true`: top1 `>0.60`
- `broad_concentration_pass=true`: top1 `<=0.50`かつtop3 `<=0.85`
- `weighting_divergence_4w = market_cap_weight_rel_spy_4w - equal_weight_rel_spy_4w`
- `market_cap_led=true`: weighting divergence `>=0.03`
- `equal_weight_led=true`: weighting divergence `<=-0.03`

閾値は暫定。一銘柄集中を防ぐgateであり、企業品質評価ではない。

### overheat breadth weak flag

`condition_flags.overheat_breadth_weak`はcode-sideで次のように生成する。

- `phase_price_overheat=false`なら`false`。
- `phase_price_overheat=true`かつ`advance_ratio_4w<0.60`または`pct_above_50dma<0.60`なら`true`。
- `phase_price_overheat=true`で両breadthが`>=0.60`なら`false`。
- `phase_price_overheat=null`、またはtrueだが必要breadthのいずれかがnullなら`null`。

これはP4の入力flagであり、GPTはbreadth弱化を独自判定しない。diffusion必須breadthと同じ0.60を再利用し、新しい閾値は追加しない。

## 6. phase決定表

phaseとdirectionは別軸。codeは全`phase_flags`を保持し、selected phaseは`price_overheat > diffusion > initial > unclassifiable`の順。overheatとdiffusion flagが同時trueでもflagは両方保存する。

| phase | 必須条件 | 補助/反対証拠 | 不足時 | JSON |
|---|---|---|---|---|
| 初動 | initial/diffusion eligible; equal-weight rel 1週>0、4週>0; direction=improving; advance ratio `>=0.25,<0.60`; top1 `<=0.60` | core advance>=0.50は補助。market-cap-ledは反対証拠 | required nullならunclassifiable | `initial` |
| 拡散 | eligible; equal-weight rel 4週>0; advance ratio>=0.60; 50DMA超過率>=0.60; top1<=0.50; top3<=0.85 | peripheral/core breadthは補助。direction worseningでもphaseは維持 | required nullならunclassifiable | `diffusion` |
| 価格過熱 | overheat eligible; rel 13週>=0.15; 52週高値5%以内比率>=0.50; volume>=1.30 **or** peripheral advance>=0.67 | top1 concentration、4週trend worseningを反対証拠として併記 | 13週/high不足ならflag null | `price_overheat` |
| 判定不能 | 上記なし、quality不足、互いに矛盾 | matched/unmatchedを保存 | — | `unclassifiable` |

## 7. recent direction決定表

| direction | 必須条件 | 反対証拠 | JSON |
|---|---|---|---|
| 改善 | rel trend improving; advanceまたは50DMA breadth improving; 他方がworseningでない | volume急減、4週trend worsening | `improving` |
| 横ばい | eligibleでimproving/worsening/outflowのいずれにも該当しない | — | `flat` |
| 悪化 | rel trend worsening; advanceまたは50DMA breadth worsening; 他方がimprovingでない | 1週relative急反発 | `worsening` |
| 流出示唆 | current equal-weight rel 4週<0; rel trend worsening; breadth worsening; volume>=1.20またはabsolute equal-weight 4週<0 | direct flow未実装を必ず表示 | `outflow_signal` |
| 判定不能 | history<3、required trend null | — | `unclassifiable` |

したがって`phase=price_overheat`かつ`direction=outflow_signal`を許可する。

## 8. evidence決定表

ordinal一軸にpositioning原因を混ぜない。`evidence.level`, `evidence.direction`, `evidence.positioning_hypothesis`を分離する。

| 表示 | 条件 | JSON level / direction |
|---|---|---|
| 直接的な資金流入・流出確認 | direct ETF flow等を実装し、正または負のflowを確認 | `direct_flow_confirmed / inflow|outflow`（v1.1では使用不可） |
| 資金流入を示唆 | rel4>0、direction improving、volume>=1.10、advance>=0.60、top1<=0.50 | `flow_suggested / inflow` |
| 資金流出を示唆 | direction outflow_signal | `flow_suggested / outflow` |
| 相対選好を示唆 | rel4の符号とbreadthは一致するがvolume条件なし | `relative_preference_suggested / inflow|outflow` |
| 価格上昇のみ確認 | rel4>0だがbreadth/concentration確認なし | `price_only / up` |
| 価格下落のみ確認 | rel4<0だがbreadth/trend確認なし | `price_only / down` |
| 証拠不足 | quality不足または方向を確認できない | `insufficient / unknown` |

`positioning_hypothesis=possible_short_term_adjustment`は、abs(rel1)>=0.08かつtop1>0.60、またはvolume>=1.80かつadvance<0.40の場合だけ。positioning data未実装なので「可能性」でありlevelではない。それ以外は`not_supported`、必要field欠損は`not_assessable`。

## 9. research priority決定表（code-side）

codeは`P0 → P1 → P2 → P5 → P4 → P3 → fallback`の順で最初に該当するruleを使用し、`classifications.research_priority`と`research_priority_rule`を保存する。GPTは再判定しない。P1とP2はselected phaseを必須にするため相互排他的である。

| rule | 条件 | 表示 / JSON |
|---|---|---|
| P0 | classification ineligible | 判定不能 / `unclassifiable` |
| P1 | `phase=diffusion`; direction improving/flat; evidence level∈{direct,flow,relative}; `evidence.direction=inflow`; concentration pass | DD優先 / `dd_priority` |
| P2 | `phase=price_overheat`; `phase_diffusion=true`; direction improving/flat; evidence level∈{direct,flow,relative}; `evidence.direction=inflow`; concentration pass | DD優先 / `dd_priority`（theme market stateはprice overheat） |
| P3 | phase initial/diffusion/price_overheat; direction improving/flat; evidence level∈{direct,flow,relative}; `evidence.direction=inflow`; P1/P2/P4/P5未達 | DD候補 / `dd_candidate` |
| P4 | `single_name_concentrated=true`、direction worsening/outflow、または`overheat_breadth_weak=true` | 監視 / `watch` |
| P5 | rel 1/4/13週すべて<=0; direction worsening/outflow; `evidence.direction∈{outflow,down,unknown}` | 優先度低 / `low_priority` |
| fallback | 上記外 | 監視 / `watch` |

P1/P2/P3で`evidence.direction∈{outflow,down,unknown,up}`は不成立。特にlevelが`flow_suggested`または`relative_preference_suggested`でもdirectionがoutflowならDD優先・DD候補にしない。priorityは企業品質、valuation、利益感応度を意味せず、「個別DDで検証する価値」である。

## 10. theme market state決定表（code-side）

schema fieldは互換性とrecord一貫性のため`timing_status`を維持するが、表示名は必ず「テーマ市場状態」とする。個別銘柄の売買・entry timingを意味しない。codeが`timing_status`と`timing_rule`を保存し、GPTは転記・説明だけを行う。

| rule | 条件 | 表示 / JSON |
|---|---|---|
| T0 | classification ineligible | 判定不能 / `unclassifiable` |
| T1 | selected phase=price_overheat | 価格過熱 / `price_overheat` |
| T2 | direction=worsening/outflow_signal | 悪化 / `deteriorating` |
| T3 | phase=initial | 初動だが未確認 / `early_unconfirmed` |
| T4 | diffusionかつdirection improving/flat | 良好 / `favorable` |
| fallback | — | 判定不能 / `unclassifiable` |

T1をT2より先に適用し、`phase=price_overheat`, `direction=outflow_signal`, `timing_status=price_overheat`として三fieldを同時保存する。流出情報は消えない。

## 11. code-side theme shortlist

`classification_eligible=true`かつresearch priorityが`dd_priority|dd_candidate|watch`のthemeだけを候補とし、`low_priority|unclassifiable`は除外する。候補を次のtupleで昇順sortし、先頭最大5件を選ぶ。加重合計や総合scoreは作らない。

1. priority: `dd_priority < dd_candidate < watch`
2. evidence direction: `inflow < up < unknown < down < outflow`
3. selected phase: `diffusion < initial < price_overheat < unclassifiable`
4. direction: `improving < flat < worsening < outflow_signal < unclassifiable`
5. concentration: `broad_concentration_pass=true < false < null`
6. `relative_strength_rank_4w`昇順。これは`equal_weight_rel_spy_4w`降順、null最後、theme_id昇順でcodeが事前生成する
7. `theme_id`昇順

各themeへ`selected_for_deep_dive`, `shortlist_rank`, `shortlist_reason_codes`, `relative_strength_rank_4w`を保存し、top-level `theme_shortlist.selected_theme_ids`にも同順で保存する。候補が3件未満でもlow/unclassifiableを穴埋めせず、全候補を選んで`SHORTLIST_BELOW_MINIMUM_3`を記録する。GPTは順位も選定も変更しない。

`shortlist_reason_codes`はpriority/rule/evidence/phase/diffusion/concentration/弱化・集中・除外理由からcode-sideでcanonical順に生成し、semantic validatorは保存配列との完全一致を要求する。

## 12. previous judgment・撤回条件

### source

`output/judgments/*.json`のschema-validかつsource latestとのsemantic一致を確認したimmutable recordだけからindexを構築し、各themeの直前recordのphase/direction/priority/theme market state/shortlistとwithdrawal評価だけを`latest.json.previous_judgments.records`へprojectionする。source run/hashまたは転記値が一致しないrecordはindexへ追加しない。会話記憶、過去session、モデル知識は使用しない。

### code-side evaluation

withdrawal conditionは`field_path`, `operator`, `value`, `persistence_weeks`。current/historyへ適用し、`triggered|not_triggered|unknown`と`observed_weeks`をprojectionへ保存する。required history不足・field nullは`unknown`。

### GPT rule

- triggered: code-sideの新priority/theme market stateとの差を踏まえ、前回判断の撤回または引下げを説明する。GPTがenumを変更せず、変更理由をcondition idとfieldで記録する。
- not triggered: 維持可能。ただし新しい反対証拠を併記。
- unknown: 「前回比較は可能だが撤回判定不能」。維持を確定しない。
- previousなし: `previous_judgment_date=null`、「前回比較不能」。

## 13. qualitative information

code-side shortlist themeの深掘りだけでWeb検索する。各itemを`confirmed_fact`, `company_or_industry_claim`, `analytical_inference`に分類し、source URLとfact dateを付ける。背景、需要持続、政策、value chain、risk、counterevidenceにだけ使用する。phase、direction、evidence、priority、theme market state、shortlistを変更しない。矛盾時は「定量判定は維持、定性上の反対証拠」と表示する。
