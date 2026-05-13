"""
news_classifier.py — Rule-based olay sınıflandırma ve anahtar kelime eşleme
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from news_collector import NewsItem
from utils import logger


# ---------------------------------------------------------------------------
# Olay Kuralları
# ---------------------------------------------------------------------------

@dataclass
class EventRule:
    name: str
    score: int
    keywords: List[str]        # en az biri geçmeli
    neg_keywords: List[str]    # hiçbiri geçmemeli (bağlam filtresi)


EVENT_RULES: List[EventRule] = [
    EventRule(
        "bilanço_pozitif",
        +25,
        ["beklentinin üstünde", "rekor kar", "bilanço pozitif", "net kar arttı",
         "rekor kâr", "güçlü sonuç", "kar beklentisini aştı", "kâr rekoru",
         "net kâr yükseldi", "satışlar arttı beklentinin üzerinde"],
        ["zarar", "beklentinin altında"],
    ),
    EventRule(
        "bilanço_negatif",
        -25,
        ["beklentinin altında", "zarar açıkladı", "net zarar", "kâr düştü",
         "kar düştü", "zayıf sonuç", "beklentilerin altında kaldı",
         "bilanço hayal kırıklığı"],
        [],
    ),
    EventRule(
        "yeni_sözleşme",
        +20,
        ["ihale aldı", "sözleşme imzaladı", "yeni proje", "yeni sözleşme",
         "ihaleyi kazandı", "büyük sipariş", "yeni ihale", "kontrat imzaladı",
         "yeni anlaşma", "ortaklık anlaşması"],
        [],
    ),
    EventRule(
        "yabancı_kurum_alım",
        +15,
        ["yabancı yatırımcı", "fon aldı", "hedef fiyat yükseltti",
         "yabancı alımı", "fon girişi", "hedef fiyat artırdı",
         "al tavsiyesi", "overweight", "outperform"],
        [],
    ),
    EventRule(
        "geri_alım",
        +15,
        ["geri alım", "buyback", "hisse alım programı", "hisse geri alımı",
         "geri alım programı", "pay geri alım"],
        [],
    ),
    EventRule(
        "temettü_artışı",
        +10,
        ["temettü artırdı", "yüksek temettü", "kar payı arttı",
         "kâr payı dağıtımı", "temettü önerisi", "nakit kar payı",
         "hisse başına temettü arttı"],
        [],
    ),
    EventRule(
        "kredi_notu_yükseltme",
        +10,
        ["kredi notu yükseltildi", "rating upgrade", "not artışı",
         "kredi derecelendirmesi artırıldı", "pozitif görünüm",
         "stable görünüm pozitife"],
        ["düşürüldü", "downgrade"],
    ),
    EventRule(
        "ana_ortak_pozitif",
        +8,
        ["ana ortak", "hakim ortak"],
        ["satış", "devretti", "sattı"],
    ),
    EventRule(
        "sektör_pozitif",
        +10,
        ["teşvik", "vergi indirimi", "yeni düzenleme", "sektör desteği",
         "pozitif düzenleme", "kolaylık sağlandı", "ihracat teşviki",
         "prim desteği"],
        ["yaptırım", "vergi artışı", "sınırlama", "yasak"],
    ),
    EventRule(
        "üst_yönetim_değişim",
        -15,
        ["istifa etti", "görevden ayrıldı", "ceo değişti", "genel müdür değişti",
         "yönetim kurulu başkanı değişti", "cfo istifa", "ceo istifa",
         "yönetimde değişiklik"],
        [],
    ),
    EventRule(
        "kredi_notu_düşürme",
        -15,
        ["kredi notu düşürüldü", "rating downgrade", "not düşürüldü",
         "kredi derecelendirmesi düşürüldü", "negatif görünüm"],
        ["yükseltildi", "upgrade"],
    ),
    EventRule(
        "dava_yasal",
        -20,
        ["dava açıldı", "ceza kesildi", "yaptırım uygulandı", "idari para cezası",
         "hukuki süreç", "mahkeme kararı", "tazminat davası", "kovuşturma"],
        [],
    ),
    EventRule(
        "spk_soruşturma",
        -30,
        ["spk inceleme", "spk soruşturma", "manipülasyon iddiası", "spk yaptırım",
         "sermaye piyasası kurulu inceleme", "borsa istanbul soruşturma",
         "piyasa dolandırıcılığı"],
        [],
    ),
    EventRule(
        "operasyonel_kriz",
        -20,
        ["yangın", "patlama", "kaza", "grev", "lokavt", "üretim durdu",
         "fabrika kapandı", "iş kazası", "operasyonel aksaklık",
         "üretim durduruldu", "tesis hasarı"],
        [],
    ),
    EventRule(
        "sektör_negatif",
        -15,
        ["yasak", "sınırlama getirildi", "vergi artışı", "ek vergi",
         "kota uygulaması", "ithalat kısıtlaması", "ihracat yasağı",
         "fiyat tavanı"],
        [],
    ),
]


# ---------------------------------------------------------------------------
# SPK Soruşturma Tespiti (risk bayrağı için)
# ---------------------------------------------------------------------------

SPK_KEYWORDS = [
    "spk", "sermaye piyasası kurulu", "borsa istanbul",
    "manipülasyon", "manipulasyon", "piyasa dolandırıcılığı",
    "muvazaa", "içeriden öğrenenler",
]


def has_spk_investigation(text: str) -> bool:
    text_lower = text.lower()
    investigation_words = ["inceleme", "soruşturma", "yaptırım", "ceza", "kovuşturma"]
    has_spk = any(kw in text_lower for kw in SPK_KEYWORDS)
    has_inv = any(kw in text_lower for kw in investigation_words)
    return has_spk and has_inv


# ---------------------------------------------------------------------------
# Rule-Based Sınıflandırma
# ---------------------------------------------------------------------------

def classify_event(item: NewsItem) -> Tuple[int, Optional[str]]:
    """
    Haber için rule-based olay skoru ve kategori adını döndürür.
    Birden fazla kural eşleşirse en yüksek/düşük olanı döndürür.
    """
    text = f"{item.title} {item.summary} {item.raw_content}".lower()

    matched: List[Tuple[int, str]] = []

    for rule in EVENT_RULES:
        # En az bir anahtar kelime eşleşmeli
        if not any(kw.lower() in text for kw in rule.keywords):
            continue
        # Hiçbir negatif bağlam olmamalı
        if any(neg.lower() in text for neg in rule.neg_keywords):
            continue
        matched.append((rule.score, rule.name))

    if not matched:
        return 0, None

    # Birden fazla eşleşme: ağırlıklı ortalama al (negatifler baskın)
    if len(matched) == 1:
        return matched[0]

    # Negatif kurallar varsa en negatifi önce al
    negative = [m for m in matched if m[0] < 0]
    positive = [m for m in matched if m[0] > 0]

    final_score = 0
    categories: List[str] = []

    if negative:
        most_negative = min(negative, key=lambda x: x[0])
        final_score += most_negative[0]
        categories.append(most_negative[1])

    if positive:
        most_positive = max(positive, key=lambda x: x[0])
        final_score += most_positive[0]
        categories.append(most_positive[1])

    # Clamp
    final_score = max(-30, min(25, final_score))
    return final_score, " + ".join(categories) if categories else None


# ---------------------------------------------------------------------------
# Söylenti Tespiti
# ---------------------------------------------------------------------------

RUMOR_KEYWORDS = [
    "iddiaya göre", "söylentilere göre", "duyumlara göre",
    "kulislere göre", "kaynaklar belirtiyor", "öğrenildi",
    "öne sürüldü", "iddia ediliyor", "haberi yayıldı",
    "kuliste konuşuluyor", "piyasada dedikodusu var",
]


def is_rumor(item: NewsItem) -> bool:
    """Haberin söylenti niteliği taşıyıp taşımadığını kontrol eder."""
    text = f"{item.title} {item.summary}".lower()
    return any(kw in text for kw in RUMOR_KEYWORDS)


# ---------------------------------------------------------------------------
# Bilanço Takvimi Tespiti
# ---------------------------------------------------------------------------

EARNINGS_KEYWORDS = [
    "bilanço açıklayacak", "finansal sonuçlar açıklanacak",
    "2025 yılı sonuçları", "2024 yılı sonuçları",
    "çeyrek bilanço", "q1 sonuçları", "q2 sonuçları",
    "q3 sonuçları", "q4 sonuçları",
    "mali tablo açıklaması",
]


def has_upcoming_earnings(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in EARNINGS_KEYWORDS)


# ---------------------------------------------------------------------------
# Yoğun Haber Akışı
# ---------------------------------------------------------------------------

def is_high_news_volume(items: List[NewsItem], threshold: int = 10) -> bool:
    """Son 3 günde 10+ haber var mı?"""
    from utils import days_ago
    recent = [i for i in items if days_ago(i.pub_date) <= 3]
    return len(recent) >= threshold


# ---------------------------------------------------------------------------
# Haber Batch Sınıflandırma
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedNews:
    item: NewsItem
    event_score: int
    event_category: Optional[str]
    is_rumor: bool
    has_spk: bool


def classify_news_batch(items: List[NewsItem]) -> List[ClassifiedNews]:
    """Haber listesini toplu olarak sınıflandırır."""
    results: List[ClassifiedNews] = []
    for item in items:
        score, category = classify_event(item)
        rumor = is_rumor(item)
        spk = has_spk_investigation(f"{item.title} {item.summary}")
        results.append(ClassifiedNews(
            item=item,
            event_score=score,
            event_category=category,
            is_rumor=rumor,
            has_spk=spk,
        ))
    return results
