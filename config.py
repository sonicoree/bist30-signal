"""
config.py — Sistem genelinde sabitler, BIST30 listesi, haber kaynakları
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# BIST 30 Hisse Listesi
# ---------------------------------------------------------------------------

@dataclass
class Stock:
    ticker: str          # Yahoo Finance sembolü (.IS dahil)
    code: str            # Borsa kodu (THYAO vb.)
    name: str            # Şirket tam adı
    sector: str          # Sektör
    keywords: List[str]  # Haber eşleme anahtar kelimeleri

BIST30: List[Stock] = [
    Stock("AKBNK.IS", "AKBNK", "Akbank T.A.Ş.",
          "Bankacılık", ["akbank", "AKBNK", "Akbank"]),
    Stock("ARCLK.IS", "ARCLK", "Arçelik A.Ş.",
          "Sanayi", ["arçelik", "arcelik", "ARCLK"]),
    Stock("ASELS.IS", "ASELS", "Aselsan Elektronik Sanayi",
          "Savunma Sanayi", ["aselsan", "ASELS"]),
    Stock("BIMAS.IS", "BIMAS", "BİM Birleşik Mağazalar A.Ş.",
          "Perakende", ["bim", "BİM", "BIMAS"]),
    Stock("DOHOL.IS", "DOHOL", "Doğan Holding A.Ş.",
          "Holding", ["doğan holding", "dogan holding", "DOHOL"]),
    Stock("EKGYO.IS", "EKGYO", "Emlak Konut GYO A.Ş.",
          "GYO", ["emlak konut", "ekgyo", "EKGYO"]),
    Stock("ENKAI.IS", "ENKAI", "Enka İnşaat ve Sanayi",
          "İnşaat", ["enka", "ENKAI"]),
    Stock("EREGL.IS", "EREGL", "Ereğli Demir ve Çelik",
          "Demir-Çelik", ["ereğli", "erdemir", "EREGL"]),
    Stock("FROTO.IS", "FROTO", "Ford Otosan A.Ş.",
          "Otomotiv", ["ford otosan", "FROTO"]),
    Stock("GARAN.IS", "GARAN", "Türkiye Garanti Bankası",
          "Bankacılık", ["garanti", "GARAN"]),
    Stock("GUBRF.IS", "GUBRF", "Gübre Fabrikaları T.A.Ş.",
          "Kimya/Tarım", ["gübre", "gubrf", "GUBRF"]),
    Stock("HALKB.IS", "HALKB", "Türkiye Halk Bankası",
          "Bankacılık", ["halkbank", "halk bankası", "HALKB"]),
    Stock("ISCTR.IS", "ISCTR", "Türkiye İş Bankası",
          "Bankacılık", ["iş bankası", "isbank", "ISCTR"]),
    Stock("KCHOL.IS", "KCHOL", "Koç Holding A.Ş.",
          "Holding", ["koç holding", "koc holding", "KCHOL"]),
    Stock("KONTR.IS", "KONTR", "Kontrolmatik Teknoloji",
          "Teknoloji", ["kontrolmatik", "KONTR"]),
    Stock("KRDMD.IS", "KRDMD", "Kardemir Karabük Demir Çelik",
          "Demir-Çelik", ["kardemir", "KRDMD"]),
    Stock("MGROS.IS", "MGROS", "Migros Ticaret A.Ş.",
          "Perakende", ["migros", "MGROS"]),
    Stock("ODAS.IS",  "ODAS",  "Odaş Elektrik Üretim",
          "Enerji", ["odaş", "odas", "ODAS"]),
    Stock("PETKM.IS", "PETKM", "Petkim Petrokimya Holding",
          "Petrokimya", ["petkim", "PETKM"]),
    Stock("PGSUS.IS", "PGSUS", "Pegasus Hava Taşımacılığı",
          "Ulaştırma", ["pegasus", "PGSUS"]),
    Stock("SAHOL.IS", "SAHOL", "Hacı Ömer Sabancı Holding",
          "Holding", ["sabancı", "sabanci", "SAHOL"]),
    Stock("SASA.IS",  "SASA",  "SASA Polyester Sanayi",
          "Sanayi", ["sasa", "SASA"]),
    Stock("SISE.IS",  "SISE",  "Türkiye Şişe ve Cam",
          "Cam/Sanayi", ["şişecam", "sisecam", "şişe cam", "SISE"]),
    Stock("TAVHL.IS", "TAVHL", "TAV Havalimanları Holding",
          "Ulaştırma", ["tav", "TAV havalimanı", "TAVHL"]),
    Stock("TCELL.IS", "TCELL", "Turkcell İletişim Hizmetleri",
          "Telekom", ["turkcell", "TCELL"]),
    Stock("THYAO.IS", "THYAO", "Türk Hava Yolları A.O.",
          "Ulaştırma", ["thy", "türk hava yolları", "turk hava yollari", "THYAO"]),
    Stock("TOASO.IS", "TOASO", "Tofaş Türk Otomobil Fabrikası",
          "Otomotiv", ["tofaş", "tofas", "TOASO"]),
    Stock("TUPRS.IS", "TUPRS", "Tüpraş Türkiye Petrol Rafinerileri",
          "Enerji", ["tüpraş", "tupras", "TUPRS"]),
    Stock("VAKBN.IS", "VAKBN", "Türkiye Vakıflar Bankası",
          "Bankacılık", ["vakıfbank", "vakifbank", "VAKBN"]),
    Stock("YKBNK.IS", "YKBNK", "Yapı ve Kredi Bankası",
          "Bankacılık", ["yapı kredi", "yapi kredi", "ykb", "YKBNK"]),
]

# Kod → Stock hızlı arama
BIST30_BY_CODE: Dict[str, Stock] = {s.code: s for s in BIST30}
BIST30_TICKERS: List[str] = [s.ticker for s in BIST30]

# ---------------------------------------------------------------------------
# Endeks
# ---------------------------------------------------------------------------
XU100_TICKER = "XU100.IS"
USDTRY_TICKER = "USDTRY=X"  # USD/TRY (Yahoo Finance formatı)

# ---------------------------------------------------------------------------
# Haber Kaynakları
# ---------------------------------------------------------------------------

@dataclass
class NewsSource:
    name: str
    tier: int            # 1, 2, 3
    weight: float        # 1.0, 0.8, 0.5
    rss_url: Optional[str] = None
    base_url: Optional[str] = None
    scrape: bool = False

NEWS_SOURCES: List[NewsSource] = [
    # Tier 1
    NewsSource("KAP", 1, 1.0,
               rss_url="https://www.kap.org.tr/tr/BildirimListesi",
               base_url="https://www.kap.org.tr",
               scrape=True),
    # Tier 2
    NewsSource("BloombergHT", 2, 0.8,
               rss_url="https://www.bloomberght.com/rss",
               base_url="https://www.bloomberght.com"),
    NewsSource("ReutersTR", 2, 0.8,
               rss_url="https://tr.reuters.com/rssFeed/businessNews",
               base_url="https://tr.reuters.com"),
    NewsSource("AnadoluAjansi", 2, 0.8,
               rss_url="https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
               base_url="https://www.aa.com.tr"),
    NewsSource("DunyaGazetesi", 2, 0.8,
               rss_url="https://www.dunya.com/rss",
               base_url="https://www.dunya.com"),
    # Tier 3
    NewsSource("MynetFinans", 3, 0.5,
               rss_url="https://finans.mynet.com/rss/",
               base_url="https://finans.mynet.com"),
    NewsSource("Bigpara", 3, 0.5,
               base_url="https://bigpara.hurriyet.com.tr",
               scrape=True),
    NewsSource("InvestingTR", 3, 0.5,
               rss_url="https://tr.investing.com/rss/news.rss",
               base_url="https://tr.investing.com"),
]

# ---------------------------------------------------------------------------
# Teknik İndikatör Parametreleri
# ---------------------------------------------------------------------------

INDICATOR_PARAMS = {
    "ema_periods": [9, 21, 50, 200],
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bb_period": 20,
    "bb_std": 2,
    "adx_period": 14,
    "atr_period": 14,
    "stoch_k": 14,
    "stoch_d": 3,
    "stoch_smooth": 3,
    "volume_ma_period": 20,
    "bb_squeeze_lookback": 60,
    "squeeze_percentile": 20,  # dar %20
    "pullback_lookback": 10,
    "pullback_tolerance": 0.02,  # %2
    "divergence_lookback": 20,
    "volume_spike_days": 5,
    "volume_spike_multiplier": 3.0,
}

# ---------------------------------------------------------------------------
# Teknik Skorlama Ağırlıkları
# ---------------------------------------------------------------------------

TECH_SCORE_WEIGHTS = {
    "xu100_above_ema50": 15,
    "ema50_above_ema200": 15,
    "price_above_ema200": 5,
    "adx_above_25": 10,
    "adx_20_25": 5,
    "setup_triggered": 20,
    "macd_positive_increasing": 10,
    "volume_1_5_to_2x": 10,
    "volume_above_2x": 15,
    "rsi_40_65": 10,
    "rr_above_2_5": 10,
}

# ---------------------------------------------------------------------------
# Likidite & Kalite Skoru
# ---------------------------------------------------------------------------

LIQUIDITY_PARAMS = {
    "volume_tl_threshold_low": 100_000_000,   # 100M TL
    "volume_tl_threshold_high": 250_000_000,  # 250M TL
    "market_cap_threshold": 5_000_000_000,    # 5 milyar TL
    "manipulation_lookback": 30,
}

# ---------------------------------------------------------------------------
# Sentiment Sınıflandırma Eşikleri
# ---------------------------------------------------------------------------

SENTIMENT_LABELS = {
    "Çok Pozitif":  (30, 50),
    "Pozitif":      (10, 29),
    "Nötr":         (-9, 9),
    "Negatif":      (-29, -10),
    "Çok Negatif":  (-50, -30),
}

# Veto eşikleri
VETO_THRESHOLD_WATCHLIST = -25
VETO_THRESHOLD_SELL = -40

# ---------------------------------------------------------------------------
# Birleşik Skor Sınıflandırması
# ---------------------------------------------------------------------------

SIGNAL_CLASSES = {
    "GÜÇLÜ AL":      {"min": 140, "max": 170, "emoji": "⭐", "risk_pct": 1.5,
                      "color": "#00ff88", "label": "GÜÇLÜ AL"},
    "AL":            {"min": 120, "max": 139, "emoji": "🟢", "risk_pct": 1.0,
                      "color": "#00cc66", "label": "AL"},
    "ALIMA UYGUN":   {"min": 100, "max": 119, "emoji": "🟡", "risk_pct": 0.5,
                      "color": "#ffcc00", "label": "ALIMA UYGUN"},
    "İZLE":          {"min": 80,  "max": 99,  "emoji": "🔵", "risk_pct": 0.0,
                      "color": "#3399ff", "label": "İZLE"},
    "NÖTR":          {"min": 60,  "max": 79,  "emoji": "⚪", "risk_pct": 0.0,
                      "color": "#888888", "label": "NÖTR"},
    "ZAYIF":         {"min": -50, "max": 59,  "emoji": "🔴", "risk_pct": 0.0,
                      "color": "#ff3333", "label": "ZAYIF"},
    "VETOLU":        {"min": -999,"max": 999, "emoji": "⛔", "risk_pct": 0.0,
                      "color": "#ff0000", "label": "VETOLU"},
}

# ---------------------------------------------------------------------------
# Risk Yönetimi
# ---------------------------------------------------------------------------

RISK_PARAMS = {
    "portfolio_size": 100_000,  # TL
    "atr_stop_multiplier": 2.0,
    "atr_target1_multiplier": 2.0,
    "atr_target2_multiplier": 4.0,
    "entry_slippage": 0.005,  # %0.5
}

# ---------------------------------------------------------------------------
# Türkiye Resmi Tatilleri (2025-2026)
# ---------------------------------------------------------------------------

TURKISH_HOLIDAYS_2025 = [
    "2025-01-01",  # Yılbaşı
    "2025-03-30",  # Ramazan Bayramı 1
    "2025-03-31",  # Ramazan Bayramı 2
    "2025-04-01",  # Ramazan Bayramı 3
    "2025-04-23",  # Ulusal Egemenlik ve Çocuk Bayramı
    "2025-05-01",  # Emek ve Dayanışma Günü
    "2025-05-19",  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    "2025-06-05",  # Kurban Bayramı 1
    "2025-06-06",  # Kurban Bayramı 2
    "2025-06-07",  # Kurban Bayramı 3
    "2025-06-08",  # Kurban Bayramı 4
    "2025-07-15",  # Demokrasi ve Millî Birlik Günü
    "2025-08-30",  # Zafer Bayramı
    "2025-10-29",  # Cumhuriyet Bayramı
]

TURKISH_HOLIDAYS_2026 = [
    "2026-01-01",  # Yılbaşı
    "2026-03-20",  # Ramazan Bayramı 1
    "2026-03-21",  # Ramazan Bayramı 2
    "2026-03-22",  # Ramazan Bayramı 3
    "2026-04-23",  # Ulusal Egemenlik ve Çocuk Bayramı
    "2026-05-01",  # Emek ve Dayanışma Günü
    "2026-05-19",  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    "2026-05-27",  # Kurban Bayramı 1
    "2026-05-28",  # Kurban Bayramı 2
    "2026-05-29",  # Kurban Bayramı 3
    "2026-05-30",  # Kurban Bayramı 4
    "2026-07-15",  # Demokrasi ve Millî Birlik Günü
    "2026-08-30",  # Zafer Bayramı
    "2026-10-29",  # Cumhuriyet Bayramı
]

TURKISH_HOLIDAYS = set(TURKISH_HOLIDAYS_2025 + TURKISH_HOLIDAYS_2026)

# ---------------------------------------------------------------------------
# TCMB Para Politikası Toplantı Takvimi (yaklaşık)
# ---------------------------------------------------------------------------

TCMB_MEETINGS_2025 = [
    "2025-01-23", "2025-02-27", "2025-04-17", "2025-05-22",
    "2025-06-19", "2025-07-24", "2025-08-21", "2025-09-25",
    "2025-10-23", "2025-11-20", "2025-12-25",
]

TCMB_MEETINGS_2026 = [
    "2026-01-22", "2026-02-26", "2026-04-16", "2026-05-21",
    "2026-06-18", "2026-07-23", "2026-08-20", "2026-09-24",
    "2026-10-22", "2026-11-19", "2026-12-24",
]

TCMB_MEETINGS = set(TCMB_MEETINGS_2025 + TCMB_MEETINGS_2026)

# ---------------------------------------------------------------------------
# Bilgi Akışı / Scraping
# ---------------------------------------------------------------------------

SCRAPE_CONFIG = {
    "request_delay_min": 1.0,   # saniye
    "request_delay_max": 3.0,   # saniye
    "timeout": 15,              # saniye
    "max_retries": 3,
    "retry_delay": 5,           # saniye
    "user_agents": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    ],
}

# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 512
CLAUDE_SENTIMENT_BATCH_SIZE = 10  # paralel istek limiti

# ---------------------------------------------------------------------------
# Veritabanı
# ---------------------------------------------------------------------------

DB_PATH = "history.db"

# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------

MAIL_CONFIG = {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "retry_count": 3,
    "retry_delay": 10,
}

# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------

TIMEZONE = "Europe/Istanbul"
