# Earnings Call NLP Signal Extractor

A system that detects evasiveness in earnings call transcripts and tests whether those signals predict next-day stock direction.

## What it does

Extracts 3 behavioral signals from SEC EDGAR earnings call transcripts for 25 US regional bank tickers:

| Signal | Method | What it captures |
|---|---|---|
| Hedging language ratio | Lexicon-based scoring | How often management uses uncertain language |
| Forward guidance specificity | Zero-shot classification (HuggingFace) | Are they giving numbers or vague direction? |
| Q&A sentiment volatility | Sentence embedding std-dev (all-MiniLM-L6-v2) | Does CEO tone shift under analyst pressure? |

Combines into a composite **evasiveness score** per transcript, then backtests directional accuracy against T+1 and T+3 price returns.

## Stack

- **Data**: SEC EDGAR public API (free), `yfinance`
- **NLP**: `sentence-transformers/all-MiniLM-L6-v2`, HuggingFace Inference API (free tier)
- **Backend**: FastAPI + SQLite
- **Frontend**: React + Recharts
- **Hosting**: Render (backend) + Vercel (frontend) — $0

## Methodology notes

**No look-ahead bias**: Signals are computed exclusively from transcript text. No price data is used as input to signal generation. Backtests use only T+1 forward price (the next trading day's close after the filing date).

**Sector focus**: Regional US banks (25 tickers, 2021–2024). Sector focus controls for macro noise — all companies face similar interest rate environment and regulatory backdrop.

**Honest reporting**: Directional accuracy is reported with confidence intervals, not as a single "accuracy" number. We report hit rate on top-quartile signals separately from the full distribution.

## Results

*(populated after backtest phase)*

## Setup

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Project structure

```
earnings-nlp/
├── data/
│   ├── raw/          # Raw transcript JSON from EDGAR
│   ├── processed/    # Parsed + scored transcripts
│   └── backtest/     # Backtest results
├── scripts/          # One-off data pipeline scripts
├── backend/          # FastAPI app
├── frontend/         # React app
└── tests/
```
