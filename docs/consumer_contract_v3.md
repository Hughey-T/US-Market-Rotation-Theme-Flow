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

Immutable files store only `generated_at`, `valid_until`, `hard_stop_after` and
UTC. A consumer applies the time-dependent `fresh`, `stale_but_displayable`, or
`hard_stop` safety gate at display time; that gate does not alter analysis bytes.

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

The weekly producer saves date-keyed daily theme and SPY returns. Risk analysis
inner-joins by date, keeps the last 60 shared dates, records used and missing
dates, and requires 20 pairs. Values are not annualized. Beta-adjusted return is
the mean theme return less beta times mean SPY return; residual momentum is the
sum of the latest 20 centered regression residuals, so the two definitions are
not aliases. Zero benchmark variance and insufficient data are `not_available`.

`selection_stability_heuristic` uses an empirical universe percentile, a 0.15
single-week penalty, and optional historical retention. It explicitly declares
that it is not a multiple-testing correction or statistical confidence.
Four-week forward outcomes store the realized theme return from prediction date
to the four-week outcome, the matching SPY return, their excess, the prediction
constituent hash, and availability. Only outcomes dated on/before generation
data date are used; five matured samples are required and future outcomes fail.

The production adapter reads optional `data/fundamentals/{data_date}.json` during
weekly generation. Its path, as-of, adapter version and raw SHA-256 are bound into
the authoritative generation identity. It has no credential dependency. Revenue growth, earnings growth,
margin, revisions, orders/contracts, capex, outlook, valuation, and theme
evidence each carry availability, value, source, and as-of. The combined status
is `price_only`, `fundamentals_only`, `price_and_fundamentals`, `unconfirmed`, or
`not_assessed`.

Constituent snapshots are fixed to `data_date` with source, universe version,
canonical hash, inclusion/exclusion reasons, missing and unavailable tickers.
Coverage applies 0.75/0.50 core thresholds to constituent and price paths.
Unconfigured fundamentals, factors, history, risk, or correlation are explicit
`not_assessed_or_partial` and cause a warning, not a false critical failure.
Core coverage below 0.50 is critical. Neither state becomes “none found.”

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
