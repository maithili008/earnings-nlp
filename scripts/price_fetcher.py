"""
scripts/price_fetcher.py

Phase 3, Step 1 — Fetch post-earnings price returns.

Reads all transcripts from SQLite, fetches T+1 and T+3 returns
via yfinance, writes back to DB.

Run:
    python scripts/price_fetcher.py
    python scripts/price_fetcher.py --ticker JPM
    python scripts/price_fetcher.py --refresh
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH

_price_cache: dict[str, pd.DataFrame] = {}


def get_prices(ticker: str) -> pd.DataFrame:
    if ticker in _price_cache:
        return _price_cache[ticker]
    print(f"    Downloading prices for {ticker}...")
    try:
        df = yf.download(ticker, start="2020-01-01", end="2025-06-01",
                         auto_adjust=True, progress=False)
        if df.empty:
            df = yf.download(ticker, start="2020-01-01", end="2023-06-01",
                             auto_adjust=False, progress=False)
        if not df.empty:
            df.index = pd.to_datetime(df.index).tz_localize(None)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
    except Exception as e:
        print(f"    Warning: {ticker} price fetch failed — {e}")
        df = pd.DataFrame()
    _price_cache[ticker] = df
    return df


def get_return(ticker: str, date_str: str, days: int) -> float | None:
    df = get_prices(ticker)
    if df.empty:
        return None
    try:
        date_only = str(date_str).split(" ")[0].split("T")[0]
        dt = pd.Timestamp(date_only)
        future_days = df.index[df.index >= dt]
        if len(future_days) < days + 1:
            return None
        close  = df["Close"]
        base   = float(close.loc[future_days[0]])
        future = float(close.loc[future_days[days]])
        if base == 0:
            return None
        return round((future - base) / base, 6)
    except Exception:
        return None


def ensure_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
    for col, dtype in [
        ("return_t1",   "REAL"), ("return_t3",   "REAL"),
        ("direction_t1","TEXT"), ("direction_t3", "TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE transcripts ADD COLUMN {col} {dtype}")
    conn.commit()


def fetch_all(ticker_filter=None, refresh=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    q = "SELECT id, symbol, date FROM transcripts"
    params = []
    if ticker_filter:
        q += " WHERE symbol=?"
        params.append(ticker_filter.upper())
    if not refresh:
        q += (" AND" if params else " WHERE") + " return_t1 IS NULL"

    rows = conn.execute(q, params).fetchall()
    print(f"Fetching prices for {len(rows)} transcripts...\n")

    by_ticker: dict[str, list] = {}
    for row in rows:
        by_ticker.setdefault(row["symbol"], []).append(row)

    updated = skipped = 0
    for ticker, ticker_rows in by_ticker.items():
        print(f"\n  {ticker} ({len(ticker_rows)} transcripts)")
        get_prices(ticker)  # pre-warm cache

        for row in sorted(ticker_rows, key=lambda r: r["date"]):
            r1 = get_return(ticker, row["date"], 1)
            r3 = get_return(ticker, row["date"], 3)

            if r1 is None:
                skipped += 1
                print(f"    {row['date']} — no price data")
                continue

            conn.execute("""
                UPDATE transcripts SET
                    return_t1=?, return_t3=?,
                    direction_t1=?, direction_t3=?
                WHERE id=?
            """, (
                r1, r3,
                "up" if r1 > 0 else "down",
                ("up" if r3 > 0 else "down") if r3 is not None else None,
                row["id"],
            ))
            conn.commit()
            updated += 1
            print(f"    {row['date']}  T+1={r1:+.2%}  T+3={r3:+.2%}")
        time.sleep(0.3)

    print(f"\nDone — {updated} updated, {skipped} skipped")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    fetch_all(ticker_filter=args.ticker, refresh=args.refresh)
