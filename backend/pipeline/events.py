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


# --- Union of everything that crosses the wire --------------------------------

TenorEvent = Annotated[
    HealthStatus | HealthPing | HealthPong,
    Field(discriminator="type"),
]

tenor_event_adapter: TypeAdapter[TenorEvent] = TypeAdapter(TenorEvent)
