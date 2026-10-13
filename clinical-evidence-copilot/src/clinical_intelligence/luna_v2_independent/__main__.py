import argparse
import json
from pathlib import Path
from . import VERSION
from .runtime import initialize, offline_a, execute, integrity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["init", "offline-a", "run-a", "run-b", "materialize-a", "evaluate", "compare", "integrity"])
    parser.add_argument("--system", choices=["V2", "A", "B"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--root", type=Path, default=Path("artifacts") / VERSION)
    args = parser.parse_args()
    repo, root = Path.cwd(), args.root.resolve()
    if args.phase == "init":
        result = initialize(repo, root)
        result = {"frozen": result["version"], "documents": len(result["cohort"])}
    elif args.phase == "offline-a":
        result = offline_a(repo, root)
    elif args.phase.startswith("run-"):
        result = execute(repo, root, args.phase[-1].upper(), args.limit)
    elif args.phase == "integrity":
        result = integrity(repo, root)
        result = {"protected_files": len(result["protected"]), "configuration_unchanged": True}
    else:
        from .evaluation import evaluate, compare, materialize_a
        result = materialize_a(repo, root) if args.phase == "materialize-a" else compare(repo, root) if args.phase == "compare" else evaluate(repo, root, args.system)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
