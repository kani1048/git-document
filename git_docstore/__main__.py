import argparse
import json
import sys

from .store import Store, StoreError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Keep development documents on docs/store")
    parser.add_argument("--repo", default=".", help="any worktree in the target repository")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("mount", "unmount", "status", "sync", "push"):
        sub.add_parser(command)
    commit = sub.add_parser("commit", help="stage and commit all document changes only")
    commit.add_argument("-m", "--message", required=True)
    sub.add_parser("ref").add_argument("path")
    read = sub.add_parser("read")
    read.add_argument("commit")
    read.add_argument("path")
    args = parser.parse_args(argv)
    try:
        store = Store(args.repo)
        if args.command == "read":
            sys.stdout.write(store.read(args.commit, args.path))
            return 0
        if args.command == "ref":
            result = store.reference(args.path)
        elif args.command == "commit":
            result = store.commit(args.message)
        else:
            result = getattr(store, args.command)()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (StoreError, OSError, UnicodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
