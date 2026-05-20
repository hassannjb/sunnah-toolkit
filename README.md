# sunnah-mcp

An [MCP](https://modelcontextprotocol.io/) server that exposes the hadith
corpus from [sunnah.com](https://sunnah.com) to AI assistants as structured
tool calls.

Built on the `AhmedBaset/hadith-json` dataset (50,884 hadiths across 17
collections, pinned to `v1.2.0`).

## Tools

| Tool | What it does |
|------|--------------|
| `list_collections` | All 17 collections with names and hadith counts |
| `list_books` | Chapters within a collection (e.g. the 97 books of Bukhari) |
| `get_hadith` | Single hadith by collection + number, with Arabic + English + narrator |
| `search_hadith` | English keyword search, BM25-ranked (optionally scoped) |
| `search_hadith_term` | Find hadiths containing a specific Arabic term, accepting any transliteration spelling (`qunut`/`qunoot`/`qonot` all match قنوت; `azan`↔`adhan`, `ramazan`↔`ramadan`). Returns matched Arabic word frequencies so collisions are visible. |
| `search_hadith_semantic` | Meaning-based search via multilingual embeddings — handles conceptual queries (`humility`, `caring for orphans`) and cross-lingual queries (`الصلاة` finds the same hadiths as `prayer`). Returns similarity scores. |
| `random_hadith` | A random hadith, optionally from one collection |

Every result includes a `sunnah.com/<collection>:<number>` reference URL so
the model can cite accurately.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m scripts.fetch_data         # downloads ~76 MB hadith JSON into data/
.venv/bin/python -m scripts.build_embeddings   # one-time, ~3 min on Apple Silicon → data/embeddings.npy (~75 MB)
```

The `build_embeddings` step is only needed if you'll use `search_hadith_semantic`. It downloads the multilingual MiniLM model (~120 MB) on first run.

## Run

### Manually (stdio)
```bash
.venv/bin/python -m sunnah_mcp
```

### From the MCP Inspector
```bash
.venv/bin/mcp dev sunnah_mcp/server.py
```

### From Claude Code
The included `.mcp.json` is auto-discovered. Restart Claude Code, then run
`/mcp` and approve the `sunnah` server.

A project-level **Claude Code Skill** also ships at
`.claude/skills/sunnah/SKILL.md`. It documents when to use which tool and
restates the verbatim-quoting policy at the Skill layer. Claude Code picks
it up automatically; you can invoke it explicitly with `/sunnah` or rely on
Claude activating it when a hadith-related question is asked.

### From Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sunnah": {
      "command": "/absolute/path/to/sunnah-mcp/.venv/bin/python",
      "args": ["-m", "sunnah_mcp"],
      "cwd": "/absolute/path/to/sunnah-mcp"
    }
  }
}
```

## Project layout

```
sunnah_mcp/
  server.py            FastMCP entrypoint, defines all tools
  data.py              loads JSON files into in-memory Library; BM25 + Arabic-skeleton indexes
  translit.py          consonant-skeleton folding for transliteration-tolerant matching
  semantic.py          lazy-loaded embeddings engine for meaning-based search
  format.py            LLM-friendly text formatters
  __main__.py          `python -m sunnah_mcp`
scripts/
  fetch_data.py        downloads the pinned hadith dataset
  build_embeddings.py  pre-computes embeddings (run once per dataset change)
data/                  (gitignored) hadith JSON + embeddings.npy live here
```

## Known limitations / future work

- **Semantic search uses a small (120 MB) multilingual model** — `paraphrase-multilingual-MiniLM-L12-v2`. Good baseline; conceptual queries on
  abstract terms (e.g. "humility in worship") may return adjacent rather
  than direct matches. Swappable: edit `MODEL_ID` in `scripts/build_embeddings.py`
  and rerun. OpenAI/Cohere/BGE-M3 are drop-in replacements (~$0.10 one-time
  re-embed cost for OpenAI's text-embedding-3-small).
- **Short skeletons can collide** in `search_hadith_term` (e.g. `azan` matches
  both أذان and زنى/أظن because both fold to `zn`). Mitigated by surfacing the
  matched Arabic words with frequencies so users can spot it.
- **Darimi has no English translation** in the dataset — its 3,406 hadiths
  are masked out of semantic search; they still appear in `get_hadith` etc.
- **One English translation** per hadith — the dataset doesn't include
  alternative translations.
- **Musnad Ahmad** chapters 8–30 are missing in the upstream dataset.
- **No grading info** (sahih / hasan / da'if) — not in the dataset.

## Credits

- Data: [AhmedBaset/hadith-json](https://github.com/AhmedBaset/hadith-json)
  (scraped from sunnah.com), released under its own terms.
- Reference architecture: [quran/quran-mcp](https://github.com/quran/quran-mcp).
- Protocol: [Model Context Protocol](https://modelcontextprotocol.io/).
