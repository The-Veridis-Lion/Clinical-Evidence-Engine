"""One server-side Responses API dispatch for a product extraction attempt."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .review_transport import strict_schema_preflight

API_URL = "https://api.openai.com/v1/responses"
MAX_PROMPT_BYTES = 250_000
MAX_SCHEMA_BYTES = 128_000
MAX_RESPONSE_BYTES = 2_000_000


def _write_once(path: Path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


class OpenAIProductProvider:
    """Implements the existing dispatch interface without a CLI dependency."""

    def __init__(self, config):
        if config.provider != "openai_api" or config.model != "gpt-6-luna" or config.reasoning_effort != "high":
            raise ValueError("Product API provider requires gpt-6-luna/high")
        self.config = config
        self.cli_version = "openai-responses-api/1"

    def preflight(self):
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ValueError("Set server-side OPENAI_API_KEY for --provider openai_api")

    def dispatch(self, document, folder):
        folder = Path(folder)
        self.preflight()
        prompt = (folder / "prompt.txt").read_text(encoding="utf-8")
        schema = json.loads((folder / "schema.json").read_text(encoding="utf-8"))
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES or len(json.dumps(schema).encode("utf-8")) > MAX_SCHEMA_BYTES:
            raise ValueError("Product API prompt or schema exceeds the bounded dispatch size")
        strict_schema_preflight(schema)
        payload = {"model": "gpt-6-luna", "reasoning": {"effort": "high"},
                   "input": prompt, "store": False,
                   "text": {"format": {"type": "json_schema", "name": "clinical_product_extraction",
                                       "schema": schema, "strict": True}}}
        # Save the exact body without credentials before opening the connection.
        _write_once(folder / "api-request.json", payload)
        _write_once(folder / "dispatch.json", {"transport": "openai_api", "model": self.config.model,
                                               "reasoning_effort": self.config.reasoning_effort,
                                               "note_sha256": getattr(document, "note_sha256", None)})
        request = Request(API_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                                   "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            # A rejected HTTP response has an identifiable status; retain its body for audit.
            body = exc.read(MAX_RESPONSE_BYTES + 1)
            if len(body) <= MAX_RESPONSE_BYTES:
                with (folder / "api-error.json").open("x", encoding="utf-8") as stream:
                    stream.write(body.decode("utf-8", errors="replace"))
            raise RuntimeError(f"OpenAI API rejected request (HTTP {exc.code}); no transport retry") from None
        except (URLError, TimeoutError, OSError):
            # Delivery cannot be proven absent; the existing product ledger keeps it consumed.
            raise TimeoutError("OpenAI API dispatch timeout or disconnected; delivery uncertain, no replay") from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("OpenAI API response exceeded the bounded capture size; no replay")
        with (folder / "api-response.json").open("xb") as stream:
            stream.write(body)
        envelope = json.loads(body)
        usage = envelope.get("usage")
        _write_once(folder / "usage.json", usage)
        if envelope.get("status") != "completed":
            raise RuntimeError("OpenAI API response did not complete; no replay")
        output = envelope.get("output", [])
        if not isinstance(output, list) or any(not isinstance(item, dict) or item.get("type") not in {"reasoning", "message"}
                                               for item in output):
            raise RuntimeError("OpenAI API response attempted a non-message operation; no replay")
        messages = [item for item in output if item.get("type") == "message"]
        if len(messages) != 1 or messages[0].get("status") not in (None, "completed"):
            raise RuntimeError("OpenAI API response has no single completed message; no replay")
        content = messages[0].get("content", [])
        if len(content) != 1 or content[0].get("type") != "output_text" or not isinstance(content[0].get("text"), str):
            raise RuntimeError("OpenAI API response has no single structured output; no replay")
        raw = content[0]["text"]
        with (folder / "raw-response.json").open("x", encoding="utf-8") as stream:
            stream.write(raw)
        return raw, usage
