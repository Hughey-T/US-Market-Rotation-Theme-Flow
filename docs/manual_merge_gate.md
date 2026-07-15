# Manual merge gate

This private repository's current GitHub plan does not permit branch-protection required checks. Do not make the repository public, retry the unavailable setting, or merge while a PR is Draft.

Before a human merge, record and verify every item:

- PR is explicitly Ready for review; a Draft PR must never be merged.
- Expected head SHA exactly matches the reviewed SHA.
- All eight non-overlapping required CI categories (the original six plus publication recovery and workflow contracts) are green for that SHA.
- Independent review is complete with Blocker 0 and Major 0.
- Local worktree is clean and the expected `main` SHA is recorded.
- The chosen squash/merge strategy and resulting commit identity are confirmed.
- Post-merge CI is observed and green.

The missing server-side branch protection remains an operational risk. This checklist is the required manual control until repository settings support enforcement.
