# Invariants

- Fragment values are exact deep copies of source JSON subtrees.
- Oversized containers fall back recursively to the established leaf projection.
- JSON Pointer escaping and reconstruction semantics are unchanged.
- Existing phase, detail, byte, part, and fragment limits remain enforced.
