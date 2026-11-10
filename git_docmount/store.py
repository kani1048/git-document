"""Git adapter and document-store operations; no external Python dependencies."""

import os
from pathlib import Path, PurePosixPath
import re
import subprocess

BRANCH = "docs/store"
REF = "refs/heads/" + BRANCH
DIRECTORY = ".docs-store"


class StoreError(Exception):
    pass


def git(cwd, *args, input=None, check=True):
    result = subprocess.run(["git", "-C", str(cwd), *args], input=input,
                            capture_output=True, encoding="utf-8")
    if check and result.returncode:
        raise StoreError(result.stderr.strip() or result.stdout.strip() or "Git operation failed")
    return result


def worktree_records(cwd):
    listing = git(cwd, "worktree", "list", "--porcelain", "-z").stdout
    records = []
    for block in listing.split("\0\0"):
        fields = dict(part.partition(" ")[::2] for part in block.split("\0") if part)
        if fields:
            records.append(fields)
    return records


class Store:
    def __init__(self, cwd, branch=BRANCH):
        # Git lists the primary worktree first; use its registered path rather
        # than assuming a .git directory is located inside the source checkout.
        records = worktree_records(cwd)
        if not records or "bare" in records[0]:
            raise StoreError("a non-bare primary worktree is required")
        self.root = Path(records[0]["worktree"]).resolve()
        if (not isinstance(branch, str) or branch.startswith("-")
                or git(self.root, "check-ref-format", "refs/heads/" + branch, check=False).returncode):
            raise StoreError("invalid branch name")
        mount_path = "." + re.sub(r"[^\w.-]", "-", branch)
        if mount_path == ".git":
            raise StoreError("branch name maps to reserved mount path .git; choose another branch")
        self.branch = branch
        self.ref = "refs/heads/" + branch
        self.directory = mount_path
        self.path = self.root / mount_path

    def mounted(self):
        if self.path.is_symlink():
            raise StoreError("mount path must not be a symlink")
        for record in worktree_records(self.root):
            if Path(record["worktree"]).resolve() == self.path:
                if record.get("branch") != self.ref:
                    raise StoreError(f"mount must be on {self.branch}; resolve the branch change manually")
                if "locked" in record:
                    raise StoreError("document worktree is locked")
                if not self.path.is_dir():
                    raise StoreError("registered document worktree is missing")
                return True
        if os.path.lexists(self.path):
            raise StoreError("mount path already exists and is not the registered document worktree")
        return False

    def require_mount(self):
        if not self.mounted():
            raise StoreError("documents are not mounted; run mount first")

    def changes(self):
        return git(self.path, "status", "--porcelain=v1", "--untracked-files=all").stdout

    def require_idle(self):
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
            path = git(self.path, "rev-parse", "--path-format=absolute", "--git-path", marker).stdout.strip()
            if Path(path).exists():
                raise StoreError("Git operation in progress; resolve it manually first")

    def require_clean(self):
        self.require_mount()
        self.require_idle()
        if self.changes():
            raise StoreError("document worktree has uncommitted changes")

    def has_remote(self):
        return git(self.root, "remote", "get-url", "origin", check=False).returncode == 0

    def fetch(self):
        if not self.has_remote():
            raise StoreError("origin is not configured")
        git(self.root, "fetch", "--no-tags", "origin", f"{self.ref}:refs/remotes/origin/{self.branch}")

    def mount(self):
        if self.mounted():
            return self.status()
        if git(self.root, "ls-files", "--", f":(literal){self.directory}").stdout:
            raise StoreError("source index already tracks the mount path")
        # A local exclusion keeps product commits unchanged and is shared by
        # linked worktrees. Never edit or stage the source .gitignore.
        exclude = Path(git(self.root, "rev-parse", "--path-format=absolute",
                           "--git-path", "info/exclude").stdout.strip())
        if exclude.is_symlink():
            raise StoreError("info/exclude must not be a symlink")
        exclude.parent.mkdir(parents=True, exist_ok=True)
        content = exclude.read_text() if exclude.exists() else ""
        line = "/" + self.directory + "/"
        if line not in content.splitlines():
            with exclude.open("a") as output:
                output.write(("\n" if content and not content.endswith("\n") else "") + line + "\n")
        if git(self.root, "show-ref", "--verify", "--quiet", self.ref, check=False).returncode:
            adopted = False
            if self.has_remote():
                remote = git(self.root, "ls-remote", "--exit-code", "origin", self.ref, check=False)
                if remote.returncode == 0:
                    self.fetch()
                    git(self.root, "branch", self.branch, f"refs/remotes/origin/{self.branch}")
                    adopted = True
                elif remote.returncode != 2:
                    raise StoreError(remote.stderr.strip() or "unable to inspect origin; no branch created")
            if not adopted:
                tree = git(self.root, "mktree", input="").stdout.strip()
                commit = git(self.root, "commit-tree", tree, "-m",
                             f"Initialize independent document history: {self.branch}").stdout.strip()
                # Compare-and-set protects an existing branch from replacement.
                git(self.root, "update-ref", self.ref, commit, "0" * len(commit))
        source = git(self.root, "rev-parse", "--verify", "HEAD", check=False)
        if source.returncode == 0:
            common = git(self.root, "merge-base", "HEAD", self.ref, check=False)
            if common.returncode == 0:
                raise StoreError("document branch shares source history; choose an independent orphan branch")
            if common.returncode != 1:
                raise StoreError(common.stderr.strip() or "unable to check branch isolation")
        git(self.root, "worktree", "add", str(self.path), self.branch)
        return Store(self.root, self.branch).status()

    def status(self):
        mounted = self.mounted()
        result = {"root": str(self.root), "path": str(self.path), "branch": self.branch,
                  "mounted": mounted, "has_origin": self.has_remote()}
        if mounted:
            result.update(commit=git(self.path, "rev-parse", "HEAD").stdout.strip(),
                          changes=self.changes())
        return result

    def unmount(self):
        self.require_clean()
        git(self.root, "worktree", "remove", str(self.path))
        return {"mounted": False, "branch_preserved": self.branch}

    def commit(self, message):
        self.require_mount()
        self.require_idle()
        if not message.strip():
            raise StoreError("commit message must be nonempty")
        if not self.changes():
            raise StoreError("no document changes to commit")
        git(self.path, "add", "--all", "--", ".")
        git(self.path, "commit", "-m", message)
        return self.status()

    def sync(self):
        self.require_clean()
        self.fetch()
        git(self.path, "merge", "--ff-only", f"refs/remotes/origin/{self.branch}")
        return self.status()

    def push(self):
        self.require_clean()
        if not self.has_remote():
            raise StoreError("origin is not configured")
        git(self.path, "push", "origin", f"{self.ref}:{self.ref}")
        return self.status()

    def document_head(self):
        """Resolve a local document branch and reject source-related history."""
        head = git(self.root, "rev-parse", "--verify", f"{self.ref}^{{commit}}").stdout.strip()
        source = git(self.root, "rev-parse", "--verify", "HEAD", check=False)
        if source.returncode == 0:
            common = git(self.root, "merge-base", "HEAD", head, check=False)
            if common.returncode == 0:
                raise StoreError("document branch shares source history")
            if common.returncode != 1:
                raise StoreError(common.stderr.strip() or "unable to check branch isolation")
        return head

    def clean_if_mounted(self):
        if self.mounted():
            self.require_clean()
        elif any(record.get("branch") == self.ref for record in worktree_records(self.root)):
            raise StoreError("branch is mounted outside its derived path; resolve it manually")

    def branch_proposal(self, name):
        base_head = self.document_head()
        self.clean_if_mounted()
        proposal = Store(self.root, name)
        # Refuse any existing branch or occupied path before making a branch.
        if git(self.root, "show-ref", "--verify", "--quiet", proposal.ref, check=False).returncode == 0:
            raise StoreError("proposal branch already exists; mount it to resume")
        proposal.mounted()
        git(self.root, "branch", proposal.branch, base_head)
        result = proposal.mount()
        return {**result, "base_branch": self.branch, "base_commit": base_head}

    def compare(self, base_branch=BRANCH):
        base = Store(self.root, base_branch)
        base_head, head = base.document_head(), self.document_head()
        if base.ref == self.ref:
            raise StoreError("proposal and base must be different branches")
        common = git(self.root, "merge-base", base_head, head, check=False)
        if common.returncode:
            raise StoreError("proposal and base must share document history")
        ancestor = common.stdout.strip()
        patch = git(self.root, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
                    ancestor, head, "--").stdout
        return {"branch": self.branch, "base_branch": base.branch,
                "base_commit": base_head, "proposal_commit": head,
                "merge_base": ancestor, "patch": patch}

    def merge_proposal(self, name):
        self.require_clean()
        proposal = Store(self.root, name)
        comparison = proposal.compare(self.branch)
        proposal.clean_if_mounted()
        # Pin the inspected commit. Never merge an unrelated branch or run a
        # conflict-producing three-way merge on the canonical document tree.
        git(self.path, "merge", "--ff-only", comparison["proposal_commit"])
        return {**self.status(), "proposal_branch": proposal.branch}

    @staticmethod
    def document_path(path):
        if (not path or path.startswith("/") or "\\" in path or "\0" in path
                or any(p in ("", ".", "..", ".git") for p in path.split("/"))):
            raise StoreError("document path must be a normalized relative POSIX path without .git or traversal")
        return PurePosixPath(path).as_posix()

    def read(self, commit, path):
        path = self.document_path(path)
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise StoreError("a full lowercase Git commit SHA is required")
        # Require a commit object, not a tag or tree SHA.
        if git(self.root, "cat-file", "-t", commit).stdout.strip() != "commit":
            raise StoreError("reference does not identify a commit")
        entries = git(self.root, "ls-tree", "-z", commit, "--", f":(literal){path}").stdout
        if not entries:
            raise StoreError("document is not tracked at the specified commit")
        entry = entries.split("\0")[0]
        mode, kind, _ = entry.split("\t")[0].split()
        if mode not in ("100644", "100755") or kind != "blob":
            raise StoreError("document must be a regular tracked file")
        return git(self.root, "show", f"{commit}:{path}").stdout

    def reference(self, path):
        self.require_mount()
        path = self.document_path(path)
        current = self.path
        for part in path.split("/"):
            current = current / part
            if current.is_symlink():
                raise StoreError("document paths must not traverse symlinks")
        if not current.is_file():
            raise StoreError("document must be an existing regular file")
        if git(self.path, "status", "--porcelain=v1", "--untracked-files=all",
               "--", f":(literal){path}").stdout:
            raise StoreError("commit this document before creating a reference")
        commit = git(self.path, "rev-parse", "HEAD").stdout.strip()
        self.read(commit, path)
        # Detect changes hidden by assume-unchanged/skip-worktree flags too.
        blob = git(self.path, "hash-object", "--", path).stdout.strip()
        expected = git(self.path, "rev-parse", f"HEAD:{path}").stdout.strip()
        if blob != expected:
            raise StoreError("working document differs from the committed version")
        return {"commit": commit, "path": path, "git_ref": f"{commit}:{path}"}
