"""
database.py — SQLite veritabanı işlemleri: signals, news cache, performance tracking
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Dict, Generator, List, Optional

from config import DB_PATH
from utils import logger, now_istanbul


# ---------------------------------------------------------------------------
# Bağlantı Yönetimi
# ---------------------------------------------------------------------------

@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Thread-safe SQLite bağlantı context manager."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Şema Oluşturma
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date   TEXT    NOT NULL,
    ticker        TEXT    NOT NULL,
    company_name  TEXT,
    sector        TEXT,
    total_score   REAL    NOT NULL,
    tech_score    REAL,
    news_score    REAL,
    liquidity_score REAL,
    classification TEXT   NOT NULL,
    entry_price   REAL,
    stop_price    REAL,
    target1       REAL,
    target2       REAL,
    rr_ratio      REAL,
    position_size INTEGER,
    risk_amount   REAL,
    setup_type    TEXT,
    close_price   REAL,
    adx           REAL,
    rsi           REAL,
    volume_ratio  REAL,
    result        TEXT    DEFAULT 'OPEN',   -- OPEN / T1 / T2 / STOP / EXPIRED
    result_date   TEXT,
    result_price  REAL,
    result_pct    REAL,
    created_at    TEXT    DEFAULT (datetime('now')),
    UNIQUE(signal_date, ticker)
);

CREATE TABLE IF NOT EXISTS news (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    news_hash     TEXT    UNIQUE NOT NULL,
    ticker        TEXT,
    source        TEXT    NOT NULL,
    tier          INTEGER,
    title         TEXT    NOT NULL,
    summary       TEXT,
    url           TEXT,
    pub_date      TEXT,
    event_score   REAL    DEFAULT 0,
    ai_sentiment  REAL    DEFAULT 0,
    ai_confidence INTEGER DEFAULT 0,
    ai_category   TEXT,
    ai_price_impact TEXT,
    is_rumor      INTEGER DEFAULT 0,
    final_score   REAL    DEFAULT 0,
    created_at    TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS performance (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start    TEXT    NOT NULL,
    week_end      TEXT    NOT NULL,
    total_signals INTEGER DEFAULT 0,
    t1_hits       INTEGER DEFAULT 0,
    t2_hits       INTEGER DEFAULT 0,
    stop_hits     INTEGER DEFAULT 0,
    expired       INTEGER DEFAULT 0,
    avg_return    REAL,
    win_rate      REAL,
    created_at    TEXT    DEFAULT (datetime('now')),
    UNIQUE(week_start)
);

CREATE INDEX IF NOT EXISTS idx_signals_date   ON signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_news_ticker    ON news(ticker);
CREATE INDEX IF NOT EXISTS idx_news_date      ON news(pub_date);
CREATE INDEX IF NOT EXISTS idx_news_hash      ON news(news_hash);
"""


def init_db() -> None:
    """Veritabanı şemasını oluşturur."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    logger.info("Veritabanı hazır: %s", DB_PATH)


# ---------------------------------------------------------------------------
# Haber Önbelleği
# ---------------------------------------------------------------------------

def news_hash(title: str, source: str, ticker: str) -> str:
    key = f"{title.strip().lower()}|{source}|{ticker}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def is_news_cached(h: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM news WHERE news_hash = ?", (h,)
        ).fetchone()
        return row is not None


def save_news(
    ticker: str,
    source: str,
    tier: int,
    title: str,
    summary: str,
    url: str,
    pub_date: datetime,
    event_score: float,
    ai_sentiment: float,
    ai_confidence: int,
    ai_category: str,
    ai_price_impact: str,
    is_rumor: bool,
    final_score: float,
) -> Optional[int]:
    h = news_hash(title, source, ticker)
    if is_news_cached(h):
        return None
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO news
               (news_hash, ticker, source, tier, title, summary, url, pub_date,
                event_score, ai_sentiment, ai_confidence, ai_category,
                ai_price_impact, is_rumor, final_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (h, ticker, source, tier, title, summary, url,
             pub_date.isoformat() if pub_date else None,
             event_score, ai_sentiment, ai_confidence, ai_category,
             ai_price_impact, int(is_rumor), final_score),
        )
        return cur.lastrowid


def get_news_for_ticker(ticker: str, days: int = 7) -> List[sqlite3.Row]:
    cutoff = (now_istanbul().date()).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM news
               WHERE ticker = ?
                 AND pub_date >= date(?, ?)
               ORDER BY pub_date DESC""",
            (ticker, cutoff, f"-{days} days"),
        ).fetchall()
    return rows


# ---------------------------------------------------------------------------
# Sinyal Kayıt & Güncelleme
# ---------------------------------------------------------------------------

def save_signal(signal_data: Dict[str, Any]) -> Optional[int]:
    cols = list(signal_data.keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    with get_connection() as conn:
        cur = conn.execute(
            f"INSERT OR REPLACE INTO signals ({col_str}) VALUES ({placeholders})",
            list(signal_data.values()),
        )
        return cur.lastrowid


def get_open_signals() -> List[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM signals WHERE result = 'OPEN' ORDER BY signal_date DESC"
        ).fetchall()


def update_signal_result(
    signal_id: int,
    result: str,
    result_price: float,
    result_pct: float,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE signals
               SET result = ?, result_date = ?, result_price = ?, result_pct = ?
               WHERE id = ?""",
            (result, now_istanbul().date().isoformat(), result_price, result_pct, signal_id),
        )


# ---------------------------------------------------------------------------
# Performans Takibi
# ---------------------------------------------------------------------------

def track_open_signals(current_prices: Dict[str, float]) -> None:
    """Açık sinyaller için fiyat seviyesi kontrolü yapar ve sonucu günceller."""
    open_sigs = get_open_signals()
    for sig in open_sigs:
        ticker = sig["ticker"]
        if ticker not in current_prices:
            continue
        price = current_prices[ticker]
        t1 = sig["target1"]
        t2 = sig["target2"]
        stop = sig["stop_price"]
        entry = sig["entry_price"]
        if price is None or entry is None:
            continue
        pct = (price - entry) / entry * 100 if entry else 0.0
        result = None
        if t2 and price >= t2:
            result = "T2"
        elif t1 and price >= t1:
            result = "T1"
        elif stop and price <= stop:
            result = "STOP"
        if result:
            update_signal_result(sig["id"], result, price, pct)
            logger.info("Sinyal güncellendi: %s → %s (%.1f%%)", ticker, result, pct)


def save_performance(data: Dict[str, Any]) -> None:
    cols = list(data.keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    with get_connection() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO performance ({col_str}) VALUES ({placeholders})",
            list(data.values()),
        )


def get_weekly_performance(week_start: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM performance WHERE week_start = ?", (week_start,)
        ).fetchone()


def get_last_week_signals() -> List[sqlite3.Row]:
    """Son haftanın tamamlanan sinyallerini döndürür."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT * FROM signals
               WHERE result != 'OPEN'
                 AND result_date >= date('now', '-7 days')
               ORDER BY result_date DESC"""
        ).fetchall()


def compute_weekly_stats() -> Dict[str, Any]:
    """Geçen haftanın performans istatistiklerini hesaplar."""
    signals = get_last_week_signals()
    if not signals:
        return {}

    total = len(signals)
    t1 = sum(1 for s in signals if s["result"] == "T1")
    t2 = sum(1 for s in signals if s["result"] == "T2")
    stop = sum(1 for s in signals if s["result"] == "STOP")
    expired = sum(1 for s in signals if s["result"] == "EXPIRED")

    returns = [s["result_pct"] for s in signals if s["result_pct"] is not None]
    avg_ret = sum(returns) / len(returns) if returns else 0.0
    wins = sum(1 for r in returns if r > 0)
    win_rate = wins / len(returns) * 100 if returns else 0.0

    today = now_istanbul().date()
    week_start = (today - __import__("datetime").timedelta(days=7)).isoformat()
    week_end = today.isoformat()

    return {
        "week_start": week_start,
        "week_end": week_end,
        "total_signals": total,
        "t1_hits": t1,
        "t2_hits": t2,
        "stop_hits": stop,
        "expired": expired,
        "avg_return": round(avg_ret, 2),
        "win_rate": round(win_rate, 2),
    }
