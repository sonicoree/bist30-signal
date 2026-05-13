"""
main.py — BIST30 Sinyal Sistemi Orkestrasyonu
Kullanım: python main.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime

# .env dosyasını otomatik yükle (python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Üretim ortamında doğrudan env var kullanılır
from typing import Dict, List, Optional

from config import BIST30, BIST30_BY_CODE
from data_loader import load_market_data
from database import (
    init_db,
    save_news,
    save_signal,
    track_open_signals,
    compute_weekly_stats,
    save_performance,
    get_weekly_performance,
    news_hash,
    is_news_cached,
)
from indicators import compute_indicators, compute_market_regime
from mailer import build_html_email, send_email
from news_classifier import classify_news_batch
from news_collector import NewsCollector, apply_manipulation_filter
from risk_manager import compute_risk_levels
from scorer import (
    CombinedSignal,
    score_and_classify,
    rank_signals,
)
from sentiment_analyzer import (
    SentimentAnalyzer,
    compute_news_score,
    aggregate_ticker_news_score,
)
from signal_engine import analyze_stock
from utils import (
    is_business_day,
    logger,
    now_istanbul,
    today_istanbul,
    next_business_day,
)


# ---------------------------------------------------------------------------
# Ortam Değişkenleri
# ---------------------------------------------------------------------------

def load_env() -> dict:
    """Çevre değişkenlerini okur ve doğrular."""
    required = {
        "RESEND_API_KEY":    os.getenv("RESEND_API_KEY", ""),
        "MAIL_FROM":         os.getenv("MAIL_FROM", ""),
        "MAIL_TO":           os.getenv("MAIL_TO", ""),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.warning("Eksik env değişkenleri: %s", ", ".join(missing))
    return required


# ---------------------------------------------------------------------------
# Haber İşleme Pipeline
# ---------------------------------------------------------------------------

def process_news(
    env: dict,
) -> tuple[Dict[str, float], Dict[str, float], Dict[str, List], Dict[str, str]]:
    """
    Haberleri topla → sınıflandır → AI sentiment → skorla.
    Dönüş:
      - ticker_news_scores: {ticker: float}  birleşik haber skoru
      - news_scores_map: {key: float}  kart görüntüleme için
      - ticker_classified: {ticker: [ClassifiedNews]}
    """
    logger.info("=== Haber Toplama Başlıyor ===")
    collector = NewsCollector()

    all_items = collector.collect_all_items()
    by_ticker = collector.collect()  # {ticker: [NewsItem]}

    # Tüm haberleri düz liste olarak sınıflandır
    classified_all = classify_news_batch(all_items)

    # AI Sentiment (Claude API)
    analyzer = SentimentAnalyzer(api_key=env["ANTHROPIC_API_KEY"])
    sentiment_by_ticker = analyzer.analyze_batch(classified_all)

    # Ticker başına haber skoru hesapla
    ticker_news_scores: Dict[str, float] = {}
    ticker_classified: Dict[str, List] = {}
    news_scores_map: Dict[str, float] = {}
    ticker_ai_summaries: Dict[str, List[str]] = {}

    for ticker, news_items in by_ticker.items():
        classified = [cn for cn in classified_all if any(
            ni.title == cn.item.title for ni in news_items
        )]
        ticker_classified[ticker] = classified

        scores: List[float] = []
        for cn in classified:
            # Manipülasyon filtresi
            manip_mult = apply_manipulation_filter(cn.item, all_items)

            # AI sentiment bul
            sentiments = sentiment_by_ticker.get(ticker, [])
            sentiment = sentiments[0] if sentiments else None

            score = compute_news_score(cn, sentiment, all_items, manip_mult)
            scores.append(score)

            # Kart görüntüleme için anahtar
            key = f"{cn.item.source}|{cn.item.title[:40]}"
            news_scores_map[key] = score

            # AI özet topla
            if sentiment and sentiment.summary:
                ticker_ai_summaries.setdefault(ticker, []).append(sentiment.summary)

            # DB'ye kaydet (tekrar cache kontrolü ile)
            h = news_hash(cn.item.title, cn.item.source, ticker)
            if not is_news_cached(h):
                save_news(
                    ticker=ticker,
                    source=cn.item.source,
                    tier=cn.item.tier,
                    title=cn.item.title,
                    summary=cn.item.summary,
                    url=cn.item.url,
                    pub_date=cn.item.pub_date,
                    event_score=cn.event_score,
                    ai_sentiment=sentiment.sentiment_score if sentiment else 0.0,
                    ai_confidence=sentiment.confidence if sentiment else 50,
                    ai_category=sentiment.category if sentiment else "",
                    ai_price_impact=sentiment.price_impact if sentiment else "nötr",
                    is_rumor=cn.is_rumor,
                    final_score=score,
                )

        total_news = aggregate_ticker_news_score(scores)
        ticker_news_scores[ticker] = total_news

    # AI yorum sentezi (hisse başına)
    ticker_ai_commentary: Dict[str, str] = {}
    for ticker, summaries in ticker_ai_summaries.items():
        if summaries:
            commentary = analyzer.synthesize_summaries(ticker, summaries)
            ticker_ai_commentary[ticker] = commentary

    logger.info(
        "Haber işleme tamamlandı: %d hisse, %d haber",
        len(ticker_news_scores), len(all_items),
    )

    return (
        ticker_news_scores,
        news_scores_map,
        ticker_classified,
        ticker_ai_commentary,
        classified_all,          # tüm sınıflandırılmış haberler (mail haber akışı için)
        sentiment_by_ticker,     # AI sentiment sonuçları
    )


# ---------------------------------------------------------------------------
# Ana Tarama Pipeline
# ---------------------------------------------------------------------------

def run_scan() -> Optional[tuple]:
    """Ana tarama akışı. (signals, market_data, news_scores_map) tuple döndürür."""

    logger.info("========================================")
    logger.info("BIST30 Sinyal Sistemi — %s", now_istanbul().strftime("%Y-%m-%d %H:%M"))
    logger.info("========================================")

    # Veritabanı başlatma
    init_db()

    # Ortam değişkenleri
    env = load_env()

    # Piyasa verisi yükle
    market_data = load_market_data(period_days=250)

    if market_data.xu100.empty:
        logger.error("XU100 verisi yüklenemedi, tarama iptal edildi")
        return None

    # Piyasa rejimi
    market_regime = compute_market_regime(market_data.xu100)
    logger.info(
        "Piyasa Rejimi: XU100=%.0f, EMA50=%.0f, Üstünde: %s",
        market_regime.get("xu100_close", 0),
        market_regime.get("ema50_val", 0),
        market_regime.get("above_ema50", False),
    )

    # Mevcut açık sinyalleri fiyat güncelle
    current_prices = {
        code: data.last_close
        for code, data in market_data.stocks.items()
        if not data.error
    }
    track_open_signals(current_prices)

    # Haber işleme
    (
        ticker_news_scores,
        news_scores_map,
        ticker_classified,
        ticker_ai_commentary,
        all_classified_news,
        sentiment_by_ticker,
    ) = process_news(env)

    # Teknik analiz ve skorlama — her hisse
    signals: List[CombinedSignal] = []

    for stock_cfg in BIST30:
        code = stock_cfg.code
        stock = market_data.stocks.get(code)
        if stock is None or stock.error:
            logger.warning("%s atlanıyor: %s", code, stock.error if stock else "veri yok")
            continue

        # Teknik indikatörler
        ind = compute_indicators(code, stock.ohlcv)
        if ind.error:
            logger.warning("%s indikatör hatası: %s", code, ind.error)
            continue

        # Teknik sinyal (R/R henüz bilinmiyor, ilk geçişte 0)
        tech_sig = analyze_stock(stock, ind, market_regime, rr_ratio=0.0)

        # Haber skoru
        news_score = ticker_news_scores.get(code, 0.0)
        classified_news = ticker_classified.get(code, [])
        ai_commentary = ticker_ai_commentary.get(code, "")

        # Birleşik skor (risk seviyelerini hesaplamak için)
        combined = score_and_classify(
            tech_signal=tech_sig,
            news_score=news_score,
            stock=stock,
            classified_news=classified_news,
            ai_commentary=ai_commentary,
            market_regime=market_regime,
        )

        signals.append(combined)

        # Veritabanına kaydet
        rl = combined.risk_levels
        save_signal({
            "signal_date":      today_istanbul().isoformat(),
            "ticker":           code,
            "company_name":     combined.company_name,
            "sector":           combined.sector,
            "total_score":      combined.total_score,
            "tech_score":       combined.tech_score,
            "news_score":       combined.news_score,
            "liquidity_score":  combined.liquidity_score,
            "classification":   combined.classification,
            "entry_price":      rl.entry if rl else None,
            "stop_price":       rl.stop if rl else None,
            "target1":          rl.target1 if rl else None,
            "target2":          rl.target2 if rl else None,
            "rr_ratio":         rl.rr_ratio if rl else None,
            "position_size":    rl.position_size if rl else None,
            "risk_amount":      rl.risk_amount if rl else None,
            "setup_type":       ",".join(tech_sig.layers.layer3_setup.active_setups()),
            "close_price":      tech_sig.close,
            "adx":              tech_sig.adx,
            "rsi":              tech_sig.rsi,
            "volume_ratio":     tech_sig.volume_ratio,
        })

        logger.info(
            "%s | Skor: %.1f | Sınıf: %s | Teknik: %d | Haber: %.1f | Likidite: %d",
            code,
            combined.total_score,
            combined.classification,
            combined.tech_score,
            combined.news_score,
            combined.liquidity_score,
        )

    logger.info("Toplam %d sinyal üretildi", len(signals))
    return signals, market_data, news_scores_map, all_classified_news, sentiment_by_ticker


# ---------------------------------------------------------------------------
# Mail Gönderme
# ---------------------------------------------------------------------------

def send_signal_email(
    signals: List[CombinedSignal],
    market_data,
    news_scores_map: Dict[str, float],
    all_classified_news,
    sentiment_by_ticker,
    env: dict,
) -> None:
    now = now_istanbul()
    is_monday = now.weekday() == 0

    weekly_perf = None
    if is_monday:
        stats = compute_weekly_stats()
        if stats:
            save_performance(stats)
            weekly_perf = stats

    market_regime = compute_market_regime(market_data.xu100)
    html = build_html_email(
        signals=signals,
        market_regime=market_regime,
        usdtry=market_data.usdtry,
        news_scores_map=news_scores_map,
        all_classified_news=all_classified_news,
        sentiment_by_ticker=sentiment_by_ticker,
        weekly_perf=weekly_perf,
        is_monday=is_monday,
    )

    ranked = rank_signals(signals)
    n_strong = len(ranked["GÜÇLÜ AL"])
    n_buy    = len(ranked["AL"])
    n_suit   = len(ranked["ALIMA UYGUN"])
    weak_tag = " ⚠ PİYASA ZAYIF" if not market_regime.get("above_ema50") else ""

    subject = (
        f"BIST30 Sinyal {now.strftime('%d.%m.%Y')} — "
        f"⭐{n_strong} 🟢{n_buy} 🟡{n_suit}{weak_tag}"
    )

    success = send_email(
        html_body=html,
        subject=subject,
        from_addr=env["MAIL_FROM"],
        to_addr=env["MAIL_TO"],
        api_key=env["RESEND_API_KEY"],
    )

    if not success:
        logger.error("Mail gönderilemedi!")
        # Alternatif: HTML dosyaya yaz
        fname = f"report_{now.strftime('%Y%m%d_%H%M')}.html"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("HTML rapor %s dosyasına kaydedildi", fname)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    # İş günü kontrolü (--force parametresiyle atlanabilir)
    force = "--force" in sys.argv
    if not force and not is_business_day():
        logger.info("Bugün iş günü değil (%s), tarama atlanıyor. --force ile zorlayabilirsiniz.",
                    today_istanbul().isoformat())
        sys.exit(0)

    try:
        result = run_scan()
        if result is None:
            logger.error("Tarama başarısız")
            sys.exit(1)

        signals, market_data, news_scores_map, all_classified_news, sentiment_by_ticker = result
        env = load_env()

        if env["RESEND_API_KEY"] and env["MAIL_TO"]:
            send_signal_email(signals, market_data, news_scores_map,
                              all_classified_news, sentiment_by_ticker, env)
        else:
            logger.warning("Mail bilgileri eksik, sadece konsol çıktısı")
            ranked = rank_signals(signals)
            for cls_name, sigs in ranked.items():
                if sigs:
                    logger.info("--- %s ---", cls_name)
                    for s in sigs:
                        logger.info("  %s: %.1f", s.ticker, s.total_score)

    except KeyboardInterrupt:
        logger.info("Kullanıcı tarafından durduruldu")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Kritik hata: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
