# Consumer contract 3.0

## Publication and integrity

`output/consumer/v3/manifest.json` is the small latest pointer. Immutable data
lives at `generations/{generation_id}/manifest.json`,
`phases/phase-N/part-P.json`, `details/phase-N/part-P.json`, and
`handoffs/part-P.json`. An identical rerun is idempotent; a different byte tree
for an existing generation ID is rejected.

The pointer binds the canonical generation-manifest file SHA-256. Inventories
bind each raw file byte count and SHA-256, consecutive part numbers, fragment
count, total bytes, and reconstructed canonical-object SHA-256. `source_sha256`
identifies the source snapshot and is never treated as a consumer content hash.
Limits are 8 normal parts, 32 detail/handoff parts, 128 KiB per Phase, and 1,000
fragments. Reconstruction requires valid JSON Pointers, dense zero-based arrays,
adjacent string continuation only, and rejects duplicate scalar, root/child, and
scalar/container conflicts.

## Authoritative presentation

`rotation.analysis_v3.build_authoritative_v3` creates the six objects before
fragmentation. Phase5 contains ordered structured companies, roles, reasons,
checks, counter-evidence, quality, trace fields, fundamental status, and the
non-recommendation notice. Phase6 is a separate bounded summary and never embeds
the Phase5 object. Numeric displays, ranks, thresholds, and margins are generated
by the producer, not by the GPT. Phase schemas and detail schemas reject unknown
top-level fields; handoffs have an independent schema and inventory.

## Methodology

Threshold confidence is deterministic: absolute margin below 2 percentage
points is low, below 5 points is medium, otherwise high. Initial observations
store no change language. Persistence fields explicitly carry history
insufficiency, prior delta, churn, selection continuity, and retention.

The independent risk path uses paired daily observations, SPY, a 60-observation
window label, and a minimum of 20 usable pairs. It reports beta, volatility,
beta-adjusted mean return, mean/volatility, residual momentum, and downside
relative strength. Insufficient data produces `not_available` without inference.

Multiple-comparison confidence uses an empirical universe percentile, a 0.15
single-week penalty, and optional historical retention. Four-week forward return
is reported only with at least five saved observations. These descriptive
statistics are neither causal evidence nor a trading recommendation.

The fundamental adapter reads a saved, point-in-time public-filing fixture. It
has no credential or network dependency. Revenue growth, earnings growth,
margin, revisions, orders/contracts, capex, outlook, valuation, and theme
evidence each carry availability, value, source, and as-of. The combined status
is `price_only`, `fundamentals_only`, `price_and_fundamentals`, `unconfirmed`, or
`not_assessed`.

Constituent snapshots are fixed to `data_date` with source, universe version,
canonical hash, inclusion/exclusion reasons, missing and unavailable tickers.
Coverage separates configured, evaluated, partial, unavailable and missing
themes plus constituent, price, and fundamental coverage. Low coverage emits a
warning or critical missing and cannot become “none found.”

Overlap analysis reports pairwise overlap rate, Jaccard similarity, shared top
constituents, return-correlation availability, common factors, deterministic
cluster ID and representative, breadth warning, and independence status. Themes
are not automatically merged. Duplicate candidates remain explicitly visible.

## Migration and compatibility

Instructions 1.7.0 probe v3 → v2 → v1 → legacy only when each higher start URL
returns exactly 404. An established v3 session uses only its saved immutable
generation. Existing v2, v1, and legacy exporters are unchanged. Timeout, 5xx,
rate limit and tool failures are retryable without state change; schema,
identity, hash, sequence, reconstruction, presentation, or hard-stop failures
are fail-closed.
