"""
scripts/run_phase3.py — Phase 3 runner

Usage:
    python scripts/run_phase3.py
    python scripts/run_phase3.py --skip-prices   # if prices already fetched
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--ticker")
    args = parser.parse_args()

    # Step 1 — fetch prices
    if not args.skip_prices:
        print("\n" + "═"*55)
        print("  STEP 1 — Fetching price returns")
        print("═"*55)
        from scripts.price_fetcher import fetch_all
        fetch_all(ticker_filter=args.ticker)

    # Step 2 — run backtest
    print("\n" + "═"*55)
    print("  STEP 2 — Running backtest")
    print("═"*55)
    from scripts.backtest import run_backtest
    run_backtest(output_path=Path("data/backtest/results.json"))


if __name__ == "__main__":
    main()
