"""HedgedLlm: first acceptable answer wins, the rest are cancelled; fast_llm model list."""

import asyncio

from pipeline.llm import HedgedLlm, LlmClient, fast_llm


class Stub(LlmClient):
    """An LlmClient that never touches the network: answers `text` after `delay`."""

    def __init__(self, text, delay=0.0, name="m"):
        super().__init__("key", name)
        self.text, self.delay = text, delay
        self.started = self.finished = self.cancelled = False

    async def generate_text(self, *, system, prompt, stage, call_id=""):
        self.started = True
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.finished = True
        return self.text


def text(h, **kw):
    return asyncio.run(h.generate_text(system="s", prompt="p", stage="llm.test", **kw))


def test_first_non_none_result_wins_and_slower_is_cancelled():
    fast, slow = Stub("fast", 0.01), Stub("slow", 5.0)

    async def main():
        return await HedgedLlm([slow, fast]).generate_text(system="s", prompt="p", stage="x")

    assert asyncio.run(main()) == "fast"
    assert slow.started and slow.cancelled and not slow.finished


def test_falls_back_to_second_when_first_returns_none():
    assert text(HedgedLlm([Stub(None, 0.0), Stub("second", 0.05)])) == "second"


def test_all_none_returns_none():
    assert text(HedgedLlm([Stub(None), Stub(None, 0.01)])) is None


def test_accept_skips_a_result_that_fails_it():
    h = HedgedLlm([Stub("bad 99%", 0.0), Stub("good", 0.05)])
    assert text(h, accept=lambda t: "99" not in t) == "good"


def test_accept_rejecting_everything_gives_none():
    assert text(HedgedLlm([Stub("a"), Stub("b")]), accept=lambda t: False) is None


def test_available_false_without_any_key():
    h = HedgedLlm([LlmClient("", "m1"), LlmClient("", "m2")])
    assert h.available is False and h.clients == []
    assert text(h) is None


def test_available_true_if_any_client_has_a_key_and_keyless_are_dropped():
    h = HedgedLlm([LlmClient("", "m1"), LlmClient("k", "m2")])
    assert h.available is True and [c.model for c in h.clients] == ["m2"]


def test_fast_llm_parses_comma_separated_models():
    h = fast_llm("key", "model-a, model-b ,,model-c", 1.5)
    assert [c.model for c in h.clients] == ["model-a", "model-b", "model-c"]
    assert all(c.timeout_s == 1.5 for c in h.clients)


def test_fast_llm_without_key_is_unavailable():
    assert fast_llm("", "a,b", 2.0).available is False
