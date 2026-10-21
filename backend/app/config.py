"""Settings loaded from the repo-root `.env` (see `.env.example`). Keys never leave the backend."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

VERSION = "0.0.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepgram_api_key: str = ""
    gemini_api_key: str = ""
    finnhub_api_key: str = ""
    resend_api_key: str = ""

    # Gemini model per job (see ai.md). Swappable without code changes.
    # Comma-separated: requests are hedged across these (first valid answer wins), because
    # per-model latency flipped between 0.8 s and 30 s across two days. See docs/decisions.md.
    tenor_model_fast: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite"  # extraction + wording, async
    tenor_llm_timeout_s: float = 8.0
    tenor_wording_timeout_s: float = 6.0
    finnhub_timeout_s: float = 3.0
    # The memo summary is hedged too: 3.8-flash returned 503/504 for two days (2026-10-20/21).
    tenor_model_memo: str = "gemini-3.8-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    tenor_memo_timeout_s: float = 20.0
    memo_email_from: str = "Tenor <onboarding@resend.dev>"  # Resend's sandbox sender
    memo_email_to: str = ""  # optional: prefills the recipient on the memo screen

    # Hosting: comma-separated browser origins allowed to call the API and open the sockets,
    # e.g. the Vercel frontend. Empty = local development, everything allowed.
    allowed_origins: str = ""
    # Where saved calls live (SQLite). Empty = backend/data. On Railway: the volume's mount path.
    tenor_data_dir: str = ""

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
