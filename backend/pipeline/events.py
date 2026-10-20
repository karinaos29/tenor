"""Typed events. Every message on the bus or over a WebSocket is one of these.

Rules (see CLAUDE.md):
- Every event is a Pydantic model with a timestamp.
- TypeScript types are generated from these models (`npm run gen:types` in
  frontend/); never hand-write duplicates on the frontend.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


def utc_now() -> datetime:
    return datetime.now(UTC)


class Event(BaseModel):
    """Base for all events. `type` is the discriminator, `ts` is when it was created."""

    model_config = ConfigDict(
        frozen=True,
        # Fields with defaults are always present once serialized, so mark them
        # required in the generated TypeScript types.
        json_schema_serialization_defaults_required=True,
    )

    ts: datetime = Field(default_factory=utc_now)


# --- Health check (M0) -------------------------------------------------------


class ServiceStatus(BaseModel):
    """Whether each external service has a key configured. Never carries the key."""

    transcription: bool
    llm: bool
    market_data: bool
    email: bool


class HealthStatus(Event):
    """Server -> client, sent once when the health socket opens."""

    type: Literal["health.status"] = "health.status"
    version: str
    services: ServiceStatus


class HealthPing(Event):
    """Client -> server. `client_sent_ms` is the client's clock, echoed back."""

    type: Literal["health.ping"] = "health.ping"
    client_sent_ms: float


class HealthPong(Event):
    """Server -> client reply to a ping; the client computes round-trip time."""

    type: Literal["health.pong"] = "health.pong"
    client_sent_ms: float
    server_ms: float = Field(description="Server time spent handling the ping, in ms")


# --- Call (M1) -------------------------------------------------------------------

Role = Literal["caller", "user"]
AudioSourceKind = Literal["mic", "replay"]


class Utterance(BaseModel):
    """One speaker turn. Times are seconds from the start of the call."""

    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    id: str
    speaker: Role = Field(description="Role when the utterance was emitted; the UI relabels from speakers.updated")
    speaker_index: int = Field(description="Diarized speaker number from speech-to-text")
    text: str
    t_start: float
    t_end: float
    is_final: bool


class CallStart(Event):
    """Client -> server, first message on /ws/call."""

    type: Literal["call.start"] = "call.start"
    source: AudioSourceKind
    replay_id: str | None = None


class CallStop(Event):
    """Client -> server: the user hung up / pressed End call."""

    type: Literal["call.stop"] = "call.stop"


class SpeakersSwap(Event):
    """Client -> server: the user says the You/Caller labels are the wrong way round."""

    type: Literal["speakers.swap"] = "speakers.swap"


class CallStarted(Event):
    type: Literal["call.started"] = "call.started"
    call_id: str
    source: AudioSourceKind
    replay_id: str | None = None


class UtterancePartial(Event):
    """Words so far in the current turn; replaced by later partials and finally by utterance.final."""

    type: Literal["utterance.partial"] = "utterance.partial"
    utterance: Utterance


class UtteranceFinal(Event):
    type: Literal["utterance.final"] = "utterance.final"
    utterance: Utterance


class SpeakersUpdated(Event):
    """Which diarized speakers are the user (diarization can split one voice in two).
    Everyone else is the caller."""

    type: Literal["speakers.updated"] = "speakers.updated"
    user_indices: list[int]
    reason: Literal["first_turn", "loudness", "manual"]
    locked: bool = Field(description="True after a manual swap: automatic relabeling stops")


class TranscriberStatus(Event):
    type: Literal["transcriber.status"] = "transcriber.status"
    state: Literal["connecting", "live", "reconnecting", "unavailable"]
    detail: str = ""


class CallEnded(Event):
    type: Literal["call.ended"] = "call.ended"
    reason: Literal["user", "replay_finished", "error"]
    detail: str = ""


# --- Bus-internal events (never sent to the browser) ------------------------------


class AudioLevel(Event):
    """Loudness of one 80 ms frame. `t` is the frame start, seconds from call start."""

    type: Literal["audio.level"] = "audio.level"
    t: float
    dbfs: float


class Word(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    start: float
    end: float
    speaker: int
    confidence: float


class TranscriptSegment(Event):
    """One speech-to-text result, normalized. Times are seconds from call start."""

    type: Literal["transcript.segment"] = "transcript.segment"
    words: list[Word]
    is_final: bool
    speech_final: bool
    start: float
    end: float


class TranscriptUtteranceEnd(Event):
    """Speech-to-text detected a gap after the last finalized word."""

    type: Literal["transcript.utterance_end"] = "transcript.utterance_end"
    last_word_end: float


class TranscriptClosed(Event):
    """The transcriber has flushed everything; no more segments will come."""

    type: Literal["transcript.closed"] = "transcript.closed"


# --- Unions -------------------------------------------------------------------------

# Everything that crosses a WebSocket. TypeScript types are generated from this.
TenorEvent = Annotated[
    HealthStatus
    | HealthPing
    | HealthPong
    | CallStart
    | CallStop
    | SpeakersSwap
    | CallStarted
    | UtterancePartial
    | UtteranceFinal
    | SpeakersUpdated
    | TranscriberStatus
    | CallEnded,
    Field(discriminator="type"),
]

# What a browser is allowed to send. Incoming messages are validated against this.
ClientEvent = Annotated[
    HealthPing | CallStart | CallStop | SpeakersSwap,
    Field(discriminator="type"),
]

tenor_event_adapter: TypeAdapter[TenorEvent] = TypeAdapter(TenorEvent)
client_event_adapter: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)


# --- REST payloads (generated into TypeScript too, not events) ----------------------


class ReplayInfo(BaseModel):
    id: str
    title: str
    duration_s: float


class ReplayList(BaseModel):
    replays: list[ReplayInfo]


REST_MODELS: list[type[BaseModel]] = [ReplayList]
