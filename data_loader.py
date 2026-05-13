"""
data_loader.py — yfinance ile BIST 30 ve XU100 OHLCV verisi yükleme
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from config import BIST30, BIST30_TICKERS, XU100_TICKER, USDTRY_TICKER
from utils import logger, retry, safe_float


# ---------------------------------------------------------------------------
# Veri Yapısı
# ---------------------------------------------------------------------------

@dataclass
class StockData:
    ticker: str
    code: str
    ohlcv: pd.DataFrame          # Open, High, Low, Close, Volume
    info: Dict                   # yfinance meta bilgisi
    market_cap: float            # TL cinsinden
    avg_volume_20: float         # 20 günlük ortalama hacim
    last_close: float
    last_volume: float
    volume_tl: float             # Son günün TL hacmi
    error: Optional[str] = None  # Başarısızsa hata mesajı


@dataclass
class MarketData:
    xu100: pd.DataFrame
    stocks: Dict[str, StockData] = field(default_factory=dict)
    usdtry: Optional[float] = None
    fetch_time: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """MultiIndex sütunlarını düzleştirir ve temizler."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.capitalize)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df = df.dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index)
    return df


def _avg_volume(df: pd.DataFrame, days: int = 20) -> float:
    if len(df) < days:
        return safe_float(df["Volume"].mean())
    return safe_float(df["Volume"].tail(days).mean())


# ---------------------------------------------------------------------------
# XU100 Yükleme
# ---------------------------------------------------------------------------

@retry(max_attempts=3, delay=5.0)
def fetch_xu100(period_days: int = 250) -> pd.DataFrame:
    """XU100 endeksi OHLCV verisini çeker."""
    end = date.today()
    start = end - timedelta(days=period_days + 30)
    logger.info("XU100 verisi çekiliyor...")
    ticker = yf.Ticker(XU100_TICKER)
    df = ticker.history(start=start.isoformat(), end=end.isoformat(), auto_adjust=True)
    df = _clean_ohlcv(df).tail(period_days)
    if len(df) < 50:
        raise ValueError(f"XU100 için yetersiz veri: {len(df)} satır")
    logger.info("XU100: %d gün veri alındı", len(df))
    return df


# ---------------------------------------------------------------------------
# USD/TRY Kuru
# ---------------------------------------------------------------------------

def fetch_usdtry() -> Optional[float]:
    try:
        ticker = yf.Ticker(USDTRY_TICKER)
        hist = ticker.history(period="2d")
        if not hist.empty:
            return safe_float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning("USD/TRY çekilemedi: %s", e)
    return None


# ---------------------------------------------------------------------------
# Tek Hisse Yükleme
# ---------------------------------------------------------------------------

def fetch_single_stock(
    yf_ticker: str,
    code: str,
    period_days: int = 250,
    attempt: int = 0,
) -> Optional[StockData]:
    """Tek hisse için 3 retry ile veri çeker."""
    end = date.today()
    start = end - timedelta(days=period_days + 30)

    for try_num in range(1, 4):
        try:
            ticker = yf.Ticker(yf_ticker)
            df = ticker.history(
                start=start.isoformat(),
                end=end.isoformat(),
                auto_adjust=True,
            )
            df = _clean_ohlcv(df).tail(period_days)

            if len(df) < 50:
                raise ValueError(f"Yetersiz veri: {len(df)} satır")

            info = {}
            try:
                info = ticker.info or {}
            except Exception:
                pass

            last_close = safe_float(df["Close"].iloc[-1])
            last_volume = safe_float(df["Volume"].iloc[-1])
            avg_vol_20 = _avg_volume(df, 20)

            # Piyasa değeri (TL): yfinance USD cinsinden verir, TL yaklaşımı
            market_cap_raw = safe_float(info.get("marketCap", 0))
            # yfinance BIST için zaten TL verebilir; kontrol et
            currency = info.get("currency", "TRY")
            usdtry = fetch_usdtry() or 32.0  # fallback kur
            if currency == "USD":
                market_cap_tl = market_cap_raw * usdtry
            else:
                market_cap_tl = market_cap_raw

            volume_tl = last_close * last_volume

            return StockData(
                ticker=yf_ticker,
                code=code,
                ohlcv=df,
                info=info,
                market_cap=market_cap_tl,
                avg_volume_20=avg_vol_20,
                last_close=last_close,
                last_volume=last_volume,
                volume_tl=volume_tl,
            )

        except Exception as exc:
            if try_num < 3:
                logger.warning(
                    "%s — %d. denemede hata: %s, 5s bekleniyor", yf_ticker, try_num, exc
                )
                time.sleep(5)
            else:
                logger.error("%s — 3 denemede başarısız: %s, atlanıyor", yf_ticker, exc)
                return StockData(
                    ticker=yf_ticker,
                    code=code,
                    ohlcv=pd.DataFrame(),
                    info={},
                    market_cap=0.0,
                    avg_volume_20=0.0,
                    last_close=0.0,
                    last_volume=0.0,
                    volume_tl=0.0,
                    error=str(exc),
                )
    return None


# ---------------------------------------------------------------------------
# Toplu Yükleme
# ---------------------------------------------------------------------------

def fetch_all_stocks(period_days: int = 250) -> Dict[str, StockData]:
    """
    Tüm BIST 30 hisselerini sıralı çeker.
    Rate limit aşımını önlemek için her istek arasında 0.5s bekler.
    """
    results: Dict[str, StockData] = {}
    total = len(BIST30)

    for i, stock_cfg in enumerate(BIST30, 1):
        logger.info("[%d/%d] %s çekiliyor...", i, total, stock_cfg.ticker)
        data = fetch_single_stock(stock_cfg.ticker, stock_cfg.code, period_days)
        if data is not None:
            results[stock_cfg.code] = data
        time.sleep(0.5)  # Yahoo Finance rate limit saygısı

    success = sum(1 for d in results.values() if not d.error)
    logger.info("Hisse verisi: %d/%d başarılı", success, total)
    return results


# ---------------------------------------------------------------------------
# Ana Yükleme Fonksiyonu
# ---------------------------------------------------------------------------

def load_market_data(period_days: int = 250) -> MarketData:
    """Tüm piyasa verisini yükler: XU100 + BIST30 hisseleri + USD/TRY."""
    from utils import now_istanbul

    logger.info("=== Piyasa Verisi Yükleniyor ===")

    xu100 = fetch_xu100(period_days)
    stocks = fetch_all_stocks(period_days)
    usdtry = fetch_usdtry()

    logger.info("USD/TRY: %.4f", usdtry or 0.0)

    return MarketData(
        xu100=xu100,
        stocks=stocks,
        usdtry=usdtry,
        fetch_time=now_istanbul(),
    )


# ---------------------------------------------------------------------------
# Anormal Hacim Kontrolü
# ---------------------------------------------------------------------------

def has_anomalous_volume(
    df: pd.DataFrame,
    lookback: int = 30,
    threshold: float = 3.0,
) -> bool:
    """Son lookback günde anormal hacim patlaması var mı?"""
    if len(df) < lookback + 5:
        return False
    recent = df.tail(lookback)
    avg = recent["Volume"].mean()
    max_vol = recent["Volume"].max()
    return bool(max_vol > avg * threshold)


def has_recent_volume_spike(
    df: pd.DataFrame,
    days: int = 5,
    multiplier: float = 3.0,
) -> bool:
    """Son 5 günde hacim 3x+ spike var mı?"""
    if len(df) < 25:
        return False
    recent = df.tail(days)
    baseline_avg = df.tail(30)["Volume"].mean()
    spike = recent["Volume"].max()
    return bool(spike > baseline_avg * multiplier)
