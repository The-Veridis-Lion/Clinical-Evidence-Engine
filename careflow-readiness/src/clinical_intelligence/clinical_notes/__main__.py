"""python -m clinical_intelligence.clinical_notes {download,freeze,run,evaluate}."""
import argparse
import json
from pathlib import Path
from .dataset import (download, verify_sources, load_notes, build_partition, selected_documents, write_json,
                      build_batch2, selected_batch2, sha)
from .schema import ClinicalNoteExtraction
from .runner import execute, CONFIG
from .evaluation import evaluate, EVALUATION_VERSION, EVALUATION_V2
from .prompt import PROMPT_VERSION, PROMPT_V2
from .ledger import Ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("download", "freeze", "run", "evaluate"))
    parser.add_argument("--batch", type=int, choices=(1, 2), default=1)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--partition", type=Path, default=Path("examples/clinical_notes/v1/partition.json"))
    args = parser.parse_args()
    args.artifacts = args.artifacts or Path(f"artifacts/clinical-notes-v{args.batch}")
    args.manifest = args.manifest or (args.partition if args.batch == 1 else Path("examples/clinical_notes/v2/batch2.json"))
    if args.batch == 2 and args.artifacts.resolve() == Path("artifacts/clinical-notes-v1").resolve():
        raise ValueError("Batch 2 must not write into Batch 1 artifacts")
    source = args.source or (args.artifacts / "source" if args.batch == 1 else Path("artifacts/clinical-notes-v1/source"))
    if args.command == "download":
        download(source)
        return
    verify_sources(source)
    notes = load_notes(source / "SimSUM.csv")
    if args.batch == 2:
        partition = json.loads(args.partition.read_text(encoding="utf-8"))
        partition_hash = sha(args.partition.read_bytes())
        if args.command == "freeze":
            write_json(args.manifest, build_batch2(notes, partition, partition_hash), immutable=True)
            print("Frozen 300 NEW development patients; 150 standard + 150 advanced notes")
            return
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        documents = selected_batch2(notes, partition, partition_hash, manifest)
    else:
        documents = None
    if args.command == "freeze":
        write_json(args.manifest, build_partition(notes), immutable=True)
        write_json(args.manifest.parent / "schema.json", ClinicalNoteExtraction.model_json_schema(), immutable=True)
        print("Frozen 8,000 development / 2,000 final-test patients; 150 standard + 150 advanced notes")
        return
    if documents is None:
        partition = json.loads(args.manifest.read_text(encoding="utf-8"))
        documents = selected_documents(notes, partition)
    if args.command == "run":
        print(json.dumps(execute(documents, args.manifest, args.artifacts,
                                 prompt_version=PROMPT_VERSION if args.batch == 1 else PROMPT_V2)))
    else:
        identity = json.loads((args.artifacts / "execution-freeze.json").read_text(encoding="utf-8"))
        ledger = Ledger(args.artifacts / "requests.sqlite3", identity, documents)
        for effective in (False, True):
            summary = evaluate(documents, source, args.artifacts, ledger.rows(), effective=effective,
                               version=EVALUATION_VERSION if args.batch == 1 else EVALUATION_V2, batch=args.batch)
            print(json.dumps({"evaluation": "effective" if effective else "first",
                              **{k: summary[k] for k in ("execution", "citation", "groups", "reference_invalid_spans")}}, indent=2))


if __name__ == "__main__":
    main()
