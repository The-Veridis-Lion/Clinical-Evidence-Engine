"""One isolated turn per attempt; one user-authorized structural retry, no clinical judgment."""
import json
import os
import subprocess
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from time import perf_counter

from ..provider import CodexCLIProvider, ProviderConfig
from .dataset import sha, write_json
from .ledger import Ledger, now
from .prompt import make_prompt, PROMPT_VERSION, PROMPT_V2, PROMPTS
from .normalization import NORMALIZATION_VERSION, CONCEPT_GROUPS
from .schema import ClinicalNoteExtraction, validate_extraction, SCHEMA_VERSION
from .views import RESPIRATORY

CONFIG = {"model": "gpt-6-luna", "reasoning_effort": "high", "max_concurrency": 10,
          "dispatch_ceiling": 600, "transport_retries": 0, "structural_retries": 1,
          "timeout_seconds": 300}


def implementation_hashes():
    return {p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))}


class SingleDispatchProvider(CodexCLIProvider):
    """Reuse executable/config discovery; preserve streams directly to durable files."""
    def preflight(self):
        # Local configuration parsing only: bundled catalogue, no inference or network refresh.
        command = self.command(Path("."))
        configs = [part for i, value in enumerate(command) if value == "-c" for part in (value, command[i+1])]
        result = subprocess.run([self.executable, "debug", "models", "--bundled", *configs],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        if result.returncode:
            raise RuntimeError("Local provider configuration failed preflight: " + result.stderr[-2000:])

    def command(self, folder):
        return [self.executable, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "--json", "--color", "never", "--model", self.config.model,
                "-c", f'model_reasoning_effort="{self.config.reasoning_effort}"',
                "-c", 'model_provider="clinical_single_dispatch"',
                "-c", 'model_providers.clinical_single_dispatch.name="OpenAI single dispatch"',
                "-c", 'model_providers.clinical_single_dispatch.wire_api="responses"',
                "-c", "model_providers.clinical_single_dispatch.requires_openai_auth=true",
                "-c", "model_providers.clinical_single_dispatch.request_max_retries=0",
                "-c", "model_providers.clinical_single_dispatch.stream_max_retries=0",
                "-c", "model_providers.clinical_single_dispatch.supports_websockets=false",
                "-c", "features.responses_websockets=false", "-c", "features.responses_websockets_v2=false",
                "-c", "project_doc_max_bytes=0", "-c", "features.shell_tool=false",
                "-c", "features.apply_patch_freeform=false", "-c", "features.multi_agent=false",
                "-c", "web_search=\"disabled\"", "-c", "mcp_servers={}",
                "--output-schema", str(folder / "schema.json"), "--output-last-message",
                str(folder / "raw-response.json"), "-"]

    def dispatch(self, document, folder):
        # All streams are saved before parsing/normalization, even on timeout or failure.
        command = self.command(folder)
        write_json(folder / "dispatch.json", {"argv": command, "cli_version": self.cli_version,
                   "started_at": now(), "note_sha256": document.note_sha256}, immutable=True)
        with (folder / "events.jsonl").open("xb") as out, (folder / "stderr.txt").open("xb") as err:
            process = subprocess.Popen(command, cwd=folder, stdin=subprocess.PIPE, stdout=out, stderr=err,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                         start_new_session=os.name != "nt")
            try:
                process.communicate((folder / "prompt.txt").read_bytes(), timeout=self.config.timeout_seconds)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
                else:
                    import signal
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=10)
                raise RuntimeError("Provider timeout; no replay")
        events = []
        for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        usage = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None)
        write_json(folder / "usage.json", usage, immutable=True)
        if process.returncode != 0 or not (folder / "raw-response.json").exists():
            errors = [e.get("message", "") for e in events if e.get("type") == "error"]
            diagnostic = '; '.join(errors) or (folder / "stderr.txt").read_text(encoding="utf-8")[-2000:]
            raise RuntimeError(f"Provider exit {process.returncode}: {diagnostic}")
        turns = [e for e in events if e.get("type") == "turn.started"]
        if len(turns) != 1:
            raise RuntimeError(f"Expected one extraction turn; observed {len(turns)}")
        if any(e.get("item", {}).get("type") in {"command_execution", "mcp_tool_call", "web_search", "file_change"}
               for e in events):
            raise RuntimeError("Provider attempted tools")
        return (folder / "raw-response.json").read_text(encoding="utf-8"), usage


def execute(documents, partition_path, root: Path, *, provider=None, prompt_version=PROMPT_VERSION):
    root = root.resolve()
    provider = provider or SingleDispatchProvider(ProviderConfig(timeout_seconds=CONFIG["timeout_seconds"]))
    if isinstance(provider, SingleDispatchProvider):
        provider.preflight()
    if len(documents) != 300 or len({d.row_id for d in documents}) != 300:
        raise ValueError("Exactly 300 distinct frozen patient records required")
    schema = ClinicalNoteExtraction.model_json_schema()
    identity = {"config": CONFIG, "schema_version": SCHEMA_VERSION, "prompt_version": prompt_version,
                "schema_sha256": sha(json.dumps(schema, sort_keys=True)), "instruction_sha256": sha(PROMPTS[prompt_version]),
                "partition_sha256": sha(partition_path.read_bytes()), "implementation": implementation_hashes(),
                "cli_version": provider.cli_version}
    if prompt_version == PROMPT_V2:
        identity["normalization_version"] = NORMALIZATION_VERSION
        identity["normalization_sha256"] = sha(json.dumps(CONCEPT_GROUPS, sort_keys=True))
        from .evaluation import EVALUATION_V2
        identity["evaluation_version"] = EVALUATION_V2
    freeze_path = root / "execution-freeze.json"
    if freeze_path.exists():
        original = json.loads(freeze_path.read_text(encoding="utf-8"))
        # Correct software defects without rewriting history or changing clinical inputs.
        for key in identity.keys() - ({"implementation"} if prompt_version == PROMPT_VERSION else set()):
            if original[key] != identity[key]:
                raise ValueError(f"Frozen extraction contract changed: {key}")
    else:
        write_json(freeze_path, identity, immutable=True)
        original = identity
    provenance_hash = sha(json.dumps(identity, sort_keys=True))
    write_json(root / "execution-provenance" / f"{provenance_hash}.json", identity, immutable=True)
    ledger = Ledger(root / "requests.sqlite3", original, documents)
    lock = root / "runner.lock"
    with lock.open("x", encoding="utf-8") as f:
        f.write(json.dumps({"pid": os.getpid(), "started_at": now()}))
    began = perf_counter()
    run_start = now()
    attempted_before = len(ledger.rows())

    def work(document, attempt=1):
        folder = root / "requests" / document.document_id.replace(":", "_") / f"attempt-{attempt}"
        # Artifacts are immutable. Any interrupted reserved case stays reserved forever.
        if not ledger.reserve(document, attempt):
            return "skipped", None
        started = perf_counter()
        status, usage, error, raw_hash = "failed", None, None, None
        try:
            folder.mkdir(parents=True, exist_ok=False)
            write_json(folder / "schema.json", schema, immutable=True)
            (folder / "prompt.txt").write_text(make_prompt(document, version=prompt_version), encoding="utf-8", newline="\n")
            raw, usage = provider.dispatch(document, folder)
            # Providers, including offline fakes, must save their original response first.
            if not (folder / "raw-response.json").exists():
                raise RuntimeError("Provider did not persist raw response")
            raw_hash = sha((folder / "raw-response.json").read_bytes())
            try:
                result = validate_extraction(raw, document)
            except ValueError as e:
                status, error = "invalid", str(e)
            else:
                write_json(folder / "facts.json", result.model_dump(), immutable=True)
                write_json(folder / "respiratory.json", RESPIRATORY.project(result, grouped=prompt_version == PROMPT_V2), immutable=True)
                status = "valid"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        finally:
            if usage is None and (folder / "usage.json").exists():
                usage = json.loads((folder / "usage.json").read_text(encoding="utf-8"))
            if raw_hash is None and (folder / "raw-response.json").exists():
                raw_hash = sha((folder / "raw-response.json").read_bytes())
            ledger.finish(document.document_id, status, attempt=attempt, latency=perf_counter()-started,
                          usage=usage, error=error, raw_sha256=raw_hash)
        if status == "invalid" and attempt == 1:
            # Fresh extraction of the SAME note, without labels or prior clinical output.
            return work(document, attempt=2)
        return status, error

    try:
        existing = {(r["document_id"], r["attempt"]): r for r in ledger.rows()}
        pending = iter((d, 1) if (d.document_id, 1) not in existing else (d, 2)
                       for d in documents if (d.document_id, 1) not in existing
                       or existing[(d.document_id, 1)]["status"] == "invalid" and (d.document_id, 2) not in existing)
        blocked = None
        consecutive_provider_failures = 0
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {}
            def add_next():
                item = next(pending, None)
                if item is not None:
                    d, attempt = item
                    futures[pool.submit(work, d, attempt)] = d.document_id
            for _ in range(10):
                add_next()
            while futures:
                completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                for f in completed:
                    document_id = futures.pop(f)
                    status, error = f.result()
                    print(json.dumps({"document_id": document_id, "status": status,
                                      "attempted": len(ledger.rows())}), flush=True)
                    # An isolated transport failure is a failed case, not loss of provider access.
                    # Ten consecutive infrastructure failures stop further dispatches.
                    if status == "failed":
                        consecutive_provider_failures += 1
                        if consecutive_provider_failures >= 10:
                            blocked = error
                    else:
                        consecutive_provider_failures = 0
                if blocked is None:
                    for _ in completed:
                        add_next()
        summary = {"started_at": run_start, "ended_at": now(), "wall_seconds": perf_counter()-began,
                   "attempted_before": attempted_before, "attempted_after": len(ledger.rows()), "blocker": blocked,
                   "execution_provenance_sha256": provenance_hash}
        write_json(root / "runs" / (sha(run_start) + ".json"), summary, immutable=True)
        return summary
    finally:
        lock.unlink()
