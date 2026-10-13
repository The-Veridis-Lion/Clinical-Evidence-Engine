"""Pinned biomedical NER; source-preserving windows and auditable raw chunk outputs."""
import json
import os
import re
import sys
import random
import subprocess
from pathlib import Path
from time import perf_counter
from .contract import CONFIG, DEFINITIONS, Candidate, Identify, canonical_candidates, validate_source
from ..clinical_notes.dataset import write_json, sha

def setup(root):
    from huggingface_hub import snapshot_download
    cache = root / "cache"
    snapshot = snapshot_download(CONFIG["gliner_model"], revision=CONFIG["gliner_revision"], cache_dir=cache,
        allow_patterns=["gliner_config.json", "pytorch_model.bin", "*token*.json", "spm.model", "README.md"])
    files = {p.name: sha(p.read_bytes()) for p in Path(snapshot).iterdir() if p.is_file()}
    write_json(root / "model-snapshot.json", {"path": snapshot, "revision": CONFIG["gliner_revision"],
        "files": files, "model_license": "Apache-2.0", "reference_repository_license": "MIT"}, immutable=True)
    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
    path = root / "dependencies.lock.txt"
    if path.exists() and path.read_text(encoding="utf-8") != freeze:
        raise ValueError("Dependency environment changed")
    path.write_text(freeze, encoding="utf-8", newline="\n")
    return snapshot

def windows(text, tokenizer, limit=350, overlap=40):
    """Bound subtoken length before the NER library. No source text reconstruction."""
    words = list(re.finditer(r"\S+", text))
    if not words:
        return []
    out, first = [], 0
    while first < len(words):
        last = first + 1
        while last < len(words):
            candidate = text[words[first].start():words[last].end()]
            if len(tokenizer(candidate, add_special_tokens=False)["input_ids"]) > limit:
                break
            last += 1
        start = 0 if first == 0 else words[first].start()
        end = len(text) if last == len(words) else words[last-1].end()
        if len(tokenizer(text[start:end], add_special_tokens=False)["input_ids"]) > limit:
            raise ValueError("Single source word exceeds configured subtoken window")
        out.append((start, end))
        if last == len(words):
            break
        first = max(first+1, last-overlap)
    # Windows cover every non-whitespace character, including original unicode/newlines.
    assert all(any(a <= m.start() and m.end() <= b for a,b in out) for m in words)
    return out

def adapt(doc, raw_chunks):
    candidates, scored = [], []
    for index, chunk in enumerate(raw_chunks):
        for entity in chunk["entities"]:
            start, end = entity["start"] + chunk["start"], entity["end"] + chunk["start"]
            c = Candidate(concept=entity["label"], evidence={"quote": entity["text"], "start": start, "end": end})
            validate_source(doc.document_id, [c], doc)
            score = float(entity["score"])
            if not 0 <= score <= 1:
                raise ValueError("Entity confidence outside probability range")
            candidates.append(c.model_dump())
            scored.append({**c.model_dump(), "confidence": score, "entity_label": entity["label"], "chunk_index": index})
    return canonical_candidates(candidates), scored

def run(root, documents, *, pilot=False):
    import torch
    import numpy as np
    from gliner import GLiNER
    random.seed(CONFIG["seed"])
    np.random.seed(CONFIG["seed"])
    torch.manual_seed(CONFIG["seed"])
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    began = perf_counter()
    path = json.loads((root / "model-snapshot.json").read_text(encoding="utf-8"))["path"]
    model = GLiNER.from_pretrained(path, local_files_only=True, load_tokenizer=True, map_location=device)
    model.to(device).eval()
    tokenizer = model.data_processor.transformer_tokenizer
    load_seconds = perf_counter()-began
    resources = {"device": device, "cpu_count": os.cpu_count(), "torch": torch.__version__,
        "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
        "load_seconds": load_seconds, "seed": CONFIG["seed"], "dtype": str(next(model.parameters()).dtype)}
    chosen = documents[:5]+documents[150:155] if pilot else documents
    for doc in chosen:
        folder = root / "gliner" / doc.document_id.replace(":", "_")
        complete = folder / "prediction.json"
        if complete.exists():
            record = json.loads(complete.read_text(encoding="utf-8"))
            if record["note_sha256"] != doc.note_sha256 or record["config"] != CONFIG:
                raise ValueError("Cached GLiNER configuration/source mismatch")
            continue
        folder.mkdir(parents=True, exist_ok=True)
        raw_path = folder / "raw.json"
        if raw_path.exists():
            raise RuntimeError("Interrupted immutable raw output requires explicit recovery, not rerun")
        start = perf_counter()
        chunks = []
        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        with torch.inference_mode():
            for a,b in windows(doc.text, tokenizer, CONFIG["gliner_subtoken_window"], CONFIG["gliner_overlap_words"]):
                entities = model.predict_entities(doc.text[a:b], list(DEFINITIONS), threshold=CONFIG["gliner_threshold"],
                                                 flat_ner=CONFIG["gliner_flat_ner"])
                chunks.append({"start": a, "end": b, "entities": entities})
        if device == "cuda":
            torch.cuda.synchronize()
        latency = perf_counter()-start
        write_json(raw_path, {"document_id": doc.document_id, "note_sha256": doc.note_sha256,
                   "config": CONFIG, "chunks": chunks}, immutable=True)
        candidates, scored = adapt(doc, chunks)
        write_json(complete, {"document_id": doc.document_id, "note_sha256": doc.note_sha256,
            "config": CONFIG, "status": "valid", "candidates": candidates, "entities": scored,
            "raw_sha256": sha(raw_path.read_bytes()), "latency_seconds": latency,
            "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated() if device == "cuda" else None}, immutable=True)
        print(json.dumps({"gliner_complete": doc.document_id, "candidates": len(candidates), "seconds": latency}), flush=True)
    resources["wall_seconds"] = perf_counter()-began
    resources["documents_selected"] = len(chosen)
    write_json(root / ("gliner-pilot-resources.json" if pilot else "gliner-resources.json"), resources, immutable=True)
