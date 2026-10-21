"""Opt-in: the real trained classifier with the real embedding model (run with -m model)."""

import pytest

from detector.classifier import TacticClassifier

pytestmark = pytest.mark.model


def test_real_model_predictions():
    clf = TacticClassifier.load_default()
    if clf is None:
        pytest.skip("model.joblib or the embedding model is unavailable")
    secret, nice = clf.predict(["Keep this between us, don't tell your bank.", "Have a nice afternoon."])
    assert "secrecy" in secret
    assert nice == set()
