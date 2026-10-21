"""MemoWriter on a real bus with fake LLMs and a temporary store."""

import asyncio

import pytest

from memo import writer as mw
from memo.writer import MemoWriter
from pipeline.bus import EventBus
from pipeline.events import (
    CallEnded, CallStarted, ClaimChecked, MemoReady, OfferUpdated, RiskUpdated, SpeakersUpdated,
    SuggestionsUpdated, TacticFlagged, UtteranceFinal,
)
from pipeline.llm import HedgedLlm, LlmClient
from tests.m3_helpers import latency_entries
from tests.m5_helpers import flag, scam_record, say, tmp_store, utt


class FakeHedged(HedgedLlm):
    def __init__(self, text, delay=0.0, available=True):
        self.text, self.delay, self._avail, self.calls = text, delay, available, []

    @property
    def available(self):
        return self._avail

    async def generate_text(self, *, system, prompt, stage, call_id="", accept=None):
        self.calls.append((prompt, accept))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.text


class FakeClient(LlmClient):
    def __init__(self, text, delay=0.0):
        self.text, self.delay, self.calls = text, delay, []

    @property
    def available(self):
        return True

    async def generate_text(self, *, system, prompt, stage, call_id=""):  # no `accept`
        self.calls.append(prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.text


def feed(bus, with_end=True):
    r = scam_record()
    bus.publish(CallStarted(call_id="c1", source="replay", replay_id="scam"))
    for u in r.utterances.values():
        bus.publish(UtteranceFinal(utterance=u))
    bus.publish(SpeakersUpdated(user_indices=[0], reason="first_turn", locked=False))
    bus.publish(OfferUpdated(offer=r.offer))
    for c in r.claims.values():
        bus.publish(ClaimChecked(claim=c))
    for f in r.flags:
        bus.publish(TacticFlagged(flag=f))
    s = list(r.say_this.values())
    bus.publish(SuggestionsUpdated(visible=s[:4], earlier=s[4:]))
    bus.publish(r.risk)
    if with_end:
        bus.publish(CallEnded(reason="replay_finished"))


def go(tmp_path, llm=None, timeout_s=5.0, store=True):
    bus = EventBus()
    st = tmp_store(tmp_path) if store else None
    w = MemoWriter(bus, st, llm, timeout_s=timeout_s)
    ready = bus.subscribe(MemoReady)
    feed(bus)

    async def main():
        memo = await asyncio.wait_for(w.run(), 10)
        return memo, ready

    memo, ready = asyncio.run(main())
    return memo, st, w, ready


def test_template_without_llm(tmp_path):
    memo, st, w, _ = go(tmp_path, None)
    assert memo.summary_wording == "template" and memo.call_id == "c1" and memo.replay_id == "scam"
    assert [s.id for s in memo.sections][0] == "glance"
    assert {u.id: u.speaker for u in memo.transcript}["u4"] == "user"  # roles from speakers.updated
    assert st.get("c1")[0] == "ready"


def test_unavailable_llm_is_ignored(tmp_path):
    llm = FakeHedged("x", available=False)
    memo, *_ = go(tmp_path, llm)
    assert memo.summary_wording == "template" and llm.calls == []


@pytest.mark.parametrize("make", [FakeHedged, FakeClient])
def test_llm_text_used_when_it_passes(tmp_path, make):
    text = "Daniel called about Kestrel Motors. One claim did not match the data."
    llm = make(text)
    memo, *_ = go(tmp_path, llm)
    assert memo.summary == text and memo.summary_wording == "gemini"
    if make is FakeHedged:
        assert llm.calls[0][1] is not None  # hedged gets the accept guard
        assert llm.calls[0][1](text) and not llm.calls[0][1]("It is safe")


@pytest.mark.parametrize("bad", [
    "The price is $9.99 a share.", "You could buy these.", "This looks safe to me.", "It is the official register.",
    "A scam call.", "   ", "",
])
def test_bad_llm_text_keeps_template(tmp_path, bad):
    memo, *_ = go(tmp_path, FakeHedged(bad))
    assert memo.summary_wording == "template" and memo.summary.startswith("Daniel from Harlow Capital")


def test_none_from_llm_keeps_template(tmp_path):
    memo, *_ = go(tmp_path, FakeHedged(None))
    assert memo.summary_wording == "template"


def test_llm_timeout_falls_back(tmp_path):
    memo, *_ = go(tmp_path, FakeHedged("Fine text.", delay=1.0), timeout_s=0.05)
    assert memo.summary_wording == "template"


def test_store_status_sequence(tmp_path, monkeypatch):
    seen = []
    from memo.store import MemoStore

    for name in ("start", "set_status", "save_memo"):
        orig = getattr(MemoStore, name)

        def wrap(self, *a, _o=orig, _n=name, **k):
            seen.append((_n, a[1] if _n == "set_status" else None))
            return _o(self, *a, **k)

        monkeypatch.setattr(MemoStore, name, wrap)
    go(tmp_path, None)
    assert seen == [("start", None), ("set_status", "writing"), ("save_memo", None)]


def test_builder_failure_marks_failed(tmp_path, monkeypatch):
    def boom(r):
        raise RuntimeError("bug")

    monkeypatch.setattr(mw, "sections", boom)
    memo, st, _, ready = go(tmp_path, None)
    assert memo is None and st.get("c1") == ("failed", None)
    assert ready._queue.empty()  # no MemoReady


def test_memo_ready_and_latency(tmp_path):
    memo, _, _, ready = go(tmp_path, None)
    evs = []
    while not ready._queue.empty():
        evs.append(ready._queue.get_nowait())
    assert [e.call_id for e in evs if e is not None] == ["c1"]
    rows = latency_entries("memo.write")
    assert len(rows) == 1 and rows[0]["call_id"] == "c1" and rows[0]["wording"] == "template"


def test_no_store_still_works(tmp_path):
    memo, st, *_ = go(tmp_path, None, store=False)
    assert memo is not None and st is None
