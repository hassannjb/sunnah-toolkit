---
name: sunnah
description: Use when the user asks about hadith, sunnah, or citing Islamic narrations — e.g. quoting Bukhari/Muslim/Nawawi-40 by reference, finding hadiths by English keyword, finding hadiths by Arabic term (qunut, ramazan, azan) regardless of spelling, or finding hadiths by concept ("kindness to neighbours", "what the Prophet said about anger"). Enforces verbatim quoting with collection + hadith-number citations.
---

# Sunnah skill

This project ships an MCP server (`sunnah-mcp`) with 50,884 hadiths across
17 collections, sourced from sunnah.com. This skill teaches you how to use
its tools effectively and how to cite the results correctly.

## QUOTING POLICY (non-negotiable)

The Quran and hadith are religious primary sources. Misquoting them is the
worst possible failure mode of this skill. Always:

1. **Never paraphrase, summarise, or reword a hadith.** Reproduce English and
   Arabic verbatim from the tool output.
2. **Always cite the collection's English title + hadith number**, e.g.
   "Sahih al-Bukhari #1", not "Bukhari" or "the first hadith of Bukhari".
3. **Search results are TRUNCATED SNIPPETS for ranking**, not quote sources.
   If you intend to quote, call `get_hadith(collection, number)` first to
   retrieve the verbatim text.
4. **Do not fabricate Arabic.** Only include Arabic that came directly from
   a tool output. If the user asks for Arabic and you only have English,
   call `get_hadith` to retrieve it.
5. **Include the reference URL** when `get_hadith` returns one
   (`sunnah.com/<slug>:<number>`).

## Available tools

| Tool | What it does |
|------|--------------|
| `list_collections` | Show the 17 collections with names and hadith counts. |
| `list_books(collection)` | Show the chapter/book list for one collection. |
| `get_hadith(collection, number)` | **Authoritative.** Fetch one hadith verbatim with Arabic, English, narrator, and reference. |
| `search_hadith(query)` | English keyword search, BM25-ranked. Returns snippets. |
| `search_hadith_term(term)` | Find hadiths containing a specific Arabic term, accepting any transliteration. Returns snippets + matched Arabic words. |
| `search_hadith_semantic(query)` | Meaning-based search (multilingual embeddings). Returns snippets + similarity scores. |
| `random_hadith` | A random hadith (or one from a given collection). Authoritative. |

## Tool-selection cheat sheet

| User intent | Pick |
|---|---|
| "Show me Bukhari hadith #1" / any explicit reference | `get_hadith` |
| "What collections do you have?" | `list_collections` |
| "Give me the table of contents of Muslim" | `list_books` |
| "Find hadiths with the word 'intentions'" (literal English keyword) | `search_hadith` |
| "Find hadiths about kindness to neighbours" (concept) | `search_hadith_semantic` |
| "Find hadiths about prayer / fasting" (English term, want translation) | `search_hadith_semantic` |
| "Find hadiths mentioning qunut" / "qunoot" / "qonot" (Arabic term, variable spelling) | `search_hadith_term` |
| "Find hadiths mentioning azan" / "ramazan" / "adhan" | `search_hadith_term` |
| "Show me a random hadith" / "daily hadith" | `random_hadith` |

When in doubt between `search_hadith` and `search_hadith_semantic`, prefer
`search_hadith_semantic` — it handles both exact words and concepts and
works across English/Arabic queries.

## Standard workflows

### A) User references a specific hadith
> "Tell me Bukhari #1"

1. `get_hadith("bukhari", 1)`
2. Quote the returned English text verbatim, include the narrator and the
   citation "Sahih al-Bukhari #1".
3. Include Arabic only if the user asked for it (don't assume).

### B) User asks for hadiths about a topic
> "What does the Prophet say about anger?"

1. `search_hadith_semantic("what does the prophet say about anger?", limit=5)`
2. Review the snippets and pick the most relevant 1–3 (check similarity
   scores; >0.6 is usually solid, <0.4 is weak).
3. For *each* hadith you intend to quote, call
   `get_hadith(collection, number)` to retrieve the verbatim text.
4. Present each as: title, narrator, full English quote, citation.

### C) User asks for hadiths containing a specific Arabic term
> "Find hadiths about qunoot"

1. `search_hadith_term("qunoot", limit=10)`
2. Look at the "Matched Arabic words" line in the result — it shows
   frequency per Arabic word. If the dominant matches are قنوت / قنت /
   يقنت, you're on target. If you see unrelated short-skeleton collisions
   (e.g. for `azan` you might see زنى, أظن), prefer hadiths matched on the
   intended Arabic word.
3. For hadiths you want to quote, call `get_hadith` to retrieve verbatim
   text. Identify the matched Arabic word in the Arabic line if you can.

### D) User asks "how many hadiths are there about X?"

1. Pick the tool that actually produces a count:
   - `search_hadith_term` — reports total matches for an Arabic term.
   - `search_hadith` — reports total BM25 matches for English keyword(s).
   - `search_hadith_semantic` does **not** produce a count — it ranks the
     whole corpus by similarity. Don't quote a number from it.
2. Read the "Found N hadith(s)…" header — that is the dataset-wide total,
   not the number of rows shown. Don't fabricate counts.

## Pitfalls to avoid

- **Don't quote from a snippet.** Search results truncate at ~140-200
  characters. Quoting from them produces incomplete sentences. Always call
  `get_hadith` for the full text before quoting.
- **Don't fabricate Arabic.** If a tool didn't return Arabic, fetch it via
  `get_hadith` rather than generating it.
- **Don't paraphrase even for "convenience".** Verbatim is the requirement.
  If you need a shorter version, use ellipses to mark omitted spans:
  *"The reward of deeds depends upon the intentions … so whoever emigrated
  for worldly benefits ..."*
- **Watch short-skeleton collisions** in `search_hadith_term`. The "Matched
  Arabic words" header makes them visible — use it.
- **For semantic search, treat low similarity as uncertainty.** A
  similarity of 0.35 means "the closest hadith I found" — not "the right
  hadith." Tell the user the match is weak; offer to refine the query.
- **Darimi has no English text in the dataset.** Semantic search masks it
  out automatically, but `get_hadith("darimi", N)` will return an empty
  English field. Inform the user when this happens; the Arabic is still
  available.

## When tools fail

- `Unknown collection: 'X'` — call `list_collections` to show valid slugs,
  then ask the user which one.
- `No hadith #N in <collection>. Valid range: 1..M.` — surface the range
  to the user and offer to fetch a nearby hadith.
- `Semantic search unavailable: Embeddings not built.` — instruct the user
  to run `python -m scripts.build_embeddings` from the project root.
