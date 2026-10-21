"""Memo REST endpoints with a temporary store and no network."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from memo import email as em
from memo.builder import build_memo
from tests.m5_helpers import scam_record, tmp_store

client = TestClient(app)


@pytest.fixture
def store(tmp_path):
    old = app.state.store
    app.state.store = tmp_store(tmp_path)
    yield app.state.store
    app.state.store = old


@pytest.fixture
def no_network(monkeypatch):
    def factory(*a, **kw):
        raise AssertionError("no network allowed")

    monkeypatch.setattr(em.httpx, "AsyncClient", factory)


def save(store):
    store.start("c1", "2026-10-01T12:00:00+00:00", "replay", "scam")
    store.save_memo(build_memo(scam_record(), "sum", "template"))


def test_memo_unknown_then_ready(store):
    assert client.get("/api/calls/zzz/memo").json() == {"status": "unknown", "memo": None}
    store.start("c1", "2026-10-01T12:00:00+00:00", "replay", "scam")
    assert client.get("/api/calls/c1/memo").json() == {"status": "live", "memo": None}
    save(store)
    body = client.get("/api/calls/c1/memo").json()
    assert body["status"] == "ready" and body["memo"]["call_id"] == "c1"


def test_calls_list(store):
    assert client.get("/api/calls").json() == {"calls": []}
    save(store)
    calls = client.get("/api/calls").json()["calls"]
    assert [c["call_id"] for c in calls] == ["c1"] and calls[0]["status"] == "ready"


def test_email_defaults(monkeypatch):
    assert client.get("/api/email").json() == {"configured": False, "to": None}
    monkeypatch.setenv("MEMO_EMAIL_TO", "me@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    get_settings.cache_clear()
    assert client.get("/api/email").json() == {"configured": True, "to": "me@example.com"}


def test_email_memo_missing(store, no_network):
    r = client.post("/api/calls/nope/email", json={"to": "a@b.co"}).json()
    assert r["ok"] is False and "isn't ready" in r["message"]


def test_email_without_key(store, no_network):
    save(store)
    r = client.post("/api/calls/c1/email", json={"to": "a@b.co"}).json()
    assert r["ok"] is False and "no Resend key" in r["message"]
