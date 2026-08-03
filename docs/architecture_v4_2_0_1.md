# Consumer v4 presentation contract 2.0.1

## Sealed assessment

AI_THEME_ASSESSMENT is generated and canonical-hash fixed before the Phase 1 response. Phase 1 exposes only the fixed-hidden state, disclosure phase, and hash. Rank, confidence, and theme-level assessment content remain sealed until Phase 7. Phase 7 discloses the same immutable assessment and does not re-run it.

## Explainable price gates

The producer retains the legacy booleans and adds tri-state gates: `pass`, `fail`, and `not_evaluable`. Relative confirmation records the observed four-week equal-weight SPY-relative return, the `>= 0.05` threshold, difference, reason code, and missing fields. Breadth and quality are separate gates. Missing data is never represented as a numeric failure.

## Selection ownership

Mechanical comparative rank is independent from formal selection eligibility. The producer records `selection_eligible`, `selection_gate_status`, `selection_gate_reasons`, and `monitoring_status`. Hard exclusions, failed or unevaluable gates, missing fundamental confirmation, and `watch_recovery` prevent formal selection. Reconciliation only assigns integrated ranks to selection-eligible themes. An empty eligible set deterministically produces `NO_SELECTION`.

## Candidate scope

Company candidate facts identify their origin, theme membership, whether a formal dynamic-industry artifact exists, ranking eligibility, and handoff scope. Candidates without a fixed theme or formal dynamic-industry artifact are `exploratory_company_candidate` / `exploratory_only` and cannot enter formal ranking or handoff.

## Phase ownership

Phase 1 owns identity, data quality, and sealed state. Phase 7 owns first assessment disclosure. Phase 9 owns the first mechanical disclosure and gate reconciliation. Phase 10 is a compact handoff view containing only final decision, formal candidates, recovery monitoring, exploratory candidates, next-update conditions, and session-local persistence status.

## Compatibility

The v4 transport, immutable generation tree, canonical hashing, sequential retrieval, exact-404 fallback, and v1-v3 compatibility remain unchanged. The enhancement layer is installed at package import and changes only producer explanation fields and session presentation payloads.
