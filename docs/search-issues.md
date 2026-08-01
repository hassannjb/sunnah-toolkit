# Search-quality issues

A running list of issues observed in the demo UI search. Captured for triage
before any solutioning. Each entry: query, mode, what we got, what we wanted,
plus notes.

---

## 1. Relevance ranking — no quality ordering

Issue: Results are not ordered by relevance. They should rank by:
  1. Collection prestige — the two Sahihs first (Bukhari, then Muslim),
     then the remaining collections.
  2. Hadith grade — Sahih > Hasan-Sahih > Hasan > ... within each tier.

Query: (any — e.g. "dua")
Mode: Concept, Keyword, Arabic term
Got: Term mode sorts by `(collection, id_in_book)` alphabetically (so
  abudawud comes before bukhari). Keyword (BM25) sorts by raw score with
  no collection/grade weight. Semantic sorts by cosine similarity, same.
Expected: Bukhari and Muslim hits float to the top; within a collection,
  Sahih hadiths come before lower grades.
Notes: This is the dominant UX complaint — even with the chip filter,
  page 1 is not "the best matches" by any classical standard.

---

## 2. Result sets are too broad (Concept + Arabic term)

Issue: For common-ish queries, both Concept and Arabic term modes return
  thousands of results. "dua" should not be relevant to 10,000+ hadiths.

Query: "dua"
Mode: Arabic term, Concept
Got: 15,360 matches in term mode; semantic returns its full top-K too.
Expected: A tighter, higher-precision result set. Quality over quantity.
Notes: Tied to issue #3 (loose Arabic matching) and issue #1 (no ranking).
  Even after better ranking, the long tail of weak matches is still noise.

---

## 3. Arabic term matching is too loose

Issue: The skeleton-folding match in term mode collapses too many
  unrelated Arabic words onto the same skeleton, so the index returns
  hadiths that have nothing to do with the query.

Query: "dua"  (intended Arabic: دعاء / دعا — "supplication")
Mode: Arabic term
Got: Top "matched words" reported by the API:
  - إذا       ×6109   (NOT relevant — "when/if")
  - داود     ×3615   (NOT relevant — "Dawud" / proper noun)
  - وإذا     ×1082   (NOT relevant — "and when")
  - عدي      ×687    (NOT relevant — "Adi" / proper noun)
  - يده      ×676    (NOT relevant — "his hand")
  - إذ       ×644    (NOT relevant — "when")
  - أعوذ    ×411    (NOT relevant — "I seek refuge")
  - دعا      ×382    (relevant — "he supplicated")
Expected: Only words from the دعا/دعاء family (or close cousins). The
  hundreds-to-thousands counts on the non-relevant words swamp the
  ~382 actually-relevant matches.
Notes: The fold step is throwing away too much information (vowels,
  hamza, maybe geminations). Needs a tighter folding model — possibly
  per-language phonetic + root-aware rather than pure consonant skeleton.

Related example: searches like
  - "sleep supplication"
  - "supplication for sleep"
  - "supplication before sleep"
  …return hadiths that mention sleep OR supplication but miss a clearly
  relevant chapter that exists: Sahih Muslim Book 17 "Supplication When
  Going To Sleep". A user reading the index would expect that chapter's
  hadiths to dominate page 1.
Notes (cont'd): That last example is technically Concept-mode behaviour,
  but it shows the same underlying problem — neither mode is aligning
  results with what a knowledgeable user would consider the canonical
  answer set for the query.

---

## 4. Underlying models may not be best-fit (BM25 + embeddings)

Issue: Current stack is BM25 for keyword and a sentence-transformers
  embedding for semantic. We should evaluate whether more advanced
  / better-tuned models exist — especially ones that handle:
  - English ⇄ Arabic alignment
  - Religious / Islamic-text register specifically
  - Multilingual queries cleanly

Query: N/A (model-level)
Mode: Keyword, Concept
Got: BM25 keyword scoring; current embedding model is whatever
  `embeddings_meta.json` points to.
Expected: A research pass on alternative models (e.g. mE5, BGE-M3,
  Arabic-specific encoders, or hadith-domain-fine-tuned ones) with
  a concrete comparison.
Notes: Pre-req before doing this: build an eval set of "expected good
  results" for ~20 representative queries so model swaps can be measured,
  not just felt.

---

## 5. Natural-language queries (with optional LLM in front)

Issue: The UI exposes four discrete modes (Concept / Keyword / Arabic
  term / Reference) but doesn't accept full natural-language questions
  like "what did the Prophet say about anger?" or "is there a dua for
  rain?". Users have to pick a mode and phrase appropriately.

Query: "what did the Prophet say about anger"
Mode: N/A (mode-design level)
Got: Have to pick Concept and hope the embedding catches it.
Expected: A single search box where natural-language input works.
  Optionally route through an LLM that:
    - decides the right underlying mode(s)
    - rewrites the query (e.g. extracts "anger" + "Prophet")
    - composes/ranks results across modes
Notes: An LLM hop costs latency + API spend per query. Evaluate whether
  a routing / rewriting LLM in front of the existing modes is enough,
  or whether the LLM should also re-rank the candidate set.

---

## Notes for triage (not issues)

- Issues 1, 2, 3 are intertwined: better ranking (1) makes the breadth
  in (2) less painful; tighter Arabic match (3) directly shrinks (2).
- Issues 4 and 5 are bigger investments — model evaluation and
  LLM-in-the-loop respectively. Worth holding until 1–3 are scoped.
- An eval set is a prerequisite for 4 and very useful for 1–3.
