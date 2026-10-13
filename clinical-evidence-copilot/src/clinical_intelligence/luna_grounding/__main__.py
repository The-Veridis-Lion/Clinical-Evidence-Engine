"""python -m clinical_intelligence.luna_grounding COMMAND [--limit pilot-size]."""
import argparse
from pathlib import Path
from .runtime import initialize, execute, integrity
from .evaluation import evaluate, promote


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("init", "comparison", "evaluate-comparison", "promote", "final", "evaluate-final", "integrity"))
    p.add_argument("--root", type=Path, default=Path("artifacts/luna-grounding-v3"))
    p.add_argument("--limit", type=int)
    args = p.parse_args()
    repo, root = Path.cwd(), args.root.resolve()
    if args.command == "init":
        initialize(repo, root)
    elif args.command in ("comparison", "final"):
        execute(repo, root, args.command, limit=args.limit)
    elif args.command.startswith("evaluate-"):
        evaluate(repo, root, args.command.split("-", 1)[1])
    elif args.command == "promote":
        promote(root)
    else:
        integrity(repo, root)


if __name__ == "__main__":
    main()
