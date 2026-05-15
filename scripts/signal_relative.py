"""
scripts/signal_relative.py

Improvement 1 — Relative Signal Scoring

Normalizes each signal against each ticker's own historical baseline.
Converts absolute scores → z-scores (how many std devs above/below normal).

This removes the "JPM always hedges at 0.10" noise and captures
genuine deviations from each bank's own pattern.

Run:
    python scripts/signal_relative.py
    python scripts/signal_relative.py --show     # print z-score table
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH


def ensure_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
    for col, dtype in [
        ("hedging_zscore",   "REAL"),
        ("guidance_zscore",  "REAL"),
        ("qa_vol_zscore",    "REAL"),
        ("composite_rel",    "REAL"),
        ("sentiment_drop",   "REAL"),
        ("sentiment_trajectory", "REAL"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE transcripts ADD COLUMN {col} {dtype}")
    conn.commit()


def compute_relative_scores(force=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    if not force:
        already = conn.execute(
            "SELECT COUNT(*) FROM transcripts WHERE hedging_zscore IS NOT NULL"
        ).fetchone()[0]
        if already > 0:
            print(f"  {already} rows already have relative scores. Use --force to recompute.")
            conn.close()
            return

    rows = conn.execute("""
        SELECT id, symbol, year, quarter,
               hedging_score, guidance_score, qa_volatility_score
        FROM transcripts
        ORDER BY symbol, year, quarter
    """).fetchall()

    # ── Group by ticker ───────────────────────────────────────────────────────
    by_ticker: dict[str, list] = {}
    for row in rows:
        by_ticker.setdefault(row["symbol"], []).append(dict(row))

    print(f"Computing relative scores for {len(rows)} transcripts across "
          f"{len(by_ticker)} tickers...\n")

    updated = 0
    for ticker, ticker_rows in sorted(by_ticker.items()):
        for signal in ["hedging_score", "guidance_score", "qa_volatility_score"]:
            vals = [r[signal] for r in ticker_rows if r[signal] is not None]
            if len(vals) < 3:
                # Not enough history — leave as None
                continue

            mean = np.mean(vals)
            std  = np.std(vals)

            col_map = {
                "hedging_score":       "hedging_zscore",
                "guidance_score":      "guidance_zscore",
                "qa_volatility_score": "qa_vol_zscore",
            }
            z_col = col_map[signal]

            for row in ticker_rows:
                val = row[signal]
                if val is None:
                    continue
                z = (val - mean) / std if std > 0 else 0.0
                conn.execute(
                    f"UPDATE transcripts SET {z_col}=? WHERE id=?",
                    (round(z, 4), row["id"])
                )

        conn.commit()

        # ── Compute relative composite ────────────────────────────────────────
        for row in ticker_rows:
            z_row = conn.execute(
                "SELECT hedging_zscore, guidance_zscore, qa_vol_zscore,"
                "       sentiment_drop, sentiment_trajectory FROM transcripts WHERE id=?",
                (row["id"],)
            ).fetchone()

            if z_row is None:
                continue

            zh = z_row["hedging_zscore"]
            zg = z_row["guidance_zscore"]
            zq = z_row["qa_vol_zscore"]
            sd = z_row["sentiment_drop"]
            st = z_row["sentiment_trajectory"]

            available, weights = [], []
            if zh is not None: available.append(zh); weights.append(0.35)
            if zg is not None: available.append(zg); weights.append(0.30)
            if zq is not None: available.append(zq); weights.append(0.20)
            if sd is not None: available.append(sd); weights.append(0.10)
            if st is not None: available.append(st); weights.append(0.05)

            if not available:
                continue

            total_w = sum(weights)
            composite = sum(v * w / total_w for v, w in zip(available, weights))
            conn.execute(
                "UPDATE transcripts SET composite_rel=? WHERE id=?",
                (round(composite, 4), row["id"])
            )
            updated += 1

        conn.commit()

        # Print per-ticker summary
        z_rows = conn.execute("""
            SELECT year, quarter, hedging_score, hedging_zscore, composite_rel
            FROM transcripts WHERE symbol=?
            ORDER BY year, quarter
        """, (ticker,)).fetchall()

        print(f"  {ticker}")
        for zr in z_rows:
            flag = " ◄" if (zr["hedging_zscore"] or 0) > 1.0 else ""
            print(f"    {zr['year']} Q{zr['quarter']}  "
                  f"hedging={zr['hedging_score']:.3f}  "
                  f"z={zr['hedging_zscore'] or 0:+.2f}  "
                  f"composite_rel={zr['composite_rel'] or 0:+.3f}{flag}")

    print(f"\nDone — {updated} rows updated with relative scores")
    conn.close()


def run_relative_backtest():
    """
    Quick backtest using composite_rel instead of absolute composite.
    High z-score = unusually evasive for this ticker = predict DOWN.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT symbol, year, quarter, composite_rel,
               return_t1, return_t3, direction_t1, direction_t3
        FROM transcripts
        WHERE composite_rel IS NOT NULL
          AND return_t1 IS NOT NULL
        ORDER BY symbol, year, quarter
    """).fetchall()
    conn.close()

    if not rows:
        print("No relative scores found. Run compute_relative_scores() first.")
        return

    # Predict: z > 0 (above own baseline) → down, z <= 0 → up
    total = len(rows)
    correct_t1 = sum(
        1 for r in rows
        if (r["composite_rel"] > 0 and r["direction_t1"] == "down") or
           (r["composite_rel"] <= 0 and r["direction_t1"] == "up")
    )
    correct_t3 = sum(
        1 for r in rows
        if r["direction_t3"] is not None and (
            (r["composite_rel"] > 0 and r["direction_t3"] == "down") or
            (r["composite_rel"] <= 0 and r["direction_t3"] == "up")
        )
    )
    has_t3 = sum(1 for r in rows if r["direction_t3"] is not None)

    # Top quartile (z > 1.0 = unusually evasive)
    top = [r for r in rows if (r["composite_rel"] or 0) > 1.0]
    top_correct = sum(
        1 for r in top if r["direction_t1"] == "down"
    )

    # Per-ticker
    by_ticker: dict[str, list] = {}
    for r in rows:
        by_ticker.setdefault(r["symbol"], []).append(r)

    print("\n" + "═"*58)
    print("  RELATIVE BACKTEST RESULTS")
    print("═"*58)
    print(f"  Transcripts        : {total}")
    print(f"  T+1 accuracy       : {correct_t1/total:.1%}  ({correct_t1}/{total})")
    print(f"  T+3 accuracy       : {correct_t3/has_t3:.1%}  ({correct_t3}/{has_t3})")
    print(f"  Baseline           : 50.0%")
    print(f"  High-z T+1 (z>1.0) : {top_correct/len(top):.1%}  "
          f"(n={len(top)}, predict all down)")
    print()
    print("  Per-ticker T+1 accuracy:")
    ticker_results = []
    for ticker, t_rows in sorted(by_ticker.items()):
        n = len(t_rows)
        c = sum(
            1 for r in t_rows
            if (r["composite_rel"] > 0 and r["direction_t1"] == "down") or
               (r["composite_rel"] <= 0 and r["direction_t1"] == "up")
        )
        ticker_results.append((ticker, c/n, n))

    for ticker, acc, n in sorted(ticker_results, key=lambda x: x[1], reverse=True):
        bar = "█" * int(acc * 20)
        print(f"  {ticker:<6} {acc:.1%}  {bar}  (n={n})")

    print("═"*58)

    # Mid-size subset
    mid = [r for r in rows if r["symbol"] in
           ("HBAN","MTB","NTRS","RF","CFG","MS","KEY","FITB","USB","STT","TFC")]
    mid_correct = sum(
        1 for r in mid
        if (r["composite_rel"] > 0 and r["direction_t1"] == "down") or
           (r["composite_rel"] <= 0 and r["direction_t1"] == "up")
    )
    if mid:
        print(f"\n  Mid-size subset    : {mid_correct/len(mid):.1%}  ({mid_correct}/{len(mid)})")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--show",  action="store_true",
                        help="Only print backtest, skip recompute")
    args = parser.parse_args()

    if not args.show:
        compute_relative_scores(force=args.force)
    run_relative_backtest()
