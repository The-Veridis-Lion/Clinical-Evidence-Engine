import argparse
import json
from pathlib import Path
from .runtime import initialize, execute, integrity
from .evaluation import evaluate, select


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "comparison", "final", "evaluate-comparison", "evaluate-final", "select", "decide-final", "integrity"])
    parser.add_argument("--configuration", choices=["A", "B"])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    repo = Path.cwd()
    root = repo / "artifacts/luna-source-constrained-v1"
    if args.command == "init":
        m = initialize(repo, root)
        print(json.dumps({"version": m["version"], "efforts": m["efforts"], "max_new_calls": 500}))
    elif args.command in {"comparison", "final"}:
        if args.configuration is None: parser.error("--configuration is required")
        execute(repo, root, args.command, args.configuration, limit=args.limit)
    elif args.command.startswith("evaluate-"):
        m = evaluate(repo, root, args.command.removeprefix("evaluate-"))
        print(json.dumps({"phase": m["phase"], "new_dispatches": m["new_dispatches"], "flagged": m["flagged_documents"]}))
    elif args.command in {"select", "decide-final"}:
        print(json.dumps(select(root, "comparison" if args.command == "select" else "final")))
    else:
        integrity(repo, root)
        print("Frozen implementation and historical artifacts intact")


if __name__ == "__main__":
    main()
