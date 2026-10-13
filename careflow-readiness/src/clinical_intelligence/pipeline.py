"""Ingest/extract once, then rebuild only the affected patient's derived abstraction."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from .domain import ABSTRACTION_VERSION, PatientAbstraction
from .extraction import Extractor
from .reconcile import POLICY_VERSION, reconcile
from .storage import Store, input_digest


def process(store: Store, paths: list[Path], extractor: Extractor, on_progress=None,
            *, max_workers: int = 1, extractor_factory=None) -> dict:
    if not 1 <= max_workers <= 10:
        raise ValueError("Extraction concurrency must be between 1 and 10")
    if max_workers > 1 and extractor_factory is None:
        raise ValueError("Concurrent extraction requires independent extractor instances")
    started = perf_counter()
    key = extractor.key
    report = {"inputs": len(paths), "registered": 0, "cache_hits": 0, "extracted": 0, "failed": 0,
              "model_calls": 0, "extraction_key": key, "documents": [None] * len(paths)}
    pending = {}

    def publish(index, item):
        report["documents"][index] = item
        if on_progress:
            on_progress(item)

    # Registry/cache work stays on the SQLite-owning thread. Group aliases before inference.
    for index, path in enumerate(sorted(paths, key=lambda p: str(p))):
        document, new = store.register(path.name, path.read_text(encoding="utf-8-sig"))
        report["registered"] += int(new)
        cached = store.extraction(document.document_id, key)
        if cached is not None:
            store.activate_extraction(document.document_id, key)
            report["cache_hits"] += 1
            publish(index, {"source": path.name, "document_id": document.document_id, "status": "cached"})
        else:
            entry = pending.setdefault(document.document_id, (document, []))
            entry[1].append((index, path.name))

    def extract_document(document):
        # Providers carry mutable per-call usage, so concurrent requests never share one.
        worker = extractor_factory() if extractor_factory is not None else extractor
        if worker.key != key:
            raise ValueError("Extractor configuration changed during processing")
        return worker.extract(document)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(extract_document, document): (document, aliases)
                   for document, aliases in pending.values()}
        for future in as_completed(futures):
            document, aliases = futures[future]
            index, name = aliases[0]
            try:
                extraction = future.result()
                if extraction.extraction_key != key:
                    raise ValueError("Extractor configuration changed during processing")
                # Only the main thread persists results; workers never access SQLite.
                store.save_extraction(extraction)
                usage = extraction.usage.model_dump()
                store.save_attempt(document.document_id, key, "extracted", usage, None)
                report["extracted"] += 1
                report["model_calls"] += extraction.usage.model_calls
                item = {"source": name, "document_id": document.document_id, "declared_id": extraction.declared_id,
                        "status": "extracted", "claims": len(extraction.claims), "usage": usage}
            except Exception as error:
                # Keep the first failure; neither aliases nor other workers trigger retries.
                message = f"{type(error).__name__}: {error}"
                usage = getattr(error, "usage", None)
                store.mark_failed(document.document_id, message)
                store.save_attempt(document.document_id, key, "failed", usage.model_dump() if usage else None, message)
                report["failed"] += 1
                report["model_calls"] += usage.model_calls if usage else 0
                item = {"source": name, "document_id": document.document_id, "status": "failed", "error": message,
                        "usage": usage.model_dump() if usage else None}
            publish(index, item)
            for alias_index, alias_name in aliases[1:]:
                if item["status"] == "extracted":
                    report["cache_hits"] += 1
                    alias = {"source": alias_name, "document_id": document.document_id, "status": "cached"}
                else:
                    report["failed"] += 1
                    alias = {"source": alias_name, "document_id": document.document_id,
                             "status": "failed", "error": item["error"], "usage": None}
                publish(alias_index, alias)
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
