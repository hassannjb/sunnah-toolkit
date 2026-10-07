"""Embed chapter (bab) titles for `core/chapters.py`.

Uses the same model as the v2 hadith vectors so one encoded query serves
both legs. ~15k short titles: about a minute on an M2, so build here and
copy `data/emb/<tag>/chapters*` to CPU-only hosts.

Usage:
    python -m scripts.build_chapter_embeddings            # tag from SEMANTIC_V2_TAG (bge-m3)
    python -m scripts.build_chapter_embeddings --tag bge-m3
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np

from sunnah_toolkit.core import semantic_v2
from sunnah_toolkit.core._device import pick_device
from sunnah_toolkit.core.chapters import clean_title, group_chapters
from sunnah_toolkit.core.data import load


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", default=semantic_v2.default_tag())
    ap.add_argument("--batch-size", type=int, default=64)
    args = ap.parse_args()

    d = semantic_v2.artifact_dir(args.tag)
    meta = json.loads((d / "meta.json").read_text())
    keys, members, arabic = group_chapters(load().bm25_corpus)
    en_titles = [clean_title(k[2]) for k in keys]
    # Fall back to the English title where a chapter has no Arabic one, so
    # the two matrices stay row-aligned.
    ar_titles = [clean_title(a) or e for a, e in zip(arabic, en_titles)]
    print(f"{len(keys)} topical chapters covering {sum(map(len, members))} hadiths")

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(meta["model_id"], device=pick_device())
    prefix = meta.get("doc_prefix", "")
    t0 = time.time()
    for name, titles in (("en", en_titles), ("ar", ar_titles)):
        vecs = model.encode(
            [prefix + t for t in titles],
            batch_size=args.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=True,
        )
        np.save(d / f"chapters_{name}.npy", vecs.astype(np.float16))
    (d / "chapters.json").write_text(json.dumps({
        "model_id": meta["model_id"],
        "count": len(keys),
        "keys": keys,
        "built": time.strftime("%Y-%m-%d %H:%M"),
    }))
    print(f"wrote {d}/chapters_{{en,ar}}.npy + chapters.json in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
