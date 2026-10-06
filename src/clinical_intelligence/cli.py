"""Small explicit CLI: inspectable structured queries instead of bespoke question pipelines."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .pipeline import process, load_patient
from .storage import SQLiteStore


def write_result(result, output=None, output_format="json"):
    # Both formats use the same runtime result and deterministic source links.
    if output_format == "audit":
        from .audit import render_audit
        text = render_audit(result)
    else:
        text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main(argv=None):
    # JSON pipes must use the same encoding as saved source text on Windows too.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="artifacts/clinical.sqlite")
    parser.add_argument("--output")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("process")
    ingest.add_argument("--input", default="data/documents")
    ingest.add_argument("--model", default="gpt-6-luna")
    ingest.add_argument("--reasoning", default="high")
    ingest.add_argument("--contract", choices=["baseline", "sparse"], default="baseline",
                        help="Sparse is an experimental contract; the reviewed baseline remains the default")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--patient")
    inspect.add_argument("--document")
    inspect.add_argument("--event")
    query = commands.add_parser("query")
    query.add_argument("--format", choices=["json", "audit"], default="json")
    query.add_argument("--spec", help="JSON QuerySpec file")
    query.add_argument("--family", choices=["utilization", "weekly_utilization", "compliance", "encounters", "compare_periods", "consecutive_under_target", "assessments", "progress", "cohort"])
    query.add_argument("--patient")
    query.add_argument("--start")
    query.add_argument("--end")
    query.add_argument("--service-types", nargs="+")
    query.add_argument("--dates", nargs="+")
    query.add_argument("--change-date")
    query.add_argument("--consecutive-weeks", type=int)
    query.add_argument("--min-sessions", type=int)
    query.add_argument("--min-minutes", type=int)
    dev = commands.add_parser("run-development")
    dev.add_argument("--format", choices=["json", "audit"], default="json")
    dev.add_argument("--questions", default="data/questions.json")
    dev.add_argument("--specs", default="data/development_queries.json")
    commands.add_parser("experiment")
    bench = commands.add_parser("benchmark")
    bench.add_argument("--iterations", type=int, default=30)
    bench.add_argument("--processing-report", default="artifacts/initial_processing.json")
    args = parser.parse_args(argv)
    try:
        with SQLiteStore(args.db) as store:
            if args.command == "process":
                # Saved inspections and queries do not construct a model provider.
                from .provider import CodexCLIProvider, ProviderConfig
                from .extraction import LangExtractExtractor
                path = Path(args.input)
                paths = list(path.glob("*.txt")) if path.is_dir() else [path]
                if not paths:
                    raise ValueError("No .txt source documents found")
                def progress(item):
                    print(json.dumps({k: item[k] for k in ("source", "status", "error") if k in item}), file=sys.stderr, flush=True)
                result = process(store, paths, LangExtractExtractor(CodexCLIProvider(ProviderConfig(model=args.model, reasoning_effort=args.reasoning)), contract=args.contract), progress)
                write_result(result, args.output)
                return int(result["failed"] > 0)
            if args.command == "inspect":
                if args.document:
                    document = next((d for d in store.documents() if d.document_id == args.document or d.declared_id == args.document), None)
                    if document is None:
                        raise ValueError("Document not found")
                    extraction = store.extraction(document.document_id, document.extraction_key) if document.extraction_key else None
                    result = {"document": document.model_dump(), "extraction": extraction.model_dump() if extraction else None}
                elif args.patient:
                    abstraction = load_patient(store, args.patient)
                    if args.event:
                        event = next((e for e in abstraction.events if e.event_id == args.event or e.encounter_ref == args.event), None)
                        if event is None:
                            raise ValueError("Event not found")
                        result = {"event": event.model_dump(), "claims": [c.model_dump() for c in abstraction.source_claims if c.claim_id in event.claim_ids]}
                    else:
                        result = abstraction.model_dump()
                else:
                    result = {"patients": store.patient_ids(), "documents": [d.model_dump(exclude={"text"}) for d in store.documents()]}
                write_result(result, args.output)
                return 0
            if args.command in {"query", "run-development"}:
                from .query import QuerySpec, query_collection, query_patient, attach_evidence
                from .pipeline import ensure_complete
                ensure_complete(store)
                if args.command == "query":
                    payload = json.loads(Path(args.spec).read_text(encoding="utf-8")) if args.spec else {
                        k: v for k, v in {"family": args.family, "patient_id": args.patient, "start": args.start,
                                         "end": args.end, "service_types": args.service_types, "dates": args.dates,
                                         "change_date": args.change_date, "consecutive_weeks": args.consecutive_weeks,
                                         "min_sessions": args.min_sessions, "min_minutes": args.min_minutes}.items() if v is not None}
                    spec = QuerySpec.model_validate(payload)
                    patients = [load_patient(store, i) for i in ([spec.patient_id] if spec.patient_id else store.patient_ids())]
                    result = query_patient(patients[0], spec) if spec.patient_id else query_collection(patients, spec)
                    write_result(attach_evidence(result, patients, store.documents()), args.output, args.format)
                else:
                    # Development questions supply QuerySpecs, not bespoke clinical logic.
                    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
                    specifications = {r["id"]: QuerySpec.model_validate(r["spec"]) for r in json.loads(Path(args.specs).read_text(encoding="utf-8"))}
                    if {q["id"] for q in questions} != set(specifications):
                        raise ValueError("Question IDs and supplied QuerySpec IDs differ")
                    patients = {i: load_patient(store, i) for i in store.patient_ids()}
                    results = []
                    for question in questions:
                        spec = specifications[question["id"]]
                        relevant = [patients[spec.patient_id]] if spec.patient_id else list(patients.values())
                        answer = query_patient(relevant[0], spec) if spec.patient_id else query_collection(relevant, spec)
                        results.append({**question, "answer": attach_evidence(answer, relevant, store.documents())})
                    write_result(results, args.output, args.format)
                return 0
            if args.command in {"experiment", "benchmark"}:
                from .evaluation import experiment, benchmark
                result = experiment(store) if args.command == "experiment" else benchmark(store, args.iterations, Path(args.processing_report))
                write_result(result, args.output)
                return 0
    except (ValueError, KeyError, RuntimeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
