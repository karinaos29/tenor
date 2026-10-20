"""Generate `m1_hello.wav`, a short two-voice test call for the M1 replay demo.

macOS only (uses the built-in `say` voices). Run from backend/:
    uv run python fixtures/calls/make_m1_clip.py

To mimic a phone on speaker next to the laptop, the caller is band-limited to
telephone range (300-3400 Hz) and 8 dB quieter than the user, who sits at the
mic. That loudness gap is exactly what the speaker labeler relies on.
Fictional firm and ticker only (Hartwell & Crane, Kestrel / KSTL).
"""

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

RATE = 16_000
OUT = Path(__file__).resolve().parent / "m1_hello.wav"

USER_VOICE, CALLER_VOICE = "Samantha", "Daniel"
USER_DBFS, CALLER_DBFS = -20.0, -28.0
NOISE_DBFS = -62.0
GAP_S = 0.6

SCRIPT: list[tuple[str, str]] = [
    ("user", "Hello?"),
    ("caller", "Good afternoon. Is this Eszter? My name is Daniel Reeves, I'm calling from Hartwell and Crane."),
    ("user", "Yes, speaking. What is this about?"),
    (
        "caller",
        "We've been following a company called Kestrel, ticker K S T L. "
        "They just signed a deal with a major carmaker, and the stock is up forty percent this quarter.",
    ),
    ("user", "I see. Can you email me the details first?"),
    ("caller", "Of course. But the price is only locked until three p.m. today. Most of our clients take ten thousand shares."),
    ("user", "I don't make decisions on the same day."),
]


def speak(voice: str, text: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "turn.wav"
        subprocess.run(
            ["say", "-v", voice, "-o", str(path), "--file-format=WAVE", f"--data-format=LEI16@{RATE}", text],
            check=True,
        )
        with wave.open(str(path), "rb") as wav:
            return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float64) / 32768


def phone_band(x: np.ndarray) -> np.ndarray:
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1 / RATE)
    spectrum[(freqs < 300) | (freqs > 3400)] = 0
    return np.fft.irfft(spectrum, n=x.size)


def at_level(x: np.ndarray, dbfs: float) -> np.ndarray:
    rms = np.sqrt(np.mean(x**2)) or 1.0
    return x * (10 ** (dbfs / 20) / rms)


def main() -> None:
    parts: list[np.ndarray] = [np.zeros(int(0.5 * RATE))]
    for role, text in SCRIPT:
        if role == "user":
            turn = at_level(speak(USER_VOICE, text), USER_DBFS)
        else:
            turn = at_level(phone_band(speak(CALLER_VOICE, text)), CALLER_DBFS)
        parts += [turn, np.zeros(int(GAP_S * RATE))]
    mix = np.concatenate(parts + [np.zeros(int(1.0 * RATE))])
    mix += np.random.default_rng(7).normal(0, 10 ** (NOISE_DBFS / 20), mix.size)
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(str(OUT), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm.tobytes())
    print(f"wrote {OUT.name}: {mix.size / RATE:.1f} s")


if __name__ == "__main__":
    main()
