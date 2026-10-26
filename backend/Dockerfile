# Tenor backend image (Railway, or any container host).
# Build context is the repo root: the app also serves eval/results/latest.json.
#   docker build -f backend/Dockerfile -t tenor-backend .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend

# Dependencies first, so source changes don't reinstall them. On Linux the lock resolves
# PyTorch to the CPU-only build (pyproject.toml): a 0.2 GB download instead of 3.0 GB.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# Bake the embedding model (~90 MB) into the image: no download on each cold start.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu')"
# And the voice-print model (~380 MB) that recognizes the user's voice after the voice check.
RUN python -c "from transformers import AutoFeatureExtractor, WavLMForXVector; n = 'microsoft/wavlm-base-plus-sv'; AutoFeatureExtractor.from_pretrained(n); WavLMForXVector.from_pretrained(n)"
ENV HF_HUB_OFFLINE=1

COPY backend/ ./
COPY eval/results/latest.json /app/eval/results/latest.json

# Fail the build, not the first call, if the tactic classifier can't load offline.
RUN python -c "from detector.classifier import TacticClassifier; TacticClassifier.load()"
RUN python -c "from pipeline.voiceprint import VoicePrinter; VoicePrinter.load('microsoft/wavlm-base-plus-sv')"

# Saved calls (SQLite). Mount a Railway volume at /data to keep them across deploys.
# Runs as root: Railway mounts volumes as root.
ENV TENOR_DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000
# One process: a call's state lives in memory for its duration. Railway sets $PORT.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
