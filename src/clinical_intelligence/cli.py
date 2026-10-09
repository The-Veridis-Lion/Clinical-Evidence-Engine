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
    ingest.add_argument("--input", default="examples/synthetic/documents")
    ingest.add_argument("--model", default="gpt-6-luna")
    ingest.add_argument("--reasoning", choices=["none","low","medium","high","xhigh","max"])
    ingest.add_argument("--extractor", choices=["optimized","baseline"], default="optimized")
    ingest.add_argument("--workers", type=int, default=8)
    ingest.add_argument("--timeout", type=int, default=180)
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
    ask = commands.add_parser("ask", help="Translate a question into an existing deterministic query")
    ask.add_argument("--patient", required=True)
    ask.add_argument("question")
    ask.add_argument("--format", choices=["json", "audit"], default="json")
    commands.add_parser("demo", help="Load independently authored synthetic claims; no inference")
    commands.add_parser("experiment")
    bench = commands.add_parser("benchmark")
    bench.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        with SQLiteStore(args.db) as store:
            if args.command == "demo":
                from .demo import run_demo
                write_result(run_demo(store), args.output)
                return 0
            if args.command == "process":
                # Saved inspections and queries do not construct a model provider.
                from .provider import CodexCLIProvider, ProviderConfig
                from .extraction import LangExtractExtractor
                from .luna_candidates import CandidateExtractor
                configuration=json.loads((Path(__file__).parent/'contracts/luna_best.json').read_text(encoding='utf-8'))
                if args.reasoning:
                    configuration['reasoning']=args.reasoning
                path = Path(args.input)
                paths = list(path.glob("*.txt")) if path.is_dir() else [path]
                if not paths:
                    raise ValueError("No .txt source documents found")
                def progress(item):
                    print(json.dumps({k: item[k] for k in ("source", "status", "error") if k in item}), file=sys.stderr, flush=True)
                def new_extractor():
                    provider=CodexCLIProvider(ProviderConfig(model=args.model,
                        reasoning_effort=configuration['reasoning'],timeout_seconds=args.timeout))
                    return (LangExtractExtractor(provider) if args.extractor=='baseline' else
                            CandidateExtractor(provider,configuration))
                # Each independent document request owns its provider and usage records.
                result = process(store, paths, new_extractor(), progress,
                                 max_workers=args.workers, extractor_factory=new_extractor)
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
            if args.command == "ask":
                from time import perf_counter
                from .natural_language import NaturalLanguageQueryInterpreter, QueryContext
                from .provider import CodexCLIProvider, ProviderConfig
                from .query import QuerySpec, _period, query_patient
                from .pipeline import ensure_complete
                if args.patient not in store.patient_ids():
                    raise ValueError("Patient not found in selected database")
                ensure_complete(store)
                abstraction = load_patient(store, args.patient)
                try:
                    start, end = _period(abstraction, QuerySpec(family="utilization"))
                    episode_year = start.year if start.year == end.year else None
                except ValueError:
                    episode_year = None
                # Only identity and an unambiguous episode year are sent to Luna.
                context = QueryContext(patient_id=args.patient, patient_name=abstraction.patient.name,
                                       episode_year=episode_year)
                provider = CodexCLIProvider(ProviderConfig())
                started = perf_counter()
                interpretation = NaturalLanguageQueryInterpreter(provider).interpret(args.question, context)
                result = {"question": args.question, "interpretation": interpretation.model_dump(),
                          "interpretation_usage": provider.usage(perf_counter() - started).model_dump()}
                if interpretation.status == "ready":
                    # The unchanged query engine alone supplies answers and clinical evidence.
                    result["answer"] = query_patient(abstraction, interpretation.query_spec, store.documents())
                write_result(result, args.output, args.format)
                return 0
            if args.command == "query":
                from .query import QuerySpec, query_collection, query_patient
                from .pipeline import ensure_complete
                ensure_complete(store)
                payload = json.loads(Path(args.spec).read_text(encoding="utf-8")) if args.spec else {
                    k: v for k, v in {"family": args.family, "patient_id": args.patient, "start": args.start,
                                     "end": args.end, "service_types": args.service_types, "dates": args.dates,
                                     "change_date": args.change_date, "consecutive_weeks": args.consecutive_weeks,
                                     "min_sessions": args.min_sessions, "min_minutes": args.min_minutes}.items() if v is not None}
                spec = QuerySpec.model_validate(payload)
                patients = [load_patient(store, i) for i in ([spec.patient_id] if spec.patient_id else store.patient_ids())]
                result = query_patient(patients[0], spec, store.documents()) if spec.patient_id else query_collection(patients, spec, store.documents())
                write_result(result, args.output, args.format)
                return 0
            if args.command in {"experiment", "benchmark"}:
                from .evaluation import experiment, benchmark
                result = experiment(store) if args.command == "experiment" else benchmark(store, args.iterations)
                write_result(result, args.output)
                return 0
    except (ValueError, KeyError, RuntimeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
