"""Generate the scripted test calls (scripts/*.txt -> <name>.wav) with Gemini TTS.

Run from backend/ (needs GEMINI_API_KEY in the repo-root .env):
    uv run python fixtures/calls/make_calls.py                   # all scripts, Gemini voices
    uv run python fixtures/calls/make_calls.py scam_kstl         # one script
    uv run python fixtures/calls/make_calls.py --voices macos    # fallback: built-in macOS voices

One TTS request per turn, one voice per role. Turns are cached in .tts_cache/
(keyed by voice, style and text), so editing one line only regenerates that line.
Like make_m1_clip.py, the caller is band-limited to telephone range and 8 dB
quieter than "You", which is what a phone on speaker next to a laptop sounds like.
"""

import argparse
import asyncio
import base64
import hashlib
import io
import sys
import wave
from pathlib import Path

import numpy as np
from google import genai
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.config import get_settings  # noqa: E402
from fixtures.calls.make_m1_clip import (  # noqa: E402
    CALLER_DBFS,
    GAP_S,
    NOISE_DBFS,
    USER_DBFS,
    at_level,
    phone_band,
)
from fixtures.calls.make_m1_clip import speak as say_speak  # noqa: E402

HERE = Path(__file__).resolve().parent
# Caller and "You" use voices of different genders: Deepgram's diarization merged two
# similar female voices into one speaker (2026-10-20), which hid every caller line.
CACHE = HERE / ".tts_cache"
MODEL = "gemini-3.8-flash-tts"
RATE = 16_000
REQUEST_TIMEOUT_S = 75  # a stalled request must not block the run (HTTP deadline is 60 s)

VOICES = {
    "scam_kstl": {
        "CALLER": ("Charon", "a smooth, confident, slightly pushy salesman on the phone"),
        "YOU": ("Sulafat", "a polite, careful woman in her late fifties"),
    },
    "honest_voo": {
        "CALLER": ("Orus", "a calm, friendly bank adviser, unhurried"),
        "YOU": ("Sulafat", "a polite, careful woman in her late fifties"),
    },
}


# Fallback when Gemini TTS is unavailable: same scripts and processing, robotic voices.
MACOS_VOICES = {
    "scam_kstl": {"CALLER": "Daniel", "YOU": "Samantha"},
    "honest_voo": {"CALLER": "Reed (English (US))", "YOU": "Samantha"},
}


def read_script(name: str) -> list[tuple[str, str]]:
    turns = []
    for line in (HERE / "scripts" / f"{name}.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            role, text = line.split(":", 1)
            turns.append((role.strip(), text.strip()))
    return turns


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    return samples, rate


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    # Low-pass below the new Nyquist, then linear interpolation.
    spectrum = np.fft.rfft(x)
    spectrum[np.fft.rfftfreq(x.size, 1 / src) > dst / 2 * 0.95] = 0
    filtered = np.fft.irfft(spectrum, n=x.size)
    t_new = np.arange(int(x.size * dst / src)) / dst
    return np.interp(t_new, np.arange(x.size) / src, filtered)


_limit = asyncio.Semaphore(4)  # be gentle with rate limits


async def speak(client: genai.Client, voice: str, style: str, text: str) -> np.ndarray:
    key = hashlib.sha256(f"{MODEL}|{voice}|{style}|{text}".encode()).hexdigest()[:16]
    cached = CACHE / f"{key}.wav"
    if not cached.exists():
        async with _limit:
            interaction = await _create(client, voice, style, text)
        CACHE.mkdir(exist_ok=True)
        cached.write_bytes(base64.b64decode(interaction.output_audio.data))
    samples, rate = decode_wav(cached.read_bytes())
    return resample(samples, rate, RATE)


async def _create(client: genai.Client, voice: str, style: str, text: str):  # noqa: ANN202
    for attempt in range(3):
        try:
            return await asyncio.wait_for(_request(client, voice, style, text), REQUEST_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - retry stalls and transient server errors, then give up loudly
            if attempt == 2:
                raise
            print(f"  retrying after {type(e).__name__}: {str(e)[:80]}", flush=True)
            await asyncio.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


async def _request(client: genai.Client, voice: str, style: str, text: str):  # noqa: ANN202
    return await client.aio.interactions.create(
        model=MODEL,
        input=[
            {
                "type": "user_input",
                "content": [{"type": "text", "text": text, "annotations": [{"type": "speech_metadata", "style": style}]}],
            }
        ],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": voice}]},
    )


async def make(client: genai.Client | None, name: str) -> None:
    turns = read_script(name)
    if client is None:
        audio = [say_speak(MACOS_VOICES[name][role], text) for role, text in turns]
    else:
        voices = VOICES[name]
        audio = await asyncio.gather(*(speak(client, *voices[role], text) for role, text in turns))
    parts: list[np.ndarray] = [np.zeros(int(0.5 * RATE))]
    for (role, _), turn in zip(turns, audio, strict=True):
        parts.append(at_level(turn, USER_DBFS) if role == "YOU" else at_level(phone_band(turn), CALLER_DBFS))
        parts.append(np.zeros(int(GAP_S * RATE)))
    mix = np.concatenate(parts + [np.zeros(RATE)])
    mix += np.random.default_rng(7).normal(0, 10 ** (NOISE_DBFS / 20), mix.size)
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(str(HERE / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    print(f"wrote {name}.wav: {mix.size / RATE:.1f} s, {len(turns)} turns", flush=True)


async def main(names: list[str], voices: str) -> None:
    client = None
    if voices == "gemini":
        client = genai.Client(api_key=get_settings().gemini_api_key, http_options=types.HttpOptions(timeout=60_000))
    for name in names:
        await make(client, name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", default=list(VOICES))
    parser.add_argument("--voices", choices=["gemini", "macos"], default="gemini")
    args = parser.parse_args()
    asyncio.run(main(args.names, args.voices))
