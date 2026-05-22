# syntax=docker/dockerfile:1.7

# ---------- Builder ----------
# Installs Python deps, converts sunnah.com's MariaDB dump into SQLite, and
# builds the embeddings. Running build_embeddings.py here also warms the
# HuggingFace cache with the SentenceTransformer model weights — those get
# copied into the runtime stage so the container has zero network
# dependencies at query time.
#
# The sunnah.com SQL dump (data/HadithTable.sql.gz) must be present in the
# build context. Get a fresh dump per sunnah.com's monthly-refresh request;
# see README § "Refresh the dataset".
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# CPU-only torch first so sentence-transformers doesn't pull the CUDA build.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY pyproject.toml ./
COPY sunnah_toolkit ./sunnah_toolkit
COPY scripts ./scripts
COPY data/HadithTable.sql.gz ./data/HadithTable.sql.gz

RUN pip install .

# Bake the SQLite database + embeddings + HF model cache into the image.
RUN python -m scripts.build_sqlite \
 && python -m scripts.build_embeddings

# ---------- Runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_OFFLINE=1

WORKDIR /app

RUN useradd --create-home --uid 1000 app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

ENTRYPOINT ["python", "-m", "sunnah_toolkit", "--transport", "http", "--host", "0.0.0.0"]
