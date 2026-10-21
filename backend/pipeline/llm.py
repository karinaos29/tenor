"""Thin Gemini wrapper: structured output, timeout, fallback, and token logging.

The LLM extracts and explains; it never decides a verdict. Every call:
- returns a validated Pydantic object, or None on timeout/error/missing key (callers
  fall back to rules; nothing is surfaced as an error mid-call);
- logs latency and token counts (input, output, cached, thinking) to the latency log.
"""

import asyncio
import logging
import time
from typing import Literal, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from pipeline.latency import record

log = logging.getLogger("tenor.llm")

# Gemini treats the HTTP timeout as a server-side deadline and rejects anything under 10 s,
# so the real (shorter) budget is enforced client-side with asyncio.wait_for.
SERVER_DEADLINE_MS = 10_000

T = TypeVar("T", bound=BaseModel)
Thinking = Literal["minimal", "low", "medium", "high"]


class LlmClient:
    def __init__(self, api_key: str, model: str, *, thinking: Thinking = "minimal", timeout_s: float = 2.5) -> None:
        self.model = model
        self.thinking = thinking
        self.timeout_s = timeout_s
        self._client = (
            genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=SERVER_DEADLINE_MS))
            if api_key
            else None
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    async def generate(self, *, system: str, prompt: str, schema: type[T], stage: str, call_id: str = "") -> T | None:
        """Structured output, validated into `schema`."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel[self.thinking.upper()]),
            temperature=0,
        )
        return await self._call(config, prompt, stage, call_id, lambda text: schema.model_validate_json(text))

    async def generate_text(self, *, system: str, prompt: str, stage: str, call_id: str = "") -> str | None:
        """Plain text (e.g. a plain-words rewording)."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel[self.thinking.upper()]),
            temperature=0,
        )

        def parse(text: str) -> str:
            if not text.strip():
                raise ValueError("empty response")
            return text.strip()

        return await self._call(config, prompt, stage, call_id, parse)

    async def _call(self, config, prompt: str, stage: str, call_id: str, parse):  # noqa: ANN001, ANN202
        if self._client is None:
            return None
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(model=self.model, contents=prompt, config=config),
                timeout=self.timeout_s,  # the real budget; cancels the request
            )
            result = parse(response.text or "")
        except (TimeoutError, ValidationError, Exception) as e:  # noqa: BLE001 - any failure -> rules-only
            record(
                stage, (time.perf_counter() - started) * 1000, call_id=call_id, model=self.model,
                ok=False, error=type(e).__name__, detail=str(e)[:120],
            )  # fmt: skip
            log.warning("%s on %s failed (%s); continuing without it", stage, self.model, type(e).__name__)
            return None
        usage = response.usage_metadata
        record(
            stage,
            (time.perf_counter() - started) * 1000,
            call_id=call_id,
            model=self.model,
            ok=True,
            input_tokens=getattr(usage, "prompt_token_count", None) or 0,
            output_tokens=getattr(usage, "candidates_token_count", None) or 0,
            cached_tokens=getattr(usage, "cached_content_token_count", None) or 0,
            thinking_tokens=getattr(usage, "thoughts_token_count", None) or 0,
        )
        return result


class HedgedLlm:
    """Send the same request to several models at once; the first valid answer wins and the
    others are cancelled. Gemini latency swings per model from under 1 s to 30 s (measured
    2026-10-20/21), so one model is a single point of slowness. Tokens are tiny, so paying
    for two requests is cheap insurance. Same interface as LlmClient."""

    def __init__(self, clients: list[LlmClient]) -> None:
        self.clients = [c for c in clients if c.available]

    @property
    def available(self) -> bool:
        return bool(self.clients)

    async def generate(self, *, system: str, prompt: str, schema: type[T], stage: str, call_id: str = "") -> T | None:
        return await self._first([c.generate(system=system, prompt=prompt, schema=schema, stage=stage, call_id=call_id) for c in self.clients])

    async def generate_text(
        self, *, system: str, prompt: str, stage: str, call_id: str = "", accept=lambda _text: True  # noqa: ANN001
    ) -> str | None:
        calls = [c.generate_text(system=system, prompt=prompt, stage=stage, call_id=call_id) for c in self.clients]
        return await self._first(calls, accept)

    @staticmethod
    async def _first(calls, accept=lambda _r: True):  # noqa: ANN001, ANN205
        tasks = [asyncio.ensure_future(c) for c in calls]
        try:
            for done in asyncio.as_completed(tasks):
                result = await done
                if result is not None and accept(result):
                    return result
            return None
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def thinking_for(model: str) -> Thinking:
    """Flash-Lite models accept "minimal"; others (e.g. gemini-3.8-flash) start at "low" and
    reject "minimal" with HTTP 400 (seen 2026-10-21)."""
    return "minimal" if "flash-lite" in model else "low"


def fast_llm(api_key: str, models: str, timeout_s: float) -> HedgedLlm:
    """Build the hedged client from a comma-separated model list (TENOR_MODEL_FAST / _MEMO)."""
    names = [m.strip() for m in models.split(",") if m.strip()]
    return HedgedLlm([LlmClient(api_key, m, thinking=thinking_for(m), timeout_s=timeout_s) for m in names])
