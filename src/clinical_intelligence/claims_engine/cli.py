"""Offline native claims CLI: clinical claims ..."""
import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

from .archive import ArchiveIndex
from .engine import build_packet, expanded_packet
from .split import create_split, load_split, partition_map
from .verification import verify_saved
from .workflow import inventory, process


def save_new(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(text, end="")
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as output:
            output.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["inventory", "inspect-claim", "packet", "batch", "split", "verify", "verify-holdout"]:
        command = commands.add_parser(name)
        command.add_argument("--archive", type=Path, required=True)
        command.add_argument("--output", type=Path)
        if name != "split":
            command.add_argument("--split", type=Path, required=name in {"verify", "verify-holdout"})
        if name in {"inspect-claim", "packet"}:
            command.add_argument("--claim-id", required=True)
        if name in {"batch", "inventory", "inspect-claim", "packet", "verify"}:
            command.add_argument("--partition", choices=["development", "holdout", "reserve"])
        if name == "split":
            command.add_argument("--seed", type=int, default=20261010)
        if name in {"verify", "verify-holdout"}:
            command.add_argument("--batch", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.exists():
            raise ValueError("OUTPUT_ALREADY_EXISTS: choose a new destination; sources and completed runs are immutable")
        if args.command in {"batch", "split", "verify-holdout"} and not args.output:
            raise ValueError("--output is required")
        split = load_split(args.split) if getattr(args, "split", None) else None
        partition = getattr(args, "partition", None)
        if partition and not split:
            raise ValueError("--partition requires --split")
        if args.command in {"verify", "verify-holdout"}:
            if args.command == "verify-holdout":
                # A manifest has one final holdout receipt, irrespective of --output.
                receipt = args.split.with_name(args.split.stem + ".holdout-receipt.json")
                save_new(receipt, {"status": "FINAL_VERIFICATION_ATTEMPT_RESERVED", "archive": str(args.archive), "batch": str(args.batch), "result_path": str(args.output),
                    "purpose": "One final deterministic verification; do not tune against this partition."})
                partition = "holdout"
            value = verify_saved(args.archive, args.batch, split, partition=partition)
            save_new(args.output, value)
            return int(bool(value["processing_failures"]))
        allowed = {e["patient_id"] for e in split["partitions"][partition]} if partition else None
        started = perf_counter()
        index = ArchiveIndex(args.archive, allowed_patients=allowed)
        indexing_seconds = perf_counter() - started
        if split and index.archive_sha256 != split["archive_sha256"]:
            raise ValueError("SPLIT_ARCHIVE_MISMATCH")
        if args.command == "split":
            value = create_split(index, args.output, args.seed)
            print(json.dumps({"eligible_patients": value["eligible_patients"], "partitions": {k: len(v) for k,v in value["partitions"].items()}, "manifest": str(args.output)}))
            return 0
        if args.command == "batch":
            value, _ = process(index, split, output=args.output, partition=partition)
            print(json.dumps({"output": str(args.output), "metrics": value["metrics"], "indexing_seconds": indexing_seconds, "processing_seconds": value["processing_seconds"]}, indent=2))
            return int(bool(value["failures"]))
        if args.command == "inventory":
            value, ledger = inventory(index, split)
            value["claim_inventory"] = ledger
            value["indexing_seconds"] = indexing_seconds
        else:
            claim = index.claim(args.claim_id)
            if args.command == "inspect-claim":
                value = {"claim": claim.model_dump(mode="json"), "transactions": [t.model_dump(mode="json") for t in index.transactions.get(args.claim_id, [])]}
            else:
                packet = build_packet(index, claim, partition=partition_map(split).get(claim.patient_id, "unassigned") if split else "unassigned")
                value = expanded_packet(index, packet)
        save_new(args.output, value)
        return 0
    except Exception as error:
        print(json.dumps({"status": "FAILED", "failure_category": str(error), "live_model_calls": 0}), file=sys.stderr)
        return 1
