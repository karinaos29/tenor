"""FastAPI entry point. Run from backend/: `uv run uvicorn app.main:app --reload`."""

import asyncio
import json
import logging
import re
import time
import wave
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import VERSION, get_settings
from audio.sources import AudioSource, FileSource, MicSource
from pipeline.events import (
    CallEnded,
    CallStart,
    CallStop,
    HealthPing,
    HealthPong,
    HealthStatus,
    ReplayInfo,
    ReplayList,
    ServiceStatus,
    SpeakersSwap,
    client_event_adapter,
)
from pipeline.latency import record
from pipeline.llm import LlmClient
from pipeline.session import CallSession
from pipeline.transcriber import DeepgramTranscriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tenor.app")

app = FastAPI(title="Tenor", version=VERSION)

# Swappable in tests (fake transcriber, temp replay folder).
app.state.transcriber_factory = lambda: DeepgramTranscriber(get_settings().deepgram_api_key)
app.state.llm_factory = lambda: LlmClient(
    get_settings().gemini_api_key, get_settings().tenor_model_fast, timeout_s=get_settings().tenor_llm_timeout_s
)
app.state.replay_dir = Path(__file__).resolve().parents[1] / "fixtures" / "calls"

REPLAY_ID = re.compile(r"^[a-z0-9_]+$")
CALL_START_TIMEOUT = 5.0


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
                event = client_event_adapter.validate_json(raw)
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


# --- Replays -------------------------------------------------------------------------


def _replay_titles(folder: Path) -> dict[str, str]:
    catalog = folder / "catalog.json"
    return json.loads(catalog.read_text()) if catalog.exists() else {}


@app.get("/api/replays")
def replays() -> ReplayList:
    folder: Path = app.state.replay_dir
    titles = _replay_titles(folder)
    items = []
    for wav in sorted(folder.glob("*.wav")):
        try:
            duration = FileSource(wav).duration_s
        except (ValueError, OSError, EOFError, wave.Error):
            log.warning("skipping unusable replay file %s", wav.name)
            continue
        items.append(ReplayInfo(id=wav.stem, title=titles.get(wav.stem, wav.stem), duration_s=round(duration, 1)))
    return ReplayList(replays=items)


def make_source(start: CallStart) -> AudioSource:
    if start.source == "mic":
        return MicSource()
    replay_id = start.replay_id or ""
    path = app.state.replay_dir / f"{replay_id}.wav"
    if not REPLAY_ID.match(replay_id) or not path.exists():
        raise ValueError(f"unknown replay: {replay_id!r}")
    return FileSource(path)


# --- Call socket ---------------------------------------------------------------------


@app.websocket("/ws/call")
async def call_socket(ws: WebSocket) -> None:
    """One call per connection. First message: call.start. Mic audio arrives as binary
    frames; call.stop and speakers.swap as JSON. UI events stream back as JSON."""
    await ws.accept()
    try:
        first = client_event_adapter.validate_json(await asyncio.wait_for(ws.receive_text(), CALL_START_TIMEOUT))
        if not isinstance(first, CallStart):
            raise ValueError("first message must be call.start")
        source = make_source(first)
    except WebSocketDisconnect:
        return
    except (TimeoutError, ValidationError, ValueError, KeyError) as e:
        log.warning("call socket: bad start: %s", e)
        await _close_with(ws, CallEnded(reason="error", detail="bad_start"))
        return

    session = CallSession(
        source,
        app.state.transcriber_factory(),
        send=lambda event: ws.send_text(event.model_dump_json()),
        replay_id=first.replay_id,
        llm=app.state.llm_factory(),
    )
    log.info("call %s started (%s)", session.id, first.source)
    run = asyncio.create_task(session.run())
    receive = asyncio.create_task(_receive_call_messages(ws, session, source))
    try:
        await run
    finally:
        receive.cancel()
        await asyncio.gather(receive, return_exceptions=True)
        log.info("call %s ended", session.id)
        try:
            await ws.close()
        except RuntimeError:
            pass  # already closed by the client


async def _receive_call_messages(ws: WebSocket, session: CallSession, source: AudioSource) -> None:
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            session.stop()
            return
        if (data := message.get("bytes")) is not None:
            if isinstance(source, MicSource):
                source.push(data)
            continue
        try:
            event = client_event_adapter.validate_json(message.get("text") or "")
        except ValidationError:
            log.warning("call %s: ignored invalid message", session.id)
            continue
        if isinstance(event, CallStop):
            session.stop()
        elif isinstance(event, SpeakersSwap):
            session.swap_speakers()


async def _close_with(ws: WebSocket, event: CallEnded) -> None:
    try:
        await ws.send_text(event.model_dump_json())
        await ws.close()
    except (RuntimeError, WebSocketDisconnect):
        pass
