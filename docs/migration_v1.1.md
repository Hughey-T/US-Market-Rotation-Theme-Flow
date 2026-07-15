# Migration to Market Rotation data 1.1

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

## Theme master

`scripts/migrate_theme_master.py` converts the provisional object map to schema 1.0 with explicit membership validity and rationale. Structure version and content version are independent. Cross-theme overlap is a warning; within-theme duplicate tickers are errors.
