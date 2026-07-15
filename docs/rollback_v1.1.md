# Rollback plan

1. Revert the 1.1 implementation commit(s) with a normal revert commit; do not rewrite history or force-push.
2. Restore the matching 1.0 generator, workflow, schema, and Custom GPT instructions together. Never read a 1.1 artifact with 1.0 instructions.
3. Retain 1.1 archives and immutable judgments. Do not delete or rewrite them during rollback.
4. Stop the weekly workflow before changing consumers, then run the restored offline test and validator.
5. If publication fails, leave `output/current.json` pointing to the last successful generation and repair on a branch. Unreferenced staging or generation directories are not public and may be inspected before safe cleanup.

Publication is generation-scoped. Rollback consumers by switching the pointer only to a fully validated retained generation; never reconstruct a current state by mixing archive, history, index, and latest files from different runs.

The pre-implementation source is preserved by the repository baseline commit. `data/legacy/` and `schemas/legacy/` provide human-readable migration context but Git history is authoritative.
