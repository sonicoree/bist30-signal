"""
news_collector.py — Haber toplama: RSS adaptörleri + scraping (KAP, BloombergHT, vb.)
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from config import BIST30, NEWS_SOURCES, NewsSource, SCRAPE_CONFIG
from utils import (
    RateLimiter, can_fetch, get_headers, logger,
    now_istanbul, localize, news_in_window,
)


# ---------------------------------------------------------------------------
# Haber Veri Yapısı
# ---------------------------------------------------------------------------

@dataclass
class NewsItem:
    source: str
    tier: int
    weight: float
    title: str
    summary: str
    url: str
    pub_date: datetime
    tickers: List[str] = field(default_factory=list)   # eşleşen hisse kodları
    raw_content: str = ""


# ---------------------------------------------------------------------------
# Hisse Eşleme (Haber başlığı/içeriğinde ticker veya şirket adı)
# ---------------------------------------------------------------------------

def detect_tickers(text: str) -> List[str]:
    """Haber metninde geçen BIST30 hisse kodlarını ve şirket adlarını tespit eder."""
    found: List[str] = []
    text_lower = text.lower()

    for stock in BIST30:
        # Doğrudan ticker kodu kontrolü (büyük harf, kelime sınırı)
        if re.search(r'\b' + re.escape(stock.code) + r'\b', text, re.IGNORECASE):
            if stock.code not in found:
                found.append(stock.code)
            continue
        # Anahtar kelime kontrolü
        for kw in stock.keywords:
            if kw.lower() in text_lower:
                if stock.code not in found:
                    found.append(stock.code)
                break

    return found


# ---------------------------------------------------------------------------
# Tarih Ayrıştırma
# ---------------------------------------------------------------------------

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """RSS / scrape kaynaklı tarih dizelerini datetime'a dönüştürür."""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d",
    ]
    import email.utils
    try:
        ts = email.utils.parsedate_to_datetime(date_str)
        return localize(ts)
    except Exception:
        pass
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return localize(dt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Temel Adaptör
# ---------------------------------------------------------------------------

class BaseNewsAdapter(ABC):
    """Tüm haber adaptörlerinin temel sınıfı."""

    def __init__(self, source: NewsSource) -> None:
        self.source = source
        self.rate_limiter = RateLimiter()
        self.session = requests.Session()
        self.session.headers.update(get_headers())

    @abstractmethod
    def fetch(self) -> List[NewsItem]:
        ...

    def _get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """robots.txt + rate limit uyumlu GET isteği."""
        if not can_fetch(url):
            logger.debug("robots.txt engel: %s", url)
            return None
        self.rate_limiter.wait()
        try:
            resp = self.session.get(
                url,
                timeout=SCRAPE_CONFIG["timeout"],
                headers=get_headers(),
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.warning("[%s] GET başarısız (%s): %s", self.source.name, url, exc)
            return None

    def _make_item(
        self,
        title: str,
        summary: str,
        url: str,
        pub_date: Optional[datetime],
        raw: str = "",
    ) -> Optional[NewsItem]:
        if not title:
            return None
        dt = pub_date or now_istanbul()
        if not news_in_window(dt, 7):
            return None
        full_text = f"{title} {summary} {raw}"
        tickers = detect_tickers(full_text)
        return NewsItem(
            source=self.source.name,
            tier=self.source.tier,
            weight=self.source.weight,
            title=title.strip(),
            summary=summary.strip()[:500],
            url=url,
            pub_date=dt,
            tickers=tickers,
            raw_content=raw[:1000],
        )


# ---------------------------------------------------------------------------
# RSS Adaptörü (Genel)
# ---------------------------------------------------------------------------

class RSSAdapter(BaseNewsAdapter):
    """feedparser ile RSS/Atom feed okur."""

    def fetch(self) -> List[NewsItem]:
        if not self.source.rss_url:
            return []
        logger.info("[%s] RSS çekiliyor: %s", self.source.name, self.source.rss_url)
        self.rate_limiter.wait()
        try:
            feed = feedparser.parse(
                self.source.rss_url,
                request_headers=get_headers(),
                agent=get_headers()["User-Agent"],
            )
        except Exception as exc:
            logger.warning("[%s] RSS parse hatası: %s", self.source.name, exc)
            return []

        items: List[NewsItem] = []
        for entry in feed.entries:
            title = getattr(entry, "title", "")
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            url = getattr(entry, "link", "")
            raw_date = getattr(entry, "published", None) or getattr(entry, "updated", None)
            pub_date = parse_date(raw_date)

            # İçerik temizleme
            if summary:
                summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
            summary = summary[:500]

            item = self._make_item(title, summary, url, pub_date)
            if item:
                items.append(item)

        logger.info("[%s] %d haber alındı", self.source.name, len(items))
        return items


# ---------------------------------------------------------------------------
# KAP Adaptörü (Tier 1)
# ---------------------------------------------------------------------------

class KAPAdapter(BaseNewsAdapter):
    """
    KAP'tan şirket bazlı resmi açıklamaları çeker.
    KAP JSON API endpoint'i kullanır (RSS mevcut değil).
    """

    KAP_API = "https://www.kap.org.tr/tr/api/disclosures"
    KAP_BASE = "https://www.kap.org.tr"

    def fetch(self) -> List[NewsItem]:
        logger.info("[KAP] Bildirimler çekiliyor...")
        items: List[NewsItem] = []

        # Tüm BIST30 hisseleri için bildirimleri al
        # KAP scraping: ana sayfadan son bildirimleri çek
        url = "https://www.kap.org.tr/tr/Bildirim/Index"
        resp = self._get(url)
        if resp is None:
            # Fallback: her hisse için ayrı sayfa
            return self._fetch_per_stock()

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("div.w-clearfix.w-inline-block.comp-row") or \
               soup.select("div[class*='comp-row']") or \
               soup.select("tr")

        for row in rows[:100]:
            try:
                link_el = row.find("a")
                if not link_el:
                    continue
                title = link_el.get_text(strip=True)
                rel_url = link_el.get("href", "")
                full_url = urljoin(self.KAP_BASE, rel_url)
                # Tarih: span veya td
                date_el = row.find(class_=re.compile(r"date|tarih", re.I)) or \
                          row.find("td", {"class": re.compile(r"date", re.I)})
                date_str = date_el.get_text(strip=True) if date_el else None
                pub_date = parse_date(date_str)

                item = self._make_item(title, "", full_url, pub_date)
                if item:
                    items.append(item)
            except Exception:
                continue

        if not items:
            items = self._fetch_per_stock()

        logger.info("[KAP] %d bildirim alındı", len(items))
        return items

    def _fetch_per_stock(self) -> List[NewsItem]:
        """Her BIST30 hissesi için KAP'tan ayrı ayrı veri çeker."""
        items: List[NewsItem] = []
        for stock in BIST30[:10]:  # İlk 10 ile sınırlı (rate limit)
            url = f"https://www.kap.org.tr/tr/Bildirim/Sirket/{stock.code}"
            resp = self._get(url)
            if resp is None:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a[href*='/Bildirim/']")[:5]:
                title = link.get_text(strip=True)
                full_url = urljoin("https://www.kap.org.tr", link["href"])
                item = self._make_item(title, "", full_url, None)
                if item:
                    item.tickers = [stock.code]
                    items.append(item)
            time.sleep(1.5)
        return items


# ---------------------------------------------------------------------------
# Bigpara Adaptörü (Tier 3)
# ---------------------------------------------------------------------------

class BigparaAdapter(BaseNewsAdapter):
    """Bigpara haber scraping."""

    BASE = "https://bigpara.hurriyet.com.tr"
    NEWS_URL = "https://bigpara.hurriyet.com.tr/haberler/"

    def fetch(self) -> List[NewsItem]:
        logger.info("[Bigpara] Haberler çekiliyor...")
        resp = self._get(self.NEWS_URL)
        if resp is None:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items: List[NewsItem] = []

        # Bigpara haber listesi yapısı
        for article in soup.select("li.haberListe, article.news-item, div.news-card")[:30]:
            try:
                link_el = article.find("a")
                if not link_el:
                    continue
                title = link_el.get_text(strip=True) or \
                        article.find(class_=re.compile(r"title|baslik")).get_text(strip=True)
                url = urljoin(self.BASE, link_el.get("href", ""))
                summary_el = article.find(class_=re.compile(r"desc|ozet|summary"))
                summary = summary_el.get_text(strip=True) if summary_el else ""
                date_el = article.find(class_=re.compile(r"date|tarih|time"))
                pub_date = parse_date(date_el.get_text(strip=True) if date_el else None)
                item = self._make_item(title, summary, url, pub_date)
                if item:
                    items.append(item)
            except Exception:
                continue

        logger.info("[Bigpara] %d haber alındı", len(items))
        return items


# ---------------------------------------------------------------------------
# Adaptör Fabrikası
# ---------------------------------------------------------------------------

def build_adapter(source: NewsSource) -> BaseNewsAdapter:
    if source.name == "KAP":
        return KAPAdapter(source)
    if source.name == "Bigpara":
        return BigparaAdapter(source)
    return RSSAdapter(source)


# ---------------------------------------------------------------------------
# Ana Toplayıcı
# ---------------------------------------------------------------------------

class NewsCollector:
    """Tüm kaynaklardan haber toplar ve ticker'a göre gruplar."""

    def __init__(self) -> None:
        self.adapters = [build_adapter(s) for s in NEWS_SOURCES]

    def collect(self) -> Dict[str, List[NewsItem]]:
        """
        Tüm kaynaklardan haber çeker.
        Dönüş: {ticker_code: [NewsItem, ...]}
        """
        all_items: List[NewsItem] = []

        for adapter in self.adapters:
            try:
                items = adapter.fetch()
                all_items.extend(items)
            except Exception as exc:
                logger.error("[%s] Beklenmeyen hata: %s", adapter.source.name, exc)

        # Tekrar haberleri kaldır (başlık + kaynak çakışması)
        seen: set = set()
        unique: List[NewsItem] = []
        for item in all_items:
            key = (item.title.lower()[:80], item.source)
            if key not in seen:
                seen.add(key)
                unique.append(item)

        # Ticker'a göre grupla
        by_ticker: Dict[str, List[NewsItem]] = {}
        for item in unique:
            if not item.tickers:
                # Ticker tespit edilemedi; tüm BIST30'a karşı genel haber
                continue
            for code in item.tickers:
                by_ticker.setdefault(code, []).append(item)

        logger.info(
            "Toplam %d benzersiz haber toplandı, %d hisse için",
            len(unique), len(by_ticker),
        )
        return by_ticker

    def collect_all_items(self) -> List[NewsItem]:
        """Tüm haberleri düz liste olarak döndürür (DB kaydetme için)."""
        all_items: List[NewsItem] = []
        for adapter in self.adapters:
            try:
                items = adapter.fetch()
                all_items.extend(items)
            except Exception as exc:
                logger.error("[%s] Hata: %s", adapter.source.name, exc)
        return all_items


# ---------------------------------------------------------------------------
# Manipülasyon Filtresi
# ---------------------------------------------------------------------------

def apply_manipulation_filter(
    item: NewsItem,
    all_items: List[NewsItem],
) -> float:
    """
    Bir haber sadece Tier 3'te ve tek kaynakta görünüyorsa 0.5 çarpanı uygular.
    """
    if item.tier != 3:
        return 1.0

    # Başlık benzerliği ile diğer kaynaklarda aynı haberi ara
    title_key = item.title.lower()[:60]
    for other in all_items:
        if other is item:
            continue
        if other.source == item.source:
            continue
        if title_key in other.title.lower():
            return 1.0  # Başka kaynakta da var, normal

    return 0.5  # Sadece bu Tier 3 kaynakta, yarıya indir
