"""
scripts/signal_guidance.py

Phase 2, Signal 2 — Forward Guidance Specificity Score

Measures how specific vs. vague management's forward-looking statements are.
Specific guidance ("Revenue will be $4.2B") = low evasiveness
Vague guidance ("We expect continued growth") = high evasiveness

Method: Zero-shot classification via HuggingFace pipeline
Model: facebook/bart-large-mnli (free, runs on CPU)

Run:
    python scripts/signal_guidance.py
    python scripts/signal_guidance.py --ticker JPM
    python scripts/signal_guidance.py --show JPM 2023 2
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH

# ── Guidance sentence extraction ──────────────────────────────────────────────

GUIDANCE_PATTERNS = [
    r'\bwe\s+expect\b', r'\bwe\s+anticipate\b', r'\bwe\s+project\b',
    r'\bwe\s+(?:are\s+)?(?:targeting|guiding|forecasting)\b',
    r'\bfull[\s\-]year\b.*\b(?:\$|percent|%|basis\s+points?|bps)\b',
    r'\bguidance\s+(?:of|is|remains?|range|for)\b',
    r'\b(?:fiscal|calendar|full)\s*year\s+20\d\d\b',
    r'\b(?:revenue|earnings|eps|net\s+income|loan\s+growth|nim|roa|roe)\b'
    r'.*\b(?:range|between|of\s+approximately|around|roughly|\$)\b',
    r'\boutlook\s+(?:for|is|remains?)\b',
    r'\b(?:q[1-4]|first|second|third|fourth)\s+quarter\b.*\bexpect\b',
]
_guidance_re = re.compile("|".join(GUIDANCE_PATTERNS), re.IGNORECASE)

# Specificity indicators — if a sentence has these, it's more specific
SPECIFIC_INDICATORS = re.compile(
    r'\b\d+(?:\.\d+)?(?:\s*(?:billion|million|thousand|%|percent|bps|basis\s+points?))?\b'
    r'|\b(?:between|range\s+of)\s+\$?\d',
    re.IGNORECASE
)


def extract_guidance_sentences(sc_json: str, raw_content: str = "") -> list[str]:
    """Extract forward-looking sentences from transcript."""
    # Try structured content first — use full transcript text
    text = ""
    if sc_json:
        try:
            turns = json.loads(sc_json)
            if isinstance(turns, list):
                text = " ".join(str(t.get("text","")) for t in turns)
        except (json.JSONDecodeError, TypeError):
            pass

    if not text and raw_content:
        text = raw_content

    if not text:
        return []

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)

    # Filter to guidance-sounding sentences
    guidance = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) > 30 and _guidance_re.search(sent):
            guidance.append(sent)

    return guidance[:30]  # cap at 30 sentences to keep inference fast


# ── Zero-shot scoring ─────────────────────────────────────────────────────────

_classifier = None

def get_classifier():
    global _classifier
    if _classifier is None:
        from transformers import pipeline
        print("  Loading facebook/bart-large-mnli (first run only, ~1.6GB)...")
        _classifier = pipeline(
            "zero-shot-classification",
            model="facebook/bart-large-mnli",
            device=-1,  # CPU
        )
        print("  Model loaded.")
    return _classifier


CANDIDATE_LABELS = [
    "specific numeric financial guidance",
    "vague directional guidance",
]


def score_guidance_specificity(sentences: list[str]) -> dict:
    """
    Score guidance specificity using zero-shot classification.
    Returns average confidence that sentences are 'specific' vs 'vague'.
    """
    if not sentences:
        return _empty_guidance()

    clf = get_classifier()
    specific_scores = []

    for sent in sentences:
        try:
            result = clf(sent, CANDIDATE_LABELS, multi_label=False)
            # Score = confidence that this is 'specific numeric guidance'
            labels = result["labels"]
            scores = result["scores"]
            specific_idx = labels.index("specific numeric financial guidance")
            specific_scores.append(scores[specific_idx])
        except Exception:
            continue

    if not specific_scores:
        return _empty_guidance()

    avg_specificity = sum(specific_scores) / len(specific_scores)

    # Also give a rule-based boost if sentences contain actual numbers
    numeric_ratio = sum(
        1 for s in sentences if SPECIFIC_INDICATORS.search(s)
    ) / len(sentences)

    # Blend: 70% model, 30% rule-based numeric detection
    blended = (avg_specificity * 0.7) + (numeric_ratio * 0.3)

    # guidance_score = evasiveness (inverse of specificity)
    # High specificity = low evasiveness score
    guidance_evasiveness = round(1.0 - blended, 4)

    return {
        "guidance_score":        guidance_evasiveness,
        "guidance_specificity":  round(blended, 4),
        "guidance_sentence_count": len(sentences),
        "numeric_ratio":         round(numeric_ratio, 4),
        "avg_model_specificity": round(avg_specificity, 4),
    }


def _empty_guidance() -> dict:
    return {
        "guidance_score": None,
        "guidance_specificity": None,
        "guidance_sentence_count": 0,
        "numeric_ratio": None,
        "avg_model_specificity": None,
    }


# ── DB operations ─────────────────────────────────────────────────────────────

def ensure_columns(conn: sqlite3.Connection):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
    for col, dtype in [
        ("guidance_score",          "REAL"),
        ("guidance_specificity",    "REAL"),
        ("guidance_sentence_count", "INTEGER"),
        ("numeric_ratio",           "REAL"),
        ("avg_model_specificity",   "REAL"),
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
        q += (" AND" if params else " WHERE") + " guidance_score IS NULL"

    rows = conn.execute(q, params).fetchall()
    print(f"Scoring guidance specificity for {len(rows)} transcripts...")
    print("Note: first run downloads bart-large-mnli (~1.6GB, one-time only)\n")

    scored = skipped = 0
    for i, row in enumerate(rows):
        sentences = extract_guidance_sentences(
            row["structured_content"], row["content"]
        )
        if not sentences:
            skipped += 1
            print(f"  {row['symbol']:<5} {row['year']} Q{row['quarter']}  "
                  f"[SKIP] no guidance sentences found")
            continue

        print(f"  [{i+1}/{len(rows)}] {row['symbol']} {row['year']} Q{row['quarter']} "
              f"— scoring {len(sentences)} sentences...", end=" ", flush=True)

        r = score_guidance_specificity(sentences)

        conn.execute("""
            UPDATE transcripts SET
                guidance_score=?, guidance_specificity=?,
                guidance_sentence_count=?, numeric_ratio=?,
                avg_model_specificity=?
            WHERE id=?
        """, (r["guidance_score"], r["guidance_specificity"],
              r["guidance_sentence_count"], r["numeric_ratio"],
              r["avg_model_specificity"], row["id"]))
        conn.commit()
        scored += 1
        print(f"evasiveness={r['guidance_score']}  "
              f"specificity={r['guidance_specificity']}  "
              f"numeric_ratio={r['numeric_ratio']}")

    print(f"\nDone — {scored} scored, {skipped} skipped")
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

    sentences = extract_guidance_sentences(row["structured_content"], row["content"])
    print(f"\n{ticker.upper()} {year} Q{quarter}")
    print(f"  Guidance sentences found: {len(sentences)}")
    for i, s in enumerate(sentences[:5]):
        has_num = bool(SPECIFIC_INDICATORS.search(s))
        print(f"  [{i+1}] {'[NUM]' if has_num else '[VAG]'} {s[:120]}")

    if sentences:
        r = score_guidance_specificity(sentences)
        print(f"\n  Guidance evasiveness : {r['guidance_score']}")
        print(f"  Specificity          : {r['guidance_specificity']}")
        print(f"  Numeric ratio        : {r['numeric_ratio']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--show",  nargs=3, metavar=("TICKER","YEAR","QUARTER"))
    args = parser.parse_args()

    if args.show:
        show_sample(args.show[0], int(args.show[1]), int(args.show[2]))
    else:
        score_all(ticker_filter=args.ticker, force=args.force)
