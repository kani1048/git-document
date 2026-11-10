# Git Docstore prototype

Purpose: manage document orphan branches and their worktree mounts in Git.
The branch is selectable (default docs/store); the mount name is derived from it
(default .docs-store). No independent mount-path override is provided.
Mount directories live directly under the primary worktree. Documents are the source of truth;
immutable references are Git commit SHA + repository-relative document path.

Scope: mount/unmount, status, commit, ref/read, explicit fast-forward-only sync and
push. No schema-specific rules, snapshots, remote APIs, acceptance evaluation or UI.
Existing stores should be reused; no dependency on harness installation or settings.

Verification: real temporary Git repositories and bare remotes. Cover orphan history,
source isolation, linked worktree entry, dirty work refusal, path conflicts, stable
references, remote adoption, divergence and non-fast-forward push refusal.

User authorized local-only work and deletion of the earlier product-evidence prototype.
Remote creation, push and draft PR are deferred.

Status: local prototype complete. 18 integration tests pass, including multiple
independent document stores, branch-only CLI options, derived mount names and collision protection, invalid configuration,
shared source-history refusal, local bare
remote adoption, fast-forward sync, divergence refusal, dirty-work protection,
source index isolation, linked worktree entry and immutable document references.
A separate Japanese-text demo confirmed read after unmount and unchanged source
status. README documents commands, boundaries and unsupported features.
