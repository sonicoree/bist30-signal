"""
indicators.py — pandas-ta ile teknik indikatör hesaplama
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta as ta

from config import INDICATOR_PARAMS
from utils import logger, safe_float


# ---------------------------------------------------------------------------
# Sonuç Yapısı
# ---------------------------------------------------------------------------

@dataclass
class IndicatorSet:
    """Tek hisse için hesaplanmış tüm teknik indikatörler."""
    ticker: str

    # EMA'lar
    ema9:   Optional[float] = None
    ema21:  Optional[float] = None
    ema50:  Optional[float] = None
    ema200: Optional[float] = None

    # EMA dizileri (setup tespiti için)
    ema21_series: Optional[pd.Series] = None
    ema50_series: Optional[pd.Series] = None

    # RSI
    rsi: Optional[float] = None
    rsi_series: Optional[pd.Series] = None

    # MACD
    macd:        Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist:   Optional[float] = None
    macd_hist_series: Optional[pd.Series] = None

    # Bollinger Bands
    bb_upper: Optional[float] = None
    bb_mid:   Optional[float] = None
    bb_lower: Optional[float] = None
    bb_width: Optional[float] = None           # (upper-lower)/mid
    bb_width_series: Optional[pd.Series] = None

    # ADX + DI
    adx: Optional[float] = None
    dip: Optional[float] = None   # DI+
    dim: Optional[float] = None   # DI-

    # ATR
    atr: Optional[float] = None

    # Stochastic
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    stoch_k_series: Optional[pd.Series] = None
    stoch_d_series: Optional[pd.Series] = None

    # OBV
    obv_series: Optional[pd.Series] = None

    # Hacim
    volume_avg_20: Optional[float] = None
    volume_ratio:  Optional[float] = None   # son hacim / 20-gün ortalama
    volume_series: Optional[pd.Series] = None

    # BB squeeze percentile
    bb_squeeze_pct: Optional[float] = None   # son genişliğin son 60gündeki yüzdelik dilimi

    # Son fiyat
    close: Optional[float] = None
    close_series: Optional[pd.Series] = None

    # Hata
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Ana Hesaplama Fonksiyonu
# ---------------------------------------------------------------------------

def compute_indicators(ticker: str, df: pd.DataFrame) -> IndicatorSet:
    """
    OHLCV DataFrame'inden tüm teknik indikatörleri hesaplar.
    Eksik sütun / yetersiz veri durumunda partial sonuç döndürür.
    """
    result = IndicatorSet(ticker=ticker)

    if df is None or len(df) < 50:
        result.error = f"Yetersiz veri ({len(df) if df is not None else 0} gün)"
        return result

    p = INDICATOR_PARAMS

    try:
        close  = df["Close"].astype(float)
        high   = df["High"].astype(float)
        low    = df["Low"].astype(float)
        volume = df["Volume"].astype(float)

        result.close_series  = close
        result.volume_series = volume
        result.close         = safe_float(close.iloc[-1])

        # ── EMA ────────────────────────────────────────────────────────────
        for period in p["ema_periods"]:
            ema = ta.ema(close, length=period)
            val = safe_float(ema.iloc[-1]) if ema is not None else None
            setattr(result, f"ema{period}", val)
            if period == 21:
                result.ema21_series = ema
            if period == 50:
                result.ema50_series = ema

        # ── RSI ────────────────────────────────────────────────────────────
        rsi_s = ta.rsi(close, length=p["rsi_period"])
        if rsi_s is not None:
            result.rsi_series = rsi_s
            result.rsi = safe_float(rsi_s.iloc[-1])

        # ── MACD ───────────────────────────────────────────────────────────
        macd_df = ta.macd(close,
                          fast=p["macd_fast"],
                          slow=p["macd_slow"],
                          signal=p["macd_signal"])
        if macd_df is not None:
            hist_col   = [c for c in macd_df.columns if "MACDh" in c or "Hist" in c]
            macd_col   = [c for c in macd_df.columns if c.startswith("MACD_")]
            signal_col = [c for c in macd_df.columns if "MACDs" in c]
            if hist_col:
                result.macd_hist_series = macd_df[hist_col[0]]
                result.macd_hist = safe_float(macd_df[hist_col[0]].iloc[-1])
            if macd_col:
                result.macd = safe_float(macd_df[macd_col[0]].iloc[-1])
            if signal_col:
                result.macd_signal = safe_float(macd_df[signal_col[0]].iloc[-1])

        # ── Bollinger Bands ────────────────────────────────────────────────
        bb = ta.bbands(close, length=p["bb_period"], std=p["bb_std"])
        if bb is not None:
            u_col = [c for c in bb.columns if "BBU" in c]
            m_col = [c for c in bb.columns if "BBM" in c]
            l_col = [c for c in bb.columns if "BBL" in c]
            if u_col and m_col and l_col:
                result.bb_upper = safe_float(bb[u_col[0]].iloc[-1])
                result.bb_mid   = safe_float(bb[m_col[0]].iloc[-1])
                result.bb_lower = safe_float(bb[l_col[0]].iloc[-1])
                mid = bb[m_col[0]]
                width = (bb[u_col[0]] - bb[l_col[0]]) / mid.replace(0, np.nan)
                result.bb_width = safe_float(width.iloc[-1])
                result.bb_width_series = width

                # BB Squeeze Percentile (son 60 gün)
                lookback = p["bb_squeeze_lookback"]
                width_tail = width.tail(lookback).dropna()
                if len(width_tail) > 5:
                    current_w = result.bb_width
                    pct = float((width_tail < current_w).mean() * 100)
                    result.bb_squeeze_pct = pct

        # ── ADX + DI ───────────────────────────────────────────────────────
        adx_df = ta.adx(high, low, close, length=p["adx_period"])
        if adx_df is not None:
            adx_col = [c for c in adx_df.columns if c.startswith("ADX_")]
            dip_col = [c for c in adx_df.columns if "DMP" in c]
            dim_col = [c for c in adx_df.columns if "DMN" in c]
            if adx_col:
                result.adx = safe_float(adx_df[adx_col[0]].iloc[-1])
            if dip_col:
                result.dip = safe_float(adx_df[dip_col[0]].iloc[-1])
            if dim_col:
                result.dim = safe_float(adx_df[dim_col[0]].iloc[-1])

        # ── ATR ────────────────────────────────────────────────────────────
        atr_s = ta.atr(high, low, close, length=p["atr_period"])
        if atr_s is not None:
            result.atr = safe_float(atr_s.iloc[-1])

        # ── Stochastic ─────────────────────────────────────────────────────
        stoch = ta.stoch(high, low, close,
                         k=p["stoch_k"],
                         d=p["stoch_d"],
                         smooth_k=p["stoch_smooth"])
        if stoch is not None:
            k_col = [c for c in stoch.columns if "STOCHk" in c]
            d_col = [c for c in stoch.columns if "STOCHd" in c]
            if k_col:
                result.stoch_k_series = stoch[k_col[0]]
                result.stoch_k = safe_float(stoch[k_col[0]].iloc[-1])
            if d_col:
                result.stoch_d_series = stoch[d_col[0]]
                result.stoch_d = safe_float(stoch[d_col[0]].iloc[-1])

        # ── OBV ────────────────────────────────────────────────────────────
        obv = ta.obv(close, volume)
        if obv is not None:
            result.obv_series = obv

        # ── Hacim ──────────────────────────────────────────────────────────
        result.volume_avg_20 = safe_float(volume.tail(p["volume_ma_period"]).mean())
        if result.volume_avg_20 > 0:
            result.volume_ratio = safe_float(volume.iloc[-1]) / result.volume_avg_20

    except Exception as exc:
        logger.error("[%s] İndikatör hesaplama hatası: %s", ticker, exc)
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# XU100 Piyasa Rejimi
# ---------------------------------------------------------------------------

def compute_market_regime(xu100_df: pd.DataFrame) -> dict:
    """
    XU100 için piyasa rejimini hesaplar.
    Dönüş: {above_ema50: bool, ema50_val: float, xu100_close: float}
    """
    result = {"above_ema50": False, "ema50_val": 0.0, "xu100_close": 0.0}
    if xu100_df is None or len(xu100_df) < 55:
        return result

    close = xu100_df["Close"].astype(float)
    ema50 = ta.ema(close, length=50)

    if ema50 is None or ema50.isna().all():
        return result

    last_close = safe_float(close.iloc[-1])
    last_ema50 = safe_float(ema50.iloc[-1])

    result["above_ema50"] = last_close > last_ema50
    result["ema50_val"]   = last_ema50
    result["xu100_close"] = last_close
    return result


# ---------------------------------------------------------------------------
# OBV Eğim Hesabı
# ---------------------------------------------------------------------------

def obv_upward_slope(obv_series: pd.Series, days: int = 10) -> bool:
    """Son N günde OBV eğimi pozitif mi?"""
    if obv_series is None or len(obv_series) < days + 2:
        return False
    recent = obv_series.tail(days).dropna()
    if len(recent) < 3:
        return False
    # Lineer regresyon eğimi
    x = np.arange(len(recent))
    y = recent.values.astype(float)
    slope = np.polyfit(x, y, 1)[0]
    return float(slope) > 0


# ---------------------------------------------------------------------------
# RSI Divergence Tespiti
# ---------------------------------------------------------------------------

def detect_bullish_rsi_divergence(
    close: pd.Series,
    rsi: pd.Series,
    lookback: int = 20,
) -> bool:
    """
    Son lookback günde fiyat yeni dip ama RSI yüksek dip yaptı mı?
    (Bullish divergence)
    """
    if close is None or rsi is None:
        return False
    c = close.tail(lookback).dropna()
    r = rsi.tail(lookback).dropna()
    if len(c) < 5 or len(r) < 5:
        return False

    # Son iki dip noktasını bul (local minima)
    def find_lows(series: pd.Series, n: int = 3):
        lows = []
        vals = series.values
        for i in range(n, len(vals) - n):
            if all(vals[i] <= vals[i-j] for j in range(1, n+1)) and \
               all(vals[i] <= vals[i+j] for j in range(1, n+1)):
                lows.append((i, vals[i]))
        return lows

    price_lows = find_lows(c)
    rsi_lows   = find_lows(r)

    if len(price_lows) < 2 or len(rsi_lows) < 2:
        return False

    # Son iki fiyat dip: daha derin dip
    p1, p2 = price_lows[-2], price_lows[-1]
    # Son iki RSI dip: daha yüzeysel dip (divergence)
    r1, r2 = rsi_lows[-2], rsi_lows[-1]

    price_lower_low = p2[1] < p1[1]
    rsi_higher_low  = r2[1] > r1[1]

    return price_lower_low and rsi_higher_low
