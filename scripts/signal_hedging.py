"""
scripts/signal_hedging.py

Phase 2, Signal 1 — Hedging Language Ratio

Measures how often management uses uncertain, hedging language
in the prepared remarks section of each earnings call.

High hedging score = management is being evasive/uncertain
Low hedging score  = management is confident and direct

Method: lexicon-based (pure Python, no ML model needed)
Run:
    python scripts/signal_hedging.py
    python scripts/signal_hedging.py --ticker JPM
    python scripts/signal_hedging.py --show JPM 2023 2
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH

# ── Hedging lexicon ───────────────────────────────────────────────────────────

STRONG_HEDGES = [
    "subject to", "contingent on", "contingent upon", "depending on",
    "no assurance", "no guarantee", "cannot guarantee", "cannot predict",
    "difficult to predict", "inherently uncertain", "highly uncertain",
    "significant uncertainty", "approximately", "in the range of",
    "somewhere between", "potentially", "there is a possibility",
    "there is a risk", "forward-looking", "forward looking", "safe harbor",
    "actual results may differ", "results may differ materially",
    "could differ materially", "differ from those anticipated",
]

WEAK_HEDGES = [
    "we believe", "we think", "we feel", "we expect", "we anticipate",
    "we hope", "we assume", "we estimate", "we project",
    "management believes", "management expects", "management anticipates",
    "may", "might", "could", "should", "would",
    "possible", "possibly", "potential", "potentially",
    "likely", "unlikely", "probable",
    "about", "around", "roughly", "nearly", "almost",
    "generally", "typically", "usually", "often", "sometimes",
    "assuming", "provided that", "in the event", "to the extent",
    "somewhat", "relatively", "fairly",
    "in our view", "in our opinion", "from our perspective",
]

_strong_pats = [re.compile(r'\b' + re.escape(p) + r'\b', re.IGNORECASE) for p in STRONG_HEDGES]
_weak_pats   = [re.compile(r'\b' + re.escape(p) + r'\b', re.IGNORECASE) for p in WEAK_HEDGES]


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_hedging(text: str) -> dict:
    if not text or len(text.strip()) < 50:
        return _empty()

    word_count = len(text.split())
    if word_count < 10:
        return _empty()

    strong_hits, weak_hits = [], []
    for pat, phrase in zip(_strong_pats, STRONG_HEDGES):
        strong_hits.extend([phrase] * len(pat.findall(text)))
    for pat, phrase in zip(_weak_pats, WEAK_HEDGES):
        weak_hits.extend([phrase] * len(pat.findall(text)))

    weighted = (len(strong_hits) * 2) + len(weak_hits)
    score    = min(weighted / (word_count / 100) / 20, 1.0)
    top      = [p for p, _ in Counter(strong_hits + weak_hits).most_common(5)]

    return {
        "hedging_score":      round(score, 4),
        "hedging_raw_count":  len(strong_hits) + len(weak_hits),
        "strong_hedge_count": len(strong_hits),
        "weak_hedge_count":   len(weak_hits),
        "word_count":         word_count,
        "top_hedges":         top,
    }


def _empty() -> dict:
    return {"hedging_score": None, "hedging_raw_count": 0,
            "strong_hedge_count": 0, "weak_hedge_count": 0,
            "word_count": 0, "top_hedges": []}


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_prepared_remarks(sc_json: str) -> str:
    """Extract executive prepared remarks — stops before Q&A."""
    if not sc_json:
        return ""
    try:
        turns = json.loads(sc_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(turns, list):
        return ""

    QA_SIGNALS = {"operator", "question", "analyst", "q&a", "question-and-answer"}
    lines, in_qa = [], False

    for turn in turns:
        speaker = str(turn.get("speaker", "")).lower()
        text    = str(turn.get("text", "")).strip()
        if any(sig in speaker for sig in QA_SIGNALS):
            in_qa = True
        if not in_qa and text:
            lines.append(text)

    return " ".join(lines)


# ── DB operations ─────────────────────────────────────────────────────────────

def ensure_columns(conn: sqlite3.Connection):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
    for col, dtype in [
        ("hedging_score",       "REAL"),
        ("hedging_raw_count",   "INTEGER"),
        ("strong_hedge_count",  "INTEGER"),
        ("weak_hedge_count",    "INTEGER"),
        ("word_count_prepared", "INTEGER"),
        ("top_hedges",          "TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE transcripts ADD COLUMN {col} {dtype}")
    conn.commit()


def score_all(ticker_filter=None, force=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    q = "SELECT id, symbol, year, quarter, structured_content, content FROM transcripts"
    params = []
    if ticker_filter:
        q += " WHERE symbol=?"
        params.append(ticker_filter.upper())
    if not force:
        q += (" AND" if params else " WHERE") + " hedging_score IS NULL"

    rows = conn.execute(q, params).fetchall()
    print(f"Scoring hedging signal for {len(rows)} transcripts...\n")

    scored = skipped = 0
    for row in rows:
        text = extract_prepared_remarks(row["structured_content"])
        if len(text) < 200:
            text = row["content"] or ""
        if len(text) < 200:
            skipped += 1
            continue

        r = score_hedging(text)
        conn.execute("""
            UPDATE transcripts SET
                hedging_score=?, hedging_raw_count=?, strong_hedge_count=?,
                weak_hedge_count=?, word_count_prepared=?, top_hedges=?
            WHERE id=?
        """, (r["hedging_score"], r["hedging_raw_count"], r["strong_hedge_count"],
              r["weak_hedge_count"], r["word_count"], json.dumps(r["top_hedges"]),
              row["id"]))
        conn.commit()
        scored += 1
        print(f"  {row['symbol']:<5} {row['year']} Q{row['quarter']}  "
              f"hedging={r['hedging_score']:.3f}  "
              f"({r['strong_hedge_count']} strong, {r['weak_hedge_count']} weak)  "
              f"words={r['word_count']:,}")

    print(f"\nDone — {scored} scored, {skipped} skipped (text too short)")
    conn.close()


def show_sample(ticker, year, quarter):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM transcripts WHERE symbol=? AND year=? AND quarter=?",
        (ticker.upper(), year, quarter)
    ).fetchone()
    conn.close()
    if not row:
        print(f"No transcript: {ticker} {year} Q{quarter}")
        return
    text = extract_prepared_remarks(row["structured_content"])
    r = score_hedging(text)
    print(f"\n{ticker.upper()} {year} Q{quarter}")
    print(f"  Hedging score : {r['hedging_score']}")
    print(f"  Strong hedges : {r['strong_hedge_count']}")
    print(f"  Weak hedges   : {r['weak_hedge_count']}")
    print(f"  Word count    : {r['word_count']:,}")
    print(f"  Top phrases   : {r['top_hedges']}")
    print(f"\n  Text preview  : {text[:400]}...")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker")
    parser.add_argument("--force",  action="store_true")
    parser.add_argument("--show",   nargs=3, metavar=("TICKER","YEAR","QUARTER"))
    args = parser.parse_args()

    if args.show:
        show_sample(args.show[0], int(args.show[1]), int(args.show[2]))
    else:
        score_all(ticker_filter=args.ticker, force=args.force)
