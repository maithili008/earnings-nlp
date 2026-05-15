"""
scripts/backtest_adaptive.py

Adaptive backtest — uses per-ticker learned signal direction.

For tickers where evasiveness historically predicts UP (inverted signal),
we flip the prediction. This is learned from historical data and applied
to the same dataset as a theoretical ceiling demonstration.

Also includes:
  - Ablation study (which signals contribute most)
  - Bootstrap confidence intervals per ticker
  - Feature importance ranking

Run:
    python scripts/backtest_adaptive.py
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_BACKTEST, DB_PATH

# ── Per-ticker direction (learned from check_direction.py) ────────────────────
# +1 = normal (high evasiveness → predict down)
# -1 = inverted (high evasiveness → predict up)
TICKER_DIRECTION = {
    "CFG":  1, "MTB":  1, "BAC":  1, "HBAN": 1,
    "NTRS": 1, "WFC":  1, "MS":   1, "STT":  1,
    "USB":  1, "FITB": 1, "KEY":  1, "RF":   1,
    "BK":  -1, "GS":  -1, "C":   -1, "JPM": -1,
    "TFC": -1, "COF": -1, "PNC": -1, "ZION":-1,
}


def bootstrap_ci(values: list[bool], n_boot=1000, ci=0.95):
    arr = np.array(values, dtype=float)
    if len(arr) == 0:
        return 0.0, 0.0
    boots = [np.mean(np.random.choice(arr, len(arr), replace=True))
             for _ in range(n_boot)]
    a = (1 - ci) / 2
    return float(np.percentile(boots, a*100)), float(np.percentile(boots, (1-a)*100))


def predict(composite_rel: float, ticker: str) -> str:
    direction = TICKER_DIRECTION.get(ticker, 1)
    if direction == 1:
        return "down" if composite_rel > 0 else "up"
    else:
        return "up" if composite_rel > 0 else "down"


def run_ablation(rows: list) -> dict:
    """
    Test each signal individually and in combinations.
    Shows which signals contribute most to accuracy.
    """
    results = {}

    signal_cols = [
        ("hedging_zscore",  "Hedging only"),
        ("guidance_zscore", "Guidance only"),
        ("qa_vol_zscore",   "Q&A volatility only"),
        ("sentiment_drop",  "Sentiment drop only"),
    ]

    for col, label in signal_cols:
        valid = [r for r in rows if r[col] is not None and r["direction_t1"]]
        if not valid:
            continue
        correct = sum(
            1 for r in valid
            if predict(r[col] * TICKER_DIRECTION.get(r["symbol"], 1)
                       * TICKER_DIRECTION.get(r["symbol"], 1),
                       r["symbol"]) == r["direction_t1"]
        )
        # Simpler: use raw col directly
        correct = sum(
            1 for r in valid
            if (r[col] > 0 and TICKER_DIRECTION.get(r["symbol"],1) == 1
                and r["direction_t1"] == "down") or
               (r[col] > 0 and TICKER_DIRECTION.get(r["symbol"],1) == -1
                and r["direction_t1"] == "up") or
               (r[col] <= 0 and TICKER_DIRECTION.get(r["symbol"],1) == 1
                and r["direction_t1"] == "up") or
               (r[col] <= 0 and TICKER_DIRECTION.get(r["symbol"],1) == -1
                and r["direction_t1"] == "down")
        )
        results[label] = {
            "accuracy": round(correct / len(valid), 4),
            "n": len(valid),
        }

    # Composite (all signals)
    valid_all = [r for r in rows if r["composite_rel"] is not None
                 and r["direction_t1"]]
    correct_all = sum(
        1 for r in valid_all
        if predict(r["composite_rel"], r["symbol"]) == r["direction_t1"]
    )
    results["All signals combined"] = {
        "accuracy": round(correct_all / len(valid_all), 4),
        "n": len(valid_all),
    }

    return results


def run_adaptive_backtest():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT symbol, year, quarter, date,
               hedging_zscore, guidance_zscore, qa_vol_zscore,
               sentiment_drop, sentiment_trajectory,
               composite_rel, return_t1, return_t3,
               direction_t1, direction_t3
        FROM transcripts
        WHERE composite_rel IS NOT NULL
          AND return_t1 IS NOT NULL
          AND direction_t1 IS NOT NULL
        ORDER BY symbol, year, quarter
    """).fetchall()
    conn.close()

    rows = [dict(r) for r in rows]
    total = len(rows)

    # ── Adaptive predictions ──────────────────────────────────────────────────
    for r in rows:
        r["predicted"] = predict(r["composite_rel"], r["symbol"])
        r["correct_t1"] = r["predicted"] == r["direction_t1"]
        r["correct_t3"] = (
            r["predicted"] == r["direction_t3"]
            if r["direction_t3"] else None
        )

    correct_t1 = sum(1 for r in rows if r["correct_t1"])
    correct_t3 = sum(1 for r in rows if r["correct_t3"])
    has_t3     = sum(1 for r in rows if r["correct_t3"] is not None)

    # ── High conviction ───────────────────────────────────────────────────────
    # abs(composite_rel) > 1.0 = strong signal regardless of direction
    high_conv = [r for r in rows if abs(r["composite_rel"]) > 1.0]
    hc_correct = sum(1 for r in high_conv if r["correct_t1"])

    # ── Correlation ───────────────────────────────────────────────────────────
    # For inverted tickers, negate composite_rel before correlating
    aligned = [
        r["composite_rel"] * TICKER_DIRECTION.get(r["symbol"], 1)
        for r in rows
    ]
    returns = [-r["return_t1"] for r in rows]  # negative: high signal → negative return
    pearson_r,  pearson_p  = stats.pearsonr(aligned, returns)
    spearman_r, spearman_p = stats.spearmanr(aligned, returns)

    # ── Per-ticker ────────────────────────────────────────────────────────────
    by_ticker: dict[str, list] = {}
    for r in rows:
        by_ticker.setdefault(r["symbol"], []).append(r)

    ticker_stats = {}
    for ticker, t_rows in sorted(by_ticker.items()):
        correct = [r["correct_t1"] for r in t_rows]
        acc = sum(correct) / len(correct)
        lo, hi = bootstrap_ci(correct)
        ticker_stats[ticker] = {
            "n": len(t_rows),
            "accuracy": round(acc, 4),
            "ci_low":   round(lo, 4),
            "ci_high":  round(hi, 4),
            "direction": "inverted" if TICKER_DIRECTION.get(ticker,1) == -1 else "normal",
            "mean_ret": round(np.mean([r["return_t1"] for r in t_rows]), 4),
        }

    # ── Ablation ──────────────────────────────────────────────────────────────
    ablation = run_ablation(rows)

    # ── Overall CI ───────────────────────────────────────────────────────────
    all_correct = [r["correct_t1"] for r in rows]
    ci_lo, ci_hi = bootstrap_ci(all_correct)

    # ── Print report ──────────────────────────────────────────────────────────
    print("\n" + "═"*62)
    print("  ADAPTIVE BACKTEST RESULTS")
    print("  (per-ticker signal direction applied)")
    print("═"*62)
    print(f"  Transcripts        : {total}")
    print(f"  Tickers            : {len(by_ticker)}")
    print()
    print(f"  ── Directional Accuracy ──")
    print(f"  T+1 accuracy       : {correct_t1/total:.1%}  "
          f"(95% CI: {ci_lo:.1%}–{ci_hi:.1%})")
    print(f"  T+3 accuracy       : {correct_t3/has_t3:.1%}")
    print(f"  Baseline           : 50.0%")
    print(f"  High-conviction    : {hc_correct/len(high_conv):.1%}  "
          f"(|z|>1.0, n={len(high_conv)})")
    print()
    print(f"  ── Aligned Correlation ──")
    print(f"  Pearson r          : {pearson_r:+.4f}  (p={pearson_p:.4f})")
    print(f"  Spearman r         : {spearman_r:+.4f}  (p={spearman_p:.4f})")
    print()
    print(f"  ── Ablation Study — Signal Contribution ──")
    for label, res in sorted(ablation.items(), key=lambda x: x[1]["accuracy"], reverse=True):
        bar = "█" * int(res["accuracy"] * 20)
        lift = res["accuracy"] - 0.5
        print(f"  {label:<28} {res['accuracy']:.1%}  {bar}  "
              f"({'+'if lift>=0 else ''}{lift:.1%} vs baseline, n={res['n']})")
    print()
    print(f"  ── Per-Ticker Accuracy (T+1) ──")
    for ticker, s in sorted(ticker_stats.items(),
                            key=lambda x: x[1]["accuracy"], reverse=True):
        bar  = "█" * int(s["accuracy"] * 20)
        flag = " ↑" if s["direction"] == "inverted" else ""
        print(f"  {ticker:<6} {s['accuracy']:.1%}  {bar}  "
              f"CI:[{s['ci_low']:.0%}–{s['ci_high']:.0%}]"
              f"  ret={s['mean_ret']:+.2%}{flag}")
    print()
    print(f"  ↑ = inverted signal applied for this ticker")
    print("═"*62)

    # ── Save results ──────────────────────────────────────────────────────────
    DATA_BACKTEST.mkdir(parents=True, exist_ok=True)
    out = {
        "method": "adaptive_per_ticker",
        "total": total,
        "accuracy_t1": round(correct_t1/total, 4),
        "accuracy_t3": round(correct_t3/has_t3, 4),
        "ci_t1": [round(ci_lo, 4), round(ci_hi, 4)],
        "high_conviction_accuracy": round(hc_correct/len(high_conv), 4),
        "high_conviction_n": len(high_conv),
        "pearson_r": round(float(pearson_r), 4),
        "pearson_p": round(float(pearson_p), 4),
        "spearman_r": round(float(spearman_r), 4),
        "spearman_p": round(float(spearman_p), 4),
        "ablation": ablation,
        "per_ticker": ticker_stats,
        "ticker_directions": TICKER_DIRECTION,
    }
    out_path = DATA_BACKTEST / "adaptive_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Results saved to {out_path}")
    return out


if __name__ == "__main__":
    run_adaptive_backtest()
