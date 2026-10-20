import pytest

from app.config import get_settings
from pipeline import latency


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, request):
    """Keep tests off the real latency log and the developer's .env keys."""
    monkeypatch.setattr(latency, "LOG_PATH", tmp_path / "latency.jsonl")
    live = request.node.get_closest_marker("deepgram") is not None
    for key in ("DEEPGRAM_API_KEY", "GEMINI_API_KEY", "FINNHUB_API_KEY", "RESEND_API_KEY"):
        if live and key == "DEEPGRAM_API_KEY":
            continue  # live Deepgram tests use the developer's real key
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
