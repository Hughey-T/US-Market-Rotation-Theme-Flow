# Indicator inventory — schema 1.1 / methodology 1.1.0

全returnはsplit-adjusted price、配当除外です。1/4/13週は5/21/63 trading intervalsで、期間間の大小を加速・減速に使いません。欠損は`null`であり0ではありません。

| 領域 | 実装field | 用途・制約 |
|---|---|---|
| market | SPY、QQQ−SPY、RSP−SPY、IWM−SPY、sector breadth、defensive/cyclical basket、DBC/GLD/XLE、HYG−LQD、VIX change、UUP | deterministic regime candidates。価格ベースでありflow確認ではない |
| ETF | 1/4/13週return/relative、50/200DMA、高値圏、volume ratio | style、sector、industry comparison |
| theme | equal-weight return/relative、advance、50DMA、高値圏、volume | 主経路。defined>=6、valid>=5、coverage>=0.75 |
| concentration | top1/top3 positive contribution | positive sum=0は`null`。top1>0.60はsingle-name |
| weighting | market-cap relative、equal/cap divergence | market-cap coverage<0.75は`null`。point-in-time非保証 |
| role | core/beneficiary/peripheral aggregate | valid>=2。coreは中心性だけ |
| trend | 4週relativeのchange/slope/state、breadth count change | current込み連続3/4週、version一致、4〜10日間隔 |
| classification | regime、phase、direction、evidence、P/T rule | code-sideのみ。GPTは変更しない |
| shortlist | relative rank、selected、rank、reason | 総合scoreなしの辞書式順序、最大5 |
| judgment | immutable record/index/projection/withdrawal | previous sourceは検証済みindexだけ |

未実装: direct ETF flow、earnings revisions/guidance、short interest/options positioning、point-in-time market-cap history。詳細な式と境界は[methodology_v1.1.md](methodology_v1.1.md)を参照してください。
