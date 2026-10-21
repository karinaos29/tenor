"""memo/email.py with httpx mocked. No real request is ever made."""

import asyncio
import json

import httpx
import pytest

from memo import email as em
from memo.builder import build_memo
from memo.email import render_html, render_text, send_memo
from pipeline.events import MemoItem, MemoSection
from tests.m3_helpers import latency_entries
from tests.m5_helpers import scam_record


@pytest.fixture
def memo():
    return build_memo(scam_record(), "A summary.", "template")


@pytest.fixture
def requests_seen(monkeypatch):
    class Seen(list):
        pass

    seen = Seen()
    state = {"handler": lambda req: httpx.Response(200, json={"id": "em_1"})}

    def handler(req):
        seen.append(req)
        return state["handler"](req)

    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(em.httpx, "AsyncClient", factory)
    seen.state = state
    return seen


def send(memo, to="e@example.com", key="re_test"):
    return asyncio.run(send_memo(memo, to, api_key=key, sender="Tenor <a@b.c>"))


def test_success(memo, requests_seen):
    res = send(memo)
    assert res.ok and res.id == "em_1" and "e@example.com" in res.message
    req = requests_seen[0]
    assert req.headers["Authorization"] == "Bearer re_test"
    body = json.loads(req.content)
    assert body["from"] == "Tenor <a@b.c>" and body["to"] == ["e@example.com"]
    assert body["subject"] == f"Tenor memo: {memo.headline}"
    assert "<h1" in body["html"] and body["text"].startswith(memo.headline)
    assert latency_entries("email.send")[-1]["ok"] is True


def test_idempotency_key(memo, requests_seen):
    send(memo)
    send(memo)
    send(memo, to="other@example.com")
    k = [r.headers["Idempotency-Key"] for r in requests_seen]
    assert k[0] == k[1] != k[2]


def test_4xx(memo, requests_seen):
    requests_seen.state["handler"] = lambda req: httpx.Response(422, text="bad")
    res = send(memo)
    assert not res.ok and "refused" in res.message and "422" in res.message
    assert latency_entries("email.send")[-1]["ok"] is False


def test_network_error(memo, requests_seen):
    def boom(req):
        raise httpx.ConnectError("down")

    requests_seen.state["handler"] = boom
    res = send(memo)
    assert not res.ok and "Couldn't reach" in res.message
    assert latency_entries("email.send")[-1]["ok"] is False


def test_no_key_and_bad_address_make_no_request(memo, requests_seen):
    r1 = send(memo, key="")
    r2 = send(memo, to="not-an-address")
    r3 = send(memo, to="a" * 260 + "@x.com")
    assert not r1.ok and "no Resend key" in r1.message
    assert not r2.ok and "doesn't look right" in r2.message and not r3.ok
    assert requests_seen == []


def test_render_escapes_and_includes_titles_and_times(memo):
    evil = memo.model_copy(update={
        "headline": "<b>Hi</b>",
        "sections": [MemoSection(id="x", title="Sec <i>", items=[MemoItem(text="a & b <script>", detail="<d>", t=65.0)], empty="e")],
    })
    h = render_html(evil)
    assert "<script>" not in h and "&lt;script&gt;" in h and "a &amp; b" in h and "&lt;b&gt;Hi" in h and "at 1:05" in h
    t = render_text(evil)
    assert "SEC <I>" in t and "[1:05]" in t
    full = render_text(memo)
    for s in memo.sections:
        assert s.title.upper() in full
    assert all(s.title in render_html(memo) for s in memo.sections)
