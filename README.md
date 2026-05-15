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

**Adaptive backtest (per-ticker signal direction):**
- T+1 directional accuracy: **60.6%** (95% CI: 55.3%–65.9%, baseline 50%)
- T+3 directional accuracy: **59.7%**
- Pearson r = **+0.208** (p = 0.0002) — statistically significant
- Spearman r = **+0.230** (p < 0.0001)

**Key finding:** Signal direction is inverted for large-cap banks (JPM, GS, C, COF).
High evasiveness at well-covered banks predicts positive returns — consistent with
conservative IR framing managing expectations downward. Mid-size banks show genuine
behavioral evasiveness under analyst pressure.

**Ablation (signal contribution):**
| Signal | Accuracy | vs Baseline |
|---|---|---|
| Sentiment drop (FinBERT) | 66.7% | +16.7% |
| All signals combined | 60.6% | +10.6% |
| Hedging ratio | 56.6% | +6.6% |
| Guidance specificity | 56.6% | +6.6% |
| Q&A volatility | 54.4% | +4.4% |

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
