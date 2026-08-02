# Consumer v4 architecture

## Boundary

Consumer v4 preserves the existing deterministic weekly snapshot and publication contracts. It adds six physically separated packages.

Blind packages:

- `facts`
- `blind`
- `companies`
- `blind-handoff`

Reconciliation packages:

- `mechanical`
- `reconciliation-handoff`

Blind packages recursively reject mechanical rank, candidate buckets, integrated rank, previous AI conclusions, AI confidence, and current/future outcomes. Reconciliation packages are not exposed by the session-local runtime until an AI assessment is validated and fixed by canonical hash.

## Publication

```text
output/consumer/v4/manifest.json
output/consumer/v4/generations/{generation_id}/manifest.json
output/consumer/v4/generations/{generation_id}/{package}/part-{n}.json
```

The moving pointer is atomically replaced. Immutable generation bytes are never overwritten; reusing a generation ID with different bytes is a collision.

Each package is canonical JSON divided into bounded UTF-8 fragments. Validation checks contract and identity fields, part sequence, fragment byte length and SHA-256, canonical reconstruction SHA-256, exact package inventory, theme/company set identities, generation identity, symlinks, and unexpected files.

## Artifact ownership

| Artifact | Owner |
|---|---|
| FACTS | deterministic producer |
| MECHANICAL_SIGNALS | deterministic producer |
| blind projection | deterministic producer |
| company/dynamic-industry facts | deterministic producer |
| AI_THEME_ASSESSMENT | Custom GPT |
| COUNTER_THESIS | Custom GPT |
| exploratory proposals | Custom GPT, isolated from formal sets |
| RECONCILIATION_ARTIFACT | session-local reconciliation runtime |
| INTEGRATED_THEME_DECISION | session-local reconciliation runtime |
| DECISION_LEDGER_RECORD | persisted only by an available write runtime |

## Persistence

The default is `session_local`. AI assessment, counter-thesis, reconciliation, and integrated decisions exist only in the current conversation. They are not described as GitHub-persisted or ledger-recorded. `runtime_persisted` is valid only when a deployed write-capable runtime is actually available.

## Compatibility

Startup preference is v4, then v3, v2, v1, and legacy. Fallback is allowed only for an exact startup 404. A malformed or identity-mismatched v4 tree fails closed. After session fixation, latest is not reread and fallback is prohibited.
