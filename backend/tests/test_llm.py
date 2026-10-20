"""LlmClient: no-key fallback, structured output, timeout, and latency logging."""

import asyncio
import json
from types import SimpleNamespace

from pydantic import BaseModel

from pipeline import latency
from pipeline.llm import LlmClient


class Answer(BaseModel):
    word: str
    n: int


def make(timeout_s: float = 2.5) -> LlmClient:
    return LlmClient("fake-key", "fake-model", timeout_s=timeout_s)


def patch(client: LlmClient, monkeypatch, fake) -> None:
    monkeypatch.setattr(client._client.aio.models, "generate_content", fake)


def call(client: LlmClient):
    return asyncio.run(client.generate(system="s", prompt="p", schema=Answer, stage="llm.extract", call_id="c1"))


def log_entries() -> list[dict]:
    path = latency.LOG_PATH
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_no_key_is_unavailable_and_returns_none_without_network():
    client = LlmClient("", "fake-model")
    assert client.available is False and client._client is None
    assert call(client) is None
    assert log_entries() == []


def test_with_key_is_available():
    assert make().available is True


def test_success_returns_validated_object_and_logs_tokens(monkeypatch):
    client = make()
    seen = {}

    async def fake(*, model, contents, config):
        seen.update(model=model, contents=contents, config=config)
        usage = SimpleNamespace(
            prompt_token_count=120, candidates_token_count=17, cached_content_token_count=5, thoughts_token_count=3
        )
        return SimpleNamespace(text='{"word": "hi", "n": 2}', usage_metadata=usage)

    patch(client, monkeypatch, fake)
    out = call(client)
    assert out == Answer(word="hi", n=2)
    assert seen["model"] == "fake-model" and seen["contents"] == "p"
    (entry,) = log_entries()
    assert entry["stage"] == "llm.extract" and entry["ok"] is True and entry["call_id"] == "c1"
    assert entry["model"] == "fake-model"
    assert (entry["input_tokens"], entry["output_tokens"]) == (120, 17)
    assert (entry["cached_tokens"], entry["thinking_tokens"]) == (5, 3)
    assert entry["ms"] >= 0


def test_success_without_usage_logs_zero_tokens(monkeypatch):
    client = make()

    async def fake(**_):
        return SimpleNamespace(text='{"word": "hi", "n": 2}', usage_metadata=None)

    patch(client, monkeypatch, fake)
    assert call(client) == Answer(word="hi", n=2)
    (entry,) = log_entries()
    assert entry["input_tokens"] == 0 and entry["output_tokens"] == 0


def test_timeout_returns_none_and_logs_failure(monkeypatch):
    client = make(timeout_s=0.05)
    cancelled = []

    async def slow(**_):
        try:
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    patch(client, monkeypatch, slow)
    assert call(client) is None
    assert cancelled == [True]  # the request is actually cancelled
    (entry,) = log_entries()
    assert entry["ok"] is False and entry["error"] == "TimeoutError" and entry["stage"] == "llm.extract"
    assert entry["ms"] < 1000


def test_invalid_json_returns_none(monkeypatch):
    client = make()

    async def fake(**_):
        return SimpleNamespace(text="not json at all", usage_metadata=None)

    patch(client, monkeypatch, fake)
    assert call(client) is None
    (entry,) = log_entries()
    assert entry["ok"] is False and entry["error"] == "ValidationError"


def test_schema_mismatch_returns_none(monkeypatch):
    client = make()

    async def fake(**_):
        return SimpleNamespace(text='{"word": "hi"}', usage_metadata=None)

    patch(client, monkeypatch, fake)
    assert call(client) is None
    assert log_entries()[0]["ok"] is False


def test_empty_response_text_returns_none(monkeypatch):
    client = make()

    async def fake(**_):
        return SimpleNamespace(text=None, usage_metadata=None)

    patch(client, monkeypatch, fake)
    assert call(client) is None


def test_exception_returns_none_and_logs_type(monkeypatch):
    client = make()

    async def boom(**_):
        raise RuntimeError("503")

    patch(client, monkeypatch, boom)
    assert call(client) is None
    (entry,) = log_entries()
    assert entry["ok"] is False and entry["error"] == "RuntimeError"
