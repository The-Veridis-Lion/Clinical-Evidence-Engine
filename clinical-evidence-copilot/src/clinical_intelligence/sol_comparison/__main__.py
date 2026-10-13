"""Controlled Sol substitution: init, pilot/run, evaluate; hard cap 100."""
import argparse
from pathlib import Path
from .runtime import initialize, execute, integrity
from .evaluation import evaluate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("init", "run", "evaluate", "integrity"))
    p.add_argument("--root", type=Path, default=Path("artifacts/sol-controlled-comparison-v1"))
    p.add_argument("--limit", type=int)
    args = p.parse_args()
    repo = Path.cwd()
    root = args.root.resolve()
    if args.command == "init":
        initialize(repo, root)
    elif args.command == "run":
        print(execute(repo, root, limit=args.limit))
    elif args.command == "evaluate":
        evaluate(repo, root)
    else:
        integrity(repo, root)


if __name__ == "__main__":
    main()
