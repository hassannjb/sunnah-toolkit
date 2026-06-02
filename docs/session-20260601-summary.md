# Session summary — 2026-05-28 → 2026-06-01

Spans the comparison with another repo, the scholarly-policy guardrail
addition, the start of eval-set curation, the discovery + fix of a
hadith-number lookup bug, and the resumption of eval curation up to Q1
ready-for-review.

---

## 1. Comparison with `shadysalman/islamic-knowledge-skill`

User asked how that repo compares with `sunnah-toolkit`. Honest read:

**Where his project is stronger**

- More disciplined `SKILL.md` prompt — explicit fatwa boundary, madhab
  neutrality, Sunni scope, scholarly-humility phrasebook
- Includes Quran (6,236 ayat) alongside Bukhari + Muslim
- Easier consumer install — single `SKILL.md` upload to claude.ai Skills
- More marketing-ready README

**Where this project is stronger**

- 3× the hadith corpus — 44,896 across 15 collections vs. his 14,736
  across only Bukhari + Muslim
- Canonical data source (sunnah.com's official MariaDB dump, monthly
  refresh script with rollback) vs. his community GitHub scrape
- Richer per-hadith metadata — grading + parsed isnad chain with stable
  narrator IDs
- Hybrid retrieval: BM25 + multilingual semantic + Arabic-transliteration
  term + optional cross-encoder reranker vs. his single OpenAI-embedding
  cosine mode
- No per-query cost or external dependency at runtime (everything baked
  into the Docker image)
- Two first-class transports (MCP stdio + streamable-http, REST) vs. his
  Supabase edge function only
- Live HF Spaces demo + GHCR + Cloudflare-tunnel ops story
- Refresh path: monthly conditional-GET refresh + image-rollback

His main advantage worth borrowing was the jurisprudential discipline of
his `SKILL.md`. Acted on next.

---

## 2. Added `SCHOLARLY POLICY (non-negotiable)` to SKILL.md

`.claude/skills/sunnah/SKILL.md` got a new section after the existing
verbatim-quoting policy. Three rules, modelled on Shady's SKILL.md minus
the Sunni-scope rule (user explicitly opted out — wanted to stay
non-sectarian):

1. **No fatwas / legal rulings.** Present what the text says; never
   declare halal/haram unless the ruling word appears in the quoted text.
   Close with "consult a qualified scholar."
2. **No madhab positions.** When hadiths could support different
   scholarly interpretations, surface the text and defer.
3. **Scholarly-humility close** for jurisprudence, family, finance,
   medical, personal-situation questions.

Committed: `ad28794 skill(sunnah): add scholarly-policy guardrails`

---

## 3. Ranking quality discussion

User raised two persistent search-quality problems:

1. **Ordering broken**: results should put Bukhari → Muslim → other
   collections first, but it doesn't happen.
2. **Reranker mis-scoring**: highly relevant hadiths get low cross-encoder
   scores; less-relevant ones get high scores.

Diagnosed root cause: the `(collection_tier, grade_tier, score)` hard
sort from closed Issue #1 is correctly implemented in `data.py` and
`semantic.py` (the legacy single-retriever paths) — but the rerank
pipeline added in Issue #2 (`tools.py`'s `_score_candidates` /
`_split_strong_weak`) sorts purely by cross-encoder logit and was never
taught about the tiers. So Issue #1's fix exists but is bypassed by the
default search path.

Same cross-encoder-only ordering causes problem #2: a relevant Bukhari
Sahih at score 0.45 sinks below threshold 0.5 while a less-relevant
Hasan at 0.55 surfaces.

Discussed fix options (hard tier sort, soft tier boost, drop threshold
entirely, hybrid score, switch model, build the eval set). User
correctly pushed back that lowering the threshold doesn't fix
mis-ranking, only shifts the cutoff. We agreed: **eval set first** —
without measurement, every other knob is guessing.

Started the eval-set curation interactively.

---

## 4. Eval-set curation — surfaced a lookup-key bug

Format: present one query with a numbered candidate list; user accepts
/ removes by number / adds by sunnah.com link.

- Q1 (sleep dua): user said "this is good"
- Q2 (toilet dua): "all great"
- Q3 (Arafah fast): user dropped 5 candidates, added muslim:1133a and
  muslim:1134b — first appearance of letter-suffix refs
- Q4 (anger): user noticed bukhari:5882 didn't contain "the strong is
  the one who controls anger" — flagged it as wrong

Investigated. Root cause was deeper than wrong labels — the dataset
keys lookup on `id_in_book` (internal ordinal) but every user-facing
path displays `hadith_number` (sunnah.com URL key). When a user pastes
`sunnah.com/bukhari:6312`, the code looks up id_in_book=6312 (which is
a completely different hadith with hadith_number=6551, the "width
between shoulders of a Kafir") and returns that. Confirmed by the
user's screenshot of the demo UI's Reference mode showing exactly that
mis-fetch.

This meant **every Q1–Q3 label the user had approved was potentially
pointing at the wrong hadith under the current code**. The whole eval
curation pipeline was at risk of being tuned against garbage labels.

---

## 5. Lookup-bug fix

Five files changed in one commit + a regression test:

- `core/data.py` — `get_hadith(slug, n)` now accepts `int | str`,
  matches `hadith_number` first (whitespace-insensitive, lowercased,
  handles paired ranges like `"272, 273"`), then accepts a bare integer
  that resolves to the first lettered variant (`/muslim:375` →
  `"375 a"`), then falls back to `id_in_book` for legacy callers and
  hadiths without a hadith_number.
- `core/tools.py` — widened signature; citation URL squashes whitespace
  and drops paired-range trailing parts.
- `api/routes.py` — `/v1/hadith/{slug}/{number}` takes a string so
  letter-suffix refs pass through.
- `api/ui.py` — `parseReference` keeps the input string (no `parseInt`);
  result-row `data-num` uses `hadith_number` so click-fetch resolves
  to the same hadith the label points at; `refLabel` /
  `referenceUrl` squash whitespace + drop trailing range parts.
- `mcp/server.py` — tool signature `int | str` + docstring noting
  sunnah.com URL convention and letter-suffix support.
- `tests/test_get_hadith_lookup.py` (new) — 8 cases including the
  `bukhari:6312` screenshot bug, `muslim:1134b` (whitespace
  normalization), `muslim:375` (lettered-variant fallback), paired
  ranges, int fallback.

49/49 tests pass. End-to-end HTTP verified through the demo server.

Committed: `db62b35 fix(lookup): get_hadith keys on sunnah.com hadith_number`

Pushed to origin/main.

---

## 6. Eval set re-design + Q1 re-verification

After the fix, restarted eval curation with the user's input on the
queries themselves too (not just hadiths). Removed redundant Arafah
keyword query, added 7 new ones at user's request:

- wudu (term)
- divorce in Islam (concept)
- advice on marriage (concept)
- treating children kindly (concept)
- qiyam ul layl (term)
- what are the rites of hajj (natural)
- how many wives can men marry (natural)

Final 25-query list locked. See `docs/eval/curation-state.md` for the
full table.

Q1 (sleep dua) re-verified against fixed lookup. Three refs from the
prior draft were silently pointing at unrelated content (the labels
"looked" right but `get_hadith` now returns different hadiths):

- `bukhari:6322` — was labelled "Ayat al-Kursī" but actually the
  toilet-entry dua → dropped
- `bukhari:6059` — was labelled "pre-sleep instructions" but actually
  about war-booty distribution → replaced with the real ref `bukhari:6296`
- `bukhari:1110` — was labelled "Satan's three knots" but actually
  about Zuhr during travel → replaced with the real ref `bukhari:1142`

Plus `bukhari:6324` added (alternate "Bismika Allāhumma amūtu wa aḥyā"
narration surfaced by post-fix search).

Q1 presented to user 2026-06-01 with 10 verified sunnah.com links.
**Awaiting user review.**

---

## Where to pick up

- Q1 is on screen waiting for confirmation or edits.
- Q2 and Q3 had been "approved" pre-fix and need re-verification — the
  old labels may be pointing at the wrong hadiths now.
- Q4–Q25 are pending curation against the fixed lookup, same format.
- Detailed per-query status is in `docs/eval/curation-state.md`.

Memory updated:

- `project_lookup_bug_fix.md` — fix landed, pushed
- `project_search_quality_tickets.md` — eval-set curation resumed; locked
  query list; Q1 awaiting review

Two background processes from this session that won't survive the restart:

- Local verification server on `:8765` — already stopped before push
- MCP server in this Claude Code session was running stale code; the next
  session's MCP server will pick up the fixed code automatically

The fix is on `origin/main` so it'll be in any environment that pulls.
