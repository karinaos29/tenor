"""Hosting: the socket Origin check and the hosting settings."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings, get_settings
from app.main import app

client = TestClient(app)
VERCEL = "https://tenor.vercel.app"


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", f"{VERCEL}/, http://localhost:5173")
    get_settings.cache_clear()


def test_origins_are_trimmed_and_split():
    s = Settings(allowed_origins=f" {VERCEL}/ ,, http://localhost:5173 ")
    assert s.origins == [VERCEL, "http://localhost:5173"]


def test_no_origins_configured_means_local_development(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "")
    get_settings.cache_clear()
    with client.websocket_connect("/ws/health", headers={"origin": "https://anything.example"}) as ws:
        assert ws.receive_json()["type"] == "health.status"


@pytest.mark.usefixtures("hosted")
def test_sockets_accept_the_frontend_origin():
    with client.websocket_connect("/ws/health", headers={"origin": VERCEL}) as ws:
        assert ws.receive_json()["type"] == "health.status"


@pytest.mark.usefixtures("hosted")
@pytest.mark.parametrize("path", ["/ws/health", "/ws/call"])
def test_sockets_refuse_other_websites(path):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(path, headers={"origin": "https://other.example"}) as ws:
            ws.receive_json()
    assert closed.value.code == 1008


@pytest.mark.usefixtures("hosted")
def test_clients_without_an_origin_are_not_browsers_and_pass():
    with client.websocket_connect("/ws/health") as ws:
        assert ws.receive_json()["type"] == "health.status"
