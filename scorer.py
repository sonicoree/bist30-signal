"""
scorer.py — Birleşik skor hesaplama, sınıflandırma, veto kuralları, risk bayrakları
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from config import (
    BIST30_BY_CODE, SIGNAL_CLASSES,
    VETO_THRESHOLD_WATCHLIST, VETO_THRESHOLD_SELL,
    TCMB_MEETINGS,
)
from data_loader import StockData, has_recent_volume_spike
from news_classifier import ClassifiedNews, has_spk_investigation, is_high_news_volume
from risk_manager import RiskLevels, compute_risk_levels, compute_liquidity_score
from signal_engine import TechnicalSignal
from utils import clamp, logger, now_istanbul


# ---------------------------------------------------------------------------
# Birleşik Sinyal Yapısı
# ---------------------------------------------------------------------------

@dataclass
class CombinedSignal:
    ticker: str
    company_name: str
    sector: str

    # Puanlar
    tech_score: int           # 0-100
    news_score: float         # -50 ile +50
    liquidity_score: int      # 0-20
    total_score: float        # -50 ile 170

    # Sınıflandırma
    classification: str       # GÜÇLÜ AL / AL / ALIMA UYGUN / İZLE / NÖTR / ZAYIF / VETOLU
    classification_info: dict

    # Risk
    risk_levels: Optional[RiskLevels]
    liquidity_reasons: List[str]

    # Teknik detaylar
    tech_signal: TechnicalSignal
    tech_reasons: List[str]

    # Haber detayları
    news_items: List[ClassifiedNews] = field(default_factory=list)
    news_sentiment_label: str = "Nötr"
    ai_commentary: str = ""

    # Risk bayrakları
    flags: List[str] = field(default_factory=list)

    # Veto
    is_vetoed: bool = False
    veto_reason: str = ""
    is_sell_warning: bool = False

    # Piyasa zayıflık bayrağı
    weak_market: bool = False


# ---------------------------------------------------------------------------
# Sentiment Etiketi
# ---------------------------------------------------------------------------

def news_score_label(score: float) -> str:
    if score >= 30:  return "Çok Pozitif"
    if score >= 10:  return "Pozitif"
    if score >= -9:  return "Nötr"
    if score >= -29: return "Negatif"
    return "Çok Negatif"


# ---------------------------------------------------------------------------
# Sınıflandırma
# ---------------------------------------------------------------------------

def classify_signal(total: float, is_vetoed: bool = False) -> Tuple[str, dict]:
    if is_vetoed:
        return "VETOLU", SIGNAL_CLASSES["VETOLU"]
    for name, info in SIGNAL_CLASSES.items():
        if name == "VETOLU":
            continue
        if info["min"] <= total <= info["max"]:
            return name, info
    return "ZAYIF", SIGNAL_CLASSES["ZAYIF"]


# ---------------------------------------------------------------------------
# Risk Bayrakları
# ---------------------------------------------------------------------------

def compute_risk_flags(
    ticker: str,
    news_items: List[ClassifiedNews],
    stock: StockData,
) -> List[str]:
    flags: List[str] = []

    # SPK soruşturması (son 30 gün)
    for cn in news_items:
        if cn.has_spk:
            flags.append("🚩 SPK incelemesi/soruşturması mevcut")
            break

    # Bilanço tarihi 7 gün içinde
    # (KAP finansal takvimden gerçek zamanlı çekme; burada anahtar kelime bazlı)
    for cn in news_items:
        text = f"{cn.item.title} {cn.item.summary}"
        if any(kw in text.lower() for kw in [
            "bilanço açıklayacak", "finansal sonuç", "çeyrek bilanço",
            "mali tablo", "faaliyet raporu"
        ]):
            flags.append("📊 Yaklaşan bilanço açıklaması (7 gün içi)")
            break

    # TCMB toplantısı 7 gün içinde
    today = now_istanbul().date()
    for meeting_str in TCMB_MEETINGS:
        try:
            meeting_date = date.fromisoformat(meeting_str)
            delta = (meeting_date - today).days
            if 0 <= delta <= 7:
                flags.append(f"💱 TCMB toplantısı {delta} gün içinde ({meeting_str})")
        except ValueError:
            pass

    # Son 3 günde 10+ haber
    if is_high_news_volume(
        [cn.item for cn in news_items], threshold=10
    ):
        flags.append("📰 Son 3 günde 10+ haber (yoğun bilgi akışı)")

    # Son 5 günde anormal hacim spike
    if not stock.ohlcv.empty and has_recent_volume_spike(stock.ohlcv, days=5, multiplier=3.0):
        flags.append("🌊 Son 5 günde anormal hacim spike (>3x)")

    return flags


# ---------------------------------------------------------------------------
# Ana Skorlama Fonksiyonu
# ---------------------------------------------------------------------------

def score_and_classify(
    tech_signal: TechnicalSignal,
    news_score: float,
    stock: StockData,
    classified_news: List[ClassifiedNews],
    ai_commentary: str,
    market_regime: dict,
) -> CombinedSignal:
    """
    Tek hisse için birleşik skor hesaplar ve sınıflandırır.
    """
    ticker = tech_signal.ticker
    stock_cfg = BIST30_BY_CODE.get(ticker)
    company = stock_cfg.name if stock_cfg else ticker
    sector  = stock_cfg.sector if stock_cfg else "Bilinmiyor"

    # Likidite skoru
    liq_score, liq_reasons = compute_liquidity_score(stock)

    # Birleşik skor
    total = clamp(
        tech_signal.tech_score + news_score + liq_score,
        -50, 170,
    )

    # Veto kuralları
    is_vetoed = False
    veto_reason = ""
    is_sell = False

    if news_score <= VETO_THRESHOLD_SELL:
        is_sell = True
        is_vetoed = True
        veto_reason = f"Haber skoru çok düşük ({news_score:.1f}): SAT/DUR uyarısı"
    elif news_score <= VETO_THRESHOLD_WATCHLIST:
        is_vetoed = True
        veto_reason = f"Haber skoru negatif ({news_score:.1f}): sadece izleme"

    # Zayıf piyasa koşulu: sadece yüksek teknik skorlar
    weak_market = not market_regime.get("above_ema50", True)
    if weak_market and tech_signal.tech_score < 85 and not is_vetoed:
        is_vetoed = True
        veto_reason = (
            f"PİYASA ZAYIF: XU100 < EMA50 ve teknik skor "
            f"yetersiz ({tech_signal.tech_score}/85)"
        )

    # Risk seviyeleri
    risk_pct = 0.0
    classification, cls_info = classify_signal(total, is_vetoed)
    if not is_vetoed:
        risk_pct = cls_info.get("risk_pct", 0.0)

    risk_lvls = None
    if risk_pct > 0 and tech_signal.close > 0 and tech_signal.atr > 0:
        risk_lvls = compute_risk_levels(
            close=tech_signal.close,
            atr=tech_signal.atr,
            risk_pct=risk_pct,
        )

    # R/R oranını güncelle (risk seviyeleri hesaplandıktan sonra)
    rr = risk_lvls.rr_ratio if risk_lvls else 0.0

    # Risk bayrakları
    flags = compute_risk_flags(ticker, classified_news, stock)

    return CombinedSignal(
        ticker=ticker,
        company_name=company,
        sector=sector,
        tech_score=tech_signal.tech_score,
        news_score=round(news_score, 2),
        liquidity_score=liq_score,
        total_score=round(total, 2),
        classification=classification,
        classification_info=cls_info,
        risk_levels=risk_lvls,
        liquidity_reasons=liq_reasons,
        tech_signal=tech_signal,
        tech_reasons=tech_signal.tech_reasons,
        news_items=classified_news,
        news_sentiment_label=news_score_label(news_score),
        ai_commentary=ai_commentary,
        flags=flags,
        is_vetoed=is_vetoed,
        veto_reason=veto_reason,
        is_sell_warning=is_sell,
        weak_market=weak_market,
    )


# ---------------------------------------------------------------------------
# Toplu Sınıflandırma & Filtreleme
# ---------------------------------------------------------------------------

def rank_signals(signals: List[CombinedSignal]) -> Dict[str, List[CombinedSignal]]:
    """
    Sinyalleri kategorilere ayırır ve skor sırasına göre sıralar.
    """
    strong_buy: List[CombinedSignal] = []
    buy:        List[CombinedSignal] = []
    suitable:   List[CombinedSignal] = []
    watch:      List[CombinedSignal] = []
    neutral:    List[CombinedSignal] = []
    weak:       List[CombinedSignal] = []
    vetoed:     List[CombinedSignal] = []

    for sig in signals:
        cls = sig.classification
        if sig.is_vetoed or cls == "VETOLU":
            vetoed.append(sig)
        elif cls == "GÜÇLÜ AL":
            strong_buy.append(sig)
        elif cls == "AL":
            buy.append(sig)
        elif cls == "ALIMA UYGUN":
            suitable.append(sig)
        elif cls == "İZLE":
            watch.append(sig)
        elif cls == "NÖTR":
            neutral.append(sig)
        else:
            weak.append(sig)

    def by_score(lst: List[CombinedSignal]) -> List[CombinedSignal]:
        return sorted(lst, key=lambda s: s.total_score, reverse=True)

    return {
        "GÜÇLÜ AL":    by_score(strong_buy),
        "AL":          by_score(buy),
        "ALIMA UYGUN": by_score(suitable),
        "İZLE":        by_score(watch),
        "NÖTR":        by_score(neutral),
        "ZAYIF":       by_score(weak),
        "VETOLU":      by_score(vetoed),
    }


def sector_distribution(signals: List[CombinedSignal]) -> Dict[str, int]:
    """Aksiyon alınabilir sinyallerin sektör dağılımını döndürür."""
    dist: Dict[str, int] = {}
    actionable_classes = {"GÜÇLÜ AL", "AL", "ALIMA UYGUN"}
    for sig in signals:
        if sig.classification in actionable_classes:
            dist[sig.sector] = dist.get(sig.sector, 0) + 1
    return dict(sorted(dist.items(), key=lambda x: x[1], reverse=True))
