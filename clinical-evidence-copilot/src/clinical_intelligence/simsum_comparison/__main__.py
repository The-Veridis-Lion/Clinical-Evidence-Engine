"""python -m clinical_intelligence.simsum_comparison PHASE [--pilot]."""
import argparse
import json
from pathlib import Path
from . import VERSION
from .contract import CONFIG, DEFINITIONS, Identify, Verification, IDENTIFY_INSTRUCTION, VERIFY_INSTRUCTION, EXTRACT_INSTRUCTION, stable_hash
from .execution import read, run_phase
from ..clinical_notes.dataset import load_notes, selected_batch2, sha, write_json, verify_sources, SOURCE_COMMIT, SOURCE_FILES
from ..clinical_notes.schema import ClinicalNoteExtraction
from ..clinical_notes.prompt import INSTRUCTION_V2
from ..clinical_notes.runner import SingleDispatchProvider, implementation_hashes
from ..provider import ProviderConfig

def documents(repo):
    source = repo / "artifacts/clinical-notes-v1/source"
    verify_sources(source)
    notes = load_notes(source / "SimSUM.csv")
    partition_path = repo / "examples/clinical_notes/v1/partition.json"
    cohort_path = repo / "examples/clinical_notes/v2/batch2.json"
    return selected_batch2(notes, read(partition_path), sha(partition_path.read_bytes()), read(cohort_path))

def initialize(repo, root, docs):
    root.mkdir(parents=True,exist_ok=True)
    baseline = read(repo / "artifacts/clinical-notes-v2/execution-freeze.json")
    if implementation_hashes() != baseline["implementation"]:
        raise ValueError("Historical clinical-note implementation changed")
    provider = SingleDispatchProvider(ProviderConfig(timeout_seconds=CONFIG["timeout_seconds"]))
    provider.preflight()
    provider_contract = {"cli_version": provider.cli_version, "argv": provider.command(Path("FROZEN_REQUEST"))}
    schemas = {"identify": Identify.model_json_schema(), "verification": Verification.model_json_schema(),
               "extract": ClinicalNoteExtraction.model_json_schema()}
    contract = {"config":CONFIG,"definitions":DEFINITIONS,"schemas":schemas,
        "prompt_hashes":{"identify":sha(IDENTIFY_INSTRUCTION),"verify":sha(VERIFY_INSTRUCTION),
                         "extract_baseline":sha(INSTRUCTION_V2),"extract_candidate_instruction":sha(EXTRACT_INSTRUCTION)},
        "provider_contract":provider_contract,"cohort_sha256":sha((repo / "examples/clinical_notes/v2/batch2.json").read_bytes())}
    protected_paths = [repo / "examples/clinical_notes/v1/partition.json", repo / "examples/clinical_notes/v2/batch2.json"]
    protected_paths += list((repo / "src/clinical_intelligence/clinical_notes").glob("*.py"))
    protected_paths += list((repo / "docs").glob("clinical-note-*.json"))
    protected_paths += list((repo / "docs").glob("clinical-note-*.md"))
    historical_raw = {}
    for version in ("v1","v2"):
        folder = repo / f"artifacts/clinical-notes-{version}"
        for p in folder.rglob("raw-response.json"):
            historical_raw[str(p.relative_to(repo))] = sha(p.read_bytes())
    manifest = {"version":VERSION,"description":"Reused development Batch 2, 300 patients; not an unseen holdout",
        "source_commit":SOURCE_COMMIT,"source_files":SOURCE_FILES,"execution_contract":contract,
        "provider_contract":provider_contract,"historical_single_pass":baseline,
        "protected_files":{str(p.relative_to(repo)):sha(p.read_bytes()) for p in protected_paths},
        "historical_raw_hashes":historical_raw,"model_repository":"https://huggingface.co/Ihor/gliner-biomed-base-v1.0",
        "reference_repository":"https://github.com/ds4dh/GLiNER-biomed",
        "audit_method":"Separate source inspection overlay; no model-generated judgment is reference truth",
        "documents":[{"document_id":d.document_id,"row_id":d.row_id,"variant":d.variant,
                      "note_sha256":d.note_sha256,"source_sha256":d.source_sha256} for d in docs]}
    write_json(root / "experiment_manifest.json",manifest,immutable=True)
    write_json(root / "inputs-freeze.json",[d.__dict__ for d in docs],immutable=True)
    for name,schema in schemas.items():
        write_json(root / "contracts" / f"{name}.json",schema,immutable=True)
    return manifest

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase",choices=["init","setup","gliner","audit-sample","identify","extract_luna_raw","extract_gliner_raw",
        "freeze","verify","derive","extract_luna_verified","extract_gliner_verified","evaluate","audit-queue","integrity"])
    parser.add_argument("--root",type=Path,default=Path("artifacts/gliner-luna-v1"))
    parser.add_argument("--pilot",action="store_true")
    args = parser.parse_args()
    repo,root = Path.cwd(), args.root.resolve()
    docs = documents(repo)
    if args.phase == "init":
        initialize(repo,root,docs)
    elif args.phase == "audit-sample":
        chosen = sum([sorted([d for d in docs if d.variant == v],
            key=lambda d:sha(f"{CONFIG['seed']}:source-only-audit:"+d.document_id))[:5]
            for v in ("text","advanced_text")],[])
        write_json(root / "source-only-audit-sample.json",[d.__dict__ for d in chosen],immutable=True)
    elif args.phase == "setup":
        from .gliner import setup
        setup(root)
    elif args.phase == "gliner":
        from .gliner import run
        run(root,docs,pilot=args.pilot)
    elif args.phase in {"identify","extract_luna_raw","extract_gliner_raw","verify","extract_luna_verified","extract_gliner_verified"}:
        if args.phase != "identify" and not args.pilot and not (root / "independent-predictions-freeze.json").exists():
            raise ValueError("Freeze both independent Identify outputs before comparison/extraction/verification")
        run_phase(root,docs,args.phase,pilot=args.pilot)
    elif args.phase in {"freeze","derive","evaluate","audit-queue"}:
        from .evaluation import freeze, derive, evaluate, audit_queue
        {"freeze":freeze,"derive":derive,"evaluate":evaluate,"audit-queue":audit_queue}[args.phase](repo,root,docs)
    elif args.phase == "integrity":
        manifest = read(root / "experiment_manifest.json")
        hashes = manifest["protected_files"] | manifest["historical_raw_hashes"]
        changed = [p for p,h in hashes.items() if sha((repo / p).read_bytes()) != h]
        if changed:
            raise ValueError(f"Protected historical files changed: {changed}")
        print(json.dumps({"protected_files_verified":len(hashes),"historical_raw_responses":len(manifest["historical_raw_hashes"])}))

if __name__ == "__main__":
    main()
