import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from evidence_verification.extensions import openai_product_transport as transport


SCHEMA = {"type": "object", "properties": {"value": {"type": "string"}},
          "required": ["value"], "additionalProperties": False}


def prepared(tmp_path: Path):
    (tmp_path / "prompt.txt").write_text("Extract the source", encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    return SimpleNamespace(provider="openai_api", model="gpt-6-luna", reasoning_effort="high", timeout_seconds=15)


def test_api_dispatch_persists_envelope_and_never_persists_key(tmp_path, monkeypatch):
    config = prepared(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-keep-out")
    seen = []
    envelope = {"id": "resp_test", "status": "completed", "usage": {"input_tokens": 7, "output_tokens": 5},
                "output": [{"type": "message", "status": "completed", "content": [
                    {"type": "output_text", "text": '{"value":"ok"}'}]}]}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return json.dumps(envelope).encode("utf-8")

    def fake_urlopen(request, timeout):
        seen.append((request, timeout))
        return Response()

    monkeypatch.setattr(transport, "urlopen", fake_urlopen)
    raw, usage = transport.OpenAIProductProvider(config).dispatch(SimpleNamespace(note_sha256="abc"), tmp_path)
    assert json.loads(raw) == {"value": "ok"}
    assert usage == envelope["usage"]
    assert len(seen) == 1 and seen[0][1] == 15
    assert json.loads(seen[0][0].data)["text"]["format"]["strict"] is True
    assert json.loads((tmp_path / "api-response.json").read_text())["id"] == "resp_test"
    assert (tmp_path / "raw-response.json").read_text() == raw
    assert "test-secret-keep-out" not in "".join(p.read_text() for p in tmp_path.iterdir() if p.is_file())


def test_missing_key_or_invalid_schema_never_dispatches(tmp_path, monkeypatch):
    config = prepared(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        transport.OpenAIProductProvider(config).dispatch(SimpleNamespace(), tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    (tmp_path / "schema.json").write_text('{"type":"object","properties":{},"required":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="additionalProperties"):
        transport.OpenAIProductProvider(config).dispatch(SimpleNamespace(), tmp_path)
    assert not (tmp_path / "api-request.json").exists()


@pytest.mark.parametrize("envelope", [
    {"status": "incomplete", "output": [], "usage": {"input_tokens": 2}},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Cannot comply"}]}]},
    {"status": "completed", "output": [{"type": "function_call"}]},
])
def test_non_structured_response_is_retained_but_never_accepted(tmp_path, monkeypatch, envelope):
    config = prepared(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return json.dumps(envelope).encode("utf-8")

    monkeypatch.setattr(transport, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="no replay"):
        transport.OpenAIProductProvider(config).dispatch(SimpleNamespace(), tmp_path)
    assert json.loads((tmp_path / "api-response.json").read_text()) == envelope
    assert not (tmp_path / "raw-response.json").exists()


@pytest.mark.parametrize("failure", ["http", "disconnect"])
def test_transport_error_has_one_dispatch_and_no_raw_result(tmp_path, monkeypatch, failure):
    config = prepared(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    calls = []

    def failing(*args, **kwargs):
        calls.append(1)
        if failure == "http":
            raise HTTPError(transport.API_URL, 429, "busy", {}, BytesIO(b'{"error":"busy"}'))
        raise URLError("disconnected")

    monkeypatch.setattr(transport, "urlopen", failing)
    with pytest.raises((RuntimeError, TimeoutError), match="no transport retry|no replay"):
        transport.OpenAIProductProvider(config).dispatch(SimpleNamespace(), tmp_path)
    assert len(calls) == 1 and not (tmp_path / "raw-response.json").exists()
    assert (tmp_path / "api-error.json").exists() is (failure == "http")
