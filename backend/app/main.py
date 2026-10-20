"""FastAPI entry point. Run from backend/: `uv run uvicorn app.main:app --reload`."""

import logging
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import VERSION, get_settings
from pipeline.events import HealthPing, HealthPong, HealthStatus, ServiceStatus, tenor_event_adapter
from pipeline.latency import record

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tenor.app")

app = FastAPI(title="Tenor", version=VERSION)


def service_status() -> ServiceStatus:
    s = get_settings()
    return ServiceStatus(
        transcription=bool(s.deepgram_api_key),
        llm=bool(s.gemini_api_key),
        market_data=bool(s.finnhub_api_key),
        email=bool(s.resend_api_key),
    )


@app.get("/api/health")
def health() -> HealthStatus:
    return HealthStatus(version=VERSION, services=service_status())


@app.websocket("/ws/health")
async def health_socket(ws: WebSocket) -> None:
    """Sends HealthStatus on open, then answers each HealthPing with a HealthPong."""
    await ws.accept()
    await ws.send_text(health().model_dump_json())
    try:
        while True:
            raw = await ws.receive_text()
            start = time.perf_counter()
            try:
                event = tenor_event_adapter.validate_json(raw)
            except ValidationError:
                log.warning("health socket: ignored invalid message")
                continue
            if not isinstance(event, HealthPing):
                continue
            server_ms = (time.perf_counter() - start) * 1000
            pong = HealthPong(client_sent_ms=event.client_sent_ms, server_ms=server_ms)
            await ws.send_text(pong.model_dump_json())
            record("health.server", server_ms)
    except WebSocketDisconnect:
        pass
