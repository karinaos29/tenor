"""Train the pressure-tactic classifier.

    cd backend && uv run python ../eval/train_detector.py

Embeds eval/data/train.jsonl + train_extra.jsonl with all-MiniLM-L6-v2, fits one
logistic regression per tactic (class_weight="balanced"), and picks each tactic's
threshold on 5-fold out-of-fold predictions *within the training set* (the held-out test
set written by a different model is never touched here). Thresholds maximize F0.5
(precision counts double): a false alarm costs Eszter's trust more than a miss, and the
rules layer adds recall. Saves backend/detector/model.joblib.
"""

import json
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import fbeta_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from detector.classifier import EMBEDDING_MODEL, MODEL_PATH, sentence_embedder  # noqa: E402
from detector.taxonomy import TACTIC_IDS  # noqa: E402

TRAIN_FILES = [ROOT / "eval" / "data" / "train.jsonl", ROOT / "eval" / "data" / "train_extra.jsonl"]
MIN_THRESHOLD = 0.5
C = 4.0  # mild regularization; 384-d normalized embeddings, ~240 lines


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def best_threshold(y: np.ndarray, p: np.ndarray) -> float:
    candidates = np.arange(MIN_THRESHOLD, 0.91, 0.025)
    scores = [fbeta_score(y, p >= t, beta=0.5, zero_division=0) for t in candidates]
    return float(candidates[int(np.argmax(scores))])


def main() -> None:
    rows = [r for path in TRAIN_FILES if path.exists() for r in load(path)]
    texts = [r["text"] for r in rows]
    embed = sentence_embedder(EMBEDDING_MODEL)
    x = embed(texts)
    models, thresholds, report = {}, {}, {}
    for tactic in TACTIC_IDS:
        y = np.array([tactic in r["tactics"] for r in rows], dtype=int)
        clf = LogisticRegression(C=C, class_weight="balanced", max_iter=2000)
        folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=7)
        oof = cross_val_predict(clf, x, y, cv=folds, method="predict_proba")[:, 1]
        thresholds[tactic] = best_threshold(y, oof)
        report[tactic] = round(fbeta_score(y, oof >= thresholds[tactic], beta=0.5, zero_division=0), 3)
        models[tactic] = clf.fit(x, y)
    joblib.dump(
        {"tactics": list(TACTIC_IDS), "models": models, "thresholds": thresholds, "embedding_model": EMBEDDING_MODEL, "train_size": len(rows)},
        MODEL_PATH,
    )
    print(f"trained on {len(rows)} lines -> {MODEL_PATH.relative_to(ROOT)} ({MODEL_PATH.stat().st_size // 1024} KB)")
    print("tactic         threshold  out-of-fold F0.5 (train)")
    for tactic in TACTIC_IDS:
        print(f"{tactic:<14} {thresholds[tactic]:>9.3f}  {report[tactic]:>6.3f}")


if __name__ == "__main__":
    main()
