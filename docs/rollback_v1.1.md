# Rollback plan

Publication contract 1.1 rollback validates a retained 1.1またはread-compatible 1.0 generation and the exact candidate pointer before atomically replacing `output/current.json`. Never mix component files or treat a consumer projection as authoritative. After switching to a data schema 1.2 generation, run `scripts/export_current_latest.py`, `scripts/export_consumer_projection.py`, and `scripts/export_consumer_details.py`; the old URL remains a full snapshot and the new URL/details must all bind to the selected generation. A legacy generation without presentation 1.2 is rejected by current Custom GPT instructions.

1. Revert the 1.1 implementation commit(s) with a normal revert commit; do not rewrite history or force-push.
2. Restore the matching 1.0 generator, workflow, schema, and Custom GPT instructions together. Never read a 1.1 artifact with 1.0 instructions.
3. Retain 1.1 archives and immutable judgments. Do not delete or rewrite them during rollback.
4. Stop the weekly workflow before changing consumers, then run the restored offline test and validator.
5. If publication fails, leave `output/current.json` pointing to the last successful generation and repair on a branch. Unreferenced staging or generation directories are not public and may be inspected before safe cleanup.

Publication is generation-scoped. Rollback consumers by switching the pointer only to a fully validated retained generation; never reconstruct a current state by mixing archive, history, index, and latest files from different runs.

The pre-implementation source is preserved by the repository baseline commit. `data/legacy/` and `schemas/legacy/` provide human-readable migration context but Git history is authoritative.
