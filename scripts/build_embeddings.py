"""Build embeddings for every hadith and cache to disk.

Run from project root:
    python -m scripts.build_embeddings

This is a one-shot script. The output (data/embeddings.npy + data/embeddings_meta.json)
is consumed by sunnah_toolkit.core.semantic at server startup.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

from sunnah_toolkit.core.data import load

MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BATCH_SIZE = 64
OUT_DIR = Path(__file__).resolve().parent.parent / "data"
EMBEDDINGS_PATH = OUT_DIR / "embeddings.npy"
META_PATH = OUT_DIR / "embeddings_meta.json"


def doc_text(narrator: str, english_text: str) -> str:
    parts = [p for p in (narrator, english_text) if p]
    return " ".join(parts)


def pick_device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def fingerprint(texts: list[str]) -> str:
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def main() -> int:
    print("Loading hadith library...")
    library = load()
    corpus = library.bm25_corpus
    print(f"  {len(corpus):,} hadiths to embed")

    texts = [doc_text(h.english_narrator, h.english_text) for h in corpus]

    from sentence_transformers import SentenceTransformer

    device = pick_device()
    print(f"Loading model {MODEL_ID} on device={device} ...")
    model = SentenceTransformer(MODEL_ID, device=device)

    t0 = time.perf_counter()
    print(f"Embedding {len(texts):,} docs in batches of {BATCH_SIZE} ...")
    vectors = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    ).astype(np.float32)
    print(f"  done in {time.perf_counter() - t0:.1f}s")
    print(f"  shape: {vectors.shape}  dtype: {vectors.dtype}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.save(EMBEDDINGS_PATH, vectors)
    META_PATH.write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "device": device,
                "vector_count": int(vectors.shape[0]),
                "dim": int(vectors.shape[1]),
                "corpus_fingerprint": fingerprint(texts),
                "normalized": True,
            },
            indent=2,
        )
    )
    print(f"Wrote {EMBEDDINGS_PATH} ({EMBEDDINGS_PATH.stat().st_size // 1024} KB)")
    print(f"Wrote {META_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
