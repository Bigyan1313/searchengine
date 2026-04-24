"""
build_index.py
Builds a Whoosh full-text index from data/lyrics.csv.
Run once before starting the Flask app (or whenever the dataset changes).

Usage:
    python build_index.py
"""

import csv
import os
import shutil
import sys
from whoosh.fields import Schema, TEXT, ID, NUMERIC, STORED
from whoosh.analysis import StemmingAnalyzer
from whoosh.index import create_in

CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "lyrics.csv")
INDEX_DIR = os.path.join(os.path.dirname(__file__), "indexdir")


def build():
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: dataset not found at {CSV_PATH}", file=sys.stderr)
        sys.exit(1)

    # Wipe and recreate the index directory so re-runs are clean.
    if os.path.exists(INDEX_DIR):
        shutil.rmtree(INDEX_DIR)
    os.makedirs(INDEX_DIR)

    # StemmingAnalyzer: "loving" matches "love", "runs" matches "run", etc.
    # Much better recall than the default analyzer for lyrics search.
    stem_ana = StemmingAnalyzer()

    schema = Schema(
        doc_id=ID(stored=True, unique=True),
        rank=NUMERIC(stored=True, sortable=True),
        title=TEXT(stored=True, analyzer=stem_ana, field_boost=2.0),
        artist=TEXT(stored=True, analyzer=stem_ana, field_boost=1.5),
        year=NUMERIC(stored=True, sortable=True),
        lyrics=TEXT(stored=True, analyzer=stem_ana),
    )

    ix = create_in(INDEX_DIR, schema)
    writer = ix.writer(limitmb=256, procs=1, multisegment=True)

    added = 0
    skipped = 0
    with open(CSV_PATH, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            try:
                rank = int(row["Rank"])
                year = int(row["Year"])
            except (ValueError, TypeError, KeyError):
                skipped += 1
                continue

            title = (row.get("Song") or "").strip()
            artist = (row.get("Artist") or "").strip()
            lyrics = (row.get("Lyrics") or "").strip()

            # Skip rows with no lyrics — nothing to search.
            if not lyrics:
                skipped += 1
                continue

            writer.add_document(
                doc_id=str(i),
                rank=rank,
                title=title,
                artist=artist,
                year=year,
                lyrics=lyrics,
            )
            added += 1

    writer.commit()
    print(f"Indexed {added} documents ({skipped} skipped).")
    print(f"Index written to: {INDEX_DIR}")


if __name__ == "__main__":
    build()
