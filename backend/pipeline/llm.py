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
        if self._client is None:
            return None
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel[self.thinking.upper()]),
            temperature=0,
        )
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(model=self.model, contents=prompt, config=config),
                timeout=self.timeout_s,  # the real budget; cancels the request
            )
            result = schema.model_validate_json(response.text or "")
        except (TimeoutError, ValidationError, Exception) as e:  # noqa: BLE001 - any failure -> rules-only
            record(stage, (time.perf_counter() - started) * 1000, call_id=call_id, model=self.model, ok=False, error=type(e).__name__)
            log.warning("%s failed (%s); continuing without the LLM", stage, type(e).__name__)
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
