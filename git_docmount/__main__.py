import argparse
import json
import sys

from .store import Store, StoreError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage orphan document branches and worktree mounts")
    parser.add_argument("--repo", default=".", help="any worktree in the target repository")
    parser.add_argument("--branch", default="docs/store", help="orphan document branch (default: docs/store)")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("mount", "unmount", "status", "sync", "push"):
        sub.add_parser(command)
    commit = sub.add_parser("commit", help="stage and commit all document changes only")
    commit.add_argument("-m", "--message", required=True)
    sub.add_parser("branch", help="derive and mount a proposal from the selected document branch").add_argument("name")
    diff = sub.add_parser("diff", help="show committed proposal changes since the merge base")
    diff.add_argument("--base", default="docs/store")
    sub.add_parser("merge", help="fast-forward the selected document branch to a proposal").add_argument("name")
    sub.add_parser("ref").add_argument("path")
    read = sub.add_parser("read")
    read.add_argument("commit")
    read.add_argument("path")
    args = parser.parse_args(argv)
    try:
        store = Store(args.repo, args.branch)
        if args.command == "read":
            sys.stdout.write(store.read(args.commit, args.path))
            return 0
        if args.command == "ref":
            result = store.reference(args.path)
        elif args.command == "commit":
            result = store.commit(args.message)
        elif args.command == "branch":
            result = store.branch_proposal(args.name)
        elif args.command == "diff":
            result = store.compare(args.base)
        elif args.command == "merge":
            result = store.merge_proposal(args.name)
        else:
            result = getattr(store, args.command)()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (StoreError, OSError, UnicodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
