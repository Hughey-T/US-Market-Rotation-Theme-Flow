# Migration to Market Rotation data 1.1

## Publication contract 1.0 migration

A fresh clone with neither current nor a fixed legacy publication starts normally. An empty `output/archive`, or that directory containing only its explicit `.gitkeep` placeholder, is also a clean bootstrap state. If `output/latest.json` is a real file without current, scheduled generation stops and directs the operator to `python scripts/migrate_publication_v1.py --explicit`; that command requires the legacy latest as its migration source, validates it, and creates a fully validated generation/current pointer. Archive JSON without a legacy latest is reported separately as a partial legacy state because the migration command cannot consume it. Unknown output or archive entries fail closed and report only their path. A valid `output/current.json` selects the normal transactional publication path even when preserved legacy files remain. Legacy latest, archive, history, and judgments are never deleted or modified. Failure preserves all legacy files and any prior public state. Consumers then use `scripts/export_current_latest.py`.

## Compatibility

Data 1.1 is intentionally incompatible with local 1.0. Consumers must require `meta.schema_version=1.1` and `meta.methodology_version=1.1.0`. Silent fallback is prohibited.

## Existing assets

- `schemas/legacy/rotation_snapshot.schema.1.0.json` preserves the old latest contract.
- `data/legacy/themes.v2-provisional.json` preserves the pre-migration master.
- old prediction/verification schemas and records remain read-only and are not judgment sources.

## Explicit legacy reader

```bash
python scripts/migrate_1_0_to_1_1.py --input old-latest.json --output migration-report.json --explicit
```

The command emits a non-publishable report. For legacy `phase=流出`, it records `phase=unclassifiable` and `direction=outflow_signal`; it never guesses lifecycle phase. Missing trend, concentration, quality, priority, theme-state, and shortlist fields are not filled with zero. Regenerate a complete 1.1 artifact from source observations.

Legacy prediction records are not converted to judgment records. Their meanings and required provenance differ.

Older locally generated 1.1 weekly history rows that do not contain
`above_50dma_count` remain readable only as insufficient 50DMA history. The
reader does not infer a count from `pct_above_50dma` and never fills the missing
value with zero. Newly generated history always persists the observed count.

## Theme master

`scripts/migrate_theme_master.py` converts the provisional object map to schema 1.0 with explicit membership validity and rationale. Structure version and content version are independent. Cross-theme overlap is a warning; within-theme duplicate tickers are errors.
