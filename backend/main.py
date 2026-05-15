"""
backend/main.py — FastAPI application entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers import tickers, signals, backtest

app = FastAPI(
    title="Earnings NLP Signal Extractor",
    description="Detects CEO evasiveness in earnings calls and backtests predictive power",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tickers.router,  prefix="/api")
app.include_router(signals.router,  prefix="/api")
app.include_router(backtest.router, prefix="/api")

@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}
