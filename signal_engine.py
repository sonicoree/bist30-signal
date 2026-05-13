"""
signal_engine.py — Çok katmanlı setup tespiti ve teknik skorlama
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import INDICATOR_PARAMS, TECH_SCORE_WEIGHTS
from data_loader import StockData
from indicators import IndicatorSet, obv_upward_slope, detect_bullish_rsi_divergence
from utils import logger, safe_float


# ---------------------------------------------------------------------------
# Setup & Sinyal Sonuç Yapıları
# ---------------------------------------------------------------------------

@dataclass
class SetupResult:
    setup_a: bool = False   # Pullback to EMA21
    setup_b: bool = False   # BB Squeeze Breakout
    setup_c: bool = False   # RSI Bullish Divergence
    triggered: bool = False

    def active_setups(self) -> List[str]:
        setups = []
        if self.setup_a:
            setups.append("Setup A (Pullback EMA21)")
        if self.setup_b:
            setups.append("Setup B (BB Squeeze Kırılım)")
        if self.setup_c:
            setups.append("Setup C (RSI Diverjans)")
        return setups


@dataclass
class LayerResult:
    """Her katmanın geçip geçmediği bilgisi."""
    layer1_market_regime: bool = False   # XU100 > EMA50
    layer2_trend: bool = False           # EMA50>EMA200, Fiyat>EMA200, ADX>20
    layer3_setup: SetupResult = field(default_factory=SetupResult)
    layer4_trigger: bool = False         # Hacim, MACD, OBV
    all_passed: bool = False


@dataclass
class TechnicalSignal:
    ticker: str
    tech_score: int                  # 0-100
    layers: LayerResult
    tech_reasons: List[str]          # Teknik gerekçe maddeleri
    volume_ratio: float
    rsi: float
    adx: float
    macd_hist: float
    close: float
    atr: float
    prev_close: float = 0.0
    # EMA seviyeleri
    ema9:   float = 0.0
    ema21:  float = 0.0
    ema50:  float = 0.0
    ema200: float = 0.0
    # Bollinger Bands
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_width: float = 0.0
    # DI+/DI-
    dip: float = 0.0
    dim: float = 0.0
    # Stochastic
    stoch_k: float = 0.0
    stoch_d: float = 0.0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Katman 1 — Piyasa Rejimi
# ---------------------------------------------------------------------------

def check_layer1(market_regime: dict) -> bool:
    return market_regime.get("above_ema50", False)


# ---------------------------------------------------------------------------
# Katman 2 — Trend Filtresi
# ---------------------------------------------------------------------------

def check_layer2(ind: IndicatorSet) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    passed = True

    # EMA50 > EMA200
    if ind.ema50 and ind.ema200:
        if ind.ema50 > ind.ema200:
            reasons.append(f"EMA50 ({ind.ema50:.2f}) > EMA200 ({ind.ema200:.2f}) ✓")
        else:
            reasons.append(f"EMA50 ({ind.ema50:.2f}) < EMA200 ({ind.ema200:.2f}) ✗")
            passed = False
    else:
        passed = False

    # Fiyat > EMA200
    if ind.close and ind.ema200:
        if ind.close > ind.ema200:
            reasons.append(f"Fiyat ({ind.close:.2f}) > EMA200 ({ind.ema200:.2f}) ✓")
        else:
            reasons.append(f"Fiyat ({ind.close:.2f}) < EMA200 ({ind.ema200:.2f}) ✗")
            passed = False
    else:
        passed = False

    # ADX > 20
    if ind.adx:
        if ind.adx > 20:
            reasons.append(f"ADX ({ind.adx:.1f}) > 20 ✓")
        else:
            reasons.append(f"ADX ({ind.adx:.1f}) < 20 — zayıf trend ✗")
            passed = False
    else:
        passed = False

    return passed, reasons


# ---------------------------------------------------------------------------
# Katman 3 — Setup Tespiti
# ---------------------------------------------------------------------------

def check_setup_a(ind: IndicatorSet, df: pd.DataFrame) -> Tuple[bool, str]:
    """
    Setup A: Son 10 günde fiyat EMA21'e %2 mesafeye düşmüş,
    bugün/dün EMA21 üstünde kapatmış, RSI 40-55.
    """
    p = INDICATOR_PARAMS
    if ind.ema21_series is None or ind.rsi_series is None or ind.close is None:
        return False, ""

    try:
        close_series = df["Close"].astype(float)
        ema21 = ind.ema21_series

        lookback = p["pullback_lookback"]
        tolerance = p["pullback_tolerance"]

        # Son 10 günde EMA21'e yaklaşma
        recent_close = close_series.tail(lookback)
        recent_ema21 = ema21.tail(lookback)

        pct_diff = (recent_close - recent_ema21).abs() / recent_ema21
        near_ema21 = (pct_diff <= tolerance).any()

        if not near_ema21:
            return False, ""

        # Bugün veya dün EMA21 üstünde kapanış
        last_close = float(close_series.iloc[-1])
        prev_close = float(close_series.iloc[-2]) if len(close_series) > 1 else last_close
        last_ema21 = float(ema21.iloc[-1])
        prev_ema21 = float(ema21.iloc[-2]) if len(ema21) > 1 else last_ema21

        above_today    = last_close > last_ema21
        above_yesterday= prev_close > prev_ema21

        if not (above_today or above_yesterday):
            return False, ""

        # RSI 40-55
        rsi_val = ind.rsi or 0
        if not (40 <= rsi_val <= 55):
            return False, ""

        desc = (
            f"EMA21'e geri çekilme ve toparlanma | "
            f"EMA21={last_ema21:.2f}, RSI={rsi_val:.1f}"
        )
        return True, desc

    except Exception as exc:
        logger.debug("Setup A hatası: %s", exc)
        return False, ""


def check_setup_b(ind: IndicatorSet, df: pd.DataFrame) -> Tuple[bool, str]:
    """
    Setup B: Son 5 günde BB band genişliği son 60 günün dar %20'sinde,
    fiyat üst bandı yukarı kırmış, hacim 1.8x+.
    """
    p = INDICATOR_PARAMS
    if ind.bb_width_series is None or ind.bb_upper is None:
        return False, ""

    try:
        # BB squeeze kontrolü: son 5 günde dar %20'de mi?
        squeeze_pct = ind.bb_squeeze_pct
        recent_5 = ind.bb_width_series.tail(5)
        lookback = p["bb_squeeze_lookback"]
        pct_threshold = p["squeeze_percentile"]

        if squeeze_pct is None:
            return False, ""

        # Son 5 günde en azından bir günde squeeze olmuş mu?
        width_tail60 = ind.bb_width_series.tail(lookback).dropna()
        if len(width_tail60) < 10:
            return False, ""

        threshold_val = np.percentile(width_tail60.values, pct_threshold)
        squeeze_days = (recent_5 <= threshold_val).sum()

        if squeeze_days < 1:
            return False, ""

        # Fiyat üst bandı kırmış mı?
        close_series = df["Close"].astype(float)
        last_close = float(close_series.iloc[-1])
        prev_close = float(close_series.iloc[-2]) if len(close_series) > 1 else last_close

        breakout = last_close > (ind.bb_upper or 0)
        if not breakout:
            return False, ""

        # Hacim 1.8x+
        vol_ratio = ind.volume_ratio or 0
        if vol_ratio < 1.8:
            return False, ""

        desc = (
            f"BB Sıkışma Kırılımı | "
            f"BB Üst={ind.bb_upper:.2f}, Hacim={vol_ratio:.1f}x, "
            f"Sıkışma={squeeze_days} gün"
        )
        return True, desc

    except Exception as exc:
        logger.debug("Setup B hatası: %s", exc)
        return False, ""


def check_setup_c(ind: IndicatorSet, df: pd.DataFrame) -> Tuple[bool, str]:
    """
    Setup C: Son 20 günde fiyat yeni dip, RSI yüksek dip,
    Stochastic %K 20 altından yukarı %D'yi kesmiş.
    """
    if ind.rsi_series is None or ind.close_series is None:
        return False, ""

    try:
        # RSI Bullish Divergence
        divergence = detect_bullish_rsi_divergence(
            ind.close_series,
            ind.rsi_series,
            lookback=INDICATOR_PARAMS["divergence_lookback"],
        )
        if not divergence:
            return False, ""

        # Stochastic: %K 20 altından %D'yi yukarı kesmiş
        if ind.stoch_k_series is None or ind.stoch_d_series is None:
            return False, ""

        k = ind.stoch_k_series.tail(5).values
        d = ind.stoch_d_series.tail(5).values

        # Son 5 gün içinde %K < 20'den %D'yi yukarı kesmesi
        stoch_cross = False
        for i in range(1, len(k)):
            if k[i-1] < 20 and k[i] > d[i] and k[i-1] <= d[i-1]:
                stoch_cross = True
                break

        if not stoch_cross:
            return False, ""

        desc = (
            f"RSI Bullish Diverjans + Stochastic Kesişimi | "
            f"Stoch K={ind.stoch_k:.1f}, RSI={ind.rsi:.1f}"
        )
        return True, desc

    except Exception as exc:
        logger.debug("Setup C hatası: %s", exc)
        return False, ""


# ---------------------------------------------------------------------------
# Katman 4 — Tetik Kontrolü
# ---------------------------------------------------------------------------

def check_layer4(ind: IndicatorSet) -> Tuple[bool, List[str]]:
    """
    Tetik koşulları:
    - Hacim ≥ 1.5x ortalama
    - MACD histogram pozitif veya negatiften pozitife dönüş (son 2 gün)
    - OBV son 10 günde yukarı eğimli
    """
    reasons: List[str] = []
    conditions: List[bool] = []

    # Hacim
    vol_ratio = ind.volume_ratio or 0
    vol_ok = vol_ratio >= 1.5
    conditions.append(vol_ok)
    if vol_ok:
        reasons.append(f"Hacim {vol_ratio:.1f}x ortalama ✓")
    else:
        reasons.append(f"Hacim {vol_ratio:.1f}x — yetersiz ✗")

    # MACD histogram
    macd_ok = False
    if ind.macd_hist_series is not None and len(ind.macd_hist_series) >= 2:
        hist_series = ind.macd_hist_series.dropna()
        if len(hist_series) >= 2:
            h_now  = float(hist_series.iloc[-1])
            h_prev = float(hist_series.iloc[-2])
            # Pozitif veya negatiften pozitife döndü
            macd_ok = h_now > 0 or (h_prev < 0 and h_now > h_prev)
            reasons.append(
                f"MACD Hist={h_now:.4f} ({'↑' if h_now > h_prev else '↓'}) "
                f"{'✓' if macd_ok else '✗'}"
            )
    conditions.append(macd_ok)

    # OBV eğimi
    obv_ok = False
    if ind.obv_series is not None:
        obv_ok = obv_upward_slope(ind.obv_series, days=10)
        reasons.append(f"OBV 10-gün eğimi {'↑ ✓' if obv_ok else '↓ ✗'}")
    conditions.append(obv_ok)

    # En az 2/3 koşul sağlanmalı (veya hacim + biri)
    passed = (vol_ok and macd_ok) or (vol_ok and obv_ok) or (all(conditions))
    return passed, reasons


# ---------------------------------------------------------------------------
# Teknik Skorlama
# ---------------------------------------------------------------------------

def compute_tech_score(
    ind: IndicatorSet,
    market_regime: dict,
    layers: LayerResult,
    rr_ratio: float,
) -> Tuple[int, List[str]]:
    """
    Teknik skoru hesaplar (0-100).
    Dönüş: (skor, gerekçe_listesi)
    """
    w = TECH_SCORE_WEIGHTS
    score = 0
    reasons: List[str] = []

    # XU100 > EMA50
    if market_regime.get("above_ema50"):
        score += w["xu100_above_ema50"]
        reasons.append(f"XU100 > EMA50 (+{w['xu100_above_ema50']})")

    # EMA50 > EMA200
    if ind.ema50 and ind.ema200 and ind.ema50 > ind.ema200:
        score += w["ema50_above_ema200"]
        reasons.append(f"EMA50 > EMA200 (+{w['ema50_above_ema200']})")

    # Fiyat > EMA200
    if ind.close and ind.ema200 and ind.close > ind.ema200:
        score += w["price_above_ema200"]
        reasons.append(f"Fiyat > EMA200 (+{w['price_above_ema200']})")

    # ADX
    adx = ind.adx or 0
    if adx > 25:
        score += w["adx_above_25"]
        reasons.append(f"ADX={adx:.1f} > 25 (+{w['adx_above_25']})")
    elif adx >= 20:
        score += w["adx_20_25"]
        reasons.append(f"ADX={adx:.1f} (20-25) (+{w['adx_20_25']})")

    # Setup tetik
    if layers.layer3_setup.triggered:
        score += w["setup_triggered"]
        active = ", ".join(layers.layer3_setup.active_setups())
        reasons.append(f"{active} tetiklendi (+{w['setup_triggered']})")

    # MACD histogram pozitif ve artıyor
    if ind.macd_hist_series is not None and len(ind.macd_hist_series) >= 2:
        hist = ind.macd_hist_series.dropna()
        if len(hist) >= 2:
            h_now  = float(hist.iloc[-1])
            h_prev = float(hist.iloc[-2])
            if h_now > 0 and h_now > h_prev:
                score += w["macd_positive_increasing"]
                reasons.append(f"MACD Hist={h_now:.4f} pozitif ve artıyor (+{w['macd_positive_increasing']})")

    # Hacim
    vol_ratio = ind.volume_ratio or 0
    if vol_ratio >= 2.0:
        score += w["volume_above_2x"]
        reasons.append(f"Hacim {vol_ratio:.1f}x (>2x) (+{w['volume_above_2x']})")
    elif vol_ratio >= 1.5:
        score += w["volume_1_5_to_2x"]
        reasons.append(f"Hacim {vol_ratio:.1f}x (1.5-2x) (+{w['volume_1_5_to_2x']})")

    # RSI 40-65
    rsi = ind.rsi or 0
    if 40 <= rsi <= 65:
        score += w["rsi_40_65"]
        reasons.append(f"RSI={rsi:.1f} (40-65 ideali) (+{w['rsi_40_65']})")

    # R/R ≥ 1:2.5
    if rr_ratio >= 2.5:
        score += w["rr_above_2_5"]
        reasons.append(f"R/R={rr_ratio:.2f}:1 (+{w['rr_above_2_5']})")

    score = min(100, max(0, score))
    return score, reasons


# ---------------------------------------------------------------------------
# Ana Sinyal Motor Fonksiyonu
# ---------------------------------------------------------------------------

def analyze_stock(
    stock_data: StockData,
    ind: IndicatorSet,
    market_regime: dict,
    rr_ratio: float = 0.0,
) -> TechnicalSignal:
    """
    Tek hisse için çok katmanlı teknik analiz yapar.
    """
    ticker = stock_data.code

    if ind.error or stock_data.error:
        return TechnicalSignal(
            ticker=ticker,
            tech_score=0,
            layers=LayerResult(),
            tech_reasons=[f"Veri hatası: {ind.error or stock_data.error}"],
            volume_ratio=0.0,
            rsi=0.0,
            adx=0.0,
            macd_hist=0.0,
            close=0.0,
            atr=0.0,
            error=ind.error or stock_data.error,
        )

    layers = LayerResult()
    all_reasons: List[str] = []

    # ── Katman 1 ───────────────────────────────────────────────────────────
    layers.layer1_market_regime = check_layer1(market_regime)
    if not layers.layer1_market_regime:
        all_reasons.append("⚠ Piyasa rejimi zayıf (XU100 < EMA50)")

    # ── Katman 2 ───────────────────────────────────────────────────────────
    layers.layer2_trend, trend_reasons = check_layer2(ind)
    all_reasons.extend(trend_reasons)

    # ── Katman 3 ───────────────────────────────────────────────────────────
    setup = SetupResult()
    df = stock_data.ohlcv

    a_ok, a_desc = check_setup_a(ind, df)
    b_ok, b_desc = check_setup_b(ind, df)
    c_ok, c_desc = check_setup_c(ind, df)

    setup.setup_a = a_ok
    setup.setup_b = b_ok
    setup.setup_c = c_ok
    setup.triggered = a_ok or b_ok or c_ok

    if a_ok:
        all_reasons.append(f"✓ {a_desc}")
    if b_ok:
        all_reasons.append(f"✓ {b_desc}")
    if c_ok:
        all_reasons.append(f"✓ {c_desc}")
    if not setup.triggered:
        all_reasons.append("✗ Hiçbir setup tetiklenmedi")

    layers.layer3_setup = setup

    # ── Katman 4 ───────────────────────────────────────────────────────────
    layers.layer4_trigger, trigger_reasons = check_layer4(ind)
    all_reasons.extend(trigger_reasons)

    # Zayıf piyasada sadece tech_score ≥ 85 değerlendirilir
    # Bu kontrolü scorer.py'de yapıyoruz.

    layers.all_passed = (
        layers.layer2_trend and
        layers.layer3_setup.triggered and
        layers.layer4_trigger
    )

    # ── Teknik Skor ────────────────────────────────────────────────────────
    tech_score, score_reasons = compute_tech_score(ind, market_regime, layers, rr_ratio)
    all_reasons = score_reasons + all_reasons

    return TechnicalSignal(
        ticker=ticker,
        tech_score=tech_score,
        layers=layers,
        tech_reasons=all_reasons,
        volume_ratio=safe_float(ind.volume_ratio),
        rsi=safe_float(ind.rsi),
        adx=safe_float(ind.adx),
        macd_hist=safe_float(ind.macd_hist),
        close=safe_float(ind.close),
        atr=safe_float(ind.atr),
        prev_close=safe_float(
            ind.close_series.iloc[-2] if ind.close_series is not None
            and len(ind.close_series) >= 2 else 0.0
        ),
        ema9=safe_float(ind.ema9),
        ema21=safe_float(ind.ema21),
        ema50=safe_float(ind.ema50),
        ema200=safe_float(ind.ema200),
        bb_upper=safe_float(ind.bb_upper),
        bb_lower=safe_float(ind.bb_lower),
        bb_width=safe_float(ind.bb_width),
        dip=safe_float(ind.dip),
        dim=safe_float(ind.dim),
        stoch_k=safe_float(ind.stoch_k),
        stoch_d=safe_float(ind.stoch_d),
    )
