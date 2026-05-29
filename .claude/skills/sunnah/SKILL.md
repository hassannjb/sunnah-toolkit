---
name: sunnah
description: Use when the user asks about hadith, sunnah, or citing Islamic narrations — e.g. quoting Bukhari/Muslim/Nawawi-40 by reference, finding hadiths by English keyword, finding hadiths by Arabic term (qunut, ramazan, azan) regardless of spelling, or finding hadiths by concept ("kindness to neighbours", "what the Prophet said about anger"). Enforces verbatim quoting with collection + hadith-number citations.
---

# Sunnah skill

This project ships the `sunnah-toolkit` package, which exposes 44,896 hadiths
across 15 collections (sourced from sunnah.com's official MariaDB snapshot)
over both MCP and a REST API at `/v1`. This skill uses the MCP surface —
REST is documented in the README. It teaches you how to use the tools
effectively and how to cite results correctly.

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
6. **Surface the grading** when it's present. The dataset carries an
   `english_grade` field per hadith (`Sahih`, `Hasan`, `Da'if`, `Sahih Isnād`,
   sometimes empty). When you quote a hadith and the grade is non-empty,
   include it inline, e.g. "Sahih al-Bukhari #1 (Sahih) — …". Don't infer or
   fabricate a grade if the field is empty.

## SCHOLARLY POLICY (non-negotiable)

This toolkit surfaces primary-source text. It is not a fatwa-issuing
authority, and you are not acting as a scholar when you use it. Always:

1. **Do not issue fatwas or legal rulings.** Present what the hadith says.
   Do not declare something *halal* or *haram* unless that exact ruling word
   appears in the quoted text. For any "is X allowed / forbidden / obligatory?"
   question, present the relevant hadith(s) and close with:
   *"For a formal ruling applicable to your situation, please consult a
   qualified scholar."*
2. **Do not take a position between madhabs.** When the hadiths you've
   surfaced could support different scholarly interpretations, present the
   text and note: *"Scholars of different madhabs have interpreted this
   differently — please consult a qualified scholar for guidance specific to
   your madhab."* Don't pick a side.
3. **Close sensitive-topic answers with scholarly-humility language.** For
   jurisprudence, family / marriage disputes, inheritance, Islamic finance,
   medical questions, or any personal-situation guidance, end the response
   by recommending the user consult a qualified local scholar who knows
   their full context. The text is necessary but not sufficient for personal
   rulings.

## Available tools

| Tool | What it does |
|------|--------------|
| `list_collections` | Show the 15 collections with names and hadith counts. |
| `list_books(collection)` | Show the chapter/book list for one collection. |
| `get_hadith(collection, number)` | **Authoritative.** Fetch one hadith verbatim with Arabic, English, narrator, **grading**, the **structured isnad chain** (narrator IDs + roles + canonical names), and reference URL. |
| `search_hadith(query)` | English keyword search, BM25-ranked. Returns snippets with per-hit grading. |
| `search_hadith_term(term)` | Find hadiths containing a specific Arabic term, accepting any transliteration. Returns snippets + matched Arabic words + per-hit grading. |
| `search_hadith_semantic(query)` | Meaning-based search (multilingual embeddings). Returns snippets + similarity scores + per-hit grading. |
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
| "What's the grading of this hadith?" / "Is this sahih?" | `get_hadith` (read the `english_grade` field) |
| "Who's in the chain for this hadith?" / "Trace the isnad" | `get_hadith` (read the `chain` list) |

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
- **Darimi and Muwatta Malik are not in this toolkit.** sunnah.com doesn't
  host them in the snapshot we use. If a user asks for them, say so plainly
  and offer an equivalent from another collection where possible.
- **The isnad chain is structured.** `get_hadith` returns a `chain` list
  with the narrators in order, each carrying `{position, id, role, tooltip,
  inline_name}`. `role` is usually `first` for the immediate narrator,
  `chain` for intermediate links, and `sahabi` for the Companion at the end.
  If the user asks about the chain or wants to trace narrators, draw from
  this list directly — don't paraphrase it from the Arabic text.

## When tools fail

- `Unknown collection: 'X'` — call `list_collections` to show valid slugs,
  then ask the user which one.
- `No hadith #N in <collection>. Valid range: 1..M.` — surface the range
  to the user and offer to fetch a nearby hadith.
- `Semantic search unavailable: Embeddings not built.` — instruct the user
  to run `python -m scripts.build_embeddings` from the project root.
