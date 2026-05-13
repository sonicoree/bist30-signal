"""
sentiment_analyzer.py — Claude API ile AI sentiment analizi (claude-3-5-haiku-latest)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import anthropic

from config import CLAUDE_MODEL, CLAUDE_MAX_TOKENS, CLAUDE_SENTIMENT_BATCH_SIZE
from news_classifier import ClassifiedNews
from utils import clamp, logger

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SENTIMENT_PROMPT = """\
Aşağıdaki Türk finans haberini analiz et ve yalnızca JSON döndür (başka metin ekleme).

Başlık: {title}
İçerik: {content}
İlgili Hisse: {ticker}
Kaynak: {source}

Yanıt formatı (tam olarak bu yapıda döndür):
{{
  "sentiment_score": <-10 ile +10 arası tam sayı>,
  "confidence": <0-100 arası tam sayı>,
  "category": "<kısa kategori adı>",
  "summary": "<1 cümle Türkçe özet>",
  "price_impact": "<pozitif/negatif/nötr>",
  "is_rumor": <true/false>
}}

Yönergeler:
- sentiment_score: -10 (çok negatif) ile +10 (çok pozitif) arası
- confidence: haberin güvenilirliği ve etkisine olan güven (0-100)
- category: "bilanço", "sözleşme", "yönetim", "düzenleme", "piyasa", "genel" gibi
- summary: tek cümleyle haberin hisse için ne anlam ifade ettiği
- price_impact: 1-10 günlük fiyat etkisi tahmini
- is_rumor: resmi açıklama değilse true"""


# ---------------------------------------------------------------------------
# Yanıt Yapısı
# ---------------------------------------------------------------------------

@dataclass
class SentimentResult:
    sentiment_score: float       # -10 ile +10
    confidence: int              # 0-100
    category: str
    summary: str
    price_impact: str            # pozitif/negatif/nötr
    is_rumor: bool
    raw_response: str = ""


DEFAULT_SENTIMENT = SentimentResult(
    sentiment_score=0,
    confidence=50,
    category="genel",
    summary="Analiz yapılamadı.",
    price_impact="nötr",
    is_rumor=False,
)


# ---------------------------------------------------------------------------
# Sentiment Analiz Motoru
# ---------------------------------------------------------------------------

class SentimentAnalyzer:

    def __init__(self, api_key: Optional[str] = None) -> None:
        import os
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            logger.warning("ANTHROPIC_API_KEY bulunamadı — sentiment atlanacak")
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=key)
        self._cache: Dict[str, SentimentResult] = {}

    def _cache_key(self, title: str, ticker: str) -> str:
        return f"{ticker}|{title[:80]}"

    def analyze_single(
        self,
        title: str,
        content: str,
        ticker: str,
        source: str,
    ) -> SentimentResult:
        """Tek haber için Claude API sentiment analizi yapar."""
        if self.client is None:
            return DEFAULT_SENTIMENT

        cache_key = self._cache_key(title, ticker)
        if cache_key in self._cache:
            return self._cache[cache_key]

        prompt = SENTIMENT_PROMPT.format(
            title=title,
            content=content[:1000],
            ticker=ticker,
            source=source,
        )

        for attempt in range(1, 4):
            try:
                response = self.client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=CLAUDE_MAX_TOKENS,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                result = self._parse_response(raw)
                self._cache[cache_key] = result
                return result

            except anthropic.RateLimitError:
                wait = 30 * attempt
                logger.warning("Claude API rate limit, %ds bekleniyor...", wait)
                time.sleep(wait)

            except anthropic.APIError as exc:
                logger.warning("Claude API hatası (%d. deneme): %s", attempt, exc)
                if attempt < 3:
                    time.sleep(10 * attempt)

            except Exception as exc:
                logger.error("Beklenmeyen sentiment hatası: %s", exc)
                break

        return DEFAULT_SENTIMENT

    def _parse_response(self, raw: str) -> SentimentResult:
        """JSON yanıtı ayrıştırır."""
        try:
            # Bazen model ```json ... ``` bloğu ekler, temizle
            raw_clean = raw
            if "```json" in raw:
                raw_clean = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw_clean = raw.split("```")[1].split("```")[0].strip()

            data = json.loads(raw_clean)
            return SentimentResult(
                sentiment_score=clamp(float(data.get("sentiment_score", 0)), -10, 10),
                confidence=max(0, min(100, int(data.get("confidence", 50)))),
                category=str(data.get("category", "genel")),
                summary=str(data.get("summary", ""))[:200],
                price_impact=str(data.get("price_impact", "nötr")).lower(),
                is_rumor=bool(data.get("is_rumor", False)),
                raw_response=raw,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Sentiment parse hatası: %s | raw: %s", exc, raw[:100])
            return DEFAULT_SENTIMENT

    def analyze_batch(
        self,
        classified_news: List[ClassifiedNews],
    ) -> Dict[str, List[SentimentResult]]:
        """
        Birden fazla haberi analiz eder.
        Dönüş: {ticker_code: [SentimentResult, ...]}

        API maliyetini düşürmek için sadece event_score=0 ve önemli haberleri API'ye gönderir.
        """
        if self.client is None:
            return {}

        results: Dict[str, List[SentimentResult]] = {}
        batch: List[ClassifiedNews] = []

        for cn in classified_news:
            # Olay sınıflandırması yoksa veya düşük güven varsa API'ye gönder
            should_analyze = (
                cn.event_score == 0  # rule-based'de yakalanamadı
                or abs(cn.event_score) < 10  # düşük skorlu, AI destekle
            )
            if should_analyze:
                batch.append(cn)

        logger.info("Claude API'ye gönderilecek haber sayısı: %d", len(batch))

        for i, cn in enumerate(batch):
            if i > 0 and i % CLAUDE_SENTIMENT_BATCH_SIZE == 0:
                logger.info("Sentiment batch %d/%d, 5s bekleniyor...", i, len(batch))
                time.sleep(5)  # Rate limit koruması

            for ticker_code in cn.item.tickers:
                sentiment = self.analyze_single(
                    title=cn.item.title,
                    content=cn.item.summary or cn.item.raw_content,
                    ticker=ticker_code,
                    source=cn.item.source,
                )
                results.setdefault(ticker_code, []).append(sentiment)

            time.sleep(0.5)  # Her istek arası kısa bekleme

        return results

    def synthesize_summaries(
        self,
        ticker: str,
        summaries: List[str],
    ) -> str:
        """
        Birden fazla haber özetini Claude ile sentezler (mail için AI yorumu).
        Maksimum 5 özeti birleştirir.
        """
        if self.client is None or not summaries:
            return "Haber analizi mevcut değil."

        top = summaries[:5]
        combined = "\n".join(f"- {s}" for s in top)

        prompt = f"""\
Aşağıdaki {ticker} hissesiyle ilgili haber özetlerine dayanarak, \
yatırımcı bakış açısıyla 2-3 cümlelik kısa bir Türkçe yorum yaz. \
Sadece yorumu yaz, başka metin ekleme.

Haber özetleri:
{combined}"""

        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as exc:
            logger.warning("Özet sentez hatası: %s", exc)
            return " ".join(top[:2])


# ---------------------------------------------------------------------------
# Nihai Haber Skoru Hesaplama
# ---------------------------------------------------------------------------

def compute_news_score(
    classified: ClassifiedNews,
    sentiment: Optional[SentimentResult],
    all_items_flat: list,
    manipulation_multiplier: float = 1.0,
) -> float:
    """
    Tek haber için nihai ağırlıklı skoru hesaplar.
    Formül: (olay_skoru + ai_sentiment) × kaynak_ağırlığı × zaman_ağırlığı × manipülasyon
    """
    from utils import time_weight

    event = classified.event_score
    ai_s = (sentiment.sentiment_score if sentiment else 0.0)

    # Confidence < 50 ise AI skorunu kır
    if sentiment and sentiment.confidence < 50:
        ai_s *= 0.7

    # Söylentiyse skoru yarıya indir
    rumor_mult = 0.5 if classified.is_rumor or (sentiment and sentiment.is_rumor) else 1.0

    tw = time_weight(classified.item.pub_date)
    src_weight = classified.item.weight

    raw = (event + ai_s) * src_weight * tw * rumor_mult * manipulation_multiplier
    return clamp(raw, -50, 50)


def aggregate_ticker_news_score(scores: List[float]) -> float:
    """Hisse için tüm haber skorlarını toplar ve −50/+50 aralığında sınırlar."""
    total = sum(scores)
    return clamp(total, -50, 50)
