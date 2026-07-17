# Implementation Notes 1.2

## Lightweight consumer projection

`scripts/export_current_latest.py` keeps the legacy compatibility path as an exact full snapshot. `rotation.consumer.build_consumer_snapshot` and `scripts/export_consumer_projection.py` produce the size-bounded v1 lightweight projection. `build_consumer_details` and `scripts/export_consumer_details.py` deterministically produce six phase-specific explanations without a clock or new analysis. Repository validation regenerates all eight consumer files; any identity, schema, inventory, canonical content, or size difference fails publication. Full generation components remain unchanged.

- `rotation/discovery.py`: ETF信号と企業breadthによる動的業種発見。
- `rotation/decisions.py`: 構造的背景を含む相互排他的4分類候補と優先順位付き企業調査観点。
- `rotation/presentation.py`: 平易な日本語の6段階構造とrender。
- `rotation/interaction.py`: 更新・次・詳細・用語・再評価の状態遷移。
- `rotation/metrics.py`: robust / concentration / liquidity metrics。
- `rotation/validation.py`: 新契約を生成ロジックから独立再計算。

決定性のため、全順序は数値キーとIDで明示的にsortします。公開時のatomic pointer、source hash、immutable judgments、TOCTOU防御は変更しません。
