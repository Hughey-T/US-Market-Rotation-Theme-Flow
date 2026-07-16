# Manual merge gate

This repository is public. GitHub branch protection is configured on `main` and is the primary server-side merge control. The manual checklist below supplements that protection; it does not replace or weaken it.

The protected branch requires:

- All changes to reach `main` through a pull request.
- The pull request branch to be up to date with `main` before merging.
- These eight status checks to succeed for the merge candidate:
  - `schema-and-canonical-fixtures`
  - `unit-and-rule-contracts`
  - `judgment-projection-semantics`
  - `pipeline-integration`
  - `repository-operations-and-transactional-publish`
  - `production-orchestration-e2e`
  - `publication-recovery-e2e`
  - `workflow-contracts`
- All review conversations to be resolved.
- Force pushes and deletion of `main` to remain disabled.

The configured approving-review count is zero, so an external approval is not required. Administrator enforcement is disabled to preserve an owner/admin emergency bypass path. That path is for recovery only and must not be used for routine merges.

The scheduled weekly workflow does not bypass or push to protected `main`. After this PR is merged, its first successful run bootstraps `publication` from `main`; later runs start from the exact fetched `publication` SHA and incorporate current `main`. The allowlist stages only current, generations, judgments, and the derived consumer export. Before a normal push, the workflow requires the remote SHA to remain unchanged and to be an ancestor of local HEAD; merge conflicts or a concurrently advanced remote stop publication. The job has only `contents: write` and never receives `pull-requests: write`. After pushing, the same workflow re-fetches the remote SHA and revalidates the current pointer, manifest, generation, schemas, and derived consumer export.

Before a human merge, record and verify every item:

- Final independent review is complete with Blocker 0 and Major 0.
- Only after that review, the PR is explicitly changed from Draft to Ready for review; a Draft PR must never be merged.
- Expected head SHA exactly matches the reviewed SHA.
- All eight required checks above are green for that exact SHA, and the branch is up to date with `main`.
- All review conversations are resolved.
- Local worktree is clean and the expected `main` SHA is recorded.
- The chosen squash/merge strategy and resulting commit identity are confirmed.
- Post-merge CI is observed and green.

If the emergency admin path is used, record the reason, actor, affected SHA, validation evidence, and follow-up action. Do not bypass the Draft lifecycle, independent review, or artifact validation for convenience.
