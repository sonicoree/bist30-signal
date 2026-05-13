"""
utils.py — Yardımcı fonksiyonlar: logging, timezone, rate limiter, retry, robots.txt
"""

from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Callable, Optional, Set, TypeVar
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytz

from config import TIMEZONE, TURKISH_HOLIDAYS, SCRAPE_CONFIG

# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------

TZ = ZoneInfo(TIMEZONE)
TZ_PYTZ = pytz.timezone(TIMEZONE)


def now_istanbul() -> datetime:
    """Europe/Istanbul saat dilimiyle şimdiki zamanı döndürür."""
    return datetime.now(TZ)


def today_istanbul() -> date:
    return now_istanbul().date()


def localize(dt: datetime) -> datetime:
    """Naive datetime'ı Istanbul'a lokalize eder; zaten aware ise dönüştürür."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


# ---------------------------------------------------------------------------
# İş Günü Kontrolü
# ---------------------------------------------------------------------------

def is_business_day(d: Optional[date] = None) -> bool:
    """Verilen tarihin (varsayılan bugün) Türkiye borsası iş günü olup olmadığını kontrol eder."""
    if d is None:
        d = today_istanbul()
    if d.weekday() >= 5:  # Cumartesi=5, Pazar=6
        return False
    if d.isoformat() in TURKISH_HOLIDAYS:
        return False
    return True


def next_business_day(d: Optional[date] = None) -> date:
    """Sonraki iş gününü döndürür."""
    if d is None:
        d = today_istanbul()
    d += timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# Loglama
# ---------------------------------------------------------------------------

def setup_logger(name: str = "bist30", level: int = logging.INFO) -> logging.Logger:
    """Yapılandırılmış logger oluşturur."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # zaten kurulu

    logger.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Konsol handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Dosya handler
    fh = logging.FileHandler("bist30_signal.log", encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


logger = setup_logger()


# ---------------------------------------------------------------------------
# Retry Decorator
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable)


def retry(max_attempts: int = 3, delay: float = 5.0,
          exceptions: tuple = (Exception,), log_name: str = "bist30"):
    """Başarısız çağrıları tekrar dener."""
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            _logger = logging.getLogger(log_name)
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        _logger.error(
                            "%s — %d. denemede başarısız: %s",
                            func.__name__, attempt, exc,
                        )
                        raise
                    _logger.warning(
                        "%s — %d. denemede hata (%s), %.0fs sonra yeniden denenecek",
                        func.__name__, attempt, exc, delay,
                    )
                    time.sleep(delay)
        return wrapper  # type: ignore[return-value]
    return decorator


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """İki çağrı arasında rastgele bekleme ekler (scraping için)."""

    def __init__(
        self,
        min_delay: float = SCRAPE_CONFIG["request_delay_min"],
        max_delay: float = SCRAPE_CONFIG["request_delay_max"],
    ) -> None:
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_call: float = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        delay = random.uniform(self.min_delay, self.max_delay)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_call = time.monotonic()


# ---------------------------------------------------------------------------
# Robots.txt Kontrolü
# ---------------------------------------------------------------------------

_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def can_fetch(url: str, user_agent: str = "*") -> bool:
    """robots.txt kurallarına göre URL'nin çekilip çekilemeyeceğini kontrol eder."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{base}/robots.txt"

    if base not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception:
            # robots.txt okunamazsa izin varsay
            _robots_cache[base] = None  # type: ignore[assignment]
            return True
        _robots_cache[base] = rp

    rp = _robots_cache[base]
    if rp is None:
        return True
    return rp.can_fetch(user_agent, url)


# ---------------------------------------------------------------------------
# User-Agent Rotasyonu
# ---------------------------------------------------------------------------

def get_random_user_agent() -> str:
    return random.choice(SCRAPE_CONFIG["user_agents"])


def get_headers() -> dict:
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }


# ---------------------------------------------------------------------------
# Yardımcı Fonksiyonlar
# ---------------------------------------------------------------------------

def safe_float(value, default: float = 0.0) -> float:
    """None veya NaN değeri güvenli biçimde float'a çevirir."""
    try:
        f = float(value)
        import math
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pct_change(new: float, old: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / old * 100


def format_tl(amount: float) -> str:
    """TL tutarını okunabilir formata çevirir."""
    if abs(amount) >= 1_000_000_000:
        return f"{amount/1_000_000_000:.2f}B TL"
    if abs(amount) >= 1_000_000:
        return f"{amount/1_000_000:.1f}M TL"
    if abs(amount) >= 1_000:
        return f"{amount/1_000:.0f}K TL"
    return f"{amount:.2f} TL"


def days_ago(dt: datetime) -> float:
    """Verilen datetime'ın kaç gün önce olduğunu döndürür."""
    now = now_istanbul()
    if dt.tzinfo is None:
        dt = localize(dt)
    delta = now - dt
    return delta.total_seconds() / 86400


def time_weight(dt: datetime) -> float:
    """Haber yaş ağırlığını döndürür."""
    age = days_ago(dt)
    if age <= 1:
        return 1.0
    elif age <= 3:
        return 0.7
    elif age <= 7:
        return 0.4
    else:
        return 0.0


def news_in_window(dt: datetime, days: int = 7) -> bool:
    return days_ago(dt) <= days
