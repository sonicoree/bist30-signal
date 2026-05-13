# BIST30 Swing Trading Sinyal Sistemi

Profesyonel, orta risk profilli, 1-10 günlük swing trading için geliştirilmiş otomatik BIST 30 sinyal sistemi. Teknik analiz, Türkiye finans haberleri ve AI sentiment skorlamasını birleştirerek günlük HTML mail raporu üretir.

---

## Özellikler

- **Çok Katmanlı Teknik Analiz** — EMA, RSI, MACD, Bollinger, ADX, Stochastic, OBV
- **3 Farklı Setup** — Pullback EMA21, BB Squeeze Kırılımı, RSI Bullish Divergence
- **Çok Kaynaklı Haber Analizi** — KAP (Tier 1), Bloomberg HT / Reuters / AA / Dünya (Tier 2), Mynet / Bigpara / Investing TR (Tier 3)
- **AI Sentiment** — Anthropic Claude API ile her haber için -10/+10 skor
- **Birleşik Skor** — Teknik (0-100) + Haber (-50/+50) + Likidite (0-20) = -50/170
- **Veto Kuralları** — Negatif haber, zayıf piyasa ve SPK soruşturması filtreleri
- **ATR Tabanlı Risk** — Otomatik stop/hedef/pozisyon boyutu hesabı
- **Koyu Tema HTML Mail** — Responsive, detaylı sinyal kartları
- **SQLite Takibi** — Sinyaller, haberler, geçmiş performans

---

## Hızlı Başlangıç

### 1. Depoyu Klonla

```bash
git clone https://github.com/KULLANICI/bist30-signal.git
cd bist30-signal
```

### 2. Sanal Ortam Oluştur

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Ortam Değişkenlerini Ayarla

```bash
cp .env.example .env
# .env dosyasını düzenleyin
```

| Değişken | Açıklama |
|----------|----------|
| `GMAIL_USER` | Gönderen Gmail adresi |
| `GMAIL_APP_PASSWORD` | Gmail uygulama şifresi (2FA gerekli) |
| `MAIL_TO` | Alıcı e-posta adresi |
| `ANTHROPIC_API_KEY` | Claude API anahtarı |

#### Gmail Uygulama Şifresi Oluşturma
1. Google Hesabı → Güvenlik → 2 Adımlı Doğrulama'yı etkinleştir
2. Güvenlik → Uygulama Şifreleri → "Posta" seç → Oluştur
3. 16 karakterli şifreyi `GMAIL_APP_PASSWORD`'e yapıştır

#### Anthropic API Anahtarı
1. [console.anthropic.com](https://console.anthropic.com) adresine git
2. API Keys → Create Key
3. `ANTHROPIC_API_KEY`'e yapıştır

### 4. Çalıştır

```bash
# Normal çalıştırma (iş günü kontrolü yapar)
python main.py

# Tatil/hafta sonu zorla çalıştır
python main.py --force
```

---

## GitHub Actions Kurulumu

### Secrets Ekleme

Repo → Settings → Secrets and variables → Actions → New repository secret:

```
GMAIL_USER           → your@gmail.com
GMAIL_APP_PASSWORD   → xxxx xxxx xxxx xxxx
MAIL_TO              → recipient@example.com
ANTHROPIC_API_KEY    → sk-ant-api03-...
```

### Otomatik Çizelge

Her hafta içi **09:00 Türkiye saati** (UTC 06:00) otomatik çalışır.

> **Kış saati notu:** Türkiye artık yaz saatini (UTC+3) kalıcı olarak kullanmaktadır.
> Workflow dosyasındaki cron `'0 6 * * 1-5'` doğru ayardır.

### Manuel Tetikleme

GitHub → Actions → "BIST30 Günlük Sinyal Taraması" → Run workflow

---

## Proje Yapısı

```
bist30-signal/
├── main.py               # Orkestrasyono giriş noktası
├── config.py             # BIST30 listesi, sabitler, haber kaynakları
├── data_loader.py        # yfinance veri yükleme
├── news_collector.py     # Haber adaptörleri (RSS + scraping)
├── news_classifier.py    # Rule-based olay sınıflandırma
├── sentiment_analyzer.py # Claude API sentiment analizi
├── indicators.py         # pandas-ta teknik indikatörler
├── signal_engine.py      # Setup tespiti ve teknik skorlama
├── scorer.py             # Birleşik skorlama ve sınıflandırma
├── risk_manager.py       # ATR risk hesaplaması
├── mailer.py             # HTML mail oluşturma ve SMTP
├── database.py           # SQLite operasyonları
├── utils.py              # Logger, timezone, retry, rate limiter
├── requirements.txt
├── .env.example
└── .github/
    └── workflows/
        └── daily-scan.yml
```

---

## Sınıflandırma Tablosu

| Sınıf | Skor | Risk % | Açıklama |
|-------|------|--------|----------|
| ⭐ GÜÇLÜ AL | 140-170 | %1.5 | Tam pozisyon |
| 🟢 AL | 120-139 | %1.0 | Normal pozisyon |
| 🟡 ALIMA UYGUN | 100-119 | %0.5 | Yarım pozisyon |
| 🔵 İZLE | 80-99 | — | Watchlist |
| ⚪ NÖTR | 60-79 | — | Bekleme |
| 🔴 ZAYIF | <60 | — | Aktif değil |
| ⛔ VETOLU | Herhangi | — | Haber/piyasa engeli |

---

## Teknik Setup'lar

### Setup A — Pullback to EMA21
- Son 10 günde fiyat EMA21'e %2 mesafeye gerilemiş
- Bugün veya dün EMA21 üstünde kapanış
- RSI 40-55 aralığında

### Setup B — BB Squeeze Breakout
- Son 5 günde BB band genişliği 60 günlük dar %20'sinde
- Fiyat üst Bollinger bandını yukarı kırmış
- Hacim 1.8x+ ortalama

### Setup C — RSI Bullish Divergence
- Son 20 günde fiyat yeni dip ama RSI yüksek dip
- Stochastic %K 20 altından %D'yi yukarı kesmiş

---

## Haber Skorlama

### Kaynak Ağırlıkları

| Tier | Kaynak | Ağırlık |
|------|--------|---------|
| 1 | KAP (resmi açıklamalar) | 1.0 |
| 2 | BloombergHT, Reuters TR, AA, Dünya | 0.8 |
| 3 | Mynet Finans, Bigpara, Investing TR | 0.5 |

### Olay Skorları (Seçim)

| Olay | Skor |
|------|------|
| Bilanço pozitif sürpriz | +25 |
| Yeni sözleşme/ihale | +20 |
| Geri alım programı | +15 |
| SPK soruşturması | -30 |
| Bilanço negatif sürpriz | -25 |
| Dava/yasal sorun | -20 |

### Zaman Ağırlıkları

| Yaş | Ağırlık |
|-----|---------|
| 0-1 gün | 1.0 |
| 1-3 gün | 0.7 |
| 3-7 gün | 0.4 |
| 7+ gün | 0 (yoksay) |

---

## Veritabanı Şeması

```
history.db
├── signals    — günlük sinyal kayıtları ve sonuçları
├── news       — haber önbelleği (tekrar işlemeyi önler)
└── performance — haftalık performans istatistikleri
```

---

## Risk Yönetimi (ATR Tabanlı)

```
Giriş   = Kapanış × (1 + %0.5 kayma)
Stop    = Giriş − 2 × ATR(14)
T1      = Giriş + 2 × ATR(14)   → yarısını sat, stop'u girişe çek
T2      = Giriş + 4 × ATR(14)   → kalanı sat
Pozisyon = (100.000 TL × risk%) / (Giriş − Stop)
```

---

## Önerilen Kullanım

1. Sistemi yalnızca araştırma ve eğitim amaçlı kullanın
2. Her sinyali kendi analizinizle doğrulayın
3. Stop seviyelerini kesinlikle uygulayın
4. Pozisyon başına maksimum %1.5 risk kuralına uyun
5. Eş anlı 3-5 pozisyondan fazlasını tutmayın

---

## Sorun Giderme

### "yfinance verisi çekilemiyor"
- Yahoo Finance IP kısıtlaması: VPN deneyin veya 1-2 dakika bekleyin
- `--force` parametresiyle yeniden çalıştırın

### "Claude API rate limit"
- `CLAUDE_SENTIMENT_BATCH_SIZE` değerini `config.py`'de düşürün (varsayılan: 10)
- API planınızı kontrol edin

### "Mail gönderilemiyor"
- Gmail 2FA etkin mi kontrol edin
- Uygulama şifresi (uygulama şifresi ≠ Gmail şifresi)
- "Daha az güvenli uygulama" seçeneği değil, uygulama şifresi kullanın

### "Haberler çekilemiyor"
- Bazı siteler IP/coğrafya kısıtlaması uygulayabilir
- GitHub Actions runner IP adresleri bazen engellenir
- `news_collector.py` loglarında hangi kaynağın hata verdiğini kontrol edin

---

## Yasal Uyarı

> Bu sistem yatırım tavsiyesi değildir. Sunulan sinyal ve analizler yalnızca
> eğitim ve araştırma amaçlıdır. Geçmiş performans gelecekteki sonuçları garanti
> etmez. Tüm yatırım kararlarınızı kendi araştırmanıza ve/veya lisanslı bir
> finansal danışmana danışarak alın.

---

## Lisans

MIT License — Detaylar için `LICENSE` dosyasına bakın.
