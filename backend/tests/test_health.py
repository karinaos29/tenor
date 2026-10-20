import json

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from pipeline import latency

client = TestClient(app)


def test_health_reports_missing_keys():
    body = client.get("/api/health").json()
    assert body["type"] == "health.status"
    assert body["services"] == {
        "transcription": False,
        "llm": False,
        "market_data": False,
        "email": False,
    }


def test_health_reports_configured_key_without_leaking_it(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")
    get_settings.cache_clear()
    res = client.get("/api/health")
    assert res.json()["services"]["llm"] is True
    assert "secret-value" not in res.text


def test_socket_sends_status_then_answers_pings():
    with client.websocket_connect("/ws/health") as ws:
        status = ws.receive_json()
        assert status["type"] == "health.status"
        assert "ts" in status

        ws.send_text(json.dumps({"type": "health.ping", "ts": status["ts"], "client_sent_ms": 123.5}))
        pong = ws.receive_json()
        assert pong["type"] == "health.pong"
        assert pong["client_sent_ms"] == 123.5
        assert pong["server_ms"] >= 0


def test_socket_ignores_invalid_messages():
    with client.websocket_connect("/ws/health") as ws:
        ws.receive_json()
        ws.send_text("not json")
        ws.send_text(json.dumps({"type": "unknown.event"}))
        ws.send_text(json.dumps({"type": "health.ping", "client_sent_ms": 1}))
        assert ws.receive_json()["type"] == "health.pong"


def test_ping_latency_is_logged():
    with client.websocket_connect("/ws/health") as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"type": "health.ping", "client_sent_ms": 1}))
        ws.receive_json()
    lines = latency.LOG_PATH.read_text().splitlines()
    entry = json.loads(lines[-1])
    assert entry["stage"] == "health.server"
    assert entry["ms"] >= 0
