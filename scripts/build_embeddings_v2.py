"""Build v2 bi-encoder embeddings — dual-language, chapter-aware, resumable.

Differences from `build_embeddings.py` (v1), all of which address logged
search-quality issues:

  * **Chapter title is embedded.** v1's document was `narrator + english_text`.
    A hadith's bab title ("Supplication When Going To Sleep") is frequently the
    single strongest topical signal it carries, and v1 threw it away. 94.4% of
    the corpus has an English bab name. This is the direct fix for the
    docs/search-issues.md #3 complaint that "supplication before sleep" misses
    the Muslim chapter of exactly that name.
  * **Narrator is dropped.** "Narrated Abu Hurairah:" appeared in every v1
    vector, contributing tokens and zero topical signal. BM25 still indexes
    narrators, and narrator lookup is a metadata filter, not a semantic query.
  * **Arabic gets its own vector.** v1 embedded English only, so Arabic queries
    were served by the transliteration-skeleton hack. A separate Arabic vector
    per hadith lets `max(sim_en, sim_ar)` serve either language natively.
    Two vectors beat one mixed-language vector — concatenating languages into
    a single embedding blurs both.

Output layout (v1 artifacts are left untouched so the running system and the
eval baseline keep working):

    data/emb/<tag>/en.npy      float16 [N, dim]
    data/emb/<tag>/ar.npy      float16 [N, dim]
    data/emb/<tag>/meta.json

Writes through a memmap and checkpoints progress, so an interrupted multi-hour
run resumes instead of starting over.

Usage:
    python -m scripts.build_embeddings_v2                    # bge-m3, both langs
    python -m scripts.build_embeddings_v2 --limit 200        # smoke test
    python -m scripts.build_embeddings_v2 --lang en          # one language
    python -m scripts.build_embeddings_v2 --batch-size 8     # if MPS OOMs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from sunnah_toolkit.core._device import pick_device
from sunnah_toolkit.core.data import Hadith, load, strip_narrator_markup

ROOT = Path(__file__).resolve().parent.parent
EMB_ROOT = ROOT / "data" / "emb"

MODELS: dict[str, dict] = {
    "bge-m3": {"model_id": "BAAI/bge-m3", "dim": 1024, "max_seq": 512},
    "e5-large": {
        "model_id": "intfloat/multilingual-e5-large",
        "dim": 1024,
        "max_seq": 512,
        # e5 requires an asymmetric prefix; queries use "query: ".
        "doc_prefix": "passage: ",
    },
    "minilm-v1": {
        "model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "dim": 384,
        "max_seq": 128,
    },
}

CHECKPOINT_EVERY = 2000


def doc_en(h: Hadith) -> str:
    """English document: chapter title + body. Narrator deliberately excluded."""
    parts = [p for p in (h.english_bab_name, h.english_text) if p and p.strip()]
    return ". ".join(parts) if parts else ""


def doc_ar(h: Hadith) -> str:
    """Arabic document: chapter title + matn with [narrator] markup stripped."""
    matn = strip_narrator_markup(h.arabic)
    parts = [p for p in (h.arabic_bab_name, matn) if p and p.strip()]
    return ". ".join(parts) if parts else ""


def fingerprint(texts: list[str]) -> str:
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _encode_resumable(
    model,
    texts: list[str],
    out_path: Path,
    dim: int,
    batch_size: int,
    label: str,
) -> np.ndarray:
    """Encode `texts` into a float16 memmap, checkpointing as we go."""
    n = len(texts)
    progress_path = out_path.with_suffix(".progress")

    if out_path.exists() and progress_path.exists():
        done = json.loads(progress_path.read_text()).get("done", 0)
        if done >= n:
            print(f"  [{label}] already complete ({n:,} vectors) — skipping")
            return np.load(out_path, mmap_mode="r")
        arr = np.lib.format.open_memmap(out_path, mode="r+")
        print(f"  [{label}] resuming at {done:,}/{n:,}")
    else:
        arr = np.lib.format.open_memmap(
            out_path, mode="w+", dtype=np.float16, shape=(n, dim)
        )
        done = 0

    t0 = time.perf_counter()
    while done < n:
        chunk = texts[done : done + CHECKPOINT_EVERY]
        vecs = model.encode(
            chunk,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        arr[done : done + len(chunk)] = vecs.astype(np.float16)
        arr.flush()
        done += len(chunk)
        progress_path.write_text(json.dumps({"done": done, "total": n}))

        elapsed = time.perf_counter() - t0
        rate = done / elapsed if elapsed else 0
        eta = (n - done) / rate if rate else 0
        print(
            f"  [{label}] {done:,}/{n:,}  {rate:.1f} doc/s  "
            f"elapsed {elapsed/60:.1f}m  eta {eta/60:.1f}m",
            flush=True,
        )

    progress_path.unlink(missing_ok=True)
    return arr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="bge-m3", choices=sorted(MODELS))
    ap.add_argument("--lang", default="both", choices=["en", "ar", "both"])
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0,
                    help="Only embed the first N hadiths (smoke test).")
    ap.add_argument("--tag", default="", help="Output dir name (default: model key).")
    args = ap.parse_args()

    spec = MODELS[args.model]
    tag = args.tag or args.model
    out_dir = EMB_ROOT / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading hadith library ...")
    library = load()
    corpus = library.bm25_corpus
    if args.limit:
        corpus = corpus[: args.limit]
    print(f"  {len(corpus):,} hadiths")

    prefix = spec.get("doc_prefix", "")
    texts_en = [prefix + doc_en(h) for h in corpus]
    texts_ar = [prefix + doc_ar(h) for h in corpus]
    n_empty_en = sum(1 for t in texts_en if not t.strip())
    n_empty_ar = sum(1 for t in texts_ar if not t.strip())
    n_bab = sum(1 for h in corpus if h.english_bab_name)
    print(f"  chapter title present: {n_bab:,} ({100*n_bab/len(corpus):.1f}%)")
    print(f"  empty docs: en={n_empty_en} ar={n_empty_ar}")

    from sentence_transformers import SentenceTransformer

    device = pick_device()
    print(f"Loading {spec['model_id']} on device={device} (first run downloads ~2.3 GB) ...")
    model = SentenceTransformer(spec["model_id"], device=device)
    model.max_seq_length = spec["max_seq"]
    # Renamed in recent sentence-transformers; support both spellings.
    _get_dim = getattr(
        model, "get_embedding_dimension", None
    ) or model.get_sentence_embedding_dimension
    dim = _get_dim()
    if dim != spec["dim"]:
        print(f"  note: model reports dim={dim}, registry said {spec['dim']}")

    langs = ["en", "ar"] if args.lang == "both" else [args.lang]
    t0 = time.perf_counter()
    for lang in langs:
        texts = texts_en if lang == "en" else texts_ar
        print(f"\nEncoding {lang} ({len(texts):,} docs, batch={args.batch_size}) ...")
        _encode_resumable(
            model, texts, out_dir / f"{lang}.npy", dim, args.batch_size, lang
        )

    meta = {
        "tag": tag,
        "model_id": spec["model_id"],
        "dim": dim,
        "max_seq": spec["max_seq"],
        "device": device,
        "vector_count": len(corpus),
        "normalized": True,
        "dtype": "float16",
        "doc_prefix": prefix,
        "query_prefix": "query: " if prefix else "",
        "languages": langs,
        "template_en": "english_bab_name + '. ' + english_text  (narrator excluded)",
        "template_ar": "arabic_bab_name + '. ' + strip_narrator_markup(arabic)",
        "fingerprint_en": fingerprint(texts_en),
        "fingerprint_ar": fingerprint(texts_ar),
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "build_seconds": round(time.perf_counter() - t0, 1),
        "partial": bool(args.limit),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    print(f"\nDone in {(time.perf_counter() - t0)/60:.1f} min")
    for lang in langs:
        p = out_dir / f"{lang}.npy"
        print(f"  {p}  ({p.stat().st_size // (1024*1024)} MB)")
    print(f"  {out_dir / 'meta.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
