"""
scripts/signal_earnings_surprise.py

Improvement 2 — Earnings Surprise Signal

Fetches actual vs estimated EPS for each transcript date via yfinance.
A negative surprise (missed estimates) amplifies the evasiveness signal.
A positive beat dampens it.

Combined signal logic:
  - High evasiveness + earnings miss  → strong bearish
  - High evasiveness + earnings beat  → signal dampened (management defensive
                                        despite good results = interesting)
  - Low evasiveness  + earnings miss  → contrarian signal
  - Low evasiveness  + earnings beat  → bullish

Run:
    python scripts/signal_earnings_surprise.py
    python scripts/signal_earnings_surprise.py --backtest
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import yfinance as yf
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH


def ensure_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
    for col, dtype in [
        ("eps_actual",    "REAL"),
        ("eps_estimate",  "REAL"),
        ("eps_surprise",  "REAL"),   # (actual - estimate) / abs(estimate)
        ("beat_miss",     "TEXT"),   # 'beat', 'miss', 'inline', or None
        ("combined_signal", "REAL"), # composite_rel adjusted by surprise
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE transcripts ADD COLUMN {col} {dtype}")
    conn.commit()


def get_earnings_history(ticker: str) -> dict:
    """
    Returns dict of {date_str: {actual, estimate, surprise}} for a ticker.
    yfinance earnings_history gives quarterly EPS data.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.earnings_history
        if hist is None or hist.empty:
            return {}

        result = {}
        for idx, row in hist.iterrows():
            date_str = str(idx.date()) if hasattr(idx, 'date') else str(idx)[:10]
            actual   = row.get("epsActual")
            estimate = row.get("epsEstimate")
            if actual is None or estimate is None:
                continue
            try:
                actual   = float(actual)
                estimate = float(estimate)
                if abs(estimate) > 0.001:
                    surprise = (actual - estimate) / abs(estimate)
                else:
                    surprise = 0.0
                result[date_str] = {
                    "actual":   round(actual, 4),
                    "estimate": round(estimate, 4),
                    "surprise": round(surprise, 4),
                }
            except (TypeError, ValueError):
                continue
        return result
    except Exception as e:
        print(f"    Warning: {ticker} earnings history failed — {e}")
        return {}


def find_closest_earnings(transcript_date: str, earnings_hist: dict,
                          max_days: int = 5) -> dict | None:
    """
    Find the earnings record closest to the transcript date.
    Earnings calls happen within a few days of the actual report date.
    """
    from datetime import datetime, timedelta

    try:
        t_date = datetime.strptime(transcript_date[:10], "%Y-%m-%d")
    except ValueError:
        return None

    best = None
    best_delta = max_days + 1

    for date_str, data in earnings_hist.items():
        try:
            e_date = datetime.strptime(date_str, "%Y-%m-%d")
            delta  = abs((t_date - e_date).days)
            if delta <= max_days and delta < best_delta:
                best       = data
                best_delta = delta
        except ValueError:
            continue

    return best


def fetch_all_surprises(force=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    if not force:
        already = conn.execute(
            "SELECT COUNT(*) FROM transcripts WHERE eps_actual IS NOT NULL"
        ).fetchone()[0]
        if already > 0:
            print(f"  {already} rows already have surprise data. Use --force to rerun.")
            conn.close()
            return

    rows = conn.execute(
        "SELECT id, symbol, date FROM transcripts ORDER BY symbol, date"
    ).fetchall()

    by_ticker: dict[str, list] = {}
    for row in rows:
        by_ticker.setdefault(row["symbol"], []).append(dict(row))

    updated = missing = 0

    for ticker, ticker_rows in sorted(by_ticker.items()):
        print(f"\n  {ticker} — fetching earnings history...")
        hist = get_earnings_history(ticker)
        print(f"    Found {len(hist)} earnings records")
        time.sleep(0.3)

        for row in ticker_rows:
            match = find_closest_earnings(row["date"], hist)
            if not match:
                missing += 1
                continue

            surprise  = match["surprise"]
            beat_miss = (
                "beat"   if surprise >  0.02 else
                "miss"   if surprise < -0.02 else
                "inline"
            )

            conn.execute("""
                UPDATE transcripts SET
                    eps_actual=?, eps_estimate=?, eps_surprise=?, beat_miss=?
                WHERE id=?
            """, (match["actual"], match["estimate"], surprise, beat_miss, row["id"]))

            print(f"    {row['date'][:10]}  "
                  f"actual={match['actual']:+.2f}  "
                  f"est={match['estimate']:+.2f}  "
                  f"surprise={surprise:+.1%}  {beat_miss}")
            updated += 1

        conn.commit()

    # ── Compute combined signal ───────────────────────────────────────────────
    print(f"\n  Computing combined signal...")
    scored = conn.execute("""
        SELECT id, composite_rel, eps_surprise, beat_miss
        FROM transcripts
        WHERE composite_rel IS NOT NULL AND eps_surprise IS NOT NULL
    """).fetchall()

    for row in scored:
        comp = row["composite_rel"]
        surp = row["eps_surprise"]

        # Combined: evasiveness z-score adjusted by earnings surprise
        # Miss amplifies evasiveness signal, beat dampens it
        surprise_adjustment = -surp * 2.0  # negative surprise → higher signal
        combined = comp + surprise_adjustment
        conn.execute(
            "UPDATE transcripts SET combined_signal=? WHERE id=?",
            (round(combined, 4), row["id"])
        )

    conn.commit()
    print(f"\n  Done — {updated} updated, {missing} no match found")
    conn.close()


def run_combined_backtest():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT symbol, year, quarter, date,
               composite_rel, combined_signal, eps_surprise, beat_miss,
               return_t1, return_t3, direction_t1, direction_t3
        FROM transcripts
        WHERE combined_signal IS NOT NULL
          AND return_t1 IS NOT NULL
        ORDER BY symbol, year, quarter
    """).fetchall()
    conn.close()

    if not rows:
        print("No combined signal data. Run fetch_all_surprises() first.")
        return

    total = len(rows)

    # Predict: combined_signal > 0 → down, <= 0 → up
    correct_t1 = sum(
        1 for r in rows
        if (r["combined_signal"] > 0 and r["direction_t1"] == "down") or
           (r["combined_signal"] <= 0 and r["direction_t1"] == "up")
    )
    correct_t3 = sum(
        1 for r in rows
        if r["direction_t3"] and (
            (r["combined_signal"] > 0 and r["direction_t3"] == "down") or
            (r["combined_signal"] <= 0 and r["direction_t3"] == "up")
        )
    )
    has_t3 = sum(1 for r in rows if r["direction_t3"])

    # High conviction: combined > 1.0 AND miss
    high_conv = [r for r in rows
                 if r["combined_signal"] > 1.0 and r["beat_miss"] == "miss"]
    hc_correct = sum(1 for r in high_conv if r["direction_t1"] == "down")

    # Per-ticker
    by_ticker: dict[str, list] = {}
    for r in rows:
        by_ticker.setdefault(r["symbol"], []).append(r)

    print("\n" + "═"*58)
    print("  COMBINED SIGNAL BACKTEST (evasiveness + earnings surprise)")
    print("═"*58)
    print(f"  Transcripts with combined signal : {total}")
    print(f"  T+1 accuracy   : {correct_t1/total:.1%}  ({correct_t1}/{total})")
    print(f"  T+3 accuracy   : {correct_t3/has_t3:.1%}  ({correct_t3}/{has_t3})")
    print(f"  Baseline       : 50.0%")
    if high_conv:
        print(f"  High-conviction (evasive + miss) : "
              f"{hc_correct/len(high_conv):.1%}  (n={len(high_conv)})")

    print(f"\n  Per-ticker T+1 accuracy:")
    ticker_results = []
    for ticker, t_rows in sorted(by_ticker.items()):
        n = len(t_rows)
        c = sum(
            1 for r in t_rows
            if (r["combined_signal"] > 0 and r["direction_t1"] == "down") or
               (r["combined_signal"] <= 0 and r["direction_t1"] == "up")
        )
        ticker_results.append((ticker, c/n, n))

    for ticker, acc, n in sorted(ticker_results, key=lambda x: x[1], reverse=True):
        bar = "█" * int(acc * 20)
        print(f"  {ticker:<6} {acc:.1%}  {bar}  (n={n})")

    # Mid-size subset
    mid_tickers = {"HBAN","MTB","NTRS","RF","CFG","MS","KEY","FITB","USB","STT","TFC"}
    mid = [r for r in rows if r["symbol"] in mid_tickers]
    if mid:
        mid_correct = sum(
            1 for r in mid
            if (r["combined_signal"] > 0 and r["direction_t1"] == "down") or
               (r["combined_signal"] <= 0 and r["direction_t1"] == "up")
        )
        print(f"\n  Mid-size subset : {mid_correct/len(mid):.1%}  "
              f"({mid_correct}/{len(mid)})")
    print("═"*58)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force",    action="store_true")
    parser.add_argument("--backtest", action="store_true",
                        help="Only run backtest, skip fetching")
    args = parser.parse_args()

    if not args.backtest:
        fetch_all_surprises(force=args.force)
    run_combined_backtest()
