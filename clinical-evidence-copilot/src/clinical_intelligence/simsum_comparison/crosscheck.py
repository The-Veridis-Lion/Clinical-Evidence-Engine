"""Independent local NER reassessment of Luna-only passages after raw freezes.

This is an entity check, not assertion adjudication. Failure to recognize is never a veto.
No reference annotations are opened or supplied. No paid provider calls are made.
"""
from time import perf_counter
from .contract import CONFIG, DEFINITIONS
from .execution import read
from .evaluation import load_jsonl, jsonl, aligned
from .gliner import adapt, windows
from ..clinical_notes.dataset import write_json, sha

def run(root,documents):
    import torch
    from gliner import GLiNER
    if not (root / "independent-predictions-freeze.json").exists():
        raise ValueError("Independent predictions must be frozen before model-to-model checks")
    freeze = read(root / "independent-predictions-freeze.json")
    for system in ("luna","gliner"):
        if sha((root / f"{system}_identify_raw.jsonl").read_bytes()) != freeze[f"{system}_identify_raw_sha256"]:
            raise ValueError("Independent prediction freeze changed")
    a = {r["document_id"]:r for r in load_jsonl(root / "luna_identify_raw.jsonl")}
    b = {r["document_id"]:r for r in load_jsonl(root / "gliner_identify_raw.jsonl")}
    torch.manual_seed(CONFIG["seed"])
    torch.set_num_threads(8)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = GLiNER.from_pretrained(read(root / "model-snapshot.json")["path"],local_files_only=True,
                                  load_tokenizer=True,map_location=device,strict=True).to(device).eval()
    tokenizer = model.data_processor.transformer_tokenizer
    records = []
    began = perf_counter()
    with torch.inference_mode():
        for doc in documents:
            if a[doc.document_id]["status"] != "valid":
                continue
            aa,bb = a[doc.document_id]["candidates"],b[doc.document_id]["candidates"]
            indices = aligned(aa,bb)["luna_only"]
            for index in indices:
                candidate = aa[index]
                dest = root / "gliner-local-checks" / doc.document_id.replace(":","_") / f"candidate-{index}.json"
                if dest.exists():
                    records.append(read(dest))
                    continue
                evidence = candidate["evidence"]
                start,end = max(0,evidence["start"]-100),min(len(doc.text),evidence["end"]+100)
                chunks = []
                tick = perf_counter()
                for x,y in windows(doc.text[start:end],tokenizer,CONFIG["gliner_subtoken_window"],CONFIG["gliner_overlap_words"]):
                    chunks.append({"start":start+x,"end":start+y,"entities":model.predict_entities(doc.text[start+x:start+y],
                        list(DEFINITIONS),threshold=CONFIG["gliner_threshold"],flat_ner=CONFIG["gliner_flat_ner"])})
                raw = {"document_id":doc.document_id,"note_sha256":doc.note_sha256,"candidate_index":index,
                       "luna_candidate":candidate,"model_revision":CONFIG["gliner_revision"],"config":CONFIG,"chunks":chunks}
                raw_path = dest.with_suffix(".raw.json")
                write_json(raw_path,raw,immutable=True)
                candidates,scored = adapt(doc,chunks)
                confirms = any(c["concept"] == candidate["concept"] and max(c["evidence"]["start"],evidence["start"]) <
                               min(c["evidence"]["end"],evidence["end"]) for c in candidates)
                result = {"document_id":doc.document_id,"note_sha256":doc.note_sha256,"candidate_index":index,
                    "luna_candidate":candidate,"gliner_candidates":candidates,"entities":scored,
                    "entity_overlap_confirmation":confirms,"latency_seconds":perf_counter()-tick,
                    "raw_sha256":sha(raw_path.read_bytes()),"nonrecognition_is_veto":False,
                    "ground_truth":False,"assertion_judgment":None}
                write_json(dest,result,immutable=True)
                records.append(result)
    jsonl(root / "gliner_luna_only_recheck.jsonl",records)
    write_json(root / "gliner-crosscheck-summary.json",{"checked_passages":len(records),
        "entity_overlap_confirmations":sum(r["entity_overlap_confirmation"] for r in records),
        "wall_seconds":perf_counter()-began,"paid_dispatches":0,"threshold":CONFIG["gliner_threshold"],
        "ground_truth":False,"prediction_changes":0,
        "interpretation":"Independent local NER check supplies corroboration only; frozen verifier decisions and predictions are unchanged"},immutable=True)
    return len(records)
