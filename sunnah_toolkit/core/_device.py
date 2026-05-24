"""Shared torch device selection.

Both `reranker.py` and `semantic.py` need to pick a torch device with the
same priority order (MPS > CUDA > CPU). Keeping the function in one place
avoids drift if a new accelerator backend is added.
"""

from __future__ import annotations


def pick_device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
