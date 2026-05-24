# Post-merge code review — PR #5 + PR #6
**Reviewer:** staff-level pass, automated (Claude)
**Main HEAD reviewed:** 6912e48
**Date:** 2026-05-23

PR #6 (`951bf36`) — collection + grade hard-tier sort across all search modes.
PR #5 (`6912e48`) — two-stage retrieve-and-rerank pipeline with cross-encoder.

## Executive summary

- **One real vulnerability**: every reranker is loaded with `trust_remote_code=True`, which executes arbitrary code from the HF repo at load time. Mitigated only in the production container by `HF_HUB_OFFLINE=1`; dev/CI runs and `scripts/build_models.py` runs are fully exposed.
- **Working-tree `ui.py` has unresolved git-conflict markers** between earlier pagination work and PR #5's weak-match toggle. The file is unparseable JavaScript — anyone running `uvicorn` against this tree will load a broken page. This is not on `main` but blocks the next push.
- **The new `_search_with_rerank` pipeline silently breaks the contract of `limit`** for both `total` and `results+results_weak`: callers asking for 50 000 results get at most ~300 (the fixed `k_per_retriever * 3` union pool), and `total` counts only that pool — not the BM25 positive-score universe the old code surfaced.
- **`trust_remote_code=True` + unbounded `model.predict` batch + per-process model singleton with `lru_cache(maxsize=1)`** form a memory/availability footgun: switching `RERANKER_NAME` evicts the cache key but the prior torch model is only freed when GC runs; a noisy query with 300 long-doc candidates is one un-batched forward that can OOM the 16 GB host.
- **Test coverage is thin** for the new code: 1 normalize-grade unit file (PR #6) + 1 latency smoke test (PR #5). No contract test for the reranker `Reranker` protocol, no test for `_search_with_rerank`'s strong/weak split, no test that the union retriever is robust to one leg failing, no test that `Library.search` tier-sort is stable.
- Code quality is otherwise solid: layering is clean (core → api, never the reverse), naming is consistent, the retrieval/reranker split is the right abstraction. Findings are mostly polish, hardening, and a couple of contract gaps.

## Findings

### Critical (must-fix before next release)

- [x] **CR-001** — `vulnerability` | `sunnah_toolkit/core/reranker.py:77, 130-133` (closed in c5c0c33)
  - **Description:** Every cross-encoder loader passes `trust_remote_code=True` to `CrossEncoder` and `AutoModelForSequenceClassification.from_pretrained`. A compromised HF repo (or anyone who pushes a malicious revision under the same model ID) executes arbitrary Python on the host at model-load time.
  - **Impact:** RCE on every host that runs `scripts/build_models.py`, `scripts/eval_search.py`, `scripts/tune_threshold.py`, or boots the app without `HF_HUB_OFFLINE=1`. The Dockerfile sets `HF_HUB_OFFLINE=1` at runtime so the deployed container is fine, *but* the builder stage runs `scripts/build_models.py --only bge-v2-m3` and dev/CI runs without that flag download fresh code each time. The four candidates in Issue #2 include two `jinaai/*` and one `mixedbread-ai/*` repo — all distinct attack surfaces.
  - **Fix:** Drop `trust_remote_code=True` for the BGE and MXBai models (CrossEncoder-shaped, no remote code needed); keep it for the Jina rerankers but pin a known-good revision via `revision="<sha>"`. Add a build-time SHA-pin manifest committed to the repo.

- [x] **CR-002** — `bad-pattern` | `sunnah_toolkit/api/ui.py:733-798, 929-968` (closed in 659893f)
  - **Description:** The working tree on disk contains unresolved git conflict markers (`<<<<<<< Updated upstream` / `=======` / `>>>>>>> Stashed changes`) inside the JavaScript string literal `INDEX_HTML`. The file parses as Python (the markers are inside an `r"""..."""` raw string) but the served HTML/JS is syntactically invalid — the page will throw `SyntaxError` on load and render nothing past the `<style>` block.
  - **Impact:** Any developer who runs `uvicorn sunnah_toolkit.api.app:create_app --factory` against the current working tree loads a broken UI. The conflict is *not* present on `main` (HEAD `6912e48` is clean) — but it will block the next push that touches `ui.py` and is silently shipping in the worktree right now.
  - **Fix:** See "Pending conflicts" section below for the merge shape.

- [x] **CR-003** — `bad-pattern` | `sunnah_toolkit/core/tools.py:144-265, 274-281` (closed in a25037f)
  - **Description:** `_search_with_rerank` redefines the meaning of `limit` and `total` versus the legacy path. (a) `k_per_retriever` is hard-coded to 100 inside `search_hadith`/`search_hadith_term`/`search_hadith_semantic`, so the union pool is at most ~300 candidates even when callers ask for `limit=50000`. (b) `total` is `len(strong) + len(weak)` — i.e. the union-pool size, not the BM25-positive-score universe the legacy `Library.search` returns. (c) The UI calls these with `limit=50000` (`ALL_LIMIT` in `ui.py`) explicitly because it expects "every hit"; with the new pipeline that promise quietly evaporates.
  - **Impact:** API consumers (including the demo UI and the eval harness) silently get a tiny slice of what they asked for. The eval script's `recall@100` metric is bounded by ~300, which is fine for the eval; the UI's "Showing N of M (filtered from X)" status line and chip counts derive from a truncated set. Cross-collection fan-out in `searchAcrossCollections` makes this worse — N collections × ~300 = ~300N candidates, but each is reranked separately, so global ordering is approximate.
  - **Fix:** Either expose `k_per_retriever` as a knob on the public functions and document the cap, OR raise `k_per_retriever` proportional to `limit` (e.g. `max(100, limit*3)`), OR (preferred) document this as the new contract in the function docstrings and stop accepting `limit > k_per_retriever * 3`.

### High

- [x] **HI-001** — `memory-leak` | `sunnah_toolkit/core/reranker.py:168-174` (closed in 82a46f3)
  - **Description:** `@functools.lru_cache(maxsize=1)` on `get_reranker(name)` evicts the previous instance from the cache on a name change, but the evicted instance holds a torch model in `self._model`. Python GC will reclaim it eventually, but `torch.cuda.empty_cache()` / `torch.mps.empty_cache()` is never called, so device-resident weights linger until process exit.
  - **Impact:** Running `scripts/eval_search.py` over all four candidates in a single process leaks ≥3 GB of FP16 weights per model swap; the second swap likely OOMs on a 16 GB host (or pushes deep into swap on the M2 Air). On the production CPU container the RAM stays mapped to FP16 weights of the prior model until GC runs.
  - **Fix:** Wrap `get_reranker` with a setter that explicitly `del`s `self._model` and calls the device-specific empty-cache before constructing the new one; or drop `lru_cache` for a single-slot manual cache that frees on miss.

- [x] **HI-002** — `performance` | `sunnah_toolkit/core/reranker.py:81-88` (closed in 82a46f3)
  - **Description:** `_CrossEncoderBase.score` calls `model.predict(pairs, show_progress_bar=False, convert_to_numpy=True)` with no `batch_size` argument and no length-bucketing. `pairs` is the entire candidate set (≤300), each pair being `query + ~2KB doc`. CrossEncoder defaults `batch_size=32` but pads to the longest in the batch — so a single 8192-token mxbai doc forces every other pair in that batch to pad to 8192.
  - **Impact:** On CPU (production container), worst-case `mxbai-v2-base` rerank of 300 candidates with one long Arabic+English doc is multiple seconds per query. The `test_retrieval_latency.py` budget (300 ms) only covers the union retriever — the reranker stage is uncovered.
  - **Fix:** Pass `batch_size=8` (or expose as env var); sort `pairs` by length before predict so each batch is uniform; truncate each doc to a fixed token budget per reranker.

- [x] **HI-003** — `error-handling` | `sunnah_toolkit/core/tools.py:187-198` (closed in 7d600c0)
  - **Description:** The `except Exception as e:` swallows every reranker error, logs at WARN, and silently falls back to the heuristic. There's no signal in the response that the reranker failed — `response["reranker"]` is rewritten to `"none"` but the caller has no way to distinguish "reranker disabled by config" from "reranker exploded on this query".
  - **Impact:** A stuck/failing reranker (OOM, GPU OOM, corrupted weights) goes unnoticed in production. The healthcheck (`/healthz`) is static `{"ok": True}` so the symptom only appears as silently degraded quality. The eval harness can't tell which queries fell back.
  - **Fix:** Add a `reranker_status` field to the response (`"ok" | "fell_back: <error>"`); raise once per process per error class and rate-limit the log; consider a circuit breaker that disables the reranker for N minutes after K failures.

- [x] **HI-004** — `concurrency` | `sunnah_toolkit/core/semantic.py:98-119` (closed in 82a46f3)
  - **Description:** `_engine.model.encode([query], ...)` is called from the bi-encoder thread inside `retrieve_union`'s `ThreadPoolExecutor`. sentence-transformers does not document `SentenceTransformer.encode` as thread-safe — internally it tokenizes, builds tensors, and writes to module state. Multiple concurrent HTTP requests hitting `/v1/search/semantic` (each spawning its own `retrieve_union` thread pool) will each call `encode` simultaneously on the *same* model object.
  - **Impact:** Under load (multiple concurrent users on the public tunnel) you can hit torch tensor races, occasional wrong-result returns, or silent crashes. Pure-CPU paths are GIL-serialized but `torch.no_grad` blocks release the GIL on every C++ kernel.
  - **Fix:** Either add a module-level `Lock` around `encode` (cheap; only one query embeds at a time), or run the bi-encoder in a single-worker `concurrent.futures.ThreadPoolExecutor` that queues encode calls.

- [x] **HI-005** — `bad-pattern` | `sunnah_toolkit/core/tools.py:200-218` (closed in 7d600c0)
  - **Description:** Heuristic-mode weights are magic numbers in an inline dict: `{"concept": (0.2, 1.0, 0.4), "keyword": (1.0, 0.4, 0.4), "term": (0.2, 0.4, 1.0)}`. Unknown `mode_hint` silently defaults to `(0.5, 0.5, 0.5)`. There is no validation that `mode_hint` is one of the three documented values — a typo (`"conept"`) succeeds silently with neutral weights.
  - **Impact:** Quality regression invisible to users — a frontend typo or a future MCP caller passing an unexpected mode_hint degrades search quality without any error. The weights were never tuned against the eval set; they're guesses.
  - **Fix:** Define a `Literal["concept", "keyword", "term"]` type alias; lift the weights to a module-level `_MODE_WEIGHTS: dict[Mode, tuple[float, float, float]]` with named constants; assert on unknown mode.

- [x] **HI-006** — `test-gap` | `sunnah_toolkit/core/tools.py:144-265` (closed in 7d600c0)
  - **Description:** `_search_with_rerank` — the central pipeline of PR #5 — has no unit tests. There are no tests covering: (a) reranker-disabled fallback ordering, (b) strong/weak split at the threshold, (c) `limit` saturation, (d) matched_words aggregation, (e) reranker exception → heuristic fallback, (f) empty-candidate short-circuit, (g) collection filter combined with rerank.
  - **Impact:** Future refactors will silently regress search quality. The eval script is integration-level (needs the SQLite + embeddings + model), so unit-level invariants are unguarded.
  - **Fix:** Add `tests/test_search_with_rerank.py` with a fake `Reranker` fixture (returning deterministic scores) and verify the seven contracts above.

### Medium

- [x] **ME-001** — `bad-pattern` | `sunnah_toolkit/core/data.py:399, 428` (closed in e4cdcf6)
  - **Description:** `COLLECTION_TIER[pair[1].collection]` and `COLLECTION_TIER[pair[0].collection]` use raw subscript access. If `COLLECTIONS_METADATA` ever gains a slug not in `COLLECTION_TIER`, `library.load()` succeeds but the first search query KeyErrors at sort time.
  - **Impact:** A future "add a 16th collection" PR that updates `COLLECTIONS_METADATA` but forgets `COLLECTION_TIER` ships in green CI (no test exercises the path) and blows up at runtime on the first search.
  - **Fix:** Use `COLLECTION_TIER.get(slug, len(COLLECTION_TIER))` so unknown slugs sort last; add a runtime assertion in `load()` that every slug in `COLLECTIONS_METADATA` is in `COLLECTION_TIER`.

- [x] **ME-002** — `lengthy-function` | `sunnah_toolkit/core/tools.py:144-265` (closed in 7d600c0)
  - **Description:** `_search_with_rerank` is 122 lines doing: union retrieval, reranker selection, scoring, exception-fallback heuristic, threshold split, response building, matched_words aggregation, and legacy field preservation. Three or four logically independent steps.
  - **Impact:** Hard to test (see HI-006), hard to review, hard to evolve. Branching on `rerank_on` is interleaved with response-shaping logic.
  - **Fix:** Split into `_score_candidates(query, candidates, mode_hint) → list[(Candidate, float)]`, `_split_strong_weak(scored, threshold, limit)`, and `_build_response(...)`.

- [x] **ME-003** — `performance` | `sunnah_toolkit/core/tools.py:124-141, sunnah_toolkit/core/data.py:234-244` (closed in 7d600c0 via lru_cache(_doc_text_by_urn))
  - **Description:** `_doc_text` rebuilds per-candidate doc strings on every search and re-runs `strip_narrator_markup` (regex-heavy) on the Arabic text. With ~300 candidates × every query that's 300 regex passes over ~1KB of text per request.
  - **Impact:** Adds ~50–100 ms per query on CPU when the reranker is the chosen path. The result is identical for the same `Hadith` so it's pure repeated work.
  - **Fix:** Precompute a `display_arabic` field on `Hadith` in `data.load()` (one-time at startup, frozen). Or cache `_doc_text(c.hadith.global_id)` via lru_cache keyed on the hashable global_id.

- [x] **ME-004** — `error-handling` | `sunnah_toolkit/api/app.py:27-40` (closed in f00b7dc)
  - **Description:** `_warm_reranker` catches `Exception`, logs at WARN, and continues. If the bundled `bge-v2-m3` weights are missing or corrupted, the app starts "healthy" (returns `{"ok": True}` from `/healthz`) but every search falls back to heuristic ordering forever.
  - **Impact:** Production drift: a deployment with bad model files looks healthy in observability but ships degraded results to every user. Mirrors HI-003 but at the boot path.
  - **Fix:** Either fail-fast on warm-load failure (raise → uvicorn exits), or surface the warm-load status via `/healthz` (`{"ok": true, "reranker": "fell_back"}`).

- [x] **ME-005** — `concurrency` | `sunnah_toolkit/core/retrieval.py:92-98` (closed in d1ea79c)
  - **Description:** A fresh `ThreadPoolExecutor(max_workers=3)` is created per `retrieve_union` call. The context manager joins on exit so this is correct, but spawning + tearing down 3 threads per query has measurable cost on CPU-pinned hosts.
  - **Impact:** Adds ~1–3 ms of pure thread-pool overhead per query, plus python-thread-create memory churn under load.
  - **Fix:** Module-level `_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="retrieval")` or use `asyncio.gather` since the API server is already async.

- [x] **ME-006** — `test-gap` | `sunnah_toolkit/core/retrieval.py` (closed in d1ea79c)
  - **Description:** `test_retrieval_latency.py` is a latency smoke test only — it asserts median ≤ 300 ms but never asserts *correctness*. There is no test that the union dedupes properly, that the per-retriever `*_norm` fields are computed from the correct retriever's hits, that a candidate hit by all three retrievers has all three `sources` populated, or that one retriever raising (FileNotFoundError for missing embeddings) doesn't crash the union.
  - **Impact:** A dedupe bug or a source-attribution bug would not be caught.
  - **Fix:** Add `tests/test_retrieval_union.py` with a stub library + monkeypatched `semantic.retrieve` covering the four cases above.

- [x] **ME-007** — `bad-pattern` | `sunnah_toolkit/core/tools.py:218, 261` (closed in 7d600c0 — added reranker_active bool; threshold stays null only when reranker isn't applying a calibrated split)
  - **Description:** Sentinel `threshold = -float("inf")` is set when the reranker is off, then JSON-serialized as `None` (line 261). This conflates two different states ("reranker disabled" vs. "threshold=0.0") in the response shape — the frontend and eval harness have to reason about `None` to mean "everything is strong".
  - **Impact:** UI complexity (the weak-toggle code in `ui.py` has to treat `null` threshold specially); eval harness has the same. `tune_threshold.py` works around this by jamming `RERANKER_THRESHOLD=-1e9` for the sweep.
  - **Fix:** Always populate `threshold` with a real float; add a separate boolean `reranker_active: bool` field to the response.

- [x] **ME-008** — `vulnerability` | `sunnah_toolkit/api/app.py:60-65` (closed in f00b7dc)
  - **Description:** `CORSMiddleware(allow_origins=["*"], allow_methods=["GET","POST"], allow_headers=["*"])`. No `allow_credentials=True`, so this is not a cookie-stealing vector. But `allow_headers=["*"]` combined with `*` origin means any site can issue authenticated `Authorization: Bearer ...` requests in the user's browser — a misconfigured tester might leak their bearer token through a malicious origin.
  - **Impact:** Low for now (bearer tokens are intended to be back-channel, not stored in browsers). But once the demo UI ships with auth, a `*` allow-origin lets any page on the internet probe the API on the user's behalf.
  - **Fix:** Restrict `allow_origins` to the actual demo origin (and `*` for unauthenticated `GET`-only endpoints if needed); never combine `*` with `Authorization`.

- [x] **ME-009** — `bad-pattern` | `sunnah_toolkit/core/tools.py:194-198` (closed in 7d600c0)
  - **Description:** Bare `except Exception` (over-broad). Catches `KeyboardInterrupt`-adjacent classes that propagate from torch (e.g. `torch.cuda.OutOfMemoryError` on non-CUDA builds), genuine bugs (`AttributeError` from a missing field), and the intended runtime failures (model-load errors).
  - **Impact:** Real bugs are silently demoted to WARN logs and degraded results.
  - **Fix:** Narrow the catch to `(RuntimeError, OSError, ValueError)`, or define a `RerankerError` subclass and re-raise unknowns.

- [~] **ME-010** — `performance` | `sunnah_toolkit/api/ui.py:624-657` (skipped — requires extending /v1/search endpoints to accept multiple collections, threading it through retrieve_union, and rewriting searchAcrossCollections; out of scope for the post-merge polish pass. Track as its own ticket alongside the union-pipeline rename.)
  - **Description:** `searchAcrossCollections` issues one parallel API call per selected collection. With 10 collections ticked, that's 10 separate `_search_with_rerank` invocations server-side — each running the cross-encoder on its own ~300 candidates. Cross-collection rerank score comparability is *assumed* (line 654 comment) but each call's `min/max` for `_minmax` differs, so the merged ordering is a best-effort sort.
  - **Impact:** 10× the server compute, 10× the model-eval cost, and inter-collection score scales aren't comparable on a per-batch basis even though the *cross-encoder logit* is roughly scale-invariant.
  - **Fix:** Pass the selected collections as a single API call (extend `/v1/search` to accept multiple `collection=` query params or a comma-separated list); rerank once over the union.

### Low / style

- [x] **LO-001** — `style` | `sunnah_toolkit/core/reranker.py:38-45, sunnah_toolkit/core/semantic.py:36-43` (closed in 82a46f3)
  - **Description:** `_pick_device()` is duplicated verbatim across `reranker.py` and `semantic.py`.
  - **Fix:** Move to a shared `_device.py` or to `core/__init__.py`.

- [x] **LO-002** — `naming` | `sunnah_toolkit/core/retrieval.py:38-45` (closed in d1ea79c)
  - **Description:** `_minmax` returns `[1.0 if v > 0 else 0.0 for v in values]` when min==max — but for BM25/term scores all values are positive, so that branch always returns all-1.0. Subtle: if all retriever hits are tied (a real edge case for term mode where 2 hadiths each match one rare word), all normalised scores become 1.0 and the heuristic fallback loses signal.
  - **Fix:** Return `[1.0]*len(values)` directly in the tied case; document the behaviour.

- [x] **LO-003** — `dead-code` | `pyproject.toml:23-26` (closed in 0311e7a)
  - **Description:** `optimum>=1.20` and `onnxruntime>=1.18` are pinned with the comment "INT8/ONNX fallback ... (Issue #2 Phase E)". Nothing in the current code imports or uses either package.
  - **Impact:** ~250 MB of unused wheels (`onnxruntime` is ~80 MB, `optimum` pulls extras) in the runtime container. The Dockerfile's 3 GB image-size budget already eats this.
  - **Fix:** Move both to `[project.optional-dependencies] onnx = [...]` until Phase E actually wires them in.

- [x] **LO-004** — `naming` | `sunnah_toolkit/core/tools.py:144` (closed in 7d600c0 — renamed to search_with_rerank, alias kept for back-compat)
  - **Description:** `_search_with_rerank` is name-prefixed `_` (private) but is the canonical pipeline called by three public functions and the eval harness. It's not actually private — `scripts/eval_search.py` does `hasattr(tools, "_search_with_rerank")` and `tools._search_with_rerank(...)`.
  - **Fix:** Rename to `search_with_rerank` (public) or to `_pipeline` if it must stay internal and refactor eval to use the public wrappers.

- [x] **LO-005** — `doc-gap` | `sunnah_toolkit/core/reranker.py:11-13` (closed in 82a46f3)
  - **Description:** Docstring says "Only one reranker is loaded into the process at a time (lru_cache(maxsize=1)) because the host RAM budget is 16 GB". Doesn't mention HI-001 (the eviction doesn't actually free GPU/MPS memory).
  - **Fix:** Note that switching rerankers may not promptly free device memory.

- [x] **LO-006** — `unnecessary` | `sunnah_toolkit/core/data.py:391` (closed in e4cdcf6)
  - **Description:** Comment `# We still need the total count across all positive scores.` on PR #5 but the line below is just `scores = self.bm25.get_scores(tokens)` — the comment refers to a sentence that's now redundant with the next line.
  - **Fix:** Drop the comment; the code is self-explanatory.

- [x] **LO-007** — `bad-pattern` | `sunnah_toolkit/core/tools.py:241-242` (closed in 7d600c0 — documented as per-retriever signal; kept conditional for back-compat)
  - **Description:** Legacy compatibility shim: `if "semantic" in cand.sources: row["similarity"] = cand.semantic`. This carries through the *raw* dot-product (not min-max normalised, not cross-encoder), and only when the bi-encoder fired. The field name `similarity` is now a per-retriever artefact, not a top-level score.
  - **Impact:** API consumers that depended on the old `similarity` field get an inconsistent payload — sometimes present (when semantic retrieved), sometimes absent.
  - **Fix:** Either always populate `similarity` (or always omit it), or drop the legacy field entirely with a deprecation note.

- [~] **LO-008** — `naming` | `sunnah_toolkit/core/tools.py:272, 304, 342` (skipped — renaming the public `rerank` flag in three search functions would break every API consumer; left for an explicit deprecation cycle alongside the ME-010 work)
  - **Description:** `rerank: bool = True` parameter on the three public search functions. The flag name suggests "should I rerank the existing results" but the actual semantic is "should I use the *new pipeline* (union + rerank) vs. the legacy single-retriever path". Two different things bundled into one flag.
  - **Fix:** Rename to `use_union_pipeline` or split into `union: bool` (use union retriever) + `rerank: bool` (apply cross-encoder).

- [x] **LO-009** — `performance` | `scripts/build_models.py:55` (closed in 0311e7a)
  - **Description:** `snapshot_download(repo_id=full, allow_patterns=None)` downloads every file in the HF repo, which for BGE/Jina includes both `pytorch_model.bin` AND `model.safetensors` AND tokenizer files AND optional `onnx/` subfolders.
  - **Impact:** ~doubles disk usage per model vs. downloading only `safetensors`.
  - **Fix:** `allow_patterns=["*.safetensors", "*.json", "tokenizer*", "vocab*"]`.

- [x] **LO-010** — `coupling` | `sunnah_toolkit/core/tools.py:131` (closed in 7d600c0)
  - **Description:** `_doc_text` does `from .data import strip_narrator_markup` inside the function body. Late import is a code smell — `data` is already imported at module top.
  - **Fix:** Move to top-of-module import.

- [x] **LO-011** — `test-gap` | `tests/test_retrieval_latency.py:37-54` (closed in 0311e7a)
  - **Description:** The latency test asserts median ≤ 300 ms but only runs locally with the embeddings file present. CI without the data dir silently passes/skips? No skip-marker present — it will fail with `FileNotFoundError`.
  - **Fix:** Add `@pytest.mark.skipif(not EMBEDDINGS_PATH.exists(), reason="embeddings not built")`.

- [x] **LO-012** — `style` | `sunnah_toolkit/core/tools.py:218` (closed in 7d600c0)
  - **Description:** `threshold = -float("inf")` followed by `float(threshold) if threshold != -float("inf") else None` on line 261 — two comparisons against negative infinity. Use `math.isfinite(threshold)`.
  - **Fix:** Minor readability win.

## Pending conflicts (working tree, not yet on main)

`sunnah_toolkit/api/ui.py` contains four conflict regions inside the `INDEX_HTML` JavaScript:

1. **Lines 733-798** — `renderResultsView`. Upstream (PR #5, on `main`): strong+weak rendering with weak-toggle button, status string `"N strong (+ M weak)"`. Stashed (earlier pagination work): paged slicing of `lastResults` with `currentPage` + `PAGE_SIZE=10`, status string `"Showing N-M of K — page P of Q"`. These are independent concerns that should coexist.

2. **Lines 929-934** — `doSearch`. Upstream: `let items = j.results || []; let weakItems = j.results_weak || [];`. Stashed: `const items = j.results || [];` (no weak handling).

3. **Lines 945-952** — `doSearch` continued. Upstream: `items = items.slice(0, displayCap); weakItems = weakItems.slice(0, Math.max(displayCap*3, 60));`. Stashed: removed the slice (presumably to defer capping to the paginator).

4. **Lines 963-968** — `doSearch` end. Upstream: `selectedResultCollections = new Set(items.concat(weakItems).map(...))`. Stashed: same but with `items` only + `currentPage = 1`.

**Suggested resolution shape:** Keep both features. Apply pagination *after* filtering, in `renderResultsView`, but page only the *strong* set; weak matches stay un-paginated and appear after the strong page (under the existing weak-toggle button). Concretely:

```
filteredStrong = applyFilters(lastResults)
filteredWeak   = applyFilters(lastResultsWeak)
pagedStrong    = paginate(filteredStrong, currentPage, PAGE_SIZE)
render(pagedStrong) + render(pageNav(filteredStrong.length)) + [weak-toggle + optional render(filteredWeak)]
```

This preserves the PR #5 contract (weak under threshold, toggled) and the earlier pagination work (10-per-page navigation for strong matches). Note that `displayCap` and `ALL_LIMIT` interact with CR-003: if `_search_with_rerank` is capped at ~300 candidates, pagination over 50 000 is moot.

## Suggested follow-up tickets

These group findings into ~5 GH issues a follow-up agent could pick up.

1. **Reranker hardening** — closes **CR-001**, **HI-001**, **HI-002**, **HI-003**, **ME-004**, **ME-009**, **LO-005**. Pin HF revisions; drop `trust_remote_code` where possible; bound `model.predict` batch size; surface fallback status; narrow exception catches; free device memory on swap.

2. **Pipeline contract clarity** — closes **CR-003**, **HI-005**, **HI-006**, **ME-002**, **ME-007**, **LO-004**, **LO-007**, **LO-008**, **LO-012**. Make `_search_with_rerank` public, split it, document the `limit` / `total` contract, type the `mode_hint`, add unit tests for the strong/weak split + fallback + saturation, rename `rerank` flag.

3. **UI conflict resolution + multi-collection search** — closes **CR-002**, **ME-010**. Land the suggested shape above; collapse `searchAcrossCollections` into a single API call.

4. **Defensive data layer** — closes **ME-001**, **ME-003**, **ME-006**, **LO-006**, **LO-010**, **LO-011**. Guard `COLLECTION_TIER` lookups; precompute display Arabic; add union retriever correctness tests; tidy late imports and dead comments.

5. **Operational polish** — closes **ME-005**, **ME-008**, **LO-001**, **LO-002**, **LO-003**, **LO-009**. Module-level thread pool; tighter CORS; share `_pick_device`; gate `optimum`/`onnxruntime` behind an optional dep; download only `safetensors`.

## Methodology

I read the full set of files PR #5 and PR #6 added or touched (`sunnah_toolkit/core/{data,retrieval,reranker,semantic,tools}.py`, `sunnah_toolkit/api/{app,ui}.py`, the four `scripts/*.py`, both `tests/*.py`, `pyproject.toml`, `Dockerfile`) plus a few adjacent files needed for context (`sunnah_toolkit/api/{auth,routes}.py`). I cross-referenced the two squash-merge diffs (`git diff 653d699 951bf36` for PR #6 and `git diff 951bf36 6912e48` for PR #5) to confirm which lines belong to which PR. I did not run the code — findings are based on static read-through.
