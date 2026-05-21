# sunnah-toolkit

REST and MCP API for the hadith corpus from [sunnah.com](https://sunnah.com).

Wraps the [`AhmedBaset/hadith-json`](https://github.com/AhmedBaset/hadith-json)
dataset (50,884 hadiths across 17 collections, pinned to `v1.2.0`) with hybrid
BM25 + multilingual-semantic search, and exposes the same 7 tools over two
transports:

- **MCP** — for AI assistants (Claude Desktop, Claude Code, Cursor, etc.) via
  stdio or streamable-http.
- **REST** — for everything else, at `/v1/*`.

## Tools

| Tool | What it does |
|------|--------------|
| `list_collections` | All 17 collections with names and hadith counts |
| `list_books` | Chapters within a collection (e.g. the 97 books of Bukhari) |
| `get_hadith` | Single hadith by collection + number, with Arabic + English + narrator |
| `search_hadith` | English keyword search, BM25-ranked |
| `search_hadith_term` | Find hadiths containing a specific Arabic term, accepting any transliteration spelling (`qunut`/`qunoot`/`qonot` all match قنوت; `azan`↔`adhan`, `ramazan`↔`ramadan`). Returns matched Arabic word frequencies so collisions are visible. |
| `search_hadith_semantic` | Meaning-based search via multilingual embeddings — handles conceptual queries (`humility`, `caring for orphans`) and cross-lingual queries (`الصلاة` finds the same hadiths as `prayer`). Returns similarity scores. |
| `random_hadith` | A random hadith, optionally from one collection |

Every result includes a `sunnah.com/<collection>:<number>` reference URL so
the model can cite accurately.

## Architecture

### Network topology

```mermaid
graph LR
    subgraph Internet
      Client["MCP client / curl"]
      CF["Cloudflare edge<br/>(TLS + rate-limit)"]
    end
    subgraph "Self-hosted server"
      Tunnel["cloudflared<br/>(outbound tunnel)"]
      Box["Docker container<br/>sunnah-toolkit :8000"]
    end
    Client -->|HTTPS| CF
    CF <-.->|persistent tunnel| Tunnel
    Tunnel -->|http://localhost:8000| Box
```

No inbound ports on the host — `cloudflared` opens an outbound tunnel to Cloudflare, which terminates TLS at the edge and forwards requests through the tunnel to the container.

### Components

```mermaid
graph TD
    subgraph Clients
      C1["MCP stdio<br/>(Claude Desktop / Code)"]
      C2["MCP HTTP<br/>(streamable-http)"]
      C3["REST<br/>(curl / apps)"]
    end

    subgraph Transports
      MCP["mcp/server.py<br/>FastMCP"]
      API["api/app.py + routes.py<br/>FastAPI · auth.py"]
    end

    subgraph "Core (protocol-agnostic)"
      Tools["core/tools.py<br/>7 tool functions"]
      Fmt["core/text_format.py"]
    end

    subgraph "Data &amp; algorithms"
      Data["core/data.py<br/>hadith JSON + BM25"]
      Sem["core/semantic.py<br/>embeddings + MiniLM"]
      Tr["core/translit.py<br/>Arabic folding"]
    end

    subgraph "On-disk assets"
      Raw[("data/raw/*.json")]
      Emb[("data/embeddings.npy")]
    end

    C1 --> MCP
    C2 --> MCP
    C3 --> API
    MCP --> Tools
    API --> Tools
    Tools --> Fmt
    Tools --> Data
    Tools --> Sem
    Tools --> Tr
    Data --> Raw
    Sem --> Emb
    Sem --> Raw
```

Both transports delegate to the same `core/tools.py` — REST returns structured JSON, MCP returns LLM-friendly text via `text_format.py`.

### Request flow — semantic search

```mermaid
sequenceDiagram
    participant C as Client
    participant A as auth.py
    participant R as routes.py
    participant T as tools.py
    participant S as semantic.py
    participant D as data.py
    participant F as text_format.py

    C->>A: GET /v1/search/semantic?query=…
    A->>A: check optional Bearer token
    A->>R: pass-through (anon or identified)
    R->>T: search_hadith_semantic(query, collection, limit)
    T->>S: encode(query) → vector
    S->>S: cosine sim vs embeddings.npy
    S-->>T: top-k hadith IDs + scores
    T->>D: hydrate(ids) → full records
    D-->>T: hadith records
    T->>F: format(records, scores)
    F-->>R: JSON (REST) / text (MCP)
    R-->>C: 200 OK
```

Semantic search exercises the most layers; BM25 keyword search (`/v1/search`) follows the same shape but skips `semantic.py` and queries `data.py`'s BM25 index directly.

### Auth flow

```mermaid
sequenceDiagram
    participant C as Client
    participant M as auth.py middleware
    participant R as route handler

    C->>M: request to /v1/* [Authorization?]

    alt no keys file loaded (open mode)
        M->>R: pass-through, caller=anonymous
        R-->>C: 200
    else keys file loaded
        alt no Authorization header
            M->>R: pass-through, caller=anonymous
            R-->>C: 200
        else valid Bearer token
            M->>R: pass-through, caller=alice
            R-->>C: 200
        else invalid Bearer token
            M-->>C: 401 Unauthorized
        end
    end

    Note over C,R: /mcp bypasses auth entirely (by design)
```

The keyed tier identifies callers; it does not gatekeep them. Rate-limiting and abuse control live at the Cloudflare edge.

### Build pipeline

```mermaid
graph LR
    subgraph Inputs
      DS["AhmedBaset/hadith-json<br/>@v1.2.0"]
      HF["HuggingFace<br/>MiniLM-L12-v2"]
    end

    subgraph "Build-time scripts"
      Fetch["scripts/fetch_data.py"]
      Build["scripts/build_embeddings.py"]
    end

    subgraph "On-disk artifacts"
      Raw[("data/raw/*.json<br/>~76 MB")]
      Emb[("data/embeddings.npy<br/>~75 MB")]
      Cache[("HF model cache<br/>~120 MB")]
    end

    Docker["Dockerfile<br/>multi-stage build"]
    Image["sunnah-toolkit image<br/>(~1.4 GB, offline at runtime)"]

    DS --> Fetch --> Raw
    HF --> Build
    Raw --> Build
    Build --> Emb
    Build --> Cache
    Raw --> Docker
    Emb --> Docker
    Cache --> Docker
    Docker --> Image
```

Data and model are baked into the image at build time — no network needed at query time, which is what lets the container survive Cloudflare outages and keeps cold-start latency predictable.

## Quickstart — local dev (stdio MCP)

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m scripts.fetch_data         # downloads ~76 MB hadith JSON into data/
.venv/bin/python -m scripts.build_embeddings   # one-time, ~3 min on Apple Silicon → data/embeddings.npy (~75 MB)
.venv/bin/python -m sunnah_toolkit             # runs MCP server over stdio
```

`build_embeddings` is only required if you'll use `search_hadith_semantic`.
It downloads the `paraphrase-multilingual-MiniLM-L12-v2` model (~120 MB) into
the HuggingFace cache on first run.

## Run as an HTTP server (Docker)

The included `Dockerfile` is a self-contained image (~1.4 GB) that bakes the
dataset, embeddings, and model cache in at build time — no network needed at
query time.

```bash
docker build -t sunnah-toolkit .
docker run --rm -p 8000:8000 sunnah-toolkit
```

The container exposes REST under `/v1/*`, MCP-over-HTTP at `/mcp`, and a
`/healthz` probe. To run HTTP mode without Docker:

```bash
.venv/bin/python -m sunnah_toolkit --transport http --host 0.0.0.0 --port 8000
```

## REST API

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/collections` | List all collections |
| GET | `/v1/collections/{slug}/books` | Chapters within a collection |
| GET | `/v1/hadith/{slug}/{number}` | Authoritative hadith fetch |
| GET | `/v1/search?query=…&collection=&limit=` | BM25 English keyword search |
| GET | `/v1/search/term?term=…&collection=&limit=` | Arabic-term search by transliteration |
| GET | `/v1/search/semantic?query=…&collection=&limit=` | Multilingual semantic search |
| GET | `/v1/random?collection=` | Random hadith |

Examples:

```bash
curl localhost:8000/v1/collections | jq '.collections[].slug'
curl localhost:8000/v1/hadith/bukhari/1 | jq
curl 'localhost:8000/v1/search/semantic?query=kindness+to+neighbours&limit=3' | jq
curl 'localhost:8000/v1/search/term?term=qunoot&limit=5' | jq
```

REST responses are structured JSON; MCP responses are LLM-friendly text. Both
transports share the same core (see `core/tools.py` + `core/text_format.py`).

## MCP integration

### stdio — Claude Code, Claude Desktop, Cursor

The included `.mcp.json` is auto-discovered by Claude Code. The same JSON
works in `~/Library/Application Support/Claude/claude_desktop_config.json`
for Claude Desktop:

```json
{
  "mcpServers": {
    "sunnah": {
      "type": "stdio",
      "command": "/absolute/path/to/sunnah-toolkit/.venv/bin/python",
      "args": ["-m", "sunnah_toolkit"],
      "cwd": "/absolute/path/to/sunnah-toolkit"
    }
  }
}
```

A project-level Claude Code skill ships at `.claude/skills/sunnah/SKILL.md` —
it documents tool-selection and enforces verbatim quoting. Claude Code picks
it up automatically; you can invoke it explicitly with `/sunnah`.

### Streamable-HTTP — when the toolkit runs over HTTP

The MCP endpoint is mounted at `/mcp` (no trailing-slash redirect). Point
any MCP client that speaks streamable-http transport at:

```
http://localhost:8000/mcp
```

## Auth

`/v1/*` supports optional bearer-token auth via a YAML keys file. Without a
keys file the server runs in **open mode** — any token (or none) accepted —
which is what you want for local dev.

`keys.yaml`:

```yaml
alice: a-long-random-token-for-alice
bob: a-long-random-token-for-bob
```

Run with auth enabled:

```bash
.venv/bin/python -m sunnah_toolkit --transport http --keys-file ./keys.yaml
```

Then call with:

```bash
curl -H 'Authorization: Bearer a-long-random-token-for-alice' \
  localhost:8000/v1/collections
```

Invalid tokens get 401; requests without an `Authorization` header fall
through as anonymous and still succeed. `/mcp` is unauthenticated by design —
the keyed tier exists for identification, and rate-limiting / abuse control
live at the edge (e.g. Cloudflare in front of the public instance).

## Self-hosting

Any Linux, Unix, or macOS host with Docker can run the container. Put a
reverse proxy (nginx, Caddy, Traefik) or a Cloudflare Tunnel in front for
TLS and a public hostname; use the platform's preferred service manager
(systemd, runit, OpenRC, etc.) to keep the container running across
reboots.

The simplest way to launch it is via the included `docker-compose.yml`:

```bash
docker compose up -d
```

Artifacts in `deploy/`:

- `deploy/cloudflared/config.yml.example` — Cloudflare Tunnel ingress example
  to expose `localhost:8000` on a hostname. Setup steps are in the file
  header.

- `deploy/keys.example.yaml` — example bearer-token map.

## Project layout

```
sunnah_toolkit/
  core/        protocol-agnostic library: tools, data loading, BM25,
               embeddings, Arabic transliteration, text formatters
  mcp/         FastMCP wrappers exporting the 7 tools over stdio + HTTP
  api/         FastAPI app: /v1/* routes, /healthz, bearer-token auth
  cli.py       argparse entrypoint: --transport {stdio,http}, --host,
               --port, --keys-file
scripts/
  fetch_data.py        downloads the pinned hadith dataset
  build_embeddings.py  pre-computes embeddings (run once per dataset change)
deploy/                cloudflared, keys.yaml examples
data/                  (gitignored) hadith JSON + embeddings.npy
Dockerfile             multi-stage, self-contained image
```

## Known limitations

- **Semantic search uses a small (~120 MB) multilingual model** —
  `paraphrase-multilingual-MiniLM-L12-v2`. Good baseline; conceptual queries
  on abstract terms (e.g. "humility in worship") may return adjacent rather
  than direct matches. Swappable: edit `MODEL_ID` in
  `scripts/build_embeddings.py` and rerun. OpenAI / Cohere / BGE-M3 are
  drop-in replacements (~$0.10 one-time re-embed cost for OpenAI's
  `text-embedding-3-small`).
- **Short skeletons can collide** in `search_hadith_term` (e.g. `azan`
  matches both أذان and زنى/أظن because both fold to `zn`). Mitigated by
  surfacing the matched Arabic words with frequencies so users can spot it.
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
