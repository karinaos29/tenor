"""Tactic classifier: sentence embeddings + one logistic regression per tactic.

Trained by `eval/train_detector.py` into `model.joblib` (weights + per-tactic thresholds,
a few hundred KB). The embedding model (all-MiniLM-L6-v2, ~90 MB) is downloaded from
Hugging Face once and cached. If anything is missing, `load_default()` returns None and
the detector runs on rules alone.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger("tenor.classifier")

MODEL_PATH = Path(__file__).resolve().parent / "model.joblib"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

Embedder = Callable[[list[str]], np.ndarray]


def sentence_embedder(name: str = EMBEDDING_MODEL) -> Embedder:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(name, device="cpu")
    return lambda texts: np.asarray(model.encode(texts, normalize_embeddings=True, show_progress_bar=False))


class TacticClassifier:
    def __init__(self, bundle: dict, embed: Embedder) -> None:
        self.tactics: list[str] = bundle["tactics"]
        self.models = bundle["models"]  # tactic -> fitted LogisticRegression
        self.thresholds: dict[str, float] = bundle["thresholds"]
        self.embedding_model: str = bundle.get("embedding_model", EMBEDDING_MODEL)
        self.embed = embed

    def predict_proba(self, texts: list[str]) -> list[dict[str, float]]:
        if not texts:
            return []
        x = self.embed(texts)
        out: list[dict[str, float]] = [{} for _ in texts]
        for tactic in self.tactics:
            probs = self.models[tactic].predict_proba(x)[:, 1]
            for i, p in enumerate(probs):
                out[i][tactic] = float(p)
        return out

    def predict(self, texts: list[str]) -> list[set[str]]:
        return [{t for t, p in probs.items() if p >= self.thresholds[t]} for probs in self.predict_proba(texts)]

    @classmethod
    def load(cls, path: Path = MODEL_PATH, embed: Embedder | None = None) -> "TacticClassifier":
        import joblib

        bundle = joblib.load(path)
        return cls(bundle, embed or sentence_embedder(bundle.get("embedding_model", EMBEDDING_MODEL)))

    @classmethod
    def load_default(cls) -> "TacticClassifier | None":
        try:
            return cls.load()
        except Exception as e:  # noqa: BLE001 - missing model/deps/offline: rules only
            log.warning("tactic classifier unavailable (%s); using rules only", type(e).__name__)
            return None
