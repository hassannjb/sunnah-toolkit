# Session summary — 2026-05-23 → 24

Welcome back. Quick view, then detail.

---

## TL;DR (one-liners)

**Today (Done):**
- 5 GH issues (#1, #2, #3, #4, #7) all merged + closed
- 12 commits past `a965690`: full implementation plan (6 steps) + Agent A's 7 review-finding refactor commits
- Code review doc with 31 findings — **26 addressed** (CR-001/2/3 + 6 high + 9 medium + 11 low)
- 41/41 tests passing (started at 0)
- Branches + worktrees cleaned, remote refs pruned
- Reranker comparison ran against 4 candidates on the noisy auto-seeded eval set; **bge-v2-m3 wins** (NDCG@10 = 0.4448, +59% over baseline)
- Threshold tune ran — provisional best 0.05, **not committed** to defaults (noisy labels)
- Local dev server running on **http://localhost:8768/** (with `RERANKER_DISABLED=1` for now)

**Tomorrow (Pickup point):**
- Curate the 19-query eval set together — candidates pre-pulled in `docs/eval/candidates-draft-20260524.json` (570 rows)
- Re-run eval comparison + threshold tune against clean labels
- Apply new defaults if the winner or threshold meaningfully changes
- Then re-enable reranker on the live server

**What's working:**
- All 5 search modes via the demo UI (Concept / Keyword / Arabic term / Reference / Natural language)
- Multi-word Arabic queries work: `dua e qunut`, `laylatul qadr`, `youm e arafat`
- NL mode falls back to concept search since no `ANTHROPIC_API_KEY` is set
- Hard tier sort (Bukhari/Muslim Sahih dominate top-of-page)
- Pagination + weak-match toggle coexist cleanly
- Chip filter is strong-only post-reranker

**What's not working / caveats:**
- Reranker **disabled** on the running server (to avoid memory contention while running evals)
- 2 of the 4 candidate rerankers had eval issues:
  - `jina-v2-base`: silent fallback (results identical to baseline) — model loading likely failed quietly
  - `mxbai-v2-base`: crashed with leaked semaphore warning, no JSON saved
- 2 review findings explicitly skipped (ME-010, LO-008) — both warrant their own tickets
- `pip install -e .` fails due to stale interpreter path (`sunnah-mcp/.venv`) — works at runtime, just needs venv rebuild
- The threshold tune ran on noisy auto-seeded labels — the 0.05 it picked is provisional and NOT committed as the new default

---

## Tomorrow's plan — focused pickup

The work-in-progress is the **eval-set curation**. Status:

1. **19 new queries drafted** (in the IDE, see `docs/session-summary.md` for the list — also reproduced below).
2. **Top 30 candidates pulled** for each query → `docs/eval/candidates-draft-20260524.json` (570 rows total).
3. **Curation not started** — we agreed yesterday on "LLM-assisted + manual walk-through" combo.

**Approach for tomorrow:**
- For each query in `candidates-draft-20260524.json`, I'll go through the 30 candidates and propose ~10–15 as "truly relevant" based on hadith knowledge.
- For each query, I'll also surface 3–5 canonical references I know are relevant but didn't appear in the API top-30 (e.g. Bukhari 6312/13/14 for "supplication when going to sleep").
- You spot-check (don't review all 200+ labels — pick a few queries and trust the rest).
- I write `docs/eval/queries.json` with the new labeled set.
- Re-run `scripts/eval_search.py` for all 4 rerankers against the clean labels.
- Re-run `scripts/tune_threshold.py` on the new winner.
- Commit defaults if they change.

Time estimate: ~30–60 minutes of interactive work.

### The 19 queries

```
Concept (8):
  1. supplication when going to sleep
  2. what to say when entering the toilet
  3. fasting on the day of Arafah
  4. controlling anger
  5. kindness to neighbours
  6. prohibition of backbiting
  7. seeking forgiveness from Allah
  8. the hadith of intentions

Keyword (3):
  9. patience
 10. knowledge
 11. Arafah

Term (4):
 12. qunut
 13. istighfar
 14. laylatul qadr
 15. dua e qunut

Natural (4):
 16. what is the dua before sleep?
 17. is fasting on Arafat recommended?
 18. is qunut required in witr?
 19. what did the Prophet say about controlling anger?
```

(Reference-mode query was dropped because reference lookups bypass the reranker.)

---

## Local server

```
http://localhost:8768/
```

Logged to `/tmp/sunnah-server.log`. Currently running with `RERANKER_DISABLED=1`.

To stop / restart:
```bash
lsof -ti:8768 | xargs kill                          # stop
.venv/bin/python -m sunnah_toolkit --transport http --port 8768 &   # restart with reranker enabled
```

If you'd rather skip the reranker again tomorrow until we have clean labels:
```bash
RERANKER_DISABLED=1 .venv/bin/python -m sunnah_toolkit --transport http --port 8768 &
```

---

## Reranker comparison results (committed to repo)

| Reranker | NDCG@10 | P@10 | Recall@100 | Status |
|---|---:|---:|---:|---|
| **bge-v2-m3** | **0.4448** | **0.404** | **0.159** | **Winner (provisional)** |
| jina-v3 | 0.4110 | 0.396 | 0.137 | clean run, second-best |
| jina-v2-base | 0.2795 | 0.252 | 0.117 | silent fallback (identical to baseline) |
| mxbai-v2-base | — | — | — | crashed, no JSON |
| (none / baseline) | 0.2795 | 0.252 | 0.117 | reference |

Results archived at `docs/eval/results-*.json`. **Re-run after labels are curated tomorrow.**

---

## Full commit history this session (past `a965690`)

```
a214dca docs(review): mark addressed findings + note skipped ME-010, LO-008
<6 review-finding refactor commits from Agent A>
7d84a1f feat(nl): natural-language search mode with Anthropic router       [Closes #4]
9ed297e feat(term): multi-word Arabic query support with AND/OR fallback   [Closes #7]
9dae464 feat(term-ui): aggregate matched_words from strong results only    [Closes #3]
a25037f fix(search): honor limit + expose pool_size for transparency       [CR-003]
c5c0c33 security(rerank): remove trust_remote_code; pin jina-v3            [CR-001]
ef57b1f feat(api): raise limit cap to 50000 on /v1/search* endpoints
659893f fix(ui): merge pagination + weak-toggle into one paginated set     [CR-002]
a965690 docs: post-merge code review of PR #5 + PR #6
```

---

## Notable follow-ups (from Agent A's review pass)

1. **`RESPONSE_SCHEMA.md`** — the search API now has subtle distinctions between `score`, `similarity`, `total`, `pool_size`, `threshold`, `reranker_active`. A doc would help downstream consumers.
2. **ME-010 + LO-008 as one ticket** — multi-collection single-call rerank + flag rename. Public-API breaking, deserves a deprecation cycle.
3. **`_doc_text_by_urn` LRU cache** (ME-003) silently grows to 8,192 entries/process. Fine now but worth a metric if memory pressure becomes a thing.
4. **README docs gap** — new env vars `RERANKER_REQUIRED=1` (fail-fast) and `CORS_ALLOW_ORIGINS` are undocumented.

---

## How to resume cleanly tomorrow

1. Open this file.
2. Check `git log --oneline -10` to confirm main is at the latest commit (should be a docs-only commit from this wrap-up).
3. Open `docs/eval/candidates-draft-20260524.json` in your IDE to scroll through queries + candidates.
4. Ping me with "let's curate" or similar — I'll start working through the 19 queries in batches of 3–4, proposing labels for each.

---

## Files / scripts you can use

- `scripts/eval_search.py --reranker {none,bge-v2-m3,jina-v2-base,mxbai-v2-base,jina-v3}` — run eval
- `scripts/tune_threshold.py --reranker <name>` — threshold sweep
- `scripts/seed_eval_set.py` — old auto-seeder (will be replaced by tomorrow's curation)
- `scripts/build_models.py` — pre-download reranker weights (already done)
- `docs/code-review-postmerge.md` — 31 findings (now with `[x]` marks for addressed)
- `docs/eval/results-*.json` — all eval runs archived
- `docs/eval/threshold-curve.json` — provisional threshold sweep result
- `docs/eval/candidates-draft-20260524.json` — work-in-progress for tomorrow

Sleep well.
