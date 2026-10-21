"""TacticClassifier wrapper with a fake embedder and tiny real sklearn models (no downloads)."""

import joblib
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from detector import classifier as clf_mod
from detector.classifier import TacticClassifier

TACTICS = ["urgency", "secrecy"]


def embed(texts):
    """Deterministic 2-d vectors: axis 0 = mentions 'now', axis 1 = mentions 'secret'."""
    return np.array([[float("now" in t), float("secret" in t)] for t in texts])


def bundle():
    x = np.array([[0, 0], [1, 0], [0, 1], [1, 1], [0, 0], [1, 0], [0, 1], [1, 1]], dtype=float)
    models = {
        "urgency": LogisticRegression().fit(x, [int(r[0]) for r in x]),
        "secrecy": LogisticRegression().fit(x, [int(r[1]) for r in x]),
    }
    return {"tactics": TACTICS, "models": models, "thresholds": {"urgency": 0.5, "secrecy": 0.5}, "embedding_model": "fake"}


def test_predict_proba_shape_and_keys():
    c = TacticClassifier(bundle(), embed)
    out = c.predict_proba(["decide now", "a secret", "hello"])
    assert len(out) == 3 and all(set(o) == set(TACTICS) for o in out)
    assert all(0.0 <= p <= 1.0 and isinstance(p, float) for o in out for p in o.values())
    assert out[0]["urgency"] > 0.5 > out[0]["secrecy"]
    assert out[1]["secrecy"] > 0.5 > out[1]["urgency"]


def test_predict_uses_per_tactic_thresholds():
    b = bundle()
    b["thresholds"] = {"urgency": 0.5, "secrecy": 0.999999}
    c = TacticClassifier(b, embed)
    assert c.predict(["decide now", "a secret", "hello"]) == [{"urgency"}, set(), set()]


def test_empty_input():
    c = TacticClassifier(bundle(), embed)
    assert c.predict_proba([]) == [] and c.predict([]) == []


def test_load_from_joblib_with_injected_embed(tmp_path):
    path = tmp_path / "m.joblib"
    joblib.dump(bundle(), path)
    c = TacticClassifier.load(path, embed=embed)
    assert c.embedding_model == "fake" and c.thresholds["urgency"] == 0.5
    assert c.predict(["decide now"]) == [{"urgency"}]


def test_load_default_returns_none_when_model_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(clf_mod, "MODEL_PATH", tmp_path / "missing.joblib")
    monkeypatch.setattr(TacticClassifier.load.__func__, "__defaults__", (tmp_path / "missing.joblib", None))
    assert TacticClassifier.load_default() is None


def test_load_default_returns_none_when_load_raises(monkeypatch):
    def boom(cls, *a, **k):
        raise OSError("no model")

    monkeypatch.setattr(TacticClassifier, "load", classmethod(boom))
    assert TacticClassifier.load_default() is None


@pytest.mark.parametrize("n", [1, 5])
def test_batch_size_is_preserved(n):
    assert len(TacticClassifier(bundle(), embed).predict(["x"] * n)) == n
