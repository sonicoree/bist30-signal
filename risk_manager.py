"""
risk_manager.py — ATR tabanlı giriş/stop/hedef hesaplama, pozisyon boyutlama, likidite skoru
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import RISK_PARAMS, LIQUIDITY_PARAMS
from data_loader import StockData, has_anomalous_volume
from utils import logger, safe_float


# ---------------------------------------------------------------------------
# Risk Hesap Yapısı
# ---------------------------------------------------------------------------

@dataclass
class RiskLevels:
    entry:          float
    stop:           float
    target1:        float
    target2:        float
    rr_ratio:       float
    position_size:  int      # hisse adedi
    risk_amount:    float    # TL cinsinden risk
    close:          float
    atr:            float


# ---------------------------------------------------------------------------
# ATR Tabanlı Seviyeler
# ---------------------------------------------------------------------------

def compute_risk_levels(
    close: float,
    atr: float,
    risk_pct: float,
    portfolio_size: float = RISK_PARAMS["portfolio_size"],
) -> Optional[RiskLevels]:
    """
    ATR bazlı giriş/stop/hedef seviyeleri ve pozisyon büyüklüğü hesaplar.
    risk_pct: portföyün yüzde kaçını riske et (örn 1.0 = %1)
    """
    if close <= 0 or atr <= 0:
        return None

    slippage = RISK_PARAMS["entry_slippage"]
    atr_stop = RISK_PARAMS["atr_stop_multiplier"]
    atr_t1   = RISK_PARAMS["atr_target1_multiplier"]
    atr_t2   = RISK_PARAMS["atr_target2_multiplier"]

    entry   = close * (1 + slippage)
    stop    = entry - atr * atr_stop
    target1 = entry + atr * atr_t1
    target2 = entry + atr * atr_t2

    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return None

    risk_amount = portfolio_size * (risk_pct / 100)
    position_size = max(1, int(risk_amount / risk_per_share))

    reward = target2 - entry
    rr_ratio = reward / risk_per_share if risk_per_share > 0 else 0.0

    return RiskLevels(
        entry=round(entry, 4),
        stop=round(stop, 4),
        target1=round(target1, 4),
        target2=round(target2, 4),
        rr_ratio=round(rr_ratio, 2),
        position_size=position_size,
        risk_amount=round(risk_amount, 2),
        close=close,
        atr=round(atr, 4),
    )


# ---------------------------------------------------------------------------
# Likidite & Kalite Skoru (0-20)
# ---------------------------------------------------------------------------

def compute_liquidity_score(stock: StockData) -> tuple[int, list[str]]:
    """
    Likidite ve kalite skoru (0-20) ile gerekçe listesi döndürür.
    """
    p = LIQUIDITY_PARAMS
    score = 0
    reasons: list[str] = []

    # Günlük TL hacim
    vol_tl = stock.volume_tl
    if vol_tl >= p["volume_tl_threshold_high"]:
        score += 10
        reasons.append(f"Günlük hacim {vol_tl/1e6:.0f}M TL (>250M) (+10)")
    elif vol_tl >= p["volume_tl_threshold_low"]:
        score += 5
        reasons.append(f"Günlük hacim {vol_tl/1e6:.0f}M TL (>100M) (+5)")
    else:
        reasons.append(f"Günlük hacim {vol_tl/1e6:.1f}M TL — düşük (0)")

    # Piyasa değeri
    mkt_cap = stock.market_cap
    if mkt_cap >= p["market_cap_threshold"]:
        score += 5
        reasons.append(f"Piyasa değeri {mkt_cap/1e9:.1f}B TL (>5B) (+5)")
    else:
        reasons.append(f"Piyasa değeri {mkt_cap/1e9:.2f}B TL — yetersiz (0)")

    # Manipülasyon / anormal hacim kontrolü
    if not stock.ohlcv.empty:
        anomaly = has_anomalous_volume(
            stock.ohlcv,
            lookback=p["manipulation_lookback"],
            threshold=3.0,
        )
        if not anomaly:
            score += 5
            reasons.append("Son 30 günde anormal hacim/fiyat patlaması yok (+5)")
        else:
            reasons.append("⚠ Son 30 günde anormal hacim tespit edildi (0)")

    return min(20, score), reasons
