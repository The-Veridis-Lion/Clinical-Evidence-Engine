"""Reproduce offline scores only; never opens a provider or dispatches a request."""
import argparse
import json
from pathlib import Path
from .evaluation import rescore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    result = rescore(repo, args.output or repo / "artifacts/luna-offline-rescore-v1")
    print(json.dumps({"new_model_calls": result["new_model_calls"],
        "overlay": result["reference_overlay"],
        "scores": {condition: {name: value["silver"]["all"]["overlap"]
                              for name, value in systems.items()}
                   for condition, systems in result["systems"].items()}}, indent=2))


if __name__ == "__main__":
    main()
