import json
from pathlib import Path

from app.schema_export import event_schema
from pipeline.events import Event, HealthPing, tenor_event_adapter

GENERATED_SCHEMA = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "events.schema.json"


def test_every_event_has_a_timestamp():
    for cls in Event.__subclasses__():
        assert "ts" in cls.model_fields, cls.__name__


def test_events_round_trip_through_the_union():
    ping = HealthPing(client_sent_ms=42)
    parsed = tenor_event_adapter.validate_json(ping.model_dump_json())
    assert parsed == ping


def test_frontend_types_are_up_to_date():
    """Fails when an event model changed but `npm run gen:types` wasn't re-run."""
    assert GENERATED_SCHEMA.exists(), "run `npm run gen:types` in frontend/"
    on_disk = json.loads(GENERATED_SCHEMA.read_text())
    assert on_disk == event_schema(), "event models changed: run `npm run gen:types` in frontend/"
