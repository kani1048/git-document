# Git Docstore prototype

Purpose: keep development documents in Git, on an independent docs/store branch,
mounted as .docs-store in the primary worktree. Documents are the source of truth;
immutable references are Git commit SHA + repository-relative document path.

Scope: mount/unmount, status, commit, ref/read, explicit fast-forward-only sync and
push. No schema-specific rules, snapshots, remote APIs, acceptance evaluation or UI.
Existing stores should be reused; no dependency on harness installation or settings.

Verification: real temporary Git repositories and bare remotes. Cover orphan history,
source isolation, linked worktree entry, dirty work refusal, path conflicts, stable
references, remote adoption, divergence and non-fast-forward push refusal.

User authorized local-only work and deletion of the earlier product-evidence prototype.
Remote creation, push and draft PR are deferred. Status: implementation in progress.
