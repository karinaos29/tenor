import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.fakes import FakeTranscriber, pcm, results, write_wav

client = TestClient(app)


@pytest.fixture
def replay_dir(tmp_path):
    """Temp replay folder + fake transcriber wired into the app; restored afterwards."""
    old_dir, old_factory = app.state.replay_dir, app.state.transcriber_factory
    folder = tmp_path / "calls"
    folder.mkdir()
    app.state.replay_dir = folder
    app.state.transcriber_factory = lambda: FakeTranscriber()
    yield folder
    app.state.replay_dir, app.state.transcriber_factory = old_dir, old_factory


def use_script(script: dict[int, list[dict]]) -> None:
    app.state.transcriber_factory = lambda: FakeTranscriber(script)


def receive_until(ws, stop_type: str, limit: int = 100) -> list[dict]:
    got = []
    for _ in range(limit):
        msg = json.loads(ws.receive_text())
        got.append(msg)
        if msg["type"] == stop_type:
            return got
    raise AssertionError(f"never saw {stop_type}: {[m['type'] for m in got]}")


def types(msgs: list[dict]) -> list[str]:
    return [m["type"] for m in msgs]


HELLO = [("Hello", 0.0, 0.3, 0), ("Eszter", 0.35, 0.7, 0)]


# --- /api/replays -----------------------------------------------------------------------


def test_replays_lists_wavs_with_catalog_titles_and_skips_bad(replay_dir):
    write_wav(replay_dir / "alpha.wav", 0.5)
    write_wav(replay_dir / "beta.wav", 1.0)
    write_wav(replay_dir / "narrow.wav", 0.5, rate=8000)
    (replay_dir / "catalog.json").write_text(json.dumps({"alpha": "Alpha call"}))
    body = client.get("/api/replays").json()
    assert body["replays"] == [
        {"id": "alpha", "title": "Alpha call", "duration_s": 0.5},
        {"id": "beta", "title": "beta", "duration_s": 1.0},
    ]


def test_replays_without_catalog_uses_ids(replay_dir):
    write_wav(replay_dir / "only.wav", 0.4)
    assert client.get("/api/replays").json()["replays"][0]["title"] == "only"


def test_replays_skips_corrupt_wav(replay_dir):
    write_wav(replay_dir / "ok.wav", 0.4)
    (replay_dir / "junk.wav").write_bytes(b"this is not a wav file at all")
    ids = [r["id"] for r in client.get("/api/replays").json()["replays"]]
    assert ids == ["ok"]


# --- replay call --------------------------------------------------------------------------


def test_replay_call_streams_events_and_ends(replay_dir):
    write_wav(replay_dir / "short.wav", 0.5)
    use_script({2: [results(HELLO, is_final=False)], 4: [results(HELLO, speech_final=True)]})
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "call.start", "source": "replay", "replay_id": "short"}))
        msgs = receive_until(ws, "call.ended")
    kinds = types(msgs)
    assert kinds[0] == "call.started"
    assert msgs[0]["source"] == "replay" and msgs[0]["replay_id"] == "short"
    for k in ("transcriber.status", "speakers.updated", "utterance.partial", "utterance.final"):
        assert k in kinds
    assert next(m for m in msgs if m["type"] == "transcriber.status")["state"] == "live"
    final = next(m for m in msgs if m["type"] == "utterance.final")["utterance"]
    assert final["text"] == "Hello Eszter" and final["speaker"] == "user" and final["is_final"]
    assert kinds.index("utterance.partial") < kinds.index("utterance.final")
    assert msgs[-1]["reason"] == "replay_finished"
    assert all("ts" in m for m in msgs)


# --- mic call -----------------------------------------------------------------------------


def test_mic_call_utterances_swap_and_stop(replay_dir):
    use_script({2: [results(HELLO, is_final=False)], 4: [results(HELLO, speech_final=True)]})
    audio = pcm(0.5, -20)
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "call.start", "source": "mic"}))
        # Uneven chunk sizes: the server re-chunks into 80 ms frames.
        for a, b in ((0, 1000), (1000, 7000), (7000, len(audio))):
            ws.send_bytes(audio[a:b])
        first = receive_until(ws, "utterance.final")
        assert first[0]["type"] == "call.started" and first[0]["source"] == "mic"
        assert "utterance.partial" in types(first)

        ws.send_text(json.dumps({"type": "speakers.swap"}))
        swapped = receive_until(ws, "speakers.updated")[-1]
        assert swapped["reason"] == "manual" and swapped["locked"] is True

        ws.send_text(json.dumps({"type": "call.stop"}))
        ended = receive_until(ws, "call.ended")[-1]
    assert ended["reason"] == "user"


def test_mic_call_ignores_garbage_messages(replay_dir):
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "call.start", "source": "mic"}))
        ws.send_text("not json")
        ws.send_text(json.dumps({"type": "health.ping", "client_sent_ms": 1}))
        ws.send_text(json.dumps({"type": "call.stop"}))
        ended = receive_until(ws, "call.ended")[-1]
    assert ended["reason"] == "user"


# --- bad starts -----------------------------------------------------------------------------


def test_first_message_not_call_start(replay_dir):
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "call.stop"}))
        msg = json.loads(ws.receive_text())
    assert msg["type"] == "call.ended" and msg["reason"] == "error" and msg["detail"] == "bad_start"


def test_first_message_invalid_json(replay_dir):
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text("hello")
        msg = json.loads(ws.receive_text())
    assert msg["reason"] == "error" and msg["detail"] == "bad_start"


@pytest.mark.parametrize("replay_id", ["nope", "../x", "..", "a/b", "UPPER", None, ""])
def test_unknown_or_path_like_replay_id_is_rejected(replay_dir, replay_id):
    write_wav(replay_dir / "real.wav", 0.4)
    start = {"type": "call.start", "source": "replay"}
    if replay_id is not None:
        start["replay_id"] = replay_id
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps(start))
        msg = json.loads(ws.receive_text())
    assert msg["type"] == "call.ended" and msg["reason"] == "error"


def test_path_traversal_does_not_reach_files_outside_replay_dir(replay_dir):
    write_wav(replay_dir.parent / "secret.wav", 0.4)  # sits next to the replay folder
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "call.start", "source": "replay", "replay_id": "../secret"}))
        msg = json.loads(ws.receive_text())
    assert msg["reason"] == "error"
