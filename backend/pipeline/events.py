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
    speaker_index: int = Field(
        description="Voice number: the diarized speaker from speech-to-text, or 100 + n for a second voice"
        " the labeler found inside speaker n by loudness"
    )
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
    """Which voices (`Utterance.speaker_index`) are the user. A list, because diarization
    can split one voice in two. Everyone else is the caller."""

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


# --- Understanding the call (M2) ---------------------------------------------------

EntityKind = Literal["ticker", "price", "percent", "quantity", "deadline", "firm", "person", "payment", "fee"]
# heard: said plainly; matched: resolved via a known list (e.g. "Kestrel" -> KSTL);
# unsure: e.g. spelled letters that match no known ticker.
Confidence = Literal["heard", "matched", "unsure"]


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    id: str
    kind: EntityKind
    value: str = Field(description="Normalized display value, e.g. 'KSTL', '$0.42', '10,000 shares'")
    text: str = Field(description="The words as they appear in the utterance text")
    number: float | None = None
    unit: str | None = None
    detail: str | None = Field(default=None, description="Extra context, e.g. the company name for a ticker")
    utterance_id: str
    speaker: Role
    t: float
    confidence: Confidence = "heard"


ClaimStatus = Literal["checking", "verified", "false", "not_found", "unverifiable"]


class Claim(BaseModel):
    """A factual statement by the caller. The LLM may extract it; only data decides its status (M3)."""

    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    id: str
    text: str
    metric: Literal["price_change", "return", "guarantee", "event", "fee", "price", "other"]
    claimed_value: float | None = None
    unit: str | None = None
    period: str | None = None
    subject: str | None = Field(default=None, description="Ticker or company the claim is about")
    utterance_id: str
    status: ClaimStatus = "checking"
    actual_value: float | None = None
    source: str | None = None
    checked_in_ms: float | None = None
    note: str | None = Field(default=None, description="Plain-words detail of the check, e.g. 'last 13 weeks'")


class Term(BaseModel):
    """One term of the offer and where it came from."""

    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    display: str
    number: float | None = None
    said: str = Field(description="Words from the transcript (empty for computed terms)")
    utterance_id: str | None = None
    t: float | None = None
    confidence: Confidence = "heard"
    source: Literal["call", "computed"] = "call"


OfferField = Literal["caller_name", "firm", "instrument", "price", "quantity", "total", "fees", "deadline", "payment"]


class TermChange(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    field: OfferField
    old: Term
    new: Term


class Offer(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    caller_name: Term | None = None
    firm: Term | None = None
    instrument: Term | None = None
    price: Term | None = None
    quantity: Term | None = None
    total: Term | None = None
    fees: Term | None = None
    deadline: Term | None = None
    payment: Term | None = None
    history: list[TermChange] = Field(default_factory=list)


class EntityDetected(Event):
    type: Literal["entity.detected"] = "entity.detected"
    entity: Entity


class ClaimExtracted(Event):
    type: Literal["claim.extracted"] = "claim.extracted"
    claim: Claim


class OfferUpdated(Event):
    type: Literal["offer.updated"] = "offer.updated"
    offer: Offer


class OfferChanged(Event):
    """A term the caller already stated changed (e.g. 5,000 -> 10,000 shares)."""

    type: Literal["offer.changed"] = "offer.changed"
    change: TermChange


# --- Verifying (M3) ---------------------------------------------------------------


class ClaimChecked(Event):
    """A claim with its verdict. The verdict comes from data and arithmetic, never from the LLM."""

    type: Literal["claim.checked"] = "claim.checked"
    claim: Claim


class Fact(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    label: str
    value: str
    source: str


class ResearchItem(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    id: str
    topic: Literal["ticker", "firm"]
    subject: str = Field(description="Ticker or firm name")
    title: str
    status: Literal["prefetching", "ready", "failed"]
    summary: str = ""
    facts: list[Fact] = Field(default_factory=list)
    source: str = ""
    checked_at: datetime | None = None
    wording: Literal["template", "gemini"] = "template"
    finding: Literal["registered", "not_registered"] | None = Field(
        default=None, description="For firms: the register result, so rules don't parse text"
    )


class ResearchReady(Event):
    """A research item started (prefetching) or finished (ready / failed)."""

    type: Literal["research.ready"] = "research.ready"
    item: ResearchItem


class Suggestion(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    id: str
    kind: Literal["say_this", "research"]
    title: str
    text: str = Field(description="For say_this: the words to say, first person")
    priority: int
    status: Literal["prefetching", "ready"]
    reason: str = Field(description="Why Tenor suggests it, in plain words")
    source: str = ""
    checked_at: datetime | None = None
    expires_at: datetime | None = None


class SuggestionsUpdated(Event):
    """At most four visible suggestions, highest priority first; the rest are kept for the memo."""

    type: Literal["suggestions.updated"] = "suggestions.updated"
    visible: list[Suggestion]
    earlier: list[Suggestion]


class RiskReason(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)

    label: str
    points: int


RiskLevel = Literal["low", "medium", "high", "critical"]


class RiskUpdated(Event):
    type: Literal["risk.updated"] = "risk.updated"
    score: int
    level: RiskLevel
    reasons: list[RiskReason]


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


class UtteranceProgress(Event):
    """The finalized words so far of a turn still in progress (no interim words). Lets the
    extractor act on a completed sentence without waiting for the whole turn to end."""

    type: Literal["utterance.progress"] = "utterance.progress"
    utterance: Utterance


class UtterancesClosed(Event):
    """The labeler has finalized its last utterance (end-of-call chain, stage 2)."""

    type: Literal["utterances.closed"] = "utterances.closed"


class OfferClosed(Event):
    """The offer tracker has published its last update (end-of-call chain)."""

    type: Literal["offer.closed"] = "offer.closed"


class ChecksClosed(Event):
    """The claim checker has finished its pending checks (end-of-call chain)."""

    type: Literal["checks.closed"] = "checks.closed"


class ResearchClosed(Event):
    """The research agent has finished its pending work (end-of-call chain)."""

    type: Literal["research.closed"] = "research.closed"


class EntitiesClosed(Event):
    """The extractor has finished, including pending LLM calls (end-of-call chain, stage 3)."""

    type: Literal["entities.closed"] = "entities.closed"


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
    | CallEnded
    | OfferUpdated
    | OfferChanged
    | ClaimChecked
    | ResearchReady
    | SuggestionsUpdated
    | RiskUpdated,
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
