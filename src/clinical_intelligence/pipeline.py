"""Ingest/extract once, then rebuild only the affected patient's derived abstraction."""
from __future__ import annotations
from pathlib import Path
from time import perf_counter
from .domain import ABSTRACTION_VERSION, PatientAbstraction
from .extraction import Extractor
from .reconcile import POLICY_VERSION, reconcile
from .storage import Store, input_digest


def process(store: Store, paths: list[Path], extractor: Extractor, on_progress=None) -> dict:
    started = perf_counter()
    report = {"inputs": len(paths), "registered": 0, "cache_hits": 0, "extracted": 0, "failed": 0,
              "model_calls": 0, "extraction_key": extractor.key, "documents": []}
    # Freeze configuration for this run; cache lookup must never mix model/prompt contracts.
    key = extractor.key
    for path in sorted(paths, key=lambda p: str(p)):
        document, new = store.register(path.name, path.read_text(encoding="utf-8-sig"))
        report["registered"] += int(new)
        cached = store.extraction(document.document_id, key)
        if cached is not None:
            # A renamed duplicate reuses this snapshot without calling the extractor.
            store.activate_extraction(document.document_id, key)
            report["cache_hits"] += 1
            item = {"source": path.name, "document_id": document.document_id, "status": "cached"}
        else:
            try:
                extraction = extractor.extract(document)
                if extraction.extraction_key != key:
                    raise ValueError("Extractor configuration changed during processing")
                store.save_extraction(extraction)
                usage = extraction.usage.model_dump()
                store.save_attempt(document.document_id, key, "extracted", usage, None)
                report["extracted"] += 1
                report["model_calls"] += extraction.usage.model_calls
                item = {"source": path.name, "document_id": document.document_id, "declared_id": extraction.declared_id,
                        "status": "extracted", "claims": len(extraction.claims), "usage": usage}
            except Exception as error:
                # Failure is missing evidence, not evidence that no therapy occurred.
                message = f"{type(error).__name__}: {error}"
                usage = getattr(error, "usage", None)
                store.mark_failed(document.document_id, message)
                store.save_attempt(document.document_id, key, "failed", usage.model_dump() if usage else None, message)
                report["failed"] += 1
                report["model_calls"] += usage.model_calls if usage else 0
                item = {"source": path.name, "document_id": document.document_id, "status": "failed", "error": message,
                        "usage": usage.model_dump() if usage else None}
        report["documents"].append(item)
        if on_progress:
            on_progress(item)
    report["elapsed_seconds"] = perf_counter() - started
    return report


def ensure_complete(store: Store):
    # Unextracted documents may belong to any patient, so coverage is checked globally.
    incomplete = [d for d in store.documents() if d.status != "extracted"]
    if incomplete:
        names = ", ".join(d.source_names[0] for d in incomplete)
        raise ValueError(f"Registered evidence is incomplete ({names}); clinical answers are unavailable until extraction succeeds. Inspect registry status.")


def load_patient(store: Store, patient_id: str) -> PatientAbstraction:
    ensure_complete(store)
    extractions = store.patient_extractions(patient_id)
    key = input_digest(extractions, ABSTRACTION_VERSION + ":" + POLICY_VERSION)
    cached = store.abstraction(patient_id, key)
    if cached is not None:
        return cached
    # Rebuild derived facts from persisted claims; no model extraction is needed here.
    abstraction = reconcile(extractions)
    store.save_abstraction(abstraction, key)
    return abstraction
