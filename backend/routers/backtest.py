"""GET /api/backtest — aggregate results, ablation, SIVB timeline"""
import json
from fastapi import APIRouter, HTTPException
from pathlib import Path

router = APIRouter()

RESULTS_PATH = Path(__file__).parent.parent.parent / "data" / "backtest" / "adaptive_results.json"

@router.get("/backtest")
def get_backtest():
    if not RESULTS_PATH.exists():
        raise HTTPException(status_code=404,
            detail="Run backtest_adaptive.py first")
    with open(RESULTS_PATH) as f:
        return json.load(f)


@router.get("/backtest/sivb")
def get_sivb_timeline():
    """SIVB evasiveness scores leading up to March 2023 collapse."""
    from backend.db import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT year, quarter, date,
               hedging_score, composite_rel, sentiment_drop,
               return_t1, direction_t1
        FROM transcripts
        WHERE symbol = 'SIVB'
        ORDER BY year, quarter
    """).fetchall()
    conn.close()
    return [
        {
            "label":        f"Q{r['quarter']} {r['year']}",
            "date":         r["date"],
            "hedging":      round(r["hedging_score"] or 0, 4),
            "composite":    round(r["composite_rel"] or 0, 4),
            "sentiment_drop": round(r["sentiment_drop"] or 0, 4) if r["sentiment_drop"] else None,
            "return_t1":    round(r["return_t1"] or 0, 4) if r["return_t1"] else None,
            "direction":    r["direction_t1"],
        }
        for r in rows
    ]


@router.get("/backtest/heatmap")
def get_all_heatmap():
    """Signal scores vs returns for all tickers — used for the main heatmap."""
    from backend.db import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT symbol, year, quarter,
               composite_rel, return_t1, direction_t1,
               hedging_score, sentiment_drop
        FROM transcripts
        WHERE composite_rel IS NOT NULL AND return_t1 IS NOT NULL
        ORDER BY symbol, year, quarter
    """).fetchall()
    conn.close()
    return [
        {
            "symbol":   r["symbol"],
            "period":   f"Q{r['quarter']} {r['year']}",
            "composite": round(r["composite_rel"] or 0, 3),
            "return_t1": round(r["return_t1"] or 0, 4),
            "direction": r["direction_t1"],
            "hedging":   round(r["hedging_score"] or 0, 4),
        }
        for r in rows
    ]
