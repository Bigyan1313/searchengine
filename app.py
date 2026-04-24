"""
app.py
Flask app serving a keyword search interface with two modes:
  - Web search   -> Brave Search API
  - Local search -> Whoosh index over lyrics.csv

Routes:
  GET  /                     main search UI
  GET  /api/web?q=...        web search JSON (Brave proxy)
  GET  /api/local?q=...      local search JSON (Whoosh)
  GET  /song/<doc_id>        full song page (title, rank, year, artist, lyrics)
"""

import os
from flask import Flask, render_template, request, jsonify, abort
import requests

from whoosh.index import open_dir
from whoosh.qparser import MultifieldParser, OrGroup
from whoosh import highlight, scoring


def _load_dotenv(dotenv_path):
    """Load simple KEY=VALUE pairs from .env into os.environ."""
    if not os.path.exists(dotenv_path):
        return

    with open(dotenv_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                # Keep terminal-set vars higher priority than .env values.
                os.environ.setdefault(key, value)


# ---------- configuration ----------
_load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
INDEX_DIR = os.path.join(os.path.dirname(__file__), "indexdir")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

RESULTS_PER_PAGE = 10
SNIPPET_MAX_CHARS = 240

app = Flask(__name__)

# ---------- Whoosh setup ----------
# Open the index once at startup and reuse across requests.
if not os.path.exists(INDEX_DIR):
    raise RuntimeError(
        f"Index directory not found at {INDEX_DIR}. "
        "Run `python build_index.py` first."
    )
ix = open_dir(INDEX_DIR)

# Query across title + artist + lyrics. OrGroup means any term matches
# (standard search-engine behavior); BM25F is Whoosh's default relevance model.
_parser = MultifieldParser(
    ["title", "artist", "lyrics"], schema=ix.schema, group=OrGroup.factory(0.9)
)


# ---------- helpers ----------
def _highlight_formatter():
    """Custom HTML formatter: wraps matched terms in <mark>."""
    return highlight.HtmlFormatter(tagname="mark", classname="hl", between=" … ")


def _make_snippet(hit, query_text):
    """
    Generate a KWIC-style snippet from the lyrics field.
    Uses Whoosh's highlighter to pick the best-matching passage.
    Falls back to the first chunk of lyrics if no terms matched that field.
    """
    hit.results.fragmenter = highlight.ContextFragmenter(
        maxchars=SNIPPET_MAX_CHARS, surround=60
    )
    hit.results.formatter = _highlight_formatter()
    snippet = hit.highlights("lyrics", top=1)
    if not snippet:
        # Term only matched title/artist — show the start of the lyrics instead.
        lyrics = hit.get("lyrics", "") or ""
        snippet = (lyrics[:SNIPPET_MAX_CHARS] + "…") if lyrics else ""
    return snippet


# ---------- routes ----------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/local")
def api_local():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"query": q, "total": 0, "results": []})

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    parsed = _parser.parse(q)
    results_payload = []
    total = 0

    with ix.searcher(weighting=scoring.BM25F()) as searcher:
        # Request one page worth of results.
        page_results = searcher.search_page(parsed, page, pagelen=RESULTS_PER_PAGE)
        total = len(page_results)  # total matches across the whole index
        page_results.results.fragmenter = highlight.ContextFragmenter(
            maxchars=SNIPPET_MAX_CHARS, surround=60
        )
        page_results.results.formatter = _highlight_formatter()

        for hit in page_results:
            snippet = hit.highlights("lyrics", top=1)
            if not snippet:
                lyrics = hit.get("lyrics", "") or ""
                snippet = (lyrics[:SNIPPET_MAX_CHARS] + "…") if lyrics else ""

            results_payload.append({
                "doc_id": hit["doc_id"],
                "title": hit.get("title", ""),
                "artist": hit.get("artist", ""),
                "year": hit.get("year", ""),
                "rank": hit.get("rank", ""),
                "snippet": snippet,
                "score": round(hit.score, 3),
            })

    return jsonify({
        "query": q,
        "page": page,
        "per_page": RESULTS_PER_PAGE,
        "total": total,
        "results": results_payload,
    })


@app.route("/api/web")
def api_web():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"query": q, "results": []})

    if not BRAVE_API_KEY:
        return jsonify({
            "error": "BRAVE_API_KEY is not configured on the server.",
            "query": q,
            "results": [],
        }), 500

    try:
        resp = requests.get(
            BRAVE_ENDPOINT,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_API_KEY,
            },
            params={"q": q, "count": RESULTS_PER_PAGE},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return jsonify({"error": f"Upstream error: {e}", "query": q, "results": []}), 502

    data = resp.json()
    web_results = (data.get("web") or {}).get("results") or []
    cleaned = [{
        "title": r.get("title", ""),
        "url": r.get("url", ""),
        "snippet": r.get("description", ""),
        "display_url": r.get("meta_url", {}).get("hostname", "") or r.get("url", ""),
    } for r in web_results]

    return jsonify({"query": q, "results": cleaned})


@app.route("/song/<doc_id>")
def song(doc_id):
    with ix.searcher() as searcher:
        doc = searcher.document(doc_id=str(doc_id))
        if not doc:
            abort(404)
        # Lyrics in the CSV have no punctuation/case, so render them as-is
        # but insert line breaks on long runs to make them readable.
        lyrics_raw = doc.get("lyrics", "") or ""
        # Simple heuristic: break on common line-start words. The source data
        # has no newlines, so any rendering is best-effort.
        return render_template(
            "song.html",
            title=doc.get("title", ""),
            artist=doc.get("artist", ""),
            year=doc.get("year", ""),
            rank=doc.get("rank", ""),
            lyrics=lyrics_raw,
        )


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    # Local dev only; production uses gunicorn (see Procfile / render.yaml).
    debug_flag = os.environ.get("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug_flag)
