"""Pre-download cross-encoder reranker weights to the local HF cache.

Used by:
- Dockerfile (in builder stage; defaults to --only bge-reranker-v2-m3 to
  keep the published image small)
- Eval (when comparing the four candidates listed in Issue #2 the user
  needs all four weights resident in ~/.cache/huggingface).

Usage:
    python -m scripts.build_models              # downloads all 4
    python -m scripts.build_models --only bge-reranker-v2-m3
    python -m scripts.build_models --only bge-v2-m3                  # alias
"""

from __future__ import annotations

import argparse

from sunnah_toolkit.core.reranker import REGISTRY


def _resolve(name: str) -> tuple[str, str]:
    if name in REGISTRY:
        return name, REGISTRY[name]
    for short, full in REGISTRY.items():
        if name == full or name.endswith("/" + full.split("/", 1)[1]):
            return short, full
    raise SystemExit(
        f"Unknown reranker {name!r}. "
        f"Choices: {sorted(REGISTRY)} or HF IDs: {sorted(REGISTRY.values())}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict download to specific model(s); short name or HF ID. Repeatable.",
    )
    args = ap.parse_args()

    if args.only:
        plan = [_resolve(n) for n in args.only]
    else:
        plan = list(REGISTRY.items())

    # LO-009: restrict the snapshot to safetensors + tokenizer/config files.
    # Without this, HF mirrors fetch both pytorch_model.bin AND
    # model.safetensors (plus optional onnx/ subdirs) — ~doubles disk per
    # model. Sentence-transformers / transformers prefer safetensors when
    # available, so dropping the .bin twin saves ~600 MB per BGE/Jina repo.
    ALLOW_PATTERNS = [
        "*.safetensors",
        "*.json",
        "tokenizer*",
        "vocab*",
        "spiece*",
        "merges.txt",
        "special_tokens_map.json",
        "modules.json",
        "*.py",  # custom modeling code (only kicks in for trust_remote_code repos)
    ]
    for short, full in plan:
        print(f"--> {short} ({full})")
        # snapshot_download fetches files via the HF resolver, respecting
        # hub caching and HF_HUB_OFFLINE.
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=full, allow_patterns=ALLOW_PATTERNS)
        print(f"   ok: {full}")


if __name__ == "__main__":
    main()
