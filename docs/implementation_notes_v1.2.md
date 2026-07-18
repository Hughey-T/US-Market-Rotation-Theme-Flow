# Implementation Notes 1.2

## Lightweight consumer projection

`scripts/export_current_latest.py` keeps the legacy compatibility path as an exact full snapshot. `rotation.consumer.build_consumer_snapshot` and `scripts/export_consumer_projection.py` produce the size-bounded v1 lightweight projection. `build_consumer_details` and `scripts/export_consumer_details.py` deterministically produce six Phase-specific v1 detail projections without a clock or new analysis. `scripts/export_consumer_v2.py` produces the size-bounded v2 manifest, normal Phase chunks, and detail chunks. Repository validation deterministically regenerates the complete legacy, v1, and v2 consumer bundle; any identity, schema, inventory, canonical content, reconstruction, or size difference fails publication. Full generation components remain unchanged.

- `rotation/discovery.py`: ETF信号と企業breadthによる動的業種発見。
- `rotation/decisions.py`: 構造的背景を含む相互排他的4分類候補と優先順位付き企業調査観点。
- `rotation/presentation.py`: 平易な日本語の6 Phase構造とrender。
- `rotation/interaction.py`: 保存済み`user_view`向けのinteraction helper。Custom GPT 1.6.0の進行コマンドは`更新`と`次`だけで、通常の質問ではPhaseを進めない。
- `rotation/metrics.py`: robust / concentration / liquidity metrics。
- `rotation/validation.py`: 新契約を生成ロジックから独立再計算。

決定性のため、全順序は数値キーとIDで明示的にsortします。公開時のatomic pointer、source hash、immutable judgments、TOCTOU防御は変更しません。
