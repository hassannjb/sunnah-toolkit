"""Tiny single-page demo UI for non-developers.

Served at `GET /` (registered before the MCP mount in app.py). The page is one
self-contained HTML document — no framework, no build step, no static assets.
Same-origin XHR to /v1/... means no CORS or auth dance for the user.
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sunnah Toolkit</title>
  <style>
    * { box-sizing: border-box; }
    :root {
      --bg: #faf9f5;
      --card: #ffffff;
      --text: #1c1c1c;
      --muted: #6b6b6b;
      --accent: #0f7058;
      --accent-hover: #0a5644;
      --border: #e5e3da;
      --soft: #f3f1e8;
    }
    html, body { margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.55;
      padding: 1rem;
    }
    main { max-width: 720px; margin: 0 auto; }
    header { margin-bottom: 1.25rem; }
    h1 { margin: 0 0 0.25rem; font-size: 1.5rem; font-weight: 700; }
    .sub { color: var(--muted); margin: 0; font-size: 0.95rem; }
    form {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem;
      margin-bottom: 1rem;
    }
    #q {
      width: 100%;
      padding: 0.8rem 0.9rem;
      font-size: 1rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
    }
    #q:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
    fieldset { border: none; padding: 0; margin: 1rem 0 0; }
    legend { font-size: 0.85rem; color: var(--muted); padding: 0; margin-bottom: 0.4rem; }
    #modes label {
      display: flex;
      align-items: baseline;
      gap: 0.6rem;
      padding: 0.5rem 0.6rem;
      border-radius: 6px;
      cursor: pointer;
      flex-wrap: wrap;
    }
    #modes label:hover { background: var(--soft); }
    #modes input[type="radio"] { margin: 0; flex-shrink: 0; }
    .lbl { font-weight: 600; min-width: 7.5rem; }
    .hint { color: var(--muted); font-size: 0.85rem; }
    .actions { display: flex; gap: 0.5rem; margin-top: 1rem; flex-wrap: wrap; }
    button {
      padding: 0.75rem 1.25rem;
      font-size: 1rem;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
      font-family: inherit;
    }
    button[type="submit"] { background: var(--accent); color: white; flex: 1 1 auto; min-width: 8rem; }
    button[type="submit"]:hover { background: var(--accent-hover); }
    #random-btn { background: var(--card); border: 1px solid var(--border); color: var(--text); }
    #random-btn:hover { background: var(--soft); }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    #status { color: var(--muted); padding: 0.25rem 0.25rem 0.75rem; font-size: 0.95rem; }
    #status.error { color: #b03a2e; }
    .hidden { display: none; }
    .result-row {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.85rem 1rem;
      margin-bottom: 0.6rem;
      cursor: pointer;
      transition: border-color 0.1s, background 0.1s;
    }
    .result-row:hover { border-color: var(--accent); background: #fff; }
    .result-row .ref { font-weight: 600; color: var(--accent); margin-bottom: 0.2rem; font-size: 0.95rem; }
    .result-row .snippet { color: var(--muted); font-size: 0.92rem; }
    .result-row .score { float: right; font-size: 0.8rem; color: var(--muted); font-weight: 400; }
    .result-row.weak { border-color: #e2d5b8; background: #fbfaf3; }
    .result-row.weak:hover { border-color: #c9b988; background: #fff; }
    .weak-divider {
      margin: 0.9rem 0 0.5rem;
      padding: 0.45rem 0.6rem;
      border-top: 1px dashed var(--border);
      color: var(--muted);
      font-size: 0.85rem;
    }
    .weak-toggle {
      display: inline-block;
      margin: 0.6rem 0;
      padding: 0.35rem 0.7rem;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--card);
      cursor: pointer;
      font-size: 0.9rem;
    }
    .weak-toggle:hover { border-color: var(--accent); }
    .hadith {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.25rem;
      margin-bottom: 1rem;
    }
    .hadith .ref { font-size: 1.05rem; font-weight: 700; color: var(--accent); margin-bottom: 0.6rem; }
    .hadith .narrator { font-style: italic; color: var(--muted); margin-bottom: 0.6rem; font-size: 0.95rem; }
    .hadith .english { white-space: pre-wrap; margin-bottom: 0.9rem; }
    .hadith .arabic {
      direction: rtl;
      text-align: right;
      font-family: "Amiri", "Scheherazade New", "Traditional Arabic", serif;
      font-size: 1.2rem;
      line-height: 2;
      padding-top: 0.85rem;
      border-top: 1px solid var(--border);
    }
    .hadith .meta {
      margin-top: 0.85rem;
      font-size: 0.85rem;
      color: var(--muted);
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
      align-items: center;
    }
    .hadith .meta a { color: var(--accent); text-decoration: none; }
    .hadith .meta a:hover { text-decoration: underline; }
    .term-hits {
      background: var(--soft);
      border-radius: 8px;
      padding: 0.7rem 0.85rem;
      margin-bottom: 0.7rem;
      font-size: 0.88rem;
      color: var(--muted);
      line-height: 1.7;
    }
    .term-hits .th-label {
      display: block;
      font-size: 0.82rem;
      margin-bottom: 0.45rem;
    }
    .word-chip, .rc-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.25rem 0.65rem;
      margin: 0 0.35rem 0.35rem 0;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      cursor: pointer;
      font-size: 0.85rem;
      color: var(--text);
    }
    .word-chip:hover, .rc-chip:hover { border-color: var(--accent); }
    .word-chip input, .rc-chip input { margin: 0; }
    .word-chip .word {
      font-family: "Amiri", "Scheherazade New", serif;
      font-size: 1.05rem;
    }
    .word-chip .word-count, .rc-chip .rc-count { color: var(--muted); }
    .result-chips {
      background: var(--soft);
      border-radius: 8px;
      padding: 0.7rem 0.85rem;
      margin-bottom: 0.6rem;
      font-size: 0.88rem;
      color: var(--muted);
      line-height: 1.7;
    }
    .result-chips .rc-label {
      display: block;
      font-size: 0.82rem;
      margin-bottom: 0.45rem;
    }
    .result-chips .rc-actions {
      display: inline-block;
      margin-left: 0.4rem;
    }
    .result-chips .rc-actions button {
      padding: 0.15rem 0.55rem;
      font-size: 0.78rem;
      background: transparent;
      color: var(--accent);
      border: 1px solid var(--border);
      font-weight: 500;
      border-radius: 12px;
      margin-left: 0.25rem;
    }
    .result-chips .rc-actions button:hover { background: var(--card); }
    #coll-filter {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.5rem 0.9rem;
      margin-top: 0.9rem;
    }
    #coll-filter[open] { padding-bottom: 0.85rem; }
    #coll-filter > summary {
      cursor: pointer;
      font-size: 0.9rem;
      color: var(--muted);
      padding: 0.3rem 0;
      list-style: revert;
    }
    #coll-filter > summary:hover { color: var(--text); }
    #coll-count {
      font-weight: 600;
      color: var(--text);
      margin-left: 0.25rem;
    }
    .coll-controls {
      display: flex;
      gap: 0.5rem;
      margin: 0.5rem 0 0.4rem;
    }
    .coll-controls button {
      padding: 0.3rem 0.7rem;
      font-size: 0.82rem;
      background: transparent;
      color: var(--accent);
      border: 1px solid var(--border);
      font-weight: 500;
    }
    .coll-controls button:hover { background: var(--soft); }
    #coll-checkboxes {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 0.15rem;
      margin-top: 0.35rem;
    }
    .coll-item {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.35rem 0.5rem;
      cursor: pointer;
      border-radius: 4px;
      font-size: 0.9rem;
    }
    .coll-item:hover { background: var(--soft); }
    .coll-item input { margin: 0; flex-shrink: 0; }
    .coll-name { flex: 1; }
    .coll-hcount { color: var(--muted); font-size: 0.78rem; }
    .page-nav {
      display: flex;
      gap: 0.3rem;
      justify-content: center;
      align-items: center;
      margin: 1rem 0 0.5rem;
      flex-wrap: wrap;
    }
    .page-nav .pn-btn {
      padding: 0.4rem 0.7rem;
      font-size: 0.9rem;
      background: var(--card);
      border: 1px solid var(--border);
      color: var(--text);
      font-weight: 500;
      min-width: 2.4rem;
    }
    .page-nav .pn-btn:hover:not(:disabled) { background: var(--soft); border-color: var(--accent); }
    .page-nav .pn-btn.pn-current {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
      cursor: default;
    }
    .page-nav .pn-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .page-nav .pn-ellipsis { color: var(--muted); padding: 0 0.2rem; }
    footer { margin-top: 2rem; text-align: center; color: var(--muted); font-size: 0.8rem; }
    footer a { color: var(--muted); }
    @media (max-width: 480px) {
      .lbl { min-width: 6rem; }
      .hint { width: 100%; padding-left: 1.7rem; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Sunnah Toolkit</h1>
      <p class="sub">Search 44,896 hadiths across 15 classical collections.</p>
    </header>

    <form id="f">
      <input type="text" id="q" placeholder="Type a question, keyword, term, or reference&hellip;" autocomplete="off" autofocus>

      <fieldset id="modes">
        <legend>Search mode</legend>
        <label>
          <input type="radio" name="m" value="semantic" checked>
          <span class="lbl">Concept</span>
          <span class="hint">meaning-based, e.g. <em>kindness to neighbours</em></span>
        </label>
        <label>
          <input type="radio" name="m" value="keyword">
          <span class="lbl">Keyword</span>
          <span class="hint">English word match, e.g. <em>intentions</em></span>
        </label>
        <label>
          <input type="radio" name="m" value="term">
          <span class="lbl">Arabic term</span>
          <span class="hint">transliteration-tolerant, e.g. <em>qunut</em>, <em>ramazan</em></span>
        </label>
        <label>
          <input type="radio" name="m" value="reference">
          <span class="lbl">Reference</span>
          <span class="hint">exact lookup, e.g. <em>Bukhari 1</em>, <em>Sahih Muslim 5</em></span>
        </label>
        <label>
          <input type="radio" name="m" value="natural">
          <span class="lbl">Natural language</span>
          <span class="hint">free-form, e.g. <em>what did the Prophet say about anger?</em></span>
        </label>
      </fieldset>

      <details id="coll-filter">
        <summary>Filter by collection <span id="coll-count">(15 of 15)</span></summary>
        <div class="coll-controls">
          <button type="button" id="coll-all">Select all</button>
          <button type="button" id="coll-none">Clear</button>
        </div>
        <div id="coll-checkboxes"></div>
      </details>

      <div class="actions">
        <button type="submit" id="search-btn">Search</button>
        <button type="button" id="random-btn">&#127922; Random hadith</button>
      </div>
    </form>

    <section id="status" class="hidden"></section>
    <section id="results">
      <div id="results-header"></div>
      <div id="results-rows"></div>
      <div id="page-nav"></div>
    </section>
    <section id="detail"></section>

    <footer>
      <p>Hadith data from <a href="https://sunnah.com" target="_blank" rel="noopener">sunnah.com</a>.</p>
    </footer>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const form = $("f");
    const qIn = $("q");
    const statusEl = $("status");
    const resultsHeaderEl = $("results-header");
    const resultsRowsEl = $("results-rows");
    const pageNavEl = $("page-nav");
    const detailEl = $("detail");

    const PAGE_SIZE = 10;
    const ALL_LIMIT = 50000;
    let currentPage = 1;
    const searchBtn = $("search-btn");
    const randomBtn = $("random-btn");
    const collCountEl = $("coll-count");
    const collBoxEl = $("coll-checkboxes");
    const collAllBtn = $("coll-all");
    const collNoneBtn = $("coll-none");

    // Collection lookup tables built from /v1/collections on load.
    const collections = {};      // slug -> {slug, english_title, ...}
    const slugByAlias = {};      // normalised name -> slug
    const selectedCollections = new Set();   // checked slugs

    // Last search state. Cached so the result-level chip filters
    // (collection chips for all modes; matched-Arabic-word chips in term mode)
    // can re-filter the displayed rows without re-fetching.
    let lastResults = [];
    let lastResultsWeak = [];                // below-threshold matches from rerank pipeline
    let weakVisible = false;                 // toggled by "Show N weak matches"
    let lastMode = null;
    let lastShowScore = false;
    let lastMatchedWords = [];               // term mode only
    let selectedWords = new Set();           // Arabic strings (term mode)
    let selectedResultCollections = new Set(); // slugs present in current results
    let lastFallback = null;                 // "llm_unavailable" | "router_failed" | null

    // Six canonical books listed first in the filter, then the rest A→Z.
    const CANONICAL_ORDER = ["bukhari", "muslim", "abudawud", "tirmidhi", "nasai", "ibnmajah"];

    const NAME_PREFIXES = ["sahih", "sunan", "jami", "musnad", "al", "an", "ar", "as", "at", "az", "ad"];

    function norm(s) {
      return (s || "")
        .toLowerCase()
        .replace(/[‘’']/g, "")
        .replace(/[-_.]/g, "")
        .replace(/\s+/g, "");
    }

    function indexAlias(name, slug) {
      let n = norm(name);
      if (!n) return;
      slugByAlias[n] = slug;
      // Strip leading prefixes (sahih, sunan, al-, an-, …) progressively.
      let changed = true;
      while (changed) {
        changed = false;
        for (const p of NAME_PREFIXES) {
          if (n.startsWith(p) && n.length > p.length) {
            n = n.slice(p.length);
            slugByAlias[n] = slug;
            changed = true;
          }
        }
      }
    }

    async function loadCollections() {
      try {
        const r = await fetch("/v1/collections");
        if (!r.ok) throw new Error("HTTP " + r.status);
        const j = await r.json();
        for (const c of (j.collections || [])) {
          collections[c.slug] = c;
          indexAlias(c.slug, c.slug);
          indexAlias(c.english_title, c.slug);
        }
        // A couple of hand-tuned aliases people will actually type
        slugByAlias[norm("nawawi")] = "forty";
        slugByAlias[norm("nawawi40")] = "forty";
        slugByAlias[norm("riyadussaliheen")] = "riyadussalihin";
        renderCollectionCheckboxes();
      } catch (e) {
        setStatus("Could not load collections: " + e.message, true);
      }
    }

    function renderCollectionCheckboxes() {
      const inCanonical = CANONICAL_ORDER.filter((s) => collections[s]).map((s) => collections[s]);
      const seen = new Set(inCanonical.map((c) => c.slug));
      const rest = Object.values(collections)
        .filter((c) => !seen.has(c.slug))
        .sort((a, b) => a.english_title.localeCompare(b.english_title));
      const ordered = inCanonical.concat(rest);
      collBoxEl.innerHTML = ordered.map((c) =>
        '<label class="coll-item">' +
          '<input type="checkbox" value="' + escapeHtml(c.slug) + '" checked>' +
          '<span class="coll-name">' + escapeHtml(c.english_title) + '</span>' +
          '<span class="coll-hcount">' + (c.hadith_count || 0).toLocaleString() + '</span>' +
        '</label>'
      ).join("");
      for (const c of ordered) selectedCollections.add(c.slug);
      updateCollCount();
      collBoxEl.addEventListener("change", () => {
        selectedCollections.clear();
        collBoxEl.querySelectorAll("input:checked").forEach((i) => selectedCollections.add(i.value));
        updateCollCount();
      });
    }

    function updateCollCount() {
      const total = Object.keys(collections).length;
      collCountEl.textContent = "(" + selectedCollections.size + " of " + total + ")";
    }

    collAllBtn.addEventListener("click", () => {
      collBoxEl.querySelectorAll("input").forEach((i) => { i.checked = true; });
      collBoxEl.dispatchEvent(new Event("change", { bubbles: true }));
    });
    collNoneBtn.addEventListener("click", () => {
      collBoxEl.querySelectorAll("input").forEach((i) => { i.checked = false; });
      collBoxEl.dispatchEvent(new Event("change", { bubbles: true }));
    });

    function setStatus(msg, isError = false) {
      if (!msg) {
        statusEl.classList.add("hidden");
        statusEl.textContent = "";
        return;
      }
      statusEl.textContent = msg;
      statusEl.classList.toggle("error", !!isError);
      statusEl.classList.remove("hidden");
    }

    function clearAll() {
      resultsHeaderEl.innerHTML = "";
      resultsRowsEl.innerHTML = "";
      pageNavEl.innerHTML = "";
      detailEl.innerHTML = "";
      lastResults = [];
      lastResultsWeak = [];
      weakVisible = false;
      lastMode = null;
      lastShowScore = false;
      lastMatchedWords = [];
      selectedWords = new Set();
      selectedResultCollections = new Set();
      lastFallback = null;
      currentPage = 1;
    }

    function escapeHtml(s) {
      return (s == null ? "" : String(s)).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }

    // Server-side Arabic has [prematn]/[matn] wrappers and inline
    // [narrator id="..." role="..." tooltip="..."]NAME[/narrator] tags.
    // Strip the wrappers and keep just the narrator name.
    function cleanArabic(s) {
      if (!s) return "";
      return s
        .replace(/\[narrator[^\]]*\]([\s\S]*?)\[\/narrator\]/g, "$1")
        .replace(/\[\/?prematn\]/g, "")
        .replace(/\[\/?matn\]/g, "")
        .replace(/[‎‏]/g, "")
        .trim();
    }

    function cleanSnippet(s) {
      if (!s) return "";
      return s.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    }

    function titleFor(slug) {
      return (collections[slug] && collections[slug].english_title) || slug;
    }

    function refLabel(slug, hadithNumber, number) {
      // Match sunnah.com's display convention: squash internal whitespace
      // ("375 a" → "375a") and drop the trailing part of a paired range.
      const raw = String(hadithNumber || number);
      const display = raw.split(",", 1)[0].replace(/\s+/g, "");
      return titleFor(slug) + " #" + display;
    }

    function referenceUrl(slug, hadithNumber, number) {
      // Sunnah.com URLs squash whitespace from suffixed numbers — the dump
      // stores "375 a" but the canonical URL is /muslim:375a. Strip spaces
      // and take the first part of a paired range like "272, 273".
      const raw = String(hadithNumber || number);
      const id = raw.split(",", 1)[0].replace(/\s+/g, "");
      return "https://sunnah.com/" + encodeURIComponent(slug) + ":" + encodeURIComponent(id);
    }

    function renderHadith(h) {
      const slug = h.collection;
      const label = refLabel(slug, h.hadith_number, h.number);
      const url = referenceUrl(slug, h.hadith_number, h.number);
      const arabic = cleanArabic(h.arabic);
      const grade = h.english_grade || "";
      return (
        '<article class="hadith">' +
          '<div class="ref">' + escapeHtml(label) + '</div>' +
          (h.narrator ? '<div class="narrator">' + escapeHtml(h.narrator) + '</div>' : '') +
          (h.english_text ? '<div class="english">' + escapeHtml(h.english_text) + '</div>' : '') +
          (arabic ? '<div class="arabic">' + escapeHtml(arabic) + '</div>' : '') +
          '<div class="meta">' +
            (grade ? '<span>Grade: ' + escapeHtml(grade) + '</span>' : '') +
            '<a href="' + url + '" target="_blank" rel="noopener">View on sunnah.com &rarr;</a>' +
          '</div>' +
        '</article>'
      );
    }

    function renderResultRow(item, showScore, isWeak) {
      const slug = item.slug;
      // Click-fetch must use hadith_number (sunnah.com URL key) so the
      // backend resolves to the same hadith the row's label points at.
      // Falls back to id_in_book for hadiths without a sunnah.com number.
      const fetchNum = item.hadith_number || item.number;
      const label = refLabel(slug, item.hadith_number, item.number);
      const snippet = cleanSnippet(item.snippet);
      let score = "";
      if (showScore && typeof item.similarity === "number") {
        score = '<span class="score">' + item.similarity.toFixed(2) + '</span>';
      } else if (typeof item.score === "number") {
        score = '<span class="score">' + item.score.toFixed(2) + '</span>';
      }
      const cls = isWeak ? "result-row weak" : "result-row";
      return (
        '<div class="' + cls + '" data-slug="' + escapeHtml(slug) + '" data-num="' + escapeHtml(String(fetchNum)) + '">' +
          '<div class="ref">' + score + escapeHtml(label) + '</div>' +
          '<div class="snippet">' + escapeHtml(snippet) + '</div>' +
        '</div>'
      );
    }

    function attachRowHandlers() {
      resultsRowsEl.querySelectorAll(".result-row").forEach((row) => {
        row.addEventListener("click", async () => {
          await fetchAndShowHadith(row.dataset.slug, row.dataset.num);
          detailEl.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      });
    }

    function isCollectionFilterActive() {
      const total = Object.keys(collections).length;
      return total > 0 && selectedCollections.size > 0 && selectedCollections.size < total;
    }

    function buildSearchUrl(mode, query, collection, limit) {
      const c = collection ? "&collection=" + encodeURIComponent(collection) : "";
      const q = encodeURIComponent(query);
      if (mode === "semantic") return "/v1/search/semantic?query=" + q + "&limit=" + limit + c;
      if (mode === "keyword")  return "/v1/search?query=" + q + "&limit=" + limit + c;
      if (mode === "term")     return "/v1/search/term?term=" + q + "&limit=" + limit + c;
      if (mode === "natural")  return "/v1/search/natural?query=" + q + "&limit=" + limit + c;
      throw new Error("unknown mode: " + mode);
    }

    // Server-side collection filtering: one API call per ticked collection in
    // parallel, then merge. For semantic we re-sort by similarity; for term we
    // also sum matched_words counts across collections.
    async function searchAcrossCollections(mode, query) {
      const filtering = isCollectionFilterActive();
      if (!filtering) {
        return await call(buildSearchUrl(mode, query, null, ALL_LIMIT));
      }
      const slugs = Array.from(selectedCollections);

      if (slugs.length === 1) {
        return await call(buildSearchUrl(mode, query, slugs[0], ALL_LIMIT));
      }

      const responses = await Promise.allSettled(
        slugs.map((s) => call(buildSearchUrl(mode, query, s, ALL_LIMIT)))
      );
      const ok = responses.filter((r) => r.status === "fulfilled").map((r) => r.value);

      const merged = { results: [], results_weak: [], matched_words: [] };
      const wordSum = new Map();
      for (const j of ok) {
        merged.results.push(...(j.results || []));
        merged.results_weak.push(...(j.results_weak || []));
        for (const w of (j.matched_words || [])) {
          wordSum.set(w.word, (wordSum.get(w.word) || 0) + w.count);
        }
      }
      merged.matched_words = Array.from(wordSum.entries())
        .map(([word, count]) => ({ word, count }))
        .sort((a, b) => (b.count - a.count) || a.word.localeCompare(b.word));

      // Cross-encoder score is comparable across collections — re-rank globally.
      const cmp = (a, b) => (b.score || b.similarity || 0) - (a.score || a.similarity || 0);
      merged.results.sort(cmp);
      merged.results_weak.sort(cmp);
      return merged;
    }

    // Renders the cached search results plus two stackable filters:
    //   - collection chips (one per slug actually present in results)
    //   - matched-Arabic-words chips (term mode only)
    // Re-running this re-applies the current filter state to lastResults
    // without re-fetching from the API.
    function renderResultsView() {
      // Build collection counts from strong + weak so chips reflect the full
      // candidate set, not just what's currently shown.
      const collCounts = new Map();
      for (const r of lastResults.concat(lastResultsWeak)) {
        collCounts.set(r.slug, (collCounts.get(r.slug) || 0) + 1);
      }
      const orderedCols = Array.from(collCounts.entries())
        .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]));

      // Collection chips appear whenever results span >= 2 collections.
      let colChipsHtml = "";
      if (orderedCols.length >= 2) {
        const chips = orderedCols.map(([slug, cnt]) => {
          const checked = selectedResultCollections.has(slug) ? " checked" : "";
          return '<label class="rc-chip">' +
                   '<input type="checkbox" value="' + escapeHtml(slug) + '"' + checked + '>' +
                   '<span>' + escapeHtml(titleFor(slug)) + '</span>' +
                   '<span class="rc-count">&times;' + cnt + '</span>' +
                 '</label>';
        }).join(" ");
        colChipsHtml =
          '<div class="result-chips" id="rc-collections">' +
            '<span class="rc-label">Collections in these results — tick to filter:' +
              '<span class="rc-actions">' +
                '<button type="button" data-act="all">All</button>' +
                '<button type="button" data-act="none">None</button>' +
              '</span>' +
            '</span>' +
            chips +
          '</div>';
      }

      // Matched-Arabic-words chips (term mode only).
      let wordChipsHtml = "";
      if (lastMode === "term" && lastMatchedWords.length) {
        const wchips = lastMatchedWords.slice(0, 8).map((w) => {
          const checked = selectedWords.has(w.word) ? " checked" : "";
          return '<label class="word-chip">' +
                   '<input type="checkbox" value="' + escapeHtml(w.word) + '"' + checked + '>' +
                   '<span class="word">' + escapeHtml(w.word) + '</span>' +
                   '<span class="word-count">&times;' + w.count + '</span>' +
                 '</label>';
        }).join(" ");
        wordChipsHtml =
          '<div class="term-hits">' +
            '<span class="th-label">Matched Arabic words — tick to filter:</span>' +
            wchips +
          '</div>';
      }

      resultsHeaderEl.innerHTML = colChipsHtml + wordChipsHtml;

      // Apply filters in sequence. An empty selection at either layer
      // means "everything passes" (avoids silent-zero confusion).
      function applyFilters(rows) {
        let f = rows;
        if (orderedCols.length >= 2 && selectedResultCollections.size > 0) {
          f = f.filter((r) => selectedResultCollections.has(r.slug));
        }
        if (lastMode === "term" && lastMatchedWords.length && selectedWords.size > 0) {
          f = f.filter((r) =>
            Array.isArray(r.matched_words) && r.matched_words.some((w) => selectedWords.has(w))
          );
        }
        return f;
      }

      // Paginate the currently-visible set.
      //   weak hidden -> paginate strong only.
      //   weak shown  -> paginate strong concatenated with weak (still 10 per page).
      // Weak rows keep their .result-row.weak styling via renderResultRow's isWeak flag.
      const filteredStrong = applyFilters(lastResults);
      const filteredWeak = applyFilters(lastResultsWeak);
      const strongCount = filteredStrong.length;
      const visible = weakVisible
        ? filteredStrong.concat(filteredWeak)
        : filteredStrong;

      const totalStrong = lastResults.length;
      const totalWeak = lastResultsWeak.length;
      const visibleTotal = visible.length;
      const totalPages = Math.max(1, Math.ceil(visibleTotal / PAGE_SIZE));
      if (currentPage > totalPages) currentPage = totalPages;
      if (currentPage < 1) currentPage = 1;
      const start = (currentPage - 1) * PAGE_SIZE;
      const pageItems = visible.slice(start, start + PAGE_SIZE);

      // A weak row is any visible-list index >= strongCount.
      let html = pageItems
        .map((it, i) => renderResultRow(it, lastShowScore, (start + i) >= strongCount))
        .join("");

      // Single weak-toggle button at the end (only when weak matches exist).
      if (totalWeak > 0) {
        const verb = weakVisible ? "Hide" : "Show";
        const noun = "weak match" + (totalWeak === 1 ? "" : "es");
        html += '<button type="button" id="show-weak" class="weak-toggle">' +
                verb + ' ' + totalWeak + ' ' + noun + '</button>';
      }

      resultsRowsEl.innerHTML = html;
      pageNavEl.innerHTML = renderPageNav(totalPages, currentPage);
      attachRowHandlers();
      attachPageNavHandlers();

      // Toggling weak resets to page 1 (the visible-set size just changed).
      const showWeakBtn = resultsRowsEl.querySelector("#show-weak");
      if (showWeakBtn) {
        showWeakBtn.addEventListener("click", () => {
          weakVisible = !weakVisible;
          currentPage = 1;
          renderResultsView();
        });
      }

      const fallbackPrefix = lastFallback
        ? "LLM router unavailable — showing concept-mode results. "
        : "";
      if (visibleTotal === 0) {
        setStatus(fallbackPrefix + "Nothing matches the current filters. Tick more chips to see hadiths.");
      } else {
        const endIdx = Math.min(start + PAGE_SIZE, visibleTotal);
        const filteredFromTotal = weakVisible ? (totalStrong + totalWeak) : totalStrong;
        const filteredNote = (visibleTotal < filteredFromTotal)
          ? " (filtered from " + filteredFromTotal.toLocaleString() + ")"
          : "";
        const pageNote = (totalPages > 1) ? " — page " + currentPage + " of " + totalPages : "";
        const weakHint = (!weakVisible && totalWeak > 0)
          ? " (+ " + totalWeak + " weak hidden)"
          : "";
        setStatus(
          fallbackPrefix +
          "Showing " + (start + 1).toLocaleString() + "–" + endIdx.toLocaleString() +
          " of " + visibleTotal.toLocaleString() + filteredNote + weakHint + pageNote +
          ". Tap a row to read the full hadith."
        );
      }

      // Wire up toggle handlers (the innerHTML rewrite blew away any prior listeners).
      resultsHeaderEl.querySelectorAll(".rc-chip input").forEach((inp) => {
        inp.addEventListener("change", () => {
          selectedResultCollections = new Set(
            Array.from(resultsHeaderEl.querySelectorAll(".rc-chip input:checked")).map((i) => i.value)
          );
          currentPage = 1;
          renderResultsView();
        });
      });
      const colsBox = resultsHeaderEl.querySelector("#rc-collections");
      if (colsBox) {
        colsBox.querySelectorAll(".rc-actions button").forEach((btn) => {
          btn.addEventListener("click", () => {
            const act = btn.dataset.act;
            const inputs = colsBox.querySelectorAll(".rc-chip input");
            inputs.forEach((i) => { i.checked = (act === "all"); });
            selectedResultCollections = new Set(
              Array.from(colsBox.querySelectorAll(".rc-chip input:checked")).map((i) => i.value)
            );
            currentPage = 1;
            renderResultsView();
          });
        });
      }
      resultsHeaderEl.querySelectorAll(".word-chip input").forEach((inp) => {
        inp.addEventListener("change", () => {
          selectedWords = new Set(
            Array.from(resultsHeaderEl.querySelectorAll(".word-chip input:checked")).map((i) => i.value)
          );
          currentPage = 1;
          renderResultsView();
        });
      });
    }

    function renderPageNav(totalPages, current) {
      if (totalPages <= 1) return "";
      const w = 2;
      const wanted = new Set([1, totalPages]);
      for (let p = Math.max(1, current - w); p <= Math.min(totalPages, current + w); p++) {
        wanted.add(p);
      }
      const sorted = Array.from(wanted).sort((a, b) => a - b);
      const parts = [];
      let prev = 0;
      for (const p of sorted) {
        if (prev && p - prev > 1) parts.push('<span class="pn-ellipsis">&hellip;</span>');
        const cls = (p === current) ? "pn-btn pn-current" : "pn-btn";
        const dis = (p === current) ? " disabled" : "";
        parts.push('<button type="button" class="' + cls + '" data-page="' + p + '"' + dis + '>' + p + '</button>');
        prev = p;
      }
      const prevDis = current <= 1 ? " disabled" : "";
      const nextDis = current >= totalPages ? " disabled" : "";
      return '<nav class="page-nav">' +
        '<button type="button" class="pn-btn" data-page="' + (current - 1) + '"' + prevDis + '>&lsaquo; Prev</button>' +
        parts.join("") +
        '<button type="button" class="pn-btn" data-page="' + (current + 1) + '"' + nextDis + '>Next &rsaquo;</button>' +
        '</nav>';
    }

    function attachPageNavHandlers() {
      pageNavEl.querySelectorAll("button[data-page]").forEach((btn) => {
        if (btn.disabled) return;
        btn.addEventListener("click", () => {
          const p = parseInt(btn.dataset.page, 10);
          if (isNaN(p)) return;
          currentPage = p;
          renderResultsView();
          const top = (resultsHeaderEl.firstChild) ? resultsHeaderEl : resultsRowsEl;
          top.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      });
    }

    async function call(url) {
      const r = await fetch(url);
      if (!r.ok) {
        let detail = await r.text();
        try { detail = JSON.parse(detail).detail || detail; } catch (_) {}
        throw new Error("HTTP " + r.status + " — " + detail);
      }
      return r.json();
    }

    async function fetchAndShowHadith(slug, number) {
      setStatus("Loading hadith…");
      try {
        const h = await call("/v1/hadith/" + encodeURIComponent(slug) + "/" + encodeURIComponent(number));
        detailEl.innerHTML = renderHadith(h);
        setStatus("");
      } catch (e) {
        setStatus("Could not load: " + e.message, true);
      }
    }

    // "<one or more words> [#] <number-or-suffixed-ref>"  → {slug, number}
    // `number` stays a string so sunnah.com letter-suffix refs like "402b"
    // or "1134b" pass through to the backend verbatim.
    function parseReference(text) {
      const m = text.trim().match(/^(.+?)\s*#?\s*([0-9][0-9a-zA-Z,\s]*?)\s*$/);
      if (!m) return null;
      const slug = slugByAlias[norm(m[1])];
      return slug ? { slug, number: m[2].trim() } : null;
    }

    async function doSearch(mode, q) {
      clearAll();
      if (!q.trim()) {
        setStatus("Type something first.", true);
        return;
      }
      setStatus("Searching…");
      searchBtn.disabled = true;
      try {
        if (mode === "reference") {
          const ref = parseReference(q);
          if (!ref) {
            setStatus('Couldn’t recognise that reference. Try "Bukhari 1" or "Sahih Muslim 5".', true);
            return;
          }
          await fetchAndShowHadith(ref.slug, ref.number);
          return;
        }

        const filtering = isCollectionFilterActive();
        const showScore = (mode === "semantic" || mode === "natural");

        const j = await searchAcrossCollections(mode, q);
        const items = j.results || [];
        const weakItems = j.results_weak || [];
        // Issue #4 AC #8: NL mode falls back to concept search when the LLM
        // router is unavailable. Stash the warning on the cached state so
        // renderResultsView can prepend it to the result-count line.
        lastFallback = j.fallback || null;

        if (!items.length && !weakItems.length) {
          if (filtering) {
            setStatus("No matches in the selected collections. Try ticking more, or change the wording.");
          } else {
            setStatus("No matches. Try a different mode or wording.");
          }
          return;
        }

        // No client-side cap — the union retriever already caps the pool
        // (k_per_retriever) and PAGE_SIZE keeps the rendered page small.
        // Cache results so the chip filters can re-render without re-fetching.
        lastResults = items;
        lastResultsWeak = weakItems;
        weakVisible = false;
        lastMode = mode;
        lastShowScore = showScore;
        lastMatchedWords = (mode === "term" && Array.isArray(j.matched_words)) ? j.matched_words : [];
        selectedWords = (mode === "term")
          ? new Set(lastMatchedWords.slice(0, 8).map((w) => w.word))
          : new Set();
        // Collection chip set spans strong + weak so toggling weak doesn't
        // suddenly surface rows whose slug isn't represented in the chip strip.
        selectedResultCollections = new Set(items.concat(weakItems).map((r) => r.slug));
        currentPage = 1;

        renderResultsView();
      } catch (e) {
        setStatus("Error: " + e.message, true);
      } finally {
        searchBtn.disabled = false;
      }
    }

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const mode = document.querySelector('input[name="m"]:checked').value;
      doSearch(mode, qIn.value);
    });

    randomBtn.addEventListener("click", async () => {
      clearAll();
      setStatus("Picking a hadith…");
      randomBtn.disabled = true;
      try {
        const h = await call("/v1/random");
        detailEl.innerHTML = renderHadith(h);
        setStatus("");
        detailEl.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (e) {
        setStatus("Error: " + e.message, true);
      } finally {
        randomBtn.disabled = false;
      }
    });

    loadCollections();
  </script>
</body>
</html>
"""


def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)