"""
scripts/backtest.py

Phase 3 — Backtest Engine

Tests whether the composite evasiveness score predicts next-day
stock direction across all 344 transcripts.

Metrics reported:
  - Overall directional accuracy (T+1 and T+3)
  - Top-quartile signal accuracy (high evasiveness → predict down)
  - Per-ticker accuracy breakdown
  - Signal-return correlation (Pearson r)
  - Confidence intervals via bootstrap

Run:
    python scripts/backtest.py
    python scripts/backtest.py --output data/backtest/results.json
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_BACKTEST, DB_PATH, TOP_QUARTILE_THRESHOLD

# ── Composite score ───────────────────────────────────────────────────────────

def compute_composite(hedging, guidance, qa_vol,
                      w_hedge=0.4, w_guidance=0.35, w_qa=0.25) -> float | None:
    """
    Weighted composite evasiveness score.
    Higher = more evasive = bearish signal.

    Weights: hedging carries most weight (most reliable signal),
    guidance second, Q&A volatility third.
    """
    available = []
    weights   = []

    if hedging is not None:
        available.append(hedging)
        weights.append(w_hedge)
    if guidance is not None:
        available.append(guidance)
        weights.append(w_guidance)
    if qa_vol is not None:
        available.append(qa_vol)
        weights.append(w_qa)

    if not available:
        return None

    # Normalize weights to sum to 1
    total_w = sum(weights)
    return sum(v * w / total_w for v, w in zip(available, weights))


# ── Bootstrap CI ──────────────────────────────────────────────────────────────

def bootstrap_accuracy(correct: list[bool], n_boot=1000, ci=0.95) -> tuple[float, float]:
    """Return (lower, upper) confidence interval for accuracy via bootstrap."""
    if not correct:
        return 0.0, 0.0
    arr = np.array(correct, dtype=float)
    boot_means = [np.mean(np.random.choice(arr, size=len(arr), replace=True))
                  for _ in range(n_boot)]
    alpha = (1 - ci) / 2
    return float(np.percentile(boot_means, alpha * 100)), \
           float(np.percentile(boot_means, (1 - alpha) * 100))


# ── Main backtest ─────────────────────────────────────────────────────────────

def run_backtest(output_path: Path | None = None) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT symbol, year, quarter, date,
               hedging_score, guidance_score, qa_volatility_score,
               return_t1, return_t3, direction_t1, direction_t3
        FROM transcripts
        WHERE return_t1 IS NOT NULL
          AND hedging_score IS NOT NULL
        ORDER BY symbol, year, quarter
    """).fetchall()
    conn.close()

    if not rows:
        print("No rows with both signals and price data. Run price_fetcher.py first.")
        return {}

    print(f"Running backtest on {len(rows)} transcripts...\n")

    # Build DataFrame
    data = []
    for r in rows:
        composite = compute_composite(
            r["hedging_score"],
            r["guidance_score"],
            r["qa_volatility_score"],
        )
        data.append({
            "symbol":    r["symbol"],
            "year":      r["year"],
            "quarter":   r["quarter"],
            "date":      r["date"],
            "hedging":   r["hedging_score"],
            "guidance":  r["guidance_score"],
            "qa_vol":    r["qa_volatility_score"],
            "composite": composite,
            "ret_t1":    r["return_t1"],
            "ret_t3":    r["return_t3"],
            "dir_t1":    r["direction_t1"],
            "dir_t3":    r["direction_t3"],
        })

    df = pd.DataFrame(data).dropna(subset=["composite", "ret_t1"])
    print(f"  Valid rows for backtest: {len(df)}")

    # ── Prediction logic ──────────────────────────────────────────────────────
    # High evasiveness (above median) → predict DOWN
    # Low evasiveness (below median)  → predict UP
    median_score = df["composite"].median()
    df["predicted_dir"] = df["composite"].apply(
        lambda x: "down" if x >= median_score else "up"
    )
    df["correct_t1"] = df["predicted_dir"] == df["dir_t1"]
    df["correct_t3"] = (df["predicted_dir"] == df["dir_t3"]).where(
        df["dir_t3"].notna(), other=False
    )

    # ── Overall accuracy ──────────────────────────────────────────────────────
    acc_t1 = df["correct_t1"].mean()
    acc_t3 = df[df["dir_t3"].notna()]["correct_t3"].mean()
    ci_t1  = bootstrap_accuracy(df["correct_t1"].tolist())
    ci_t3  = bootstrap_accuracy(
        df[df["dir_t3"].notna()]["correct_t3"].tolist()
    )

    # ── Top-quartile accuracy ─────────────────────────────────────────────────
    q75 = df["composite"].quantile(TOP_QUARTILE_THRESHOLD)
    top_q = df[df["composite"] >= q75]
    top_acc_t1 = (top_q["predicted_dir"] == top_q["dir_t1"]).mean() \
        if len(top_q) else 0.0

    # ── Correlation ───────────────────────────────────────────────────────────
    pearson_t1, pval_t1 = stats.pearsonr(
        df["composite"], -df["ret_t1"]  # negative: high evasion → negative return
    )
    spearman_t1, spval_t1 = stats.spearmanr(df["composite"], -df["ret_t1"])

    # ── Per-ticker accuracy ───────────────────────────────────────────────────
    per_ticker = {}
    for ticker, group in df.groupby("symbol"):
        per_ticker[ticker] = {
            "n":           len(group),
            "accuracy_t1": round(group["correct_t1"].mean(), 4),
            "accuracy_t3": round(
                group[group["dir_t3"].notna()]["correct_t3"].mean(), 4
            ) if group["dir_t3"].notna().any() else None,
            "mean_composite": round(group["composite"].mean(), 4),
            "mean_return_t1": round(group["ret_t1"].mean(), 4),
        }

    # ── Per-quarter accuracy (trend over time) ────────────────────────────────
    per_quarter = {}
    for (year, quarter), group in df.groupby(["year", "quarter"]):
        per_quarter[f"{year} Q{quarter}"] = {
            "n":           len(group),
            "accuracy_t1": round(group["correct_t1"].mean(), 4),
            "mean_composite": round(group["composite"].mean(), 4),
        }

    # ── SIVB spotlight ────────────────────────────────────────────────────────
    sivb = df[df["symbol"] == "SIVB"].sort_values("date")
    sivb_rows = []
    for _, row in sivb.iterrows():
        sivb_rows.append({
            "date":      row["date"],
            "quarter":   f"{row['year']} Q{int(row['quarter'])}",
            "composite": round(row["composite"], 4),
            "hedging":   round(row["hedging"], 4),
            "ret_t1":    round(row["ret_t1"], 4),
            "correct":   bool(row["correct_t1"]),
        })

    # ── Assemble results ──────────────────────────────────────────────────────
    results = {
        "summary": {
            "total_transcripts":    len(df),
            "tickers":              sorted(df["symbol"].unique().tolist()),
            "date_range":           f"{df['date'].min()} to {df['date'].max()}",
            "median_composite":     round(float(median_score), 4),
        },
        "accuracy": {
            "overall_t1":          round(float(acc_t1), 4),
            "overall_t3":          round(float(acc_t3), 4),
            "ci_t1_lower":         round(ci_t1[0], 4),
            "ci_t1_upper":         round(ci_t1[1], 4),
            "ci_t3_lower":         round(ci_t3[0], 4),
            "ci_t3_upper":         round(ci_t3[1], 4),
            "top_quartile_t1":     round(float(top_acc_t1), 4),
            "top_quartile_n":      len(top_q),
            "baseline":            0.50,
        },
        "correlation": {
            "pearson_r":    round(float(pearson_t1), 4),
            "pearson_pval": round(float(pval_t1), 4),
            "spearman_r":   round(float(spearman_t1), 4),
            "spearman_pval":round(float(spval_t1), 4),
        },
        "per_ticker": per_ticker,
        "per_quarter": per_quarter,
        "sivb_timeline": sivb_rows,
        "signal_weights": {
            "hedging":  0.40,
            "guidance": 0.35,
            "qa_vol":   0.25,
        },
    }

    # ── Print report ──────────────────────────────────────────────────────────
    _print_report(results)

    # ── Save ──────────────────────────────────────────────────────────────────
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Results saved to {output_path}")

    return results


def _print_report(r: dict):
    acc  = r["accuracy"]
    corr = r["correlation"]
    summ = r["summary"]

    print("\n" + "═"*58)
    print("  BACKTEST RESULTS")
    print("═"*58)
    print(f"  Transcripts        : {summ['total_transcripts']}")
    print(f"  Tickers            : {len(summ['tickers'])}")
    print(f"  Date range         : {summ['date_range']}")
    print()
    print(f"  ── Directional Accuracy ──")
    print(f"  T+1 accuracy       : {acc['overall_t1']:.1%}  "
          f"(95% CI: {acc['ci_t1_lower']:.1%}–{acc['ci_t1_upper']:.1%})")
    print(f"  T+3 accuracy       : {acc['overall_t3']:.1%}  "
          f"(95% CI: {acc['ci_t3_lower']:.1%}–{acc['ci_t3_upper']:.1%})")
    print(f"  Baseline (random)  : {acc['baseline']:.1%}")
    print(f"  Top-quartile T+1   : {acc['top_quartile_t1']:.1%}  "
          f"(n={acc['top_quartile_n']})")
    print()
    print(f"  ── Signal-Return Correlation ──")
    print(f"  Pearson r          : {corr['pearson_r']:+.4f}  "
          f"(p={corr['pearson_pval']:.4f})")
    print(f"  Spearman r         : {corr['spearman_r']:+.4f}  "
          f"(p={corr['spearman_pval']:.4f})")
    print()
    print(f"  ── Per-Ticker Accuracy (T+1) ──")
    ticker_acc = sorted(
        r["per_ticker"].items(),
        key=lambda x: x[1]["accuracy_t1"],
        reverse=True
    )
    for ticker, stats in ticker_acc:
        bar = "█" * int(stats["accuracy_t1"] * 20)
        print(f"  {ticker:<6} {stats['accuracy_t1']:.1%}  {bar}  "
              f"(n={stats['n']}, mean_ret={stats['mean_return_t1']:+.2%})")

    if r["sivb_timeline"]:
        print()
        print(f"  ── SIVB Evasiveness Timeline (pre-collapse) ──")
        for row in r["sivb_timeline"]:
            flag = " ◄ HIGH" if row["composite"] > 0.11 else ""
            print(f"  {row['quarter']}  composite={row['composite']:.3f}  "
                  f"T+1={row['ret_t1']:+.2%}  {'✓' if row['correct'] else '✗'}{flag}")

    print("═"*58)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/backtest/results.json")
    args = parser.parse_args()
    run_backtest(output_path=Path(args.output))
