"""Voice fingerprints: is this stretch of speech the user's voice?

A speaker-verification model (WavLM Base Plus, x-vector head) turns a stretch of audio into
a vector; two stretches by the same person point the same way (cosine similarity), however
loud or bass-heavy they are. The user's print comes from a sentence spoken at the mic check
(POST /api/voice), through the same mic and room as the call.

Measured on test voices (2 s lines): same person 0.86-0.96, different people 0.69-0.86,
and a voice through the phone band still matched itself (0.89-0.95). Under ~0.6 s a print
is unreliable, so short stretches fall back to the other cues (see pipeline/speakers.py).
"""

import logging

import numpy as np

log = logging.getLogger("tenor.voiceprint")

SAMPLE_RATE = 16_000
MIN_SECONDS = 0.6  # shorter audio doesn't say who's speaking
ENROLL_MIN_SECONDS = 1.5  # speech needed for the user's print
ENROLL_GATE_DBFS = -50.0  # frames quieter than this aren't speech


class VoicePrinter:
    def __init__(self, extractor, model) -> None:  # noqa: ANN001 - transformers types
        self.extractor = extractor
        self.model = model

    @classmethod
    def load(cls, name: str) -> "VoicePrinter":
        from transformers import AutoFeatureExtractor, WavLMForXVector

        return cls(AutoFeatureExtractor.from_pretrained(name), WavLMForXVector.from_pretrained(name).eval())

    @classmethod
    def load_default(cls) -> "VoicePrinter | None":
        from app.config import get_settings

        try:
            return cls.load(get_settings().tenor_voice_model)
        except Exception as e:  # noqa: BLE001 - missing model/deps/offline: no voice recognition
            log.warning("voice prints unavailable (%s); speakers are told apart by sound only", type(e).__name__)
            return None

    def embed(self, samples: np.ndarray) -> np.ndarray:
        """A unit vector for 16 kHz float samples (-1..1). Blocking: call it off the event loop."""
        import torch

        inputs = self.extractor(samples.astype(np.float32), sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.inference_mode():
            vector = self.model(**inputs).embeddings[0].numpy()
        return vector / (np.linalg.norm(vector) or 1.0)


def pcm_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768


def speech_only(samples: np.ndarray, frame: int = 1280) -> np.ndarray:
    """The 80 ms frames loud enough to be speech, joined (pauses carry no voice)."""
    n = samples.size // frame
    if n == 0:
        return samples[:0]
    frames = samples[: n * frame].reshape(n, frame)
    dbfs = 10 * np.log10(np.mean(frames**2, axis=1) + 1e-12)
    return frames[dbfs > ENROLL_GATE_DBFS].reshape(-1)
