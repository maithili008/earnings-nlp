"""GET /api/tickers — list all tickers with summary stats"""
from fastapi import APIRouter
from backend.db import get_conn

router = APIRouter()

TICKER_DIRECTION = {
    "CFG":1,"MTB":1,"BAC":1,"HBAN":1,"NTRS":1,"WFC":1,
    "MS":1,"STT":1,"USB":1,"FITB":1,"KEY":1,"RF":1,
    "BK":-1,"GS":-1,"C":-1,"JPM":-1,"TFC":-1,
    "COF":-1,"PNC":-1,"ZION":-1,
}

@router.get("/tickers")
def list_tickers():
    conn = get_conn()
    rows = conn.execute("""
        SELECT symbol,
               COUNT(*)                          AS transcript_count,
               AVG(hedging_score)                AS avg_hedging,
               AVG(guidance_score)               AS avg_guidance,
               AVG(qa_volatility_score)          AS avg_qa_vol,
               AVG(composite_rel)                AS avg_composite,
               AVG(sentiment_drop)               AS avg_sentiment_drop,
               MIN(year)                         AS first_year,
               MAX(year)                         AS last_year
        FROM transcripts
        WHERE hedging_score IS NOT NULL
        GROUP BY symbol
        ORDER BY symbol
    """).fetchall()
    conn.close()
    return [
        {
            "symbol":           r["symbol"],
            "transcript_count": r["transcript_count"],
            "avg_hedging":      round(r["avg_hedging"] or 0, 4),
            "avg_guidance":     round(r["avg_guidance"] or 0, 4),
            "avg_qa_vol":       round(r["avg_qa_vol"] or 0, 4),
            "avg_composite":    round(r["avg_composite"] or 0, 4),
            "avg_sentiment_drop": round(r["avg_sentiment_drop"] or 0, 4),
            "first_year":       r["first_year"],
            "last_year":        r["last_year"],
            "signal_direction": TICKER_DIRECTION.get(r["symbol"], 1),
        }
        for r in rows
    ]
