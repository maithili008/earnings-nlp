# config.py — single source of truth for the whole project

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT           = Path(__file__).parent
DATA_RAW       = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_BACKTEST  = ROOT / "data" / "backtest"
DB_PATH        = ROOT / "data" / "transcripts.db"  # local SQLite after ingest

# ── Tickers ───────────────────────────────────────────────────────────────────
# Large-cap US banks — confirmed present in kurry/sp500_earnings_transcripts
TICKERS = [
    "JPM", "BAC", "GS",  "MS",  "C",   "PNC",
    "WFC", "USB", "TFC", "COF", "MTB", "RF",
    "KEY", "CFG", "HBAN","FITB","CMA", "ZION",
    "STT", "BK",  "NTRS","FHN", "SNV", "BOKF",
]

# ── Date range ────────────────────────────────────────────────────────────────
START_DATE = "2021-01-01"
END_DATE   = "2024-12-31"
START_YEAR = 2021
END_YEAR   = 2024

# ── NLP ───────────────────────────────────────────────────────────────────────
EMBEDDING_MODEL    = "sentence-transformers/all-MiniLM-L6-v2"
HF_INFERENCE_MODEL = "facebook/bart-large-mnli"
MIN_TRANSCRIPT_CHARS = 3_000

# ── Backtest ──────────────────────────────────────────────────────────────────
RETURN_WINDOWS         = [1, 3]
TOP_QUARTILE_THRESHOLD = 0.75
