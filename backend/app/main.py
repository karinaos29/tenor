"""FastAPI entry point. Run from backend/: `uv run uvicorn app.main:app --reload`."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import logging
import re
import time
import wave
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.config import VERSION, get_settings
from audio.sources import AudioSource, FileSource, MicSource
from pipeline.events import (
    CallMemoResponse,
    EmailDefaults,
    EmailRequest,
    EmailResult,
    SavedCallList,
    EvalReport,
    EvalResponse,
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
from pipeline.llm import fast_llm
from pipeline.session import CallSession
from pipeline.transcriber import DeepgramTranscriber
from detector.classifier import TacticClassifier
from memo.email import send_memo
from memo.store import DEFAULT_PATH, MemoStore
from providers.catalog import default_catalog
from providers.market import FinnhubProvider, FixtureProvider, RoutedMarketData

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tenor.app")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Loading the embedding model takes a few seconds (and downloads it once); do it off the loop.
    app.state.classifier = await asyncio.to_thread(TacticClassifier.load_default)
    yield


app = FastAPI(title="Tenor", version=VERSION, lifespan=lifespan)
app.state.classifier = None  # set at startup; None = tactic rules only

# Hosted, the frontend (Vercel) and this API (Railway) are different origins.
# Allow any Vercel deployment (*.vercel.app) plus any explicitly configured origins.
origins = get_settings().origins or ["https://tenor-ai.vercel.app"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Swappable in tests (fake transcriber, temp replay folder).
app.state.transcriber_factory = lambda: DeepgramTranscriber(get_settings().deepgram_api_key)
app.state.llm_factory = lambda: fast_llm(
    get_settings().gemini_api_key, get_settings().tenor_model_fast, get_settings().tenor_llm_timeout_s
)
app.state.market_factory = lambda: RoutedMarketData(
    FixtureProvider(default_catalog()),
    FinnhubProvider(get_settings().finnhub_api_key, timeout_s=get_settings().finnhub_timeout_s),
)
app.state.memo_llm_factory = lambda: fast_llm(get_settings().gemini_api_key, get_settings().tenor_model_memo, get_settings().tenor_memo_timeout_s)
_data_dir = get_settings().tenor_data_dir
app.state.store = MemoStore(Path(_data_dir) / "tenor.sqlite" if _data_dir else DEFAULT_PATH)
app.state.background: set[asyncio.Task] = set()  # memo writers outlive their call socket
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


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "Tenor", "version": VERSION}


@app.get("/health")
@app.get("/api/health")
def health() -> HealthStatus:
    return HealthStatus(version=VERSION, services=service_status())


def origin_allowed(ws: WebSocket) -> bool:
    """CORS doesn't cover WebSockets, so the sockets check the browser's Origin themselves.
    It stops other websites from using this backend (and its API keys) from a visitor's
    browser; it can't stop a script that fakes the header."""
    allowed = get_settings().origins
    if not allowed or "*" in allowed:
        return True
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    clean = origin.rstrip("/")
    if clean in allowed:
        return True
    # Allow any Vercel domain (production, preview, branch deployments)
    if clean.endswith(".vercel.app"):
        return True
    return False


@app.websocket("/ws/health")
async def health_socket(ws: WebSocket) -> None:
    """Sends HealthStatus on open, then answers each HealthPing with a HealthPong."""
    if not origin_allowed(ws):
        await ws.close(code=1008)
        return
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


# --- Evaluation ------------------------------------------------------------------------

app.state.eval_results = Path(__file__).resolve().parents[2] / "eval" / "results" / "latest.json"


@app.get("/api/eval")
def eval_report() -> EvalResponse:
    """The latest evaluation run (eval/run_eval.py), or null if none has been run."""
    path: Path = app.state.eval_results
    if not path.exists():
        return EvalResponse(report=None)
    try:
        return EvalResponse(report=EvalReport.model_validate_json(path.read_text()))
    except ValueError:
        log.warning("eval results at %s are unreadable", path)
        return EvalResponse(report=None)


# --- Calls and memos -------------------------------------------------------------------


@app.get("/api/calls")
def saved_calls() -> SavedCallList:
    return SavedCallList(calls=app.state.store.recent())


@app.get("/api/calls/{call_id}/memo")
def call_memo(call_id: str) -> CallMemoResponse:
    status, memo = app.state.store.get(call_id)
    return CallMemoResponse(status=status if status in ("live", "writing", "ready", "failed") else "unknown", memo=memo)  # type: ignore[arg-type]


@app.get("/api/email")
def email_defaults() -> EmailDefaults:
    s = get_settings()
    return EmailDefaults(configured=bool(s.resend_api_key), to=s.memo_email_to or None)


@app.post("/api/calls/{call_id}/email")
async def email_memo(call_id: str, request: EmailRequest) -> EmailResult:
    _, memo = app.state.store.get(call_id)
    if memo is None:
        return EmailResult(ok=False, message="The memo isn't ready yet.")
    s = get_settings()
    return await send_memo(memo, request.to.strip(), api_key=s.resend_api_key, sender=s.memo_email_from)


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
    if not origin_allowed(ws):
        await ws.close(code=1008)
        return
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
        market=app.state.market_factory(),
        wording_timeout=get_settings().tenor_wording_timeout_s,
        classifier=app.state.classifier,
        store=app.state.store,
        memo_llm=app.state.memo_llm_factory(),
        memo_timeout=get_settings().tenor_memo_timeout_s,
    )
    log.info("call %s started (%s)", session.id, first.source)
    run = asyncio.create_task(session.run())
    receive = asyncio.create_task(_receive_call_messages(ws, session, source))
    try:
        await run
    finally:
        if session.memo_task is not None:
            app.state.background.add(session.memo_task)
            session.memo_task.add_done_callback(app.state.background.discard)
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
