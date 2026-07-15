# Test classification

The original T01-T49 identifiers retain their design meanings. New behavior
uses T50 and later. Each numbered case has one primary ownership category even
when it also exercises a neighboring layer.

| IDs | Primary category | Purpose |
| --- | --- | --- |
| T01-T10 | unit / rule contract | Core regime, phase, direction, quality, and missing-input rules |
| T11 | schema validation | Unsupported schema version |
| T12 | semantic validator | Freshness and hard-stop behavior |
| T13-T14 | repository operation | Previous judgment and withdrawal operation |
| T15-T19 | unit / rule contract | Role, weighting, overlap, and qualitative-boundary rules |
| T20 | semantic validator | Locked run identity |
| T21-T30 | unit / rule contract | Numeric boundaries, missingness, history, and evidence rules |
| T31-T32 | semantic validator | Failed manifest and source hash |
| T33 | schema validation | NaN and Infinity rejection |
| T34-T36 | semantic validator | Duplicate and overlap consistency |
| T37-T49 | unit / rule contract | Regime, priority, timing, overheat, and shortlist rules |
| T50-T52 | raw generation E2E | 50DMA-only direction changes and point-in-time membership |
| T53-T63 | semantic validator | Status, judgment, canonical reasons, tri-state flags, and `equal_weight_led` |
| T64 | repository operation | Failed publish preserves the existing successful latest artifact |
| T65-T70 | raw generation E2E | P1/P2/P5, overheat+outflow, shortlist determinism, publish rejection, judgment projection, and old-history missingness |

Numbered case totals are: schema validation 2, unit/rule contract 38, raw
generation E2E 9, semantic validator 18, and repository operation 3 (70 total).
The Python suite also retains 28 pre-existing unnumbered pipeline and rule
reachability support tests, for 98 tests total.

The three required CI layers are:

1. `schema-and-fixture-validation`: strict repository/canonical fixture checks
   plus semantic consistency tests.
2. `unit-and-rule-contracts`: T01-T49, P0-P5/fallback and T0-T4/fallback
   reachability, and repository operation contracts.
3. `generation-e2e`: raw theme master, observations, history, provenance, and
   previous-judgment inputs through the publish boundary.
