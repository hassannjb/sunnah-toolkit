# Eval-set curation — Batch 1 draft (NEEDS EXPERT REVIEW)

**Status:** Paused 2026-05-24 — waiting on hadith-knowledgeable reviewer.

These are LLM-proposed labels (Claude) for 4 of the 19 queries in the
new eval set. They are NOT verified by an expert and should not be
committed to `docs/eval/queries.json` until reviewed.

For each query: candidate hadiths picked from the API top-30 + canonical
references added from Claude's training data. Some hadith numbers may
not exist in this project's sunnah.com dump or may have different
numbering — verification needed.

The other 15 queries' candidate pool sits in
`docs/eval/candidates-draft-20260524.json` (30 per query), untouched.

---

## Q1: supplication when going to sleep  [concept]

| Ref | Rationale |
|---|---|
| bukhari:6059 | "When you intend going to bed at night..." pre-sleep instructions |
| bukhari:6312 | canonical "Allahumma bismika amutu wa-ahya" |
| bukhari:6313 | same dua, different narration |
| bukhari:6314 | same chapter, sleep dua |
| bukhari:6315 | same chapter |
| bukhari:6320 | Tasbih before sleep (Fatimah/Ali narration) |
| bukhari:6322 | recite Ayat al-Kursi before sleep |
| bukhari:7393 | sleep dua |
| bukhari:1110 | Satan's three knots when sleeping (indirect) |
| muslim:2710 | canonical sleep dua |

## Q2: what to say when entering the toilet  [concept]

| Ref | Rationale |
|---|---|
| bukhari:142 | CANONICAL "Allahumma inni a`udhu bika min al-khubuthi wal khaba'ith" |
| bukhari:6085 | same dua, different chapter |
| abudawud:4 | canonical toilet entry dua |
| abudawud:5 | toilet manners |
| tirmidhi:5 | canonical toilet dua |
| tirmidhi:6 | toilet manners |
| muslim:375 | canonical |
| nasai:19 | related toilet manners |
| ibnmajah:296 | canonical |

## Q3: fasting on the day of Arafah  [concept]

| Ref | Rationale |
|---|---|
| bukhari:1602 | Prophet's non-fast on Arafah during Hajj |
| bukhari:1917 | same topic, different narrator |
| bukhari:1988 | Arafah day fasting context |
| bukhari:1989 | same |
| muslim:1162 | CANONICAL: Arafah fast expiates 2 years of sins |
| abudawud:2425 | Arafah fast |
| tirmidhi:749 | Arafah fast virtue |
| nasai:2376 | Arafah fast |
| ibnmajah:1730 | Arafah fast |
| ibnmajah:1731 | same |

## Q4: controlling anger  [concept]

| Ref | Rationale |
|---|---|
| bukhari:5882 | "The strong is the one who controls anger when angry" CANONICAL |
| bukhari:5884 | "Do not become angry" CANONICAL |
| bukhari:6116 | canonical do-not-be-angry narration |
| bukhari:6889 | "Do not judge when angry" |
| bukhari:5763 | anger/witchcraft narration |
| bukhari:3147 | anger advice |
| muslim:2609 | canonical strong-is-who-controls-anger |
| abudawud:4782 | perform wudu when angry |
| abudawud:4783 | sit/lie down when angry |
| abudawud:4784 | seek refuge from Satan |
| tirmidhi:2020 | anger |

---

## How the expert should use this

1. For each query, decide if the proposed labels are truly relevant. Remove any that aren't.
2. Add any obvious canonical references that are missing.
3. Cross-check the hadith numbers against the actual content in this project's data
   (use `GET /v1/hadith/<slug>/<number>` or `gh api ...` or simply the sunnah.com web UI).
4. The remaining 15 queries' candidates are pre-pulled at
   `docs/eval/candidates-draft-20260524.json` — same approach.
5. Once labels are finalised, write them into `docs/eval/queries.json` (replacing
   the noisy auto-seeded set) and run:
   ```
   .venv/bin/python -m scripts.eval_search --reranker bge-v2-m3 --save
   .venv/bin/python -m scripts.tune_threshold --reranker bge-v2-m3
   ```
6. If the new winner or threshold differs meaningfully from the provisional
   `bge-v2-m3` / `0.5`, commit the updated defaults in `core/reranker.py`.

## Queries still un-drafted (15)

1. kindness to neighbours (concept)
2. prohibition of backbiting (concept)
3. seeking forgiveness from Allah (concept)
4. the hadith of intentions (concept)
5. patience (keyword)
6. knowledge (keyword)
7. Arafah (keyword)
8. qunut (term)
9. istighfar (term)
10. laylatul qadr (term)
11. dua e qunut (term)
12. what is the dua before sleep? (natural)
13. is fasting on Arafat recommended? (natural)
14. is qunut required in witr? (natural)
15. what did the Prophet say about controlling anger? (natural)
