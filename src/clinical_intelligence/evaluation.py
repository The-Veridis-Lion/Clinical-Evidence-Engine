"""Actual same-evidence design experiment and small-dataset measurements."""
from __future__ import annotations
import json
import statistics
import platform
import sqlite3
import subprocess
import sys
from time import perf_counter
from .pipeline import ensure_complete, load_patient
from .query import QuerySpec, compliance, query_collection, query_patient, utilization
from .reconcile import reconcile


def experiment(store):
    ensure_complete(store)
    patients = []
    for patient_id in store.patient_ids():
        evidence = store.patient_extractions(patient_id)
        # Hold extracted evidence fixed so differences come from reconciliation policy.
        explicit = reconcile(evidence, "explicit")
        naive = reconcile(evidence, "latest_wins")
        dates = [d for e in explicit.events for d in e.date_options]
        if not dates:
            continue
        start, end = min(dates), max(dates)
        changed = []
        naive_events = {e.event_id: e for e in naive.events}
        for event in explicit.events:
            other = naive_events[event.event_id]
            if (event.minutes_lower, event.minutes_upper, event.state) != (other.minutes_lower, other.minutes_upper, other.state):
                changed.append({"encounter_ref": event.encounter_ref, "event_id": event.event_id,
                                "explicit": event.model_dump(), "latest_wins": other.model_dump()})
        patients.append({"patient_id": patient_id, "start": start, "end": end,
                         "same_source_claim_ids": sorted(c.claim_id for c in explicit.source_claims) == sorted(c.claim_id for c in naive.source_claims),
                         "explicit": {"totals": utilization(explicit, start, end)["totals"], "weeks": compliance(explicit, start, end),
                                      "conflicts": [c.model_dump() for c in explicit.conflicts]},
                         "latest_wins": {"totals": utilization(naive, start, end)["totals"], "weeks": compliance(naive, start, end),
                                         "conflicts": [c.model_dump() for c in naive.conflicts]},
                         "changed_events": changed})
    return {"experiment": "same extracted evidence: latest recorded document wins versus explicit field relationships and retained conflicts",
            "patients": patients, "interpretation": "Compare derived conflict retention and active calculation provenance. Both policies retain the same original source claims; only the experimental resolution policy differs."}


def benchmark(store, iterations, processing_report):
    if iterations < 1:
        raise ValueError("Benchmark iterations must be positive")
    ensure_complete(store)
    # This timer excludes interpreter startup, CLI setup and opening the database.
    began = perf_counter()
    patients = [load_patient(store, i) for i in store.patient_ids()]
    if not patients:
        raise ValueError("No complete patients available for benchmarking")
    cold_load = perf_counter() - began
    def measure(operation):
        values = []
        for _ in range(iterations):
            t = perf_counter()
            operation()
            values.append((perf_counter() - t) * 1000)
        return {"iterations": iterations, "median_ms": statistics.median(values), "min_ms": min(values),
                "max_ms": max(values), "p95_ms": sorted(values)[min(len(values)-1, int(len(values)*0.95))]}
    spec = QuerySpec(family="compliance")
    documents = store.documents()
    dates = [d for e in patients[0].events for d in e.date_options]
    start, end = min(dates), max(dates)
    public_answer = query_patient(patients[0], spec, documents)
    def cli_request():
        # A real child interpreter includes startup, loading, audit assembly and JSON output.
        completed = subprocess.run([sys.executable, "-m", "clinical_intelligence", "--db", str(store.path.resolve()),
                                    "query", "--patient", patients[0].patient.patient_id, "--family", "compliance"],
                                   capture_output=True, encoding="utf-8", timeout=30, check=True)
        assert json.loads(completed.stdout)["provenance_completeness"] == "complete"
    cli_samples = []
    for _ in range(min(iterations, 3)):
        began = perf_counter()
        cli_request()
        cli_samples.append((perf_counter() - began) * 1000)
    initial = json.loads(processing_report.read_text(encoding="utf-8")) if processing_report.exists() else None
    current = [x for pid in store.patient_ids() for x in store.patient_extractions(pid)]
    # Active corpus usage excludes earlier extraction versions and exploratory calls.
    usage = [e.usage for e in current]
    def total(field):
        values = [getattr(u, field) for u in usage]
        return sum(values) if all(v is not None for v in values) else None
    return {"scope": "MEASURED on the supplied corpus only; collection currently contains one patient.",
            "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "platform": platform.platform()},
            "documents": len(store.documents()), "patients": len(patients), "claims": sum(len(p.source_claims) for p in patients),
            "initial_processing_report": initial,
            "database_bytes": store.path.stat().st_size,
            "saved_abstraction_json_bytes": sum(len(p.model_dump_json().encode()) for p in patients),
            "first_in_process_patient_load_seconds": cold_load,
            "measurement_boundaries": {
                "numerical_compliance": "In-memory clinical calculations; excludes evidence/provenance assembly.",
                "patient_query": "Public query plus final field evidence and provenance; preloaded abstraction/registry, no serialization.",
                "collection_query": "One public collection request with one final evidence index; preloaded abstractions/registry.",
                "json_serialization": "Serialize an already assembled public answer.",
                "new_process_cli_query": "New interpreter, imports, SQLite load, provenance assembly and JSON capture; includes parent JSON validation.",
            },
            "persisted_patient_load": measure(lambda: load_patient(store, patients[0].patient.patient_id)),
            "numerical_compliance": measure(lambda: compliance(patients[0], start, end)),
            "patient_query": measure(lambda: query_patient(patients[0], spec, documents)),
            "collection_query": measure(lambda: query_collection(patients, spec, documents)),
            "json_serialization": measure(lambda: json.dumps(public_answer, default=str)),
            "new_process_cli_query": {"iterations": len(cli_samples), "median_ms": statistics.median(cli_samples),
                                      "min_ms": min(cli_samples), "max_ms": max(cli_samples)},
            "query_model_calls": 0,
            "current_extraction_usage": {"models": sorted({u.model for u in usage}), "model_calls": total("model_calls"),
                                         "input_tokens": total("input_tokens"), "output_tokens": total("output_tokens"),
                                         "cached_tokens": total("cached_tokens"), "cost_usd": total("cost_usd"),
                                         "cost_note": "Codex subscription billing unavailable; token counts are CLI-reported usage, CLI invocations counted as extraction calls."},
            "scale_discussion": {"measured_at_large_scale": False,
                                 "first_bottleneck": "One Codex subprocess and model inference per new/changed document in pipeline.process/extraction; fixed instruction/startup context and sequential invocation dominate time and token use.",
                                 "next_bottleneck": "load_patient materializes all source claims for a patient; attach_evidence and the current CLI load the registry for audit. Collection queries load every patient abstraction.",
                                 "production_changes": "Use a measured direct provider with bounded parallel/batch extraction and equivalent grounding validation; incrementally materialize patient facts and relational aggregates. Keep source claims in indexed storage and fetch only referenced passages for audits. Test semantic accuracy and reconciliation before throughput tuning.",
                                 "estimate_policy": "No throughput or cost extrapolation is asserted for 500K/1M documents; the small dataset does not measure those workloads."}}
