# Eval-set curation — interactive state

**Last updated:** 2026-06-01 (session paused for system restart)
**Curator:** user (hassan.najeeb)
**Workflow:** I present one query at a time with verified sunnah.com links; user
removes by number or pastes sunnah.com links to add; when locked we move on.

Resume by saying "continue eval curation" or "start Q2".

---

## Locked query list (25)

Decisions captured 2026-05-29 → 2026-06-01:

- Dropped from prior draft: the standalone keyword query "Arafah" (redundant
  with the concept and natural-language Arafah twins).
- Added topics requested by user: wudu, divorce, marriage, behaviour with
  children, qiyam ul layl, rites of hajj, polygamy.
- Twin pairs (concept ↔ natural-language) kept deliberately — they let us
  measure whether the LLM router beats plain semantic on the same topic.

| # | Query | mode_hint |
|---|---|---|
| 1 | supplication when going to sleep | concept |
| 2 | what to say when entering the toilet | concept |
| 3 | fasting on the day of Arafah | concept |
| 4 | controlling anger | concept |
| 5 | kindness to neighbours | concept |
| 6 | prohibition of backbiting | concept |
| 7 | seeking forgiveness from Allah | concept |
| 8 | the hadith of intentions | concept |
| 9 | divorce in Islam | concept |
| 10 | advice on marriage | concept |
| 11 | treating children kindly | concept |
| 12 | patience | keyword |
| 13 | knowledge | keyword |
| 14 | qunut | term |
| 15 | istighfar | term |
| 16 | laylatul qadr | term |
| 17 | dua e qunut | term |
| 18 | wudu | term |
| 19 | qiyam ul layl | term |
| 20 | what is the dua before sleep? | natural |
| 21 | is fasting on Arafat recommended? | natural |
| 22 | is qunut required in witr? | natural |
| 23 | what did the Prophet say about controlling anger? | natural |
| 24 | what are the rites of hajj | natural |
| 25 | how many wives can men marry | natural |

---

## Per-query label status

### Q1 — "supplication when going to sleep" (concept)  — **AWAITING USER REVIEW**

Presented to user 2026-06-01 with sunnah.com links. 10 candidates after
verification against the fixed `get_hadith` lookup. Three refs from the
prior draft were silently pointing at the wrong hadith under the corrected
numbering — replaced with the real canonical refs.

| # | Ref | Content |
|---|---|---|
| 1 | https://sunnah.com/bukhari:6312 | Hudhayfa: pre-sleep "Bismika Allāhumma amūtu wa aḥyā" |
| 2 | https://sunnah.com/bukhari:6313 | Al-Barāʾ: "Allāhumma aslamtu nafsī ilayka…" |
| 3 | https://sunnah.com/bukhari:6314 | Hudhayfa: hand under cheek + "bismika amūtu wa aḥyā" |
| 4 | https://sunnah.com/bukhari:6315 | Al-Barāʾ: right-side sleep + "aslamtu nafsī" dua |
| 5 | https://sunnah.com/bukhari:6320 | Abū Hurayra: shake out the bed before sleeping |
| 6 | https://sunnah.com/bukhari:6324 | Hudhayfa: alternate "Bismika Allāhumma amūtu wa aḥyā" |
| 7 | https://sunnah.com/bukhari:6296 | Jābir: lights out / doors closed / cover food at night |
| 8 | https://sunnah.com/bukhari:7393 | Abū Hurayra: dust the bed thrice + bedtime dua |
| 9 | https://sunnah.com/bukhari:1142 | Abū Hurayra: Satan ties three knots during sleep |
| 10 | https://sunnah.com/muslim:2710a | Al-Barāʾ: canonical Muslim sleep-dua sequence |

Dropped from prior draft because the lookup pointed at unrelated content:
`bukhari:6322` (was labelled Ayat al-Kursī — actually the toilet-entry dua).
Open question for user: add `bukhari:5010` (Abū Hurayra / thief / Ayat
al-Kursī)?

### Q2 — "what to say when entering the toilet" (concept) — pending

Prior draft accepted by user verbatim during 2026-05-29 session. NEEDS
RE-VERIFICATION against fixed lookup (some refs may have pointed at the
wrong hadith under the old code). When resuming, re-do Q2 from scratch
with sunnah.com links.

### Q3 — "fasting on the day of Arafah" (concept) — partially edited

During 2026-05-29 session user dropped #4, #5, #7, #8, #10 and added
muslim:1133a, muslim:1134b. Surviving set:
- muslim:1133a
- muslim:1134b
- muslim:1162
- bukhari:1988
- bukhari:1989
- abudawud:2425
- ibnmajah:1730

Same caveat as Q2 — these were approved against the unfixed lookup. The
muslim:1134b add prompted the lookup-bug discovery. Re-verify on resume.

### Q4 — "controlling anger" (concept) — re-do from scratch

Original draft used hallucinated hadith numbers (e.g. bukhari:5882 didn't
contain the "strong is the one who controls anger" hadith — that's
actually at bukhari:6114). My partial Q4 attempt found via MCP search:

- https://sunnah.com/bukhari:6114 — "strong is one who controls himself in anger" (canonical)
- https://sunnah.com/bukhari:6116 — "Do not become angry" (Abū Hurayra)
- https://sunnah.com/muslim:2609a — canonical strong-not-wrestler
- https://sunnah.com/muslim:2609b — alternate narration
- https://sunnah.com/abudawud:4779 — wrestling / anger
- https://sunnah.com/abudawud:4782 — sit-down-when-angry-while-standing
- https://sunnah.com/bukhari:3282 — Sulaymān b. Ṣurad / seek refuge from Shayṭān
- https://sunnah.com/bukhari:6048 — abused-each-other / seek refuge from Shayṭān
- https://sunnah.com/tirmidhi:2020 — "Do not get angry" (Sahih)
- https://sunnah.com/forty:16 — Nawawi 40 #16 "Do not become angry"
- https://sunnah.com/adab:1317 — strong-not-wrestler (Sahih)

These are pre-verified against the fixed lookup. Present cleanly when we
get to Q4.

### Q5–Q25 — pending, candidates not yet drafted

Candidate pools for queries 5–25 sit at
`docs/eval/candidates-draft-20260524.json` (auto-pulled top-30 from the
union retriever, untouched). Use those as a starting point; verify each
with `get_hadith` against the fixed lookup before presenting.

---

## How to resume

1. User confirms or edits Q1 (current state).
2. Move through Q2…Q25 one at a time, same format:
   - Numbered list, each row a sunnah.com link + one-line content gist
   - Verify each ref via `lib.get_hadith(slug, num)` against the fixed
     lookup before presenting — never repeat the prior session's
     hallucinated numbers
   - Accept remove-by-number and add-by-link edits
3. Once all 25 are locked, write to `docs/eval/queries.json` and run:
   ```
   .venv/bin/python -m scripts.eval_search --reranker bge-v2-m3 --save
   .venv/bin/python -m scripts.tune_threshold --reranker bge-v2-m3
   ```
4. If the eval surfaces a better reranker / threshold than the provisional
   bge-v2-m3 / 0.5, commit the new defaults in `core/reranker.py`.

## Why the previous labels can't be trusted blindly

Until 2026-06-01 (commit `db62b35`), `Library.get_hadith(slug, n)` keyed on
`id_in_book`, not the sunnah.com `hadith_number` that every user-facing path
displays. A user pasting `sunnah.com/bukhari:6312` got the hadith at
id_in_book=6312 (which is the "width between shoulders of a Kafir" hadith,
hadith_number=6551) instead of the sleep-dua at hadith_number=6312. The
fix makes hadith_number the canonical lookup key and accepts strings with
letter suffixes (`1134b`), paired ranges (`272, 273`), and bare-integer
lookups that resolve to the first lettered variant (`/muslim:375` →
`375 a`). 49 tests pass; full diagnosis in commit message.
