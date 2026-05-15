"""
scripts/hf_ingestor.py

Phase 1 (revised) — Stream kurry/sp500_earnings_transcripts from HuggingFace,
filter to bank tickers, save to local SQLite database.

Run ONCE. After this, all phases read from data/transcripts.db — no network needed.

Usage:
    python scripts/hf_ingestor.py                  # full run
    python scripts/hf_ingestor.py --preview        # scan first 2000 records, show stats only
    python scripts/hf_ingestor.py --tickers JPM BAC GS  # specific tickers only
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_RAW, END_DATE, START_DATE, TICKERS

# ── Target tickers ────────────────────────────────────────────────────────────
# Large-cap US banks confirmed in dataset + extras that may appear further in
BANK_TICKERS = {
    "JPM", "BAC", "GS",  "MS",  "C",   "PNC",
    "WFC", "USB", "TFC", "COF", "MTB", "RF",
    "KEY", "CFG", "HBAN","FITB","CMA", "ZION",
    "STT", "BK",  "NTRS","SIVB","FHN", "SNV",
    "BOKF",
}

# Date filter — only keep transcripts in our backtest window
START_YEAR = 2021
END_YEAR   = 2024

DB_PATH = Path(__file__).parent.parent / "data" / "transcripts.db"


# ── Database setup ────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    """Create the transcripts table and indexes if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol              TEXT NOT NULL,
            company_name        TEXT,
            year                INTEGER,
            quarter             INTEGER,
            date                TEXT,
            content             TEXT,
            structured_content  TEXT,   -- JSON string of speaker turns
            prepared_remarks    TEXT,   -- extracted by parser
            guidance            TEXT,   -- extracted by parser
            qa_turns            TEXT,   -- JSON string of Q&A turns only
            ingested_at         TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_symbol
            ON transcripts(symbol);
        CREATE INDEX IF NOT EXISTS idx_year_quarter
            ON transcripts(year, quarter);
        CREATE INDEX IF NOT EXISTS idx_symbol_year
            ON transcripts(symbol, year);
    """)
    conn.commit()


def record_exists(conn: sqlite3.Connection, symbol: str, year: int, quarter: int) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM transcripts WHERE symbol=? AND year=? AND quarter=?",
        (symbol, year, quarter)
    )
    return cur.fetchone() is not None


def insert_record(conn: sqlite3.Connection, record: dict):
    sc = record.get("structured_content")
    conn.execute("""
        INSERT INTO transcripts
            (symbol, company_name, year, quarter, date, content, structured_content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        record.get("symbol", ""),
        record.get("company_name", ""),
        record.get("year"),
        record.get("quarter"),
        record.get("date", ""),
        record.get("content", ""),
        json.dumps(sc) if sc else None,
    ))
    conn.commit()


# ── Main ingestor ─────────────────────────────────────────────────────────────

def run_ingestor(
    tickers: set[str] = BANK_TICKERS,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    preview: bool = False,
):
    from datasets import load_dataset

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Check what's already in the DB
    existing = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
    if existing > 0:
        print(f"  DB already has {existing} transcripts.")
        print("  Will skip already-ingested records (safe to re-run).\n")

    print("Loading dataset from local cache (no download needed)...")
    print(f"Filtering: {len(tickers)} tickers, {start_year}–{end_year}")
    print(f"Saving to: {DB_PATH}\n")

    ds = load_dataset(
        "kurry/sp500_earnings_transcripts",
        split="train",
        # No streaming — reads from local cache
    )

    # ── Counters ──────────────────────────────────────────────────────────────
    checked  = 0
    saved    = 0
    skipped  = 0   # already in DB
    filtered = 0   # wrong ticker or year
    counts: dict[str, int] = {t: 0 for t in tickers}

    start_time = time.time()

    for record in ds:
        checked += 1
        symbol = record.get("symbol", "")
        year   = record.get("year") or 0
        quarter= record.get("quarter") or 0

        # ── Filter ────────────────────────────────────────────────────────────
        if symbol not in tickers or not (start_year <= year <= end_year):
            filtered += 1
        elif preview:
            # Preview mode — just count, don't write
            counts[symbol] = counts.get(symbol, 0) + 1
            saved += 1
        elif record_exists(conn, symbol, year, quarter):
            skipped += 1
        else:
            insert_record(conn, record)
            counts[symbol] = counts.get(symbol, 0) + 1
            saved += 1

        # ── Progress every 1000 records ───────────────────────────────────────
        if checked % 1000 == 0:
            elapsed = time.time() - start_time
            rate = checked / elapsed
            found = sum(counts.values())
            print(
                f"  [{checked:>6} scanned] "
                f"saved={found}  "
                f"rate={rate:.0f} rec/s  "
                f"elapsed={elapsed:.0f}s"
            )

        # Stop early in preview mode
        if preview and checked >= 2000:
            break

    # ── Final summary ─────────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    print(f"\n{'='*55}")
    print(f"  INGEST {'PREVIEW ' if preview else ''}COMPLETE")
    print(f"{'='*55}")
    print(f"  Total scanned : {checked:,}")
    print(f"  Saved to DB   : {saved}")
    print(f"  Skipped (dupe): {skipped}")
    print(f"  Filtered out  : {filtered:,}")
    print(f"  Time elapsed  : {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"\n  Per-ticker breakdown:")

    found_tickers = {t: c for t, c in counts.items() if c > 0}
    missing = {t for t in tickers if counts.get(t, 0) == 0}

    for ticker, count in sorted(found_tickers.items()):
        print(f"    {'OK':>2}  {ticker:<6} {count} transcripts")
    for ticker in sorted(missing):
        print(f"    {'--':>2}  {ticker:<6} 0 transcripts (not found yet)")

    if not preview:
        db_count = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
        db_size  = DB_PATH.stat().st_size / 1024
        print(f"\n  DB total records : {db_count}")
        print(f"  DB file size     : {db_size:.1f} KB")
        print(f"\n  To free HF cache after this run:")
        print(f"  Remove-Item -Recurse -Force $env:USERPROFILE\\.cache\\huggingface")

    conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest HuggingFace transcripts to SQLite")
    parser.add_argument("--tickers", nargs="+", help="Specific tickers only")
    parser.add_argument("--preview", action="store_true",
                        help="Scan first 2000 records only, no DB writes")
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year",   type=int, default=END_YEAR)
    args = parser.parse_args()

    tickers = set(t.upper() for t in args.tickers) if args.tickers else BANK_TICKERS

    run_ingestor(
        tickers=tickers,
        start_year=args.start_year,
        end_year=args.end_year,
        preview=args.preview,
    )
