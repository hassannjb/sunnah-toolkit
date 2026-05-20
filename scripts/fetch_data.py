"""Download the AhmedBaset/hadith-json dataset (pinned to v1.2.0) into data/.

Run from the project root:
    python -m scripts.fetch_data
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

DATASET_TAG = "v1.2.0"
RAW_BASE = (
    f"https://raw.githubusercontent.com/AhmedBaset/hadith-json/{DATASET_TAG}/db/by_book"
)

FILES: dict[str, list[str]] = {
    "the_9_books": [
        "bukhari.json",
        "muslim.json",
        "abudawud.json",
        "tirmidhi.json",
        "nasai.json",
        "ibnmajah.json",
        "malik.json",
        "ahmed.json",
        "darimi.json",
    ],
    "forties": [
        "nawawi40.json",
        "qudsi40.json",
        "shahwaliullah40.json",
    ],
    "other_books": [
        "riyad_assalihin.json",
        "shamail_muhammadiyah.json",
        "bulugh_almaram.json",
        "aladab_almufrad.json",
        "mishkat_almasabih.json",
    ],
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "by_book"


def fetch_one(client: httpx.Client, category: str, filename: str) -> None:
    target = DATA_DIR / category / filename
    if target.exists():
        print(f"  skip  {category}/{filename}")
        return
    url = f"{RAW_BASE}/{category}/{filename}"
    resp = client.get(url, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(resp.content)
    kb = len(resp.content) // 1024
    print(f"  ok    {category}/{filename} ({kb} KB)")


def main() -> int:
    print(f"Downloading hadith dataset @ {DATASET_TAG} into {DATA_DIR}")
    with httpx.Client() as client:
        for category, filenames in FILES.items():
            for filename in filenames:
                fetch_one(client, category, filename)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
