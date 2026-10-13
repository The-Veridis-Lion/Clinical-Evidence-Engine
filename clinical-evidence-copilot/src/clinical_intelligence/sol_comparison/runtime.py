"""Reuse the exact frozen grounding contract; change only the requested model.

No Identify, verifier, transport retry, model repair, or replacement document.
Reservations are durable and never replay, including interrupted requests.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
import json

from . import VERSION
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.runner import SingleDispatchProvider
from ..provider import ProviderConfig
from ..luna_grounding.contract import prompt, schema, resolve
from ..luna_grounding.runtime import integrity as luna_integrity
from ..luna_rescore.evaluation import verify_index
from ..simsum_comparison.contract import stable_hash
from ..simsum_comparison.ledger import Ledger, now
from ..simsum_comparison.__main__ import documents

CONFIG = {"model": "gpt-6.1-sol", "reasoning_effort": "high", "timeout_seconds": 300,
          "max_concurrency": 10, "dispatch_cap": 100, "transport_retries": 0,
          "structural_retries": 0, "model_repairs": 0}
STAGE = "sol.extract"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def chosen(repo):
    m = read(repo / "artifacts/luna-grounding-v3/manifest.json")
    result = [d for d in documents(repo) if d.document_id in m["comparison_ids"]]
    if len(result) != 100 or len({d.row_id for d in result}) != 100 or sum(d.variant == "text" for d in result) != 50:
        raise ValueError("Exact frozen balanced 100-patient cohort required")
    return result


def code_hashes():
    return {str(p): sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))}


def provider():
    return SingleDispatchProvider(ProviderConfig(model=CONFIG["model"], reasoning_effort=CONFIG["reasoning_effort"],
                                                timeout_seconds=CONFIG["timeout_seconds"]))


def comparable_command(command):
    """Only output paths/model differ; preserve the actual CLI behavior otherwise."""
    value = list(command)
    for flag in ("--model", "--output-schema", "--output-last-message"):
        value[value.index(flag) + 1] = "MODEL" if flag == "--model" else flag + "-PATH"
    return value


def initialize(repo, root, supplied_provider=None):
    historical = repo / "artifacts/luna-grounding-v3"
    luna = luna_integrity(repo, historical)
    protections = {"luna": verify_index(historical),
                   "offline_rescore": verify_index(repo / "artifacts/luna-offline-rescore-v1")}
    docs = chosen(repo)
    p = supplied_provider or provider()
    p.preflight()  # Configuration parsing only; no inference.
    if (p.config.model, p.config.reasoning_effort, p.config.timeout_seconds) != (
            CONFIG["model"], CONFIG["reasoning_effort"], CONFIG["timeout_seconds"]):
        raise ValueError("Only the model may change from the frozen Luna provider configuration")
    if p.cli_version != luna["provider"]["cli_version"]:
        raise ValueError("Changing the CLI as well as model would break this comparison")
    if comparable_command(p.command(Path("FROZEN_REQUEST"))) != comparable_command(luna["provider"]["argv"]):
        raise ValueError("Provider dispatch flags differ beyond the requested model/output paths")
    contracts = {}
    for d in docs:
        directory = historical / "comparison/requests" / d.document_id.replace(":", "_")
        text, shape = (directory / "prompt.txt").read_bytes(), read(directory / "schema.json")
        expected = luna["per_document_contracts"][d.document_id]
        if sha(text) != expected["prompt_sha256"] or stable_hash(shape) != expected["schema_sha256"]:
            raise ValueError("Saved Luna prompt/schema do not match the frozen contract")
        if sha(prompt(d)) != sha(text) or stable_hash(schema(d)) != stable_hash(shape):
            raise ValueError("Grounding implementation differs from the saved request")
        contracts[d.document_id] = {**expected, "note_sha256": d.note_sha256,
                                  "luna_request_path": str(directory.relative_to(repo))}
    # Freeze known error targets before inference. They are never part of model inputs.
    target_paths = [historical / "confirmed-semantic-fact-errors.jsonl",
                    repo / "artifacts/luna-offline-rescore-v1/residual_source_review.jsonl"]
    protected_paths = [repo / "artifacts/luna-offline-rescore-v1/experiment_manifest.json",
        repo / "artifacts/luna-offline-rescore-v1/metrics.json",
        repo / "artifacts/luna-offline-rescore-v1/reference_adjudication_overlay.jsonl",
        repo / "artifacts/luna-round2-v1/source-review-final.jsonl", *target_paths]
    m = {"version": VERSION, "config": CONFIG, "code_hashes": code_hashes(),
         "comparison_ids": [d.document_id for d in docs], "per_document_contracts": contracts,
         "baseline": "cached Luna Grounded v3, exactly the same application prompt/schema/grounding",
         "provider": {"cli_version": p.cli_version, "argv": p.command(Path("FROZEN_REQUEST"))},
         "historical_seals": protections,
         "protected_paths": {str(path.relative_to(repo)): sha(path.read_bytes()) for path in protected_paths},
         "scoring": "frozen luna-offline-rescore-v1: unchanged one-to-one matcher and assertion audit; all 100 in denominator",
         "reference_conditions": ["original silver", "same chest-pain normalization and 26 confirmed overlay edits"],
         "semantic_review": {"known_targets_first": True, "max_flagged_documents": 20,
             "new_model_verification_calls": 0, "uncertain_cases_remain_uncertain": True,
             "no_reference_or_scoring_changes_after_inference": True},
         "sampling": {"temperature": "not explicitly set, as in baseline", "top_p": "not explicitly set",
                      "generation_seed": None, "max_output_tokens": None},
         "limits": "one initial request per document, hard cap 100 including failures; no further cohort",
         "limitations": ["reused development benchmark", "one stochastic run per model, no replication",
             "backend snapshot and backend sampling defaults not exposed",
             "Codex may use model-specific built-in instructions; application-level inputs and CLI flags held fixed"],
         "cost_basis": {"url": "https://learn.chatgpt.com/docs/pricing", "retrieved_date": "2026-10-11",
             "standard_credits_per_million": {"gpt-6.1-sol": {"input": 50, "cached_input": 2.5, "output": 250},
                                              "gpt-6-luna": {"input": 2.5, "cached_input": 0.25, "output": 12.5}},
             "actual_subscription_bill": None, "no_credit_purchase_or_limit_reset": True}}
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "experiment_manifest.json", m, immutable=True)
    write_json(root / "inputs-freeze.json", [{"document_id": d.document_id, **d.__dict__} for d in docs], immutable=True)
    integrity(repo, root)
    return m


def integrity(repo, root):
    m = read(root / "experiment_manifest.json")
    if m["config"] != CONFIG or m["code_hashes"] != code_hashes():
        raise ValueError("Frozen Sol experiment configuration/code changed")
    luna_integrity(repo, repo / "artifacts/luna-grounding-v3")
    for label, name in (("luna", "luna-grounding-v3"), ("offline_rescore", "luna-offline-rescore-v1")):
        if verify_index(repo / "artifacts" / name) != m["historical_seals"][label]:
            raise ValueError("Historical seal changed")
    for name, expected in m["protected_paths"].items():
        if sha((repo / name).read_bytes()) != expected:
            raise ValueError("Frozen scoring/reference/target changed: " + name)
    return m


class OneRequestLedger(Ledger):
    def __init__(self, path, manifest):
        self.allowed = set(manifest["comparison_ids"])
        super().__init__(path, {"manifest": stable_hash(manifest)}, total_cap=100, batch_cap=100)
        with self.connect() as db:
            db.executescript("""
                CREATE UNIQUE INDEX IF NOT EXISTS single_document ON requests(document_id);
                CREATE TRIGGER IF NOT EXISTS one_request BEFORE INSERT ON requests
                WHEN NEW.attempt!=1 OR NEW.stage!='sol.extract' OR NEW.batch!='comparison'
                BEGIN SELECT RAISE(ABORT,'one initial request only'); END;
            """)

    def reserve(self, stage, doc, attempt, batch, input_hash):
        if doc not in self.allowed or stage != STAGE or attempt != 1 or batch != "comparison":
            raise ValueError("Only one initial request for a selected document is allowed")
        return super().reserve(stage, doc, attempt, batch, input_hash)


def execute(repo, root, *, limit=None, supplied_provider=None):
    m = integrity(repo, root)
    ledger = OneRequestLedger(root / "requests.sqlite3", m)
    docs = chosen(repo)
    # A small pilot consumes part of the same 100, never additional requests.
    pending = [d for d in docs if d.document_id not in {r["document_id"] for r in ledger.rows()}]
    if limit is not None:
        if not 1 <= limit <= 100:
            raise ValueError("Pilot size outside cohort")
        pending = pending[:limit]
    if not pending:
        return {"new_dispatches": 0, "already_reserved": len(ledger.rows())}
    p = supplied_provider or provider()
    p.preflight()
    if p.cli_version != m["provider"]["cli_version"] or comparable_command(p.command(Path("FROZEN_REQUEST"))) != comparable_command(m["provider"]["argv"]):
        raise ValueError("Frozen provider changed")
    # Reject accidental Luna substitution even when command skeletons match.
    if (p.config.model, p.config.reasoning_effort, p.config.timeout_seconds) != (
            CONFIG["model"], CONFIG["reasoning_effort"], CONFIG["timeout_seconds"]):
        raise ValueError("Only authorized Sol/high is allowed")
    lock = root / "runner.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps({"started_at": now(), "model": CONFIG["model"]}))
    began = perf_counter()

    def work(doc):
        contract = m["per_document_contracts"][doc.document_id]
        old = repo / contract["luna_request_path"]
        text, shape = (old / "prompt.txt").read_bytes(), read(old / "schema.json")
        if sha(text) != contract["prompt_sha256"] or stable_hash(shape) != contract["schema_sha256"] or doc.note_sha256 != contract["note_sha256"]:
            raise ValueError("Selected input changed before dispatch")
        input_hash = stable_hash({"contract": contract, "config": CONFIG, "provider": m["provider"]})
        if not ledger.reserve(STAGE, doc.document_id, 1, "comparison", input_hash):
            return "already_reserved_no_replay"
        folder = root / "requests" / doc.document_id.replace(":", "_")
        started = perf_counter()
        status, error, usage, raw_hash = "failed", None, None, None
        try:
            folder.mkdir(parents=True, exist_ok=False)
            (folder / "prompt.txt").write_bytes(text)
            write_json(folder / "schema.json", shape, immutable=True)
            write_json(folder / "input-identity.json", {"document_id": doc.document_id,
                "note_sha256": doc.note_sha256, "prompt_sha256": sha(text), "schema_sha256": stable_hash(shape),
                "input_hash": input_hash, "model": CONFIG["model"]}, immutable=True)
            raw, usage = p.dispatch(doc, folder)
            if not (folder / "raw-response.json").exists():
                raise RuntimeError("Raw response must precede postprocessing")
            try:
                value, provenance = resolve(raw, doc)
            except ValueError as exc:
                status, error = "invalid", str(exc)
            else:
                write_json(folder / "result.json", value, immutable=True)
                write_json(folder / "offset-provenance.json", provenance, immutable=True)
                status = "valid"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if (folder / "raw-response.json").exists():
                raw_hash = sha((folder / "raw-response.json").read_bytes())
            if (folder / "usage.json").exists():
                usage = read(folder / "usage.json")
            ledger.finish(STAGE, doc.document_id, 1, status, perf_counter() - started, usage, error, raw_hash)
        print(json.dumps({"document_id": doc.document_id, "status": status, "error": error}), flush=True)
        return status

    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            statuses = list(pool.map(work, pending))
    finally:
        lock.unlink()
    result = {"wall_seconds": perf_counter() - began, "new_dispatches": len(pending), "statuses": statuses}
    write_json(root / "runs" / (now().replace(":", "-") + ".json"), result, immutable=True)
    integrity(repo, root)
    return result
