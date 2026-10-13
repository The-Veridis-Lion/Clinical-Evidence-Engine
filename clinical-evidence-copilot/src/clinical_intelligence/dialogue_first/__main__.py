"""python -m clinical_intelligence.dialogue_first {prepare,run,report,note}."""
import argparse
import json
import subprocess
from pathlib import Path
from .dataset import download, freeze_inputs, note_document, training_documents
from .runtime import report, run

CHECKPOINT = "601fcab26f4647fd0bad988ac4399d85c60c55e8"


def main():
    parser = argparse.ArgumentParser(description="Dialogue-first universal extraction; no accuracy scoring")
    parser.add_argument("action", choices=["prepare", "run", "report", "note"])
    parser.add_argument("--root", type=Path, default=Path("artifacts/dialogue-first-v1"))
    parser.add_argument("--input", type=Path, help="Ordinary clinical note input for action=note")
    parser.add_argument("--limit", type=int, help="Bound local run count without changing frozen selection")
    args = parser.parse_args()
    if args.limit is not None and not 1 <= args.limit <= 10:
        parser.error("--limit must be between 1 and 10")
    checked = subprocess.run(["git", "check-ignore", "-q", "--", str(args.root.resolve())], capture_output=True)
    if checked.returncode != 0:
        parser.error("--root must be a Git-ignored output directory; use artifacts/<run-name>")
    if args.action == "prepare":
        download(args.root / "dataset")
        value = freeze_inputs(args.root, training_documents(args.root / "dataset/train.csv"), checkpoint=CHECKPOINT)
    elif args.action == "note":
        if not args.input or args.root == Path("artifacts/dialogue-first-v1"):
            parser.error("note requires --input and a separate --root to isolate it from dialogue pilot")
        freeze_inputs(args.root, [note_document(args.input)], checkpoint=CHECKPOINT)
        value = run(args.root)
    else:
        value = run(args.root, limit=args.limit) if args.action == "run" else report(args.root)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
