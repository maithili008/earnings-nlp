"""GET /api/signals/{ticker} — all transcript scores for one ticker"""
from fastapi import APIRouter, HTTPException
from backend.db import get_conn

router = APIRouter()

@router.get("/signals/{ticker}")
def get_signals(ticker: str):
    conn = get_conn()
    rows = conn.execute("""
        SELECT symbol, year, quarter, date,
               hedging_score, guidance_score, qa_volatility_score,
               hedging_zscore, guidance_zscore, qa_vol_zscore,
               composite_rel, sentiment_drop, sentiment_trajectory,
               prepared_sentiment, qa_sentiment,
               return_t1, return_t3, direction_t1, direction_t3,
               top_hedges
        FROM transcripts
        WHERE symbol = ?
        ORDER BY year, quarter
    """, (ticker.upper(),)).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")

    import json
    return [
        {
            "symbol":        r["symbol"],
            "year":          r["year"],
            "quarter":       r["quarter"],
            "date":          r["date"],
            "signals": {
                "hedging_score":      r["hedging_score"],
                "guidance_score":     r["guidance_score"],
                "qa_volatility":      r["qa_volatility_score"],
                "sentiment_drop":     r["sentiment_drop"],
                "sentiment_trajectory": r["sentiment_trajectory"],
                "prepared_sentiment": r["prepared_sentiment"],
                "qa_sentiment":       r["qa_sentiment"],
                "composite_rel":      r["composite_rel"],
                "hedging_zscore":     r["hedging_zscore"],
            },
            "returns": {
                "t1": r["return_t1"],
                "t3": r["return_t3"],
                "direction_t1": r["direction_t1"],
                "direction_t3": r["direction_t3"],
            },
            "top_hedges": json.loads(r["top_hedges"]) if r["top_hedges"] else [],
        }
        for r in rows
    ]


@router.get("/signals/{ticker}/heatmap")
def get_heatmap(ticker: str):
    """Returns signal vs return data formatted for heatmap visualization."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT year, quarter, composite_rel, return_t1, direction_t1,
               hedging_score, sentiment_drop
        FROM transcripts
        WHERE symbol = ? AND composite_rel IS NOT NULL AND return_t1 IS NOT NULL
        ORDER BY year, quarter
    """, (ticker.upper(),)).fetchall()
    conn.close()

    return [
        {
            "label":        f"Q{r['quarter']} {r['year']}",
            "composite":    round(r["composite_rel"] or 0, 3),
            "return_t1":    round(r["return_t1"] or 0, 4),
            "direction":    r["direction_t1"],
            "hedging":      round(r["hedging_score"] or 0, 4),
            "sentiment_drop": round(r["sentiment_drop"] or 0, 4),
        }
        for r in rows
    ]
