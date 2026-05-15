"""backend/db.py — shared DB connection"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "transcripts.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
