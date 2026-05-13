"""
mailer.py — Koyu tema finans paneli HTML mail oluşturma ve Resend API gönderme
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

import resend

from config import MAIL_CONFIG, SIGNAL_CLASSES
from news_classifier import ClassifiedNews
from scorer import CombinedSignal, rank_signals, sector_distribution
from utils import format_tl, logger, now_istanbul

# ---------------------------------------------------------------------------
# Renk Paleti
# ---------------------------------------------------------------------------

COLORS = {
    "bg":       "#0d1117",
    "card":     "#161b22",
    "border":   "#30363d",
    "text":     "#c9d1d9",
    "muted":    "#8b949e",
    "green":    "#3fb950",
    "red":      "#f85149",
    "yellow":   "#d29922",
    "blue":     "#58a6ff",
    "purple":   "#bc8cff",
    "orange":   "#ffa657",
    "header_bg":"#1f2937",
}

CLS_COLOR = {
    "GÜÇLÜ AL":    "#00ff88",
    "AL":          "#3fb950",
    "ALIMA UYGUN": "#d29922",
    "İZLE":        "#58a6ff",
    "NÖTR":        "#8b949e",
    "ZAYIF":       "#f85149",
    "VETOLU":      "#ff0000",
}

# Haber sentiment etiketi → renk
SENTIMENT_COLOR = {
    "Çok Pozitif": "#00ff88",
    "Pozitif":     "#3fb950",
    "Nötr":        "#8b949e",
    "Negatif":     "#f85149",
    "Çok Negatif": "#ff3333",
}


# ---------------------------------------------------------------------------
# Yardımcı HTML Parçaları
# ---------------------------------------------------------------------------

def _progress_bar(value: float, max_val: float, color: str, width: int = 180) -> str:
    pct = max(0, min(100, value / max_val * 100)) if max_val else 0
    bar_w = int(width * pct / 100)
    return (
        f'<div style="background:{COLORS["border"]};border-radius:4px;height:8px;'
        f'width:{width}px;display:inline-block;vertical-align:middle;">'
        f'<div style="background:{color};height:8px;width:{bar_w}px;border-radius:4px;"></div>'
        f'</div> <span style="color:{COLORS["muted"]};font-size:11px;">{value:.1f}</span>'
    )


def _badge(text: str, color: str, bg: str = "") -> str:
    bg = bg or color + "22"
    return (
        f'<span style="background:{bg};color:{color};border:1px solid {color};'
        f'border-radius:4px;padding:2px 8px;font-size:12px;font-weight:700;">{text}</span>'
    )


def _flag_html(flags: List[str]) -> str:
    if not flags:
        return ""
    items = "".join(
        f'<div style="margin:2px 0;font-size:12px;color:{COLORS["orange"]};">{f}</div>'
        for f in flags
    )
    return (
        f'<div style="background:#2d2213;border:1px solid {COLORS["orange"]};'
        f'border-radius:6px;padding:8px 12px;margin-top:8px;">'
        f'<b style="color:{COLORS["orange"]};">⚠ Risk Bayrakları</b>{items}</div>'
    )


def _news_row(cn: ClassifiedNews, final_score: float) -> str:
    days = (now_istanbul() - cn.item.pub_date).days
    age  = f"{days}g önce" if days > 0 else "bugün"
    color = COLORS["green"] if final_score > 0 else (
        COLORS["red"] if final_score < 0 else COLORS["muted"]
    )
    score_badge = (
        f'<span style="color:{color};font-size:11px;font-weight:700;">'
        f'{"+" if final_score > 0 else ""}{final_score:.1f}</span>'
    )
    url = cn.item.url or "#"
    return (
        f'<tr><td style="padding:4px 0;border-bottom:1px solid {COLORS["border"]};">'
        f'<span style="color:{COLORS["muted"]};font-size:11px;">'
        f'[{cn.item.source}, {age}]</span> '
        f'<a href="{url}" style="color:{COLORS["text"]};text-decoration:none;font-size:12px;">'
        f'{cn.item.title[:90]}…</a>'
        f'</td><td style="padding:4px 6px;text-align:right;white-space:nowrap;">'
        f'{score_badge}</td></tr>'
    )


# ---------------------------------------------------------------------------
# Sektör Dağılım Çubuğu
# ---------------------------------------------------------------------------

def _sector_bars(dist: Dict[str, int], total: int) -> str:
    if not dist or total == 0:
        return "<p>—</p>"
    rows = ""
    for sector, count in list(dist.items())[:8]:
        pct = count / total * 100
        bar_w = int(pct * 2)
        rows += (
            f'<div style="margin:3px 0;display:flex;align-items:center;gap:8px;">'
            f'<span style="color:{COLORS["muted"]};font-size:12px;width:130px;'
            f'white-space:nowrap;overflow:hidden;">{sector}</span>'
            f'<div style="background:{COLORS["green"]};height:14px;width:{bar_w}px;'
            f'border-radius:3px;"></div>'
            f'<span style="color:{COLORS["text"]};font-size:12px;">{count}</span>'
            f'</div>'
        )
    return rows


# ---------------------------------------------------------------------------
# Sinyal Kartı
# ---------------------------------------------------------------------------

def _signal_card(sig: CombinedSignal, news_scores: Dict[str, float]) -> str:
    cls   = sig.classification
    color = CLS_COLOR.get(cls, COLORS["muted"])
    emoji = sig.classification_info.get("emoji", "")

    rl = sig.risk_levels
    close = sig.tech_signal.close
    prev  = sig.tech_signal.prev_close

    # Günlük fiyat değişimi
    pct_chg = (close - prev) / prev * 100 if prev > 0 else 0.0
    chg_color = COLORS["green"] if pct_chg >= 0 else COLORS["red"]
    chg_sign  = "+" if pct_chg >= 0 else ""

    # Strateji tablosu
    if rl:
        strategy_html = f"""
        <table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:12px;">
        <tr style="color:{COLORS['muted']};">
          <td>Giriş</td><td>Stop</td><td>T1</td><td>T2</td>
          <td>R/R</td><td>Adet</td><td>Risk</td>
        </tr>
        <tr style="color:{COLORS['text']};font-weight:700;">
          <td>{rl.entry:.2f}</td>
          <td style="color:{COLORS['red']};">{rl.stop:.2f}</td>
          <td style="color:{COLORS['green']};">{rl.target1:.2f}</td>
          <td style="color:{COLORS['green']};">{rl.target2:.2f}</td>
          <td>{rl.rr_ratio:.1f}:1</td>
          <td>{rl.position_size:,}</td>
          <td>{format_tl(rl.risk_amount)}</td>
        </tr>
        </table>"""
    else:
        strategy_html = (
            f'<p style="color:{COLORS["muted"]};font-size:12px;">'
            f'Risk seviyeleri hesaplanamadı (veri yetersiz veya sinyal aktif değil)</p>'
        )

    # Teknik gerekçeler
    tech_html = ""
    for reason in sig.tech_reasons[:8]:
        tech_html += (
            f'<li style="color:{COLORS["text"]};font-size:12px;'
            f'margin:2px 0;">{reason}</li>'
        )

    # Haber özeti (en etkili 5)
    news_rows = ""
    sorted_news = sorted(
        sig.news_items,
        key=lambda cn: abs(news_scores.get(f"{cn.item.source}|{cn.item.title[:40]}", 0)),
        reverse=True,
    )[:5]
    for cn in sorted_news:
        ns = news_scores.get(f"{cn.item.source}|{cn.item.title[:40]}", 0.0)
        news_rows += _news_row(cn, ns)

    news_html = (
        f'<table style="width:100%;border-collapse:collapse;">{news_rows}</table>'
        if news_rows else
        f'<p style="color:{COLORS["muted"]};font-size:12px;">Son 7 günde ilgili haber yok</p>'
    )

    # AI yorumu
    ai_html = ""
    if sig.ai_commentary:
        ai_html = (
            f'<div style="background:#1a2332;border-left:3px solid {COLORS["blue"]};'
            f'padding:8px 12px;border-radius:0 6px 6px 0;margin-top:8px;">'
            f'<span style="color:{COLORS["blue"]};font-size:11px;font-weight:700;">🤖 AI Yorum</span>'
            f'<p style="color:{COLORS["text"]};font-size:12px;margin:4px 0 0 0;">'
            f'{sig.ai_commentary}</p></div>'
        )

    # Veto banner
    veto_html = ""
    if sig.is_vetoed:
        banner_color = COLORS["red"] if sig.is_sell_warning else COLORS["orange"]
        veto_html = (
            f'<div style="background:{banner_color}22;border:1px solid {banner_color};'
            f'border-radius:6px;padding:8px 12px;margin-top:8px;">'
            f'<b style="color:{banner_color};">'
            f'{"⛔ SAT/DUR UYARISI" if sig.is_sell_warning else "⛔ VETOLU"}</b> — '
            f'<span style="color:{COLORS["text"]};font-size:12px;">{sig.veto_reason}</span>'
            f'</div>'
        )

    return f"""
    <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
         border-radius:10px;padding:20px;margin-bottom:16px;">

      <!-- Başlık Satırı -->
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div>
          <span style="font-size:24px;font-weight:900;color:{COLORS['text']};">{sig.ticker}</span>
          <span style="color:{COLORS['muted']};font-size:13px;margin-left:8px;">{sig.company_name}</span>
          <span style="color:{COLORS['muted']};font-size:12px;margin-left:6px;">· {sig.sector}</span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
          {_badge(f"{emoji} {cls}", color)}
          <span style="font-size:20px;font-weight:900;color:{color};">
            {sig.total_score:.0f}
          </span>
        </div>
      </div>

      <!-- Skor Barları -->
      <div style="margin-top:12px;display:flex;gap:12px;flex-wrap:wrap;align-items:center;">
        <div>
          <span style="color:{COLORS['muted']};font-size:11px;">TEKNİK</span><br>
          {_progress_bar(sig.tech_score, 100, COLORS['green'])}
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:11px;">HABER</span><br>
          {_progress_bar(sig.news_score + 50, 100,
            COLORS['green'] if sig.news_score >= 0 else COLORS['red'])}
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:11px;">LİKİDİTE</span><br>
          {_progress_bar(sig.liquidity_score, 20, COLORS['blue'])}
        </div>
      </div>

      <!-- Fiyat Bilgisi -->
      <div style="margin-top:12px;display:flex;gap:20px;flex-wrap:wrap;">
        <div>
          <span style="color:{COLORS['muted']};font-size:11px;">KAPANIŞ</span><br>
          <span style="color:{COLORS['text']};font-size:16px;font-weight:700;">{close:.2f} TL</span>
          <span style="color:{chg_color};font-size:12px;"> {chg_sign}{pct_chg:.2f}%</span>
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:11px;">RSI</span><br>
          <span style="color:{COLORS['text']};font-size:16px;">{sig.tech_signal.rsi:.1f}</span>
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:11px;">ADX</span><br>
          <span style="color:{COLORS['text']};font-size:16px;">{sig.tech_signal.adx:.1f}</span>
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:11px;">HACİM</span><br>
          <span style="color:{COLORS['text']};font-size:16px;">{sig.tech_signal.volume_ratio:.1f}x</span>
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:11px;">HABER</span><br>
          <span style="color:{SENTIMENT_COLOR.get(sig.news_sentiment_label, COLORS['muted'])};
            font-size:14px;">{sig.news_sentiment_label} ({sig.news_score:+.1f})</span>
        </div>
      </div>

      <!-- Strateji -->
      <div style="margin-top:12px;border-top:1px solid {COLORS['border']};padding-top:12px;">
        <b style="color:{COLORS['muted']};font-size:12px;letter-spacing:1px;">STRATEJİ</b>
        {strategy_html}
      </div>

      <!-- Teknik Gerekçeler -->
      <div style="margin-top:12px;border-top:1px solid {COLORS['border']};padding-top:12px;">
        <b style="color:{COLORS['muted']};font-size:12px;letter-spacing:1px;">TEKNİK GEREKÇELER</b>
        <ul style="margin:6px 0 0 16px;padding:0;">{tech_html}</ul>
      </div>

      <!-- Haberler -->
      <div style="margin-top:12px;border-top:1px solid {COLORS['border']};padding-top:12px;">
        <b style="color:{COLORS['muted']};font-size:12px;letter-spacing:1px;">SON HABERLER</b>
        <div style="margin-top:6px;">{news_html}</div>
        {ai_html}
      </div>

      {_flag_html(sig.flags)}
      {veto_html}
    </div>"""


# ---------------------------------------------------------------------------
# Watchlist ve Vetolu Bölümler
# ---------------------------------------------------------------------------

def _watchlist_section(signals: List[CombinedSignal]) -> str:
    if not signals:
        return ""
    rows = ""
    for sig in signals[:15]:
        rows += (
            f'<tr>'
            f'<td style="color:{COLORS["text"]};font-weight:700;padding:4px 8px;">{sig.ticker}</td>'
            f'<td style="color:{COLORS["muted"]};font-size:12px;padding:4px 8px;">{sig.company_name}</td>'
            f'<td style="color:{COLORS["muted"]};font-size:12px;padding:4px 8px;">{sig.sector}</td>'
            f'<td style="color:{CLS_COLOR["İZLE"]};font-weight:700;padding:4px 8px;">{sig.total_score:.0f}</td>'
            f'<td style="color:{COLORS["muted"]};font-size:12px;padding:4px 8px;">'
            f'{sig.tech_signal.close:.2f} TL</td>'
            f'</tr>'
        )
    return f"""
    <h2 style="color:{COLORS['text']};margin-top:24px;">
      🔵 Watchlist ({len(signals)} hisse)
    </h2>
    <table style="width:100%;border-collapse:collapse;background:{COLORS['card']};
         border:1px solid {COLORS['border']};border-radius:8px;">
      <tr style="color:{COLORS['muted']};font-size:11px;border-bottom:1px solid {COLORS['border']};">
        <th style="padding:6px 8px;text-align:left;">Hisse</th>
        <th style="padding:6px 8px;text-align:left;">Şirket</th>
        <th style="padding:6px 8px;text-align:left;">Sektör</th>
        <th style="padding:6px 8px;text-align:left;">Skor</th>
        <th style="padding:6px 8px;text-align:left;">Fiyat</th>
      </tr>
      {rows}
    </table>"""


def _vetoed_section(signals: List[CombinedSignal]) -> str:
    if not signals:
        return ""
    rows = ""
    for sig in signals[:10]:
        rows += (
            f'<tr>'
            f'<td style="color:{COLORS["text"]};font-weight:700;padding:4px 8px;">{sig.ticker}</td>'
            f'<td style="color:{COLORS["muted"]};font-size:12px;padding:4px 8px;">'
            f'{sig.tech_score}</td>'
            f'<td style="color:{COLORS["red"]};font-size:12px;padding:4px 8px;">'
            f'{sig.veto_reason}</td>'
            f'</tr>'
        )
    return f"""
    <h2 style="color:{COLORS['red']};margin-top:24px;">
      ⛔ Vetolu / Reddedilenler ({len(signals)} hisse)
    </h2>
    <table style="width:100%;border-collapse:collapse;background:{COLORS['card']};
         border:1px solid {COLORS['border']};border-radius:8px;">
      <tr style="color:{COLORS['muted']};font-size:11px;border-bottom:1px solid {COLORS['border']};">
        <th style="padding:6px 8px;text-align:left;">Hisse</th>
        <th style="padding:6px 8px;text-align:left;">Teknik Skor</th>
        <th style="padding:6px 8px;text-align:left;">Veto Sebebi</th>
      </tr>
      {rows}
    </table>"""


def _performance_section(perf: Optional[dict]) -> str:
    if not perf:
        return ""
    wr = perf.get("win_rate", 0)
    ar = perf.get("avg_return", 0)
    return f"""
    <h2 style="color:{COLORS['text']};margin-top:24px;">📈 Geçen Hafta Performansı</h2>
    <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
         border-radius:8px;padding:16px;display:flex;gap:24px;flex-wrap:wrap;">
      <div>
        <span style="color:{COLORS['muted']};font-size:11px;">TOPLAM SİNYAL</span><br>
        <span style="color:{COLORS['text']};font-size:20px;font-weight:700;">
          {perf.get('total_signals', 0)}</span>
      </div>
      <div>
        <span style="color:{COLORS['muted']};font-size:11px;">T1 İSABET</span><br>
        <span style="color:{COLORS['green']};font-size:20px;font-weight:700;">
          {perf.get('t1_hits', 0)}</span>
      </div>
      <div>
        <span style="color:{COLORS['muted']};font-size:11px;">T2 İSABET</span><br>
        <span style="color:{COLORS['green']};font-size:20px;font-weight:700;">
          {perf.get('t2_hits', 0)}</span>
      </div>
      <div>
        <span style="color:{COLORS['muted']};font-size:11px;">STOP</span><br>
        <span style="color:{COLORS['red']};font-size:20px;font-weight:700;">
          {perf.get('stop_hits', 0)}</span>
      </div>
      <div>
        <span style="color:{COLORS['muted']};font-size:11px;">KAZANMA ORANI</span><br>
        <span style="color:{'#3fb950' if wr >= 50 else '#f85149'};font-size:20px;font-weight:700;">
          %{wr:.1f}</span>
      </div>
      <div>
        <span style="color:{COLORS['muted']};font-size:11px;">ORT. GETİRİ</span><br>
        <span style="color:{'#3fb950' if ar >= 0 else '#f85149'};font-size:20px;font-weight:700;">
          {'+' if ar >= 0 else ''}{ar:.2f}%</span>
      </div>
    </div>"""


# ---------------------------------------------------------------------------
# Ana HTML Oluşturma
# ---------------------------------------------------------------------------

def build_html_email(
    signals: List[CombinedSignal],
    market_regime: dict,
    usdtry: Optional[float],
    news_scores_map: Dict[str, float],
    weekly_perf: Optional[dict],
    is_monday: bool,
) -> str:
    now = now_istanbul()
    ranked = rank_signals(signals)

    strong_buy = ranked["GÜÇLÜ AL"]
    buy        = ranked["AL"]
    suitable   = ranked["ALIMA UYGUN"]
    watch_list = ranked["İZLE"]
    vetoed     = ranked["VETOLU"]
    all_active = strong_buy + buy + suitable

    dist = sector_distribution(signals)
    total_active = len(all_active)

    xu100_close = market_regime.get("xu100_close", 0)
    ema50_val   = market_regime.get("ema50_val", 0)
    market_ok   = market_regime.get("above_ema50", False)
    market_label = "GÜÇLÜ" if market_ok else "ZAYIF"
    market_color = COLORS["green"] if market_ok else COLORS["red"]

    usdtry_str = f"{usdtry:.4f}" if usdtry else "—"

    # Özet satırları
    summary_html = f"""
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px;">
      <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
           border-radius:8px;padding:12px 16px;flex:1;min-width:140px;">
        <div style="color:{COLORS['muted']};font-size:11px;">XU100</div>
        <div style="color:{COLORS['text']};font-size:18px;font-weight:700;">
          {xu100_close:,.0f}</div>
        <div style="color:{market_color};font-size:12px;">
          {'▲' if market_ok else '▼'} EMA50={ema50_val:,.0f} · {market_label}</div>
      </div>
      <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
           border-radius:8px;padding:12px 16px;flex:1;min-width:140px;">
        <div style="color:{COLORS['muted']};font-size:11px;">USD/TRY</div>
        <div style="color:{COLORS['text']};font-size:18px;font-weight:700;">{usdtry_str}</div>
      </div>
      <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
           border-radius:8px;padding:12px 16px;flex:1;min-width:140px;">
        <div style="color:{COLORS['muted']};font-size:11px;">⭐ GÜÇLÜ AL</div>
        <div style="color:{CLS_COLOR['GÜÇLÜ AL']};font-size:24px;font-weight:900;">
          {len(strong_buy)}</div>
      </div>
      <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
           border-radius:8px;padding:12px 16px;flex:1;min-width:140px;">
        <div style="color:{COLORS['muted']};font-size:11px;">🟢 AL</div>
        <div style="color:{CLS_COLOR['AL']};font-size:24px;font-weight:900;">{len(buy)}</div>
      </div>
      <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
           border-radius:8px;padding:12px 16px;flex:1;min-width:140px;">
        <div style="color:{COLORS['muted']};font-size:11px;">🟡 UYGUN</div>
        <div style="color:{CLS_COLOR['ALIMA UYGUN']};font-size:24px;font-weight:900;">
          {len(suitable)}</div>
      </div>
      <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
           border-radius:8px;padding:12px 16px;flex:1;min-width:140px;">
        <div style="color:{COLORS['muted']};font-size:11px;">⛔ VETOLU</div>
        <div style="color:{CLS_COLOR['VETOLU']};font-size:24px;font-weight:900;">
          {len(vetoed)}</div>
      </div>
    </div>"""

    # Sektör dağılımı
    sector_html = f"""
    <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
         border-radius:8px;padding:16px;margin-bottom:16px;">
      <b style="color:{COLORS['muted']};font-size:12px;letter-spacing:1px;">SEKTÖR DAĞILIMI</b>
      <div style="margin-top:8px;">{_sector_bars(dist, total_active)}</div>
    </div>"""

    # Sinyal kartları
    def render_section(sigs: List[CombinedSignal], title: str, color: str) -> str:
        if not sigs:
            return ""
        cards = "".join(_signal_card(s, news_scores_map) for s in sigs)
        return f"""
        <h2 style="color:{color};margin-top:24px;margin-bottom:12px;">{title}</h2>
        {cards}"""

    main_html = (
        render_section(strong_buy, "⭐ GÜÇLÜ AL Sinyalleri", CLS_COLOR["GÜÇLÜ AL"]) +
        render_section(buy, "🟢 AL Sinyalleri", CLS_COLOR["AL"]) +
        render_section(suitable, "🟡 ALIMA UYGUN Sinyalleri", CLS_COLOR["ALIMA UYGUN"])
    )

    perf_html = _performance_section(weekly_perf) if is_monday else ""

    next_scan = "Yarın 09:00 TR (iş günü ise)"
    version   = "BIST30-Signal v1.0"

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BIST30 Sinyal Raporu</title>
<style>
  body {{ margin:0;padding:0;font-family:'Segoe UI',Arial,sans-serif;
          background:{COLORS['bg']};color:{COLORS['text']}; }}
  a {{ color:{COLORS['blue']}; }}
  table {{ width:100%; }}
  @media(max-width:600px){{
    .card-flex {{ flex-direction:column!important; }}
  }}
</style>
</head>
<body>
<div style="max-width:800px;margin:0 auto;padding:16px;">

  <!-- BAŞLIK -->
  <div style="background:{COLORS['header_bg']};border:1px solid {COLORS['border']};
       border-radius:10px;padding:20px;margin-bottom:16px;text-align:center;">
    <h1 style="margin:0;font-size:24px;color:{COLORS['text']};">
      📊 BIST30 Swing Trading Sinyal Raporu
    </h1>
    <p style="color:{COLORS['muted']};margin:4px 0 0 0;font-size:13px;">
      {now.strftime('%d %B %Y, %A')} · Tarama: {now.strftime('%H:%M')} TR
      {'· <b style="color:' + COLORS['red'] + ';">PİYASA ZAYIF</b>' if not market_ok else ''}
    </p>
  </div>

  <!-- ÖZET -->
  {summary_html}

  <!-- SEKTÖR -->
  {sector_html}

  <!-- SINYAL KARTLARI -->
  {main_html if main_html.strip() else
   '<p style="color:' + COLORS['muted'] + ';text-align:center;">Bugün aksiyon alınabilir sinyal yok.</p>'}

  <!-- WATCHLIST -->
  {_watchlist_section(watch_list)}

  <!-- VETOLU -->
  {_vetoed_section(vetoed)}

  <!-- PERFORMANS (Pazartesi) -->
  {perf_html}

  <!-- FOOTER -->
  <div style="margin-top:32px;padding-top:16px;border-top:1px solid {COLORS['border']};
       text-align:center;">
    <p style="color:{COLORS['muted']};font-size:11px;line-height:1.6;">
      ⚠ <b>Bu rapor yatırım tavsiyesi değildir.</b> Sunulan bilgiler yalnızca
      eğitim ve bilgilendirme amaçlıdır. Geçmiş performans gelecek getirileri
      garanti etmez. Yatırım kararlarınızı almadan önce lisanslı bir yatırım
      danışmanına başvurunuz.<br><br>
      Sonraki tarama: <b>{next_scan}</b> · Sistem: <b>{version}</b>
    </p>
  </div>

</div>
</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# Resend API Gönderme
# ---------------------------------------------------------------------------

def send_email(
    html_body: str,
    subject: str,
    from_addr: str,
    to_addr: str,
    api_key: str,
) -> bool:
    """Resend API ile HTML mail gönderir (3 retry)."""
    cfg = MAIL_CONFIG
    resend.api_key = api_key

    for attempt in range(1, cfg["retry_count"] + 1):
        try:
            resend.Emails.send({
                "from": from_addr,
                "to": [to_addr],
                "subject": subject,
                "html": html_body,
            })
            logger.info("Mail gönderildi → %s", to_addr)
            return True
        except Exception as exc:
            if attempt < cfg["retry_count"]:
                logger.warning(
                    "Mail gönderilemedi (%d. deneme): %s, %ds bekleniyor",
                    attempt, exc, cfg["retry_delay"],
                )
                time.sleep(cfg["retry_delay"])
            else:
                logger.error("Mail 3 denemede gönderilemedi: %s", exc)
    return False
