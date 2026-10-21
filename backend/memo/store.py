"""Saved calls and their memos, in SQLite (backend/data/tenor.sqlite, gitignored)."""

import sqlite3
import threading
from pathlib import Path

from pipeline.events import Memo, SavedCall

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "tenor.sqlite"


class MemoStore:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS calls (call_id TEXT PRIMARY KEY, started_at TEXT, source TEXT, "
                "replay_id TEXT, status TEXT, risk_level TEXT, headline TEXT, memo_json TEXT)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def start(self, call_id: str, started_at: str, source: str, replay_id: str | None) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO calls (call_id, started_at, source, replay_id, status) VALUES (?, ?, ?, ?, 'live')",
                (call_id, started_at, source, replay_id),
            )

    def set_status(self, call_id: str, status: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE calls SET status = ? WHERE call_id = ?", (status, call_id))

    def save_memo(self, memo: Memo) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE calls SET status = 'ready', risk_level = ?, headline = ?, memo_json = ? WHERE call_id = ?",
                (memo.risk_level, memo.headline, memo.model_dump_json(), memo.call_id),
            )

    def get(self, call_id: str) -> tuple[str, Memo | None]:
        with self._connect() as db:
            row = db.execute("SELECT status, memo_json FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        if row is None:
            return "unknown", None
        status, memo_json = row
        return status, Memo.model_validate_json(memo_json) if memo_json else None

    def recent(self, limit: int = 20) -> list[SavedCall]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT call_id, started_at, source, replay_id, status, risk_level, headline FROM calls "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            SavedCall(call_id=r[0], started_at=r[1], source=r[2], replay_id=r[3], status=r[4], risk_level=r[5], headline=r[6])
            for r in rows
        ]
