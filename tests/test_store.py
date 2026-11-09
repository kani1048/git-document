import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from git_docstore.store import BRANCH, REF, Store, StoreError, git

ROOT = Path(__file__).resolve().parents[1]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="git-docstore-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        (self.repo / "app.txt").write_text("source\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "source")
        self.source_head = git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def store(self):
        return Store(self.repo)

    def add_document(self, content="first\n", path="requirements/example.md"):
        store = self.store()
        target = store.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        store.commit("document")
        return self.store().reference(path)

    def remote(self):
        remote = self.base / "remote.git"
        remote.mkdir()
        git(remote, "init", "--bare")
        git(self.repo, "remote", "add", "origin", str(remote))
        git(self.repo, "push", "origin", "main")
        return remote

    def clone(self, remote):
        clone = self.base / "clone"
        git(self.base, "clone", "-b", "main", str(remote), str(clone))
        git(clone, "config", "user.name", "Test")
        git(clone, "config", "user.email", "test@example.invalid")
        return clone

    def test_independent_history_and_source_isolation(self):
        (self.repo / "app.txt").write_text("source work in progress\n")
        git(self.repo, "add", "app.txt")
        before = git(self.repo, "diff", "--cached").stdout
        self.store().mount()
        self.add_document()
        self.assertEqual(git(self.repo, "diff", "--cached").stdout, before)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), self.source_head)
        self.assertFalse((self.repo / ".docs-store/app.txt").exists())
        self.assertEqual(git(self.repo, "merge-base", "main", BRANCH, check=False).returncode, 1)
        self.assertNotIn(".docs-store", git(self.repo, "status", "--porcelain").stdout)

    def test_mount_idempotent_unmount_preserves_history(self):
        self.store().mount()
        self.assertTrue(self.store().mount()["mounted"])
        reference = self.add_document()
        self.store().unmount()
        self.assertFalse(self.store().status()["mounted"])
        self.assertEqual(self.store().read(reference["commit"], reference["path"]), "first\n")
        self.store().mount()
        self.assertEqual((self.store().path / reference["path"]).read_text(), "first\n")

    def test_dirty_unmount_refuses_without_data_loss(self):
        self.store().mount()
        (self.store().path / "untracked.md").write_text("keep me")
        with self.assertRaises(StoreError):
            self.store().unmount()
        self.assertEqual((self.store().path / "untracked.md").read_text(), "keep me")

    def test_path_conflict_and_symlink_are_preserved(self):
        path = self.repo / ".docs-store"
        path.mkdir()
        (path / "existing.md").write_text("keep")
        with self.assertRaises(StoreError):
            self.store().mount()
        self.assertEqual((path / "existing.md").read_text(), "keep")
        (path / "existing.md").unlink()
        path.rmdir()
        path.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(StoreError):
            self.store().mount()

    def test_tracked_mount_path_is_refused(self):
        path = self.repo / ".docs-store"
        path.mkdir()
        (path / "keep.md").write_text("keep")
        git(self.repo, "add", ".")
        with self.assertRaises(StoreError):
            self.store().mount()

    def test_entry_from_linked_source_worktree(self):
        linked = self.base / "feature"
        git(self.repo, "worktree", "add", "-b", "feature", str(linked))
        store = Store(linked)
        self.assertEqual(store.root, self.repo)
        store.mount()
        self.assertTrue(self.store().path.is_dir())
        self.assertFalse((linked / ".docs-store").exists())

    def test_reference_is_stable_and_rejects_uncommitted_file(self):
        self.store().mount()
        first = self.add_document()
        (self.store().path / first["path"]).write_text("second\n")
        with self.assertRaises(StoreError):
            self.store().reference(first["path"])
        self.store().commit("second version")
        second = self.store().reference(first["path"])
        self.assertNotEqual(first["commit"], second["commit"])
        self.assertEqual(self.store().read(first["commit"], first["path"]), "first\n")

    def test_bad_paths_symlinks_and_noncommit_refs(self):
        self.store().mount()
        reference = self.add_document(path="文書/space name.md")
        self.assertEqual(self.store().read(reference["commit"], reference["path"]), "first\n")
        for path in ("../app.txt", "/etc/passwd", "a/../b", ".git/config", "a//b"):
            with self.subTest(path=path), self.assertRaises(StoreError):
                self.store().read(reference["commit"], path)
        (self.store().path / "link.md").symlink_to("requirements/example.md")
        self.store().commit("link")
        head = self.store().status()["commit"]
        with self.assertRaises(StoreError):
            self.store().read(head, "link.md")
        with self.assertRaises(StoreError):
            self.store().read("main", reference["path"])
        tree = git(self.repo, "rev-parse", "docs/store^{tree}").stdout.strip()
        with self.assertRaises(StoreError):
            self.store().read(tree, reference["path"])

    def test_remote_adoption_and_fast_forward(self):
        remote = self.remote()
        self.store().mount()
        reference = self.add_document()
        self.store().push()
        clone = self.clone(remote)
        Store(clone).mount()
        self.assertEqual(Store(clone).status()["commit"], reference["commit"])
        self.add_document("new\n")
        self.store().push()
        Store(clone).sync()
        self.assertEqual((Store(clone).path / reference["path"]).read_text(), "new\n")

    def test_divergence_and_nonfastforward_push_do_not_destroy_work(self):
        remote = self.remote()
        self.store().mount()
        self.add_document()
        self.store().push()
        clone = self.clone(remote)
        Store(clone).mount()
        (Store(clone).path / "local.md").write_text("local")
        Store(clone).commit("local")
        local_head = Store(clone).status()["commit"]
        self.add_document("remote advance\n")
        self.store().push()
        with self.assertRaises(StoreError):
            Store(clone).sync()
        with self.assertRaises(StoreError):
            Store(clone).push()
        self.assertEqual(Store(clone).status()["commit"], local_head)
        self.assertEqual((Store(clone).path / "local.md").read_text(), "local")

    def test_missing_remote_and_connection_failure(self):
        self.store().mount()
        with self.assertRaises(StoreError):
            self.store().sync()
        with self.assertRaises(StoreError):
            self.store().push()
        self.store().unmount()
        git(self.repo, "branch", "-D", BRANCH)
        git(self.repo, "remote", "add", "origin", str(self.base / "missing.git"))
        with self.assertRaises(StoreError):
            self.store().mount()
        self.assertNotEqual(git(self.repo, "show-ref", "--verify", "--quiet", REF, check=False).returncode, 0)

    def test_wrong_branch_is_not_committed(self):
        self.store().mount()
        git(self.store().path, "switch", "-c", "docs/proposal")
        with self.assertRaises(StoreError):
            self.store().commit("must fail")

    def test_cli_json_and_errors(self):
        def invoke(*args):
            return subprocess.run([sys.executable, "-m", "git_docstore", "--repo", str(self.repo), *args],
                                  cwd=ROOT, capture_output=True, text=True)
        result = invoke("mount")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["mounted"])
        result = invoke("ref", "../bad")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))
        reference = self.add_document()
        result = invoke("read", reference["commit"], reference["path"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "first\n")


if __name__ == "__main__":
    unittest.main()
