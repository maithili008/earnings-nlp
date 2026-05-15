"""
scripts/run_phase1.py

Runs the complete Phase 1 pipeline:
  1. Scrape EDGAR for transcripts   → data/raw/
  2. Parse transcripts into sections → data/processed/
  3. Fetch price returns             → data/processed/ (enriched)

Usage:
    python scripts/run_phase1.py                  # full run, all tickers
    python scripts/run_phase1.py --tickers JPM BAC # subset
    python scripts/run_phase1.py --skip-scrape    # parse + prices only (if raw/ exists)
    python scripts/run_phase1.py --dry-run        # preview scrape without saving
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATA_PROCESSED, DATA_RAW, TICKERS


def main():
    parser = argparse.ArgumentParser(description="Run Phase 1 pipeline")
    parser.add_argument("--tickers", nargs="+", help="Subset of tickers")
    parser.add_argument("--skip-scrape", action="store_true")
    parser.add_argument("--skip-parse", action="store_true")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers] if args.tickers else TICKERS

    # ── Step 1: Scrape ────────────────────────────────────────────────────────
    if not args.skip_scrape:
        print("\n" + "═"*60)
        print("  STEP 1 — Scraping EDGAR")
        print("═"*60)
        from scripts.edgar_scraper import scrape_all
        scrape_all(tickers=tickers, dry_run=args.dry_run)
    else:
        print("\n[SKIP] Scraping (--skip-scrape)")

    if args.dry_run:
        print("\n[DRY RUN] Stopping after scrape preview.")
        return

    # ── Step 2: Parse ─────────────────────────────────────────────────────────
    if not args.skip_parse:
        print("\n" + "═"*60)
        print("  STEP 2 — Parsing transcripts")
        print("═"*60)
        from scripts.transcript_parser import process_all
        for ticker in tickers:
            process_all(ticker_filter=ticker)
    else:
        print("\n[SKIP] Parsing (--skip-parse)")

    # ── Step 3: Price returns ─────────────────────────────────────────────────
    if not args.skip_prices:
        print("\n" + "═"*60)
        print("  STEP 3 — Fetching price returns")
        print("═"*60)
        from scripts.price_fetcher import fetch_all_prices, print_coverage_report
        for ticker in tickers:
            fetch_all_prices(ticker_filter=ticker)
        print_coverage_report()
    else:
        print("\n[SKIP] Price fetching (--skip-prices)")

    print("\n" + "═"*60)
    print("  PHASE 1 COMPLETE")
    raw_count = len(list(DATA_RAW.glob("*.json")))
    proc_count = len(list(DATA_PROCESSED.glob("*.json")))
    print(f"  Raw transcripts:       {raw_count}")
    print(f"  Processed transcripts: {proc_count}")
    print("═"*60)
    print("\nNext: run Phase 2 signal extraction")
    print("  python scripts/run_phase2.py")


if __name__ == "__main__":
    main()
