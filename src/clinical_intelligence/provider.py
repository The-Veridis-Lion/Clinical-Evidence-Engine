"""Local Codex CLI provider. SDK/library objects stay inside extraction adapters."""
from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from .domain import ExtractionUsage, Model


class ProviderConfig(Model):
    provider: str = "codex_cli"
    model: str = "gpt-6-luna"
    reasoning_effort: str = "high"
    timeout_seconds: int = 300


class Provider(Protocol):
    config: ProviderConfig
    def language_model(self, examples: list[Any], source_text: str) -> Any: ...
    def reset_usage(self) -> None: ...
    def usage(self, elapsed: float) -> ExtractionUsage: ...


def extraction_envelope_schema(classes: list[str], source_text: str) -> dict:
    # LangExtract's raw class-keyed envelope, constrained by the CLI before alignment.
    variants = []
    for name in classes:
        variants.append({"type": "object", "additionalProperties": False,
                         "properties": {name: {"$ref": "#/$defs/source_passage"}, name + "_attributes": {
                             "type": "object", "additionalProperties": False,
                             "properties": {"data": {"type": "string"}}, "required": ["data"]}},
                         "required": [name, name + "_attributes"]})
    # Restrict quotations to source lines; the extractor verifies their exact offsets.
    passages = sorted({s.strip() for s in source_text.splitlines() if s.strip()})
    return {"type": "object", "additionalProperties": False,
            "$defs": {"source_passage": {"type": "string", "enum": passages}},
            "properties": {"extractions": {"type": "array", "items": {"anyOf": variants}}},
            "required": ["extractions"]}


class CodexCLIProvider:
    def __init__(self, config: ProviderConfig):
        if config.provider != "codex_cli":
            raise ValueError("Supported provider: codex_cli")
        self.config = config
        self.executable = shutil.which("codex")
        if not self.executable:
            raise ValueError("Install Codex CLI and run codex login before extracting new documents")
        self.cli_version = subprocess.run([self.executable, "--version"], capture_output=True, text=True,
                                         encoding="utf-8", timeout=10, check=True).stdout.strip()
        self.reset_usage()

    def reset_usage(self):
        self._records = []
        self._calls = 0
        self._call_metrics = []
        self._parse_failures = 0

    def output_schema(self, classes, source_text):
        return extraction_envelope_schema(classes, source_text)

    def prepare_prompt(self, prompt):
        return prompt

    def map_output(self, output):
        return output

    def run_cli(self, command, request, folder):
        return subprocess.run(command, input=request, cwd=folder, capture_output=True,
                              text=True, encoding="utf-8", timeout=self.config.timeout_seconds,
                              check=False)

    def language_model(self, examples, source_text):
        # LangExtract-specific types stay inside this adapter and the extractor.
        from langextract.core.base_model import BaseLanguageModel
        from langextract.core.types import ScoredOutput
        owner = self
        classes = sorted({x.extraction_class for e in examples for x in e.extractions})
        schema = owner.output_schema(classes, source_text)

        class CodexLanguageModel(BaseLanguageModel):
            def __init__(self):
                super().__init__()
                self.set_fence_output(False)

            def infer(self, batch_prompts, **kwargs):
                for prompt in batch_prompts:
                    # Empty ephemeral work directory plus ignored user/project instructions:
                    # clinical extraction never receives the repository, interview context or keys.
                    with tempfile.TemporaryDirectory(prefix="clinical-codex-") as directory:
                        folder = Path(directory)
                        schema_path, answer_path = folder / "schema.json", folder / "answer.json"
                        schema_path.write_text(json.dumps(schema), encoding="utf-8")
                        command = [owner.executable, "exec", "--ignore-user-config", "--ephemeral",
                                   "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--color", "never",
                                   "--model", owner.config.model,
                                   "-c", f'model_reasoning_effort="{owner.config.reasoning_effort}"',
                                   "-c", "project_doc_max_bytes=0", "-c", "features.shell_tool=false",
                                   "-c", "features.apply_patch_freeform=false", "-c", "features.multi_agent=false",
                                   "--output-schema", str(schema_path), "--output-last-message", str(answer_path), "-"]
                        owner._calls += 1
                        request = ("Perform only the extraction requested below. "
                                   "Do not use tools, read files, or perform calculations. "
                                   "Return raw JSON matching the supplied schema.\n\n" + owner.prepare_prompt(prompt))
                        schema_text = schema_path.read_text(encoding="utf-8")
                        quote_schema_chars = len(json.dumps(schema["$defs"]["source_passage"]["enum"]))
                        metric = {"source_characters": len(source_text),
                                  "request_prompt_characters": len(request),
                                  "source_occurrences_in_prompt": request.count(source_text),
                                  "output_schema_characters": len(schema_text),
                                  "source_quote_schema_characters": quote_schema_chars,
                                  "schema_structure_characters": len(schema_text) - quote_schema_chars,
                                  "status": "started"}
                        # This allocation excludes hidden CLI instructions and is not a token count.
                        if metric["source_occurrences_in_prompt"] == 1:
                            metric["instruction_example_wrapper_characters"] = len(request) - len(source_text)
                        owner._call_metrics.append(metric)
                        call_started = perf_counter()
                        try:
                            completed = owner.run_cli(command, request, folder)
                        except subprocess.TimeoutExpired:
                            metric["status"] = "timeout"
                            raise
                        finally:
                            metric["model_call_seconds"] = perf_counter() - call_started
                        events = []
                        for line in completed.stdout.splitlines():
                            try:
                                events.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                        usage = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None)
                        owner._records.append(usage)
                        metric["tokens"] = usage
                        if completed.returncode != 0 or not answer_path.exists():
                            metric["status"] = "cli_failed"
                            errors = [e.get("message", "") for e in events if e.get("type") == "error"]
                            raise RuntimeError(f"Codex CLI extraction failed (exit {completed.returncode}): "
                                               + ("; ".join(errors) or "see local CLI login/network configuration"))
                        # Reject tool use even if the CLI returned a valid extraction response.
                        for event in events:
                            if event.get("type") in {"item.started", "item.completed"}:
                                kind = event.get("item", {}).get("type")
                                if kind in {"command_execution", "mcp_tool_call", "web_search", "file_change"}:
                                    raise RuntimeError("Extraction provider attempted a tool operation")
                        output = answer_path.read_text(encoding="utf-8")
                        metric["response_characters"] = len(output)
                        try:
                            json.loads(output)  # reject malformed output before LangExtract alignment
                        except json.JSONDecodeError:
                            owner._parse_failures += 1
                            metric["status"] = "parse_failed"
                            raise
                        metric["status"] = "completed"
                        output = owner.map_output(output)
                        # This score satisfies the library interface; it is not clinical confidence.
                        yield [ScoredOutput(score=1.0, output=output)]

        return CodexLanguageModel()

    def usage(self, elapsed):
        # Failed/incomplete runs cannot provide a complete token total.
        complete = len(self._records) == self._calls and self._calls > 0 and all(self._records)
        return ExtractionUsage(provider=self.config.provider, model=self.config.model,
                               settings={**self.config.model_dump(), "cli_version": self.cli_version,
                                         "sandbox": "read-only", "tools": "disabled", "ephemeral": True},
                               latency_seconds=elapsed, model_calls=self._calls,
                               input_tokens=sum(r["input_tokens"] for r in self._records) if complete and all("input_tokens" in r for r in self._records) else None,
                               output_tokens=sum(r["output_tokens"] for r in self._records) if complete and all("output_tokens" in r for r in self._records) else None,
                               cached_tokens=sum(r["cached_input_tokens"] for r in self._records) if complete and all("cached_input_tokens" in r for r in self._records) else None,
                               call_metrics=self._call_metrics, parse_failures=self._parse_failures,
                               cost_usd=None, cost_basis="Codex subscription: actual billed cost unavailable")
