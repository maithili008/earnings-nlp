"""
scripts/signal_qa.py

Phase 2, Signal 3 — Q&A Sentiment Volatility

Measures how much executive sentiment shifts during analyst Q&A.
High volatility = tone is inconsistent under pressure = evasive signal.

FIX: Dataset uses speaker names (e.g. "Jamie Dimon") not titles.
     We classify by POSITION: after Operator opens Q&A, alternating
     analyst question → executive response pattern.

Run:
    python scripts/signal_qa.py
    python scripts/signal_qa.py --ticker JPM
    python scripts/signal_qa.py --show JPM 2023 2
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH

# ── Sentiment anchors ─────────────────────────────────────────────────────────

POSITIVE_ANCHORS = [
    "We are confident in our strong performance and outlook.",
    "Results exceeded expectations with robust growth.",
    "We delivered excellent returns and strong profitability.",
    "Our business is performing very well with solid momentum.",
]

NEGATIVE_ANCHORS = [
    "We face significant challenges and uncertainty ahead.",
    "Results were disappointing with weaker than expected performance.",
    "We are concerned about deteriorating conditions and risks.",
    "Headwinds are creating a difficult operating environment.",
]

# ── Model loading ─────────────────────────────────────────────────────────────

_model = None
_pos_embs = None
_neg_embs = None


def get_model():
    global _model, _pos_embs, _neg_embs
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print("  Loading all-MiniLM-L6-v2 (~80MB, one-time)...")
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        _pos_embs = _model.encode(POSITIVE_ANCHORS, convert_to_numpy=True)
        _neg_embs = _model.encode(NEGATIVE_ANCHORS, convert_to_numpy=True)
        print("  Model loaded.\n")
    return _model, _pos_embs, _neg_embs


def cosine_sim(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(np.dot(a, b) / (na * nb)) if na and nb else 0.0


def sentiment_score(embedding, pos_embs, neg_embs):
    pos = np.mean([cosine_sim(embedding, p) for p in pos_embs])
    neg = np.mean([cosine_sim(embedding, n) for n in neg_embs])
    return float(pos - neg)


# ── Q&A extraction — position-based ──────────────────────────────────────────

# Known operator names/phrases in this dataset
OPERATOR_NAMES = {"operator", "moderator", "coordinator", "conference"}

# Known analyst firm keywords (appear in speaker names sometimes)
ANALYST_FIRM_KEYWORDS = {
    "barclays", "goldman", "morgan", "jp morgan", "jpmorgan", "wells",
    "citi", "ubs", "deutsche", "evercore", "keefe", "kbw", "piper",
    "raymond", "jefferies", "baird", "truist", "wolfe", "rbc", "bmo",
    "credit suisse", "hsbc", "autonomous", "compass", "stephens",
}


def is_operator(speaker: str) -> bool:
    s = speaker.lower().strip()
    return any(op in s for op in OPERATOR_NAMES)


def is_analyst(speaker: str) -> bool:
    """Check if speaker name contains known analyst firm keywords."""
    s = speaker.lower()
    return any(firm in s for firm in ANALYST_FIRM_KEYWORDS)


def extract_qa_executive_turns(sc_json: str) -> list[str]:
    """
    Extract executive responses from Q&A section.

    Strategy (position-based since dataset has names not titles):
    1. Find Q&A start = first Operator turn that contains 'question' keyword
    2. After that, identify speakers: Operator intros, then alternating
       analyst question → executive response
    3. Executive = any non-operator speaker responding AFTER an analyst turn
    4. Minimum 30 words per response
    """
    if not sc_json:
        return []
    try:
        turns = json.loads(sc_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(turns, list) or len(turns) < 4:
        return []

    # ── Step 1: Find Q&A start ────────────────────────────────────────────────
    qa_start_idx = None
    for i, turn in enumerate(turns):
        speaker = str(turn.get("speaker", "")).lower()
        text    = str(turn.get("text", "")).lower()
        if is_operator(speaker) and any(
            kw in text for kw in ["question", "q&a", "open the floor", "line is open",
                                   "please go ahead", "your line", "first question"]
        ):
            qa_start_idx = i
            break

    # Fallback: use second half of transcript as Q&A proxy
    if qa_start_idx is None:
        qa_start_idx = len(turns) // 2

    qa_turns = turns[qa_start_idx:]

    # ── Step 2: Identify speakers in Q&A ─────────────────────────────────────
    # Collect unique non-operator speakers and their first appearances
    # First non-operator speaker after Q&A start = likely exec (they often
    # give a brief intro). After that, alternating pattern.

    # Get the set of speakers from PREPARED REMARKS (= executives)
    prepared_speakers = set()
    for turn in turns[:qa_start_idx]:
        spk = str(turn.get("speaker", "")).strip()
        if spk and not is_operator(spk):
            prepared_speakers.add(spk.lower())

    # ── Step 3: Extract executive responses ───────────────────────────────────
    exec_responses = []
    prev_was_question = False

    for turn in qa_turns:
        speaker = str(turn.get("speaker", "")).strip()
        text    = str(turn.get("text", "")).strip()
        s_lower = speaker.lower()

        if is_operator(s_lower):
            prev_was_question = False
            continue

        # Is this speaker an analyst? (firm keyword OR not in prepared speakers)
        speaker_is_analyst = (
            is_analyst(s_lower) or
            (s_lower not in prepared_speakers and len(prepared_speakers) > 0)
        )

        # Is this speaker an executive? (was in prepared remarks)
        speaker_is_exec = s_lower in prepared_speakers

        if speaker_is_analyst and not speaker_is_exec:
            prev_was_question = True
        elif speaker_is_exec and prev_was_question:
            # Executive responding to analyst question
            words = text.split()
            if len(words) >= 30:
                exec_responses.append(text)
            prev_was_question = False
        else:
            # Ambiguous — use heuristic: short text = question, long = answer
            if len(text.split()) < 50:
                prev_was_question = True
            elif prev_was_question and len(text.split()) >= 30:
                exec_responses.append(text)
                prev_was_question = False

    return exec_responses


# ── Volatility scoring ────────────────────────────────────────────────────────

def score_qa_volatility(exec_responses: list[str]) -> dict:
    if len(exec_responses) < 3:
        return _empty()

    model, pos_embs, neg_embs = get_model()
    embeddings = model.encode(exec_responses, convert_to_numpy=True, show_progress_bar=False)
    scores = [sentiment_score(emb, pos_embs, neg_embs) for emb in embeddings]

    mean_s = float(np.mean(scores))
    std_s  = float(np.std(scores))
    vol    = min(std_s / 0.20, 1.0)

    return {
        "qa_volatility_score": round(vol, 4),
        "qa_sentiment_mean":   round(mean_s, 4),
        "qa_sentiment_std":    round(std_s, 4),
        "qa_turn_count":       len(exec_responses),
        "qa_sentiment_min":    round(min(scores), 4),
        "qa_sentiment_max":    round(max(scores), 4),
    }


def _empty():
    return {"qa_volatility_score": None, "qa_sentiment_mean": None,
            "qa_sentiment_std": None, "qa_turn_count": 0,
            "qa_sentiment_min": None, "qa_sentiment_max": None}


# ── DB operations ─────────────────────────────────────────────────────────────

def ensure_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
    for col, dtype in [
        ("qa_volatility_score", "REAL"), ("qa_sentiment_mean", "REAL"),
        ("qa_sentiment_std",    "REAL"), ("qa_turn_count",     "INTEGER"),
        ("qa_sentiment_min",    "REAL"), ("qa_sentiment_max",  "REAL"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE transcripts ADD COLUMN {col} {dtype}")
    conn.commit()


def score_all(ticker_filter=None, force=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    q = "SELECT id, symbol, year, quarter, structured_content FROM transcripts"
    params = []
    if ticker_filter:
        q += " WHERE symbol=?"
        params.append(ticker_filter.upper())
    if not force:
        q += (" AND" if params else " WHERE") + " qa_volatility_score IS NULL"

    rows = conn.execute(q, params).fetchall()
    print(f"Scoring Q&A volatility for {len(rows)} transcripts...")
    print("Note: first run downloads all-MiniLM-L6-v2 (~80MB)\n")

    scored = skipped = 0
    for i, row in enumerate(rows):
        responses = extract_qa_executive_turns(row["structured_content"])

        if len(responses) < 3:
            skipped += 1
            print(f"  {row['symbol']:<5} {row['year']} Q{row['quarter']}  "
                  f"[SKIP] only {len(responses)} exec responses (need ≥3)")
            continue

        print(f"  [{i+1}/{len(rows)}] {row['symbol']} {row['year']} Q{row['quarter']} "
              f"— {len(responses)} turns...", end=" ", flush=True)

        r = score_qa_volatility(responses)
        conn.execute("""
            UPDATE transcripts SET
                qa_volatility_score=?, qa_sentiment_mean=?, qa_sentiment_std=?,
                qa_turn_count=?, qa_sentiment_min=?, qa_sentiment_max=?
            WHERE id=?
        """, (r["qa_volatility_score"], r["qa_sentiment_mean"], r["qa_sentiment_std"],
              r["qa_turn_count"], r["qa_sentiment_min"], r["qa_sentiment_max"], row["id"]))
        conn.commit()
        scored += 1
        print(f"volatility={r['qa_volatility_score']}  "
              f"mean={r['qa_sentiment_mean']}  "
              f"std={r['qa_sentiment_std']}  "
              f"turns={r['qa_turn_count']}")

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

    # Show raw structured_content speakers first
    sc = json.loads(row["structured_content"] or "[]")
    unique_speakers = list(dict.fromkeys(t.get("speaker","") for t in sc))
    print(f"\n{ticker.upper()} {year} Q{quarter}")
    print(f"  All speakers in transcript: {unique_speakers[:10]}")

    responses = extract_qa_executive_turns(row["structured_content"])
    print(f"  Executive Q&A responses extracted: {len(responses)}")
    for i, r in enumerate(responses[:3]):
        print(f"  [{i+1}] {r[:120]}...")

    if len(responses) >= 3:
        result = score_qa_volatility(responses)
        print(f"\n  Volatility : {result['qa_volatility_score']}")
        print(f"  Mean       : {result['qa_sentiment_mean']}")
        print(f"  Std dev    : {result['qa_sentiment_std']}")
        print(f"  Turns      : {result['qa_turn_count']}")


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