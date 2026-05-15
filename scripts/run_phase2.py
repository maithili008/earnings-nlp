"""
scripts/run_phase2.py — Phase 2 signal extraction runner

Usage:
    python scripts/run_phase2.py                    # all signals
    python scripts/run_phase2.py --signal hedging   # one signal
    python scripts/run_phase2.py --ticker JPM       # one ticker
    python scripts/run_phase2.py --skip-guidance    # skip large model
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH


def safe_count(conn, col):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
    if col not in cols:
        return 0
    return conn.execute(
        f"SELECT COUNT(*) FROM transcripts WHERE {col} IS NOT NULL"
    ).fetchone()[0]


def print_summary():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
    h = safe_count(conn, "hedging_score")
    g = safe_count(conn, "guidance_score")
    q = safe_count(conn, "qa_volatility_score")

    print(f"\n{'='*55}")
    print(f"  PHASE 2 SIGNAL COVERAGE")
    print(f"{'='*55}")
    print(f"  Total transcripts    : {total}")
    print(f"  Signal 1 (hedging)   : {h}/{total} ({100*h//total if total else 0}%)")
    print(f"  Signal 2 (guidance)  : {g}/{total} ({100*g//total if total else 0}%)")
    print(f"  Signal 3 (qa)        : {q}/{total} ({100*q//total if total else 0}%)")

    if h > 0:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
        g_sel = "guidance_score" if "guidance_score" in cols else "NULL"
        q_sel = "qa_volatility_score" if "qa_volatility_score" in cols else "NULL"
        rows = conn.execute(f"""
            SELECT symbol, year, quarter, hedging_score, {g_sel}, {q_sel}
            FROM transcripts
            WHERE hedging_score IS NOT NULL
            ORDER BY hedging_score DESC LIMIT 5
        """).fetchall()
        print(f"\n  Top 5 most evasive (by hedging score):")
        for r in rows:
            print(f"    {r[0]:<5} {r[1]} Q{r[2]}  "
                  f"hedging={r[3]:.3f}  "
                  f"guidance={round(r[4],3) if r[4] else 'n/a'}  "
                  f"qa={round(r[5],3) if r[5] else 'n/a'}")
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker")
    parser.add_argument("--signal", choices=["hedging", "guidance", "qa"])
    parser.add_argument("--skip-guidance", action="store_true")
    parser.add_argument("--skip-qa",       action="store_true")
    parser.add_argument("--force",         action="store_true")
    args = parser.parse_args()

    run_hedging  = args.signal in (None, "hedging")
    run_guidance = args.signal in (None, "guidance") and not args.skip_guidance
    run_qa       = args.signal in (None, "qa")       and not args.skip_qa

    if run_hedging:
        print("\n" + "═"*55)
        print("  SIGNAL 1 — Hedging Language Ratio")
        print("═"*55)
        from scripts.signal_hedging import score_all
        score_all(ticker_filter=args.ticker, force=args.force)

    if run_guidance:
        print("\n" + "═"*55)
        print("  SIGNAL 2 — Guidance Specificity (~1.6GB model first run)")
        print("═"*55)
        from scripts.signal_guidance import score_all
        score_all(ticker_filter=args.ticker, force=args.force)

    if run_qa:
        print("\n" + "═"*55)
        print("  SIGNAL 3 — Q&A Sentiment Volatility (~80MB model)")
        print("═"*55)
        from scripts.signal_qa import score_all
        score_all(ticker_filter=args.ticker, force=args.force)

    print_summary()


if __name__ == "__main__":
    main()