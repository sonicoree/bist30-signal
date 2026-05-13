"""
mailer.py — Koyu tema finans paneli HTML mail oluşturma ve Resend API gönderme
"""

from __future__ import annotations

import time
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
    "bg":        "#0d1117",
    "card":      "#161b22",
    "card2":     "#1c2128",
    "border":    "#30363d",
    "border2":   "#21262d",
    "text":      "#e6edf3",
    "muted":     "#8b949e",
    "green":     "#3fb950",
    "green2":    "#00ff88",
    "red":       "#f85149",
    "yellow":    "#d29922",
    "blue":      "#58a6ff",
    "purple":    "#bc8cff",
    "orange":    "#ffa657",
    "header_bg": "#161b22",
    "teal":      "#39d353",
}

CLS_COLOR = {
    "GÜÇLÜ AL":    "#00ff88",
    "AL":          "#3fb950",
    "ALIMA UYGUN": "#d29922",
    "İZLE":        "#58a6ff",
    "NÖTR":        "#8b949e",
    "ZAYIF":       "#f85149",
    "VETOLU":      "#ff4444",
}

CLS_BG = {
    "GÜÇLÜ AL":    "#0d2818",
    "AL":          "#0d2010",
    "ALIMA UYGUN": "#1f1a08",
    "İZLE":        "#0d1f3c",
    "NÖTR":        "#1a1a1a",
    "ZAYIF":       "#2d0f0f",
    "VETOLU":      "#2d0808",
}

CLS_EMOJI = {
    "GÜÇLÜ AL":    "⭐",
    "AL":          "🟢",
    "ALIMA UYGUN": "🟡",
    "İZLE":        "🔵",
    "NÖTR":        "⚪",
    "ZAYIF":       "🔴",
    "VETOLU":      "⛔",
}

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

def _bar(value: float, max_val: float, color: str, width: int = 160) -> str:
    pct = max(0, min(100, value / max_val * 100)) if max_val else 0
    bar_w = int(width * pct / 100)
    return (
        f'<div style="display:inline-flex;align-items:center;gap:6px;">'
        f'<div style="background:{COLORS["border"]};border-radius:4px;height:7px;'
        f'width:{width}px;">'
        f'<div style="background:{color};height:7px;width:{bar_w}px;border-radius:4px;"></div>'
        f'</div>'
        f'<span style="color:{COLORS["muted"]};font-size:11px;min-width:28px;">{value:.0f}</span>'
        f'</div>'
    )


def _badge(text: str, color: str, bg: str = "") -> str:
    bg = bg or color + "22"
    return (
        f'<span style="background:{bg};color:{color};border:1px solid {color}33;'
        f'border-radius:5px;padding:2px 10px;font-size:12px;font-weight:700;'
        f'white-space:nowrap;">{text}</span>'
    )


def _news_row(cn: ClassifiedNews, final_score: float) -> str:
    days = (now_istanbul() - cn.item.pub_date).days
    age  = f"{days}g" if days > 0 else "bugün"
    color = COLORS["green"] if final_score > 0 else (
        COLORS["red"] if final_score < 0 else COLORS["muted"]
    )
    url = cn.item.url or "#"
    return (
        f'<tr>'
        f'<td style="padding:5px 0;border-bottom:1px solid {COLORS["border2"]};">'
        f'<span style="color:{COLORS["muted"]};font-size:10px;">[{cn.item.source} · {age}]</span> '
        f'<a href="{url}" style="color:{COLORS["text"]};text-decoration:none;font-size:12px;">'
        f'{cn.item.title[:80]}{"…" if len(cn.item.title) > 80 else ""}</a>'
        f'</td>'
        f'<td style="padding:5px 6px;text-align:right;white-space:nowrap;">'
        f'<span style="color:{color};font-size:11px;font-weight:700;">'
        f'{"+" if final_score > 0 else ""}{final_score:.1f}</span>'
        f'</td></tr>'
    )


# ---------------------------------------------------------------------------
# Sinyal Açıklama Kılavuzu
# ---------------------------------------------------------------------------

def _legend_section() -> str:
    rows = [
        ("⭐ GÜÇLÜ AL",    "140–170", "#1.5", "Tüm koşullar mükemmel. Tam pozisyon.",            "#00ff88", "#0d2818"),
        ("🟢 AL",          "120–139", "%1.0", "Güçlü setup + olumlu haberler. Normal pozisyon.", "#3fb950", "#0d2010"),
        ("🟡 ALIMA UYGUN", "100–119", "%0.5", "Yeterli sinyal var. Yarım pozisyon.",             "#d29922", "#1f1a08"),
        ("🔵 İZLE",        "80–99",   "—",   "Henüz olgunlaşmamış. Takip listesi.",             "#58a6ff", "#0d1f3c"),
        ("⚪ NÖTR",        "60–79",   "—",   "Belirgin bir yön yok. Bekle.",                    "#8b949e", "#1a1a1a"),
        ("🔴 ZAYIF",       "<60",     "—",   "Setup oluşmamış. İşlem yapma.",                   "#f85149", "#2d0f0f"),
        ("⛔ VETOLU",      "—",       "—",   "Haber/piyasa veto kuralı devrede.",               "#ff4444", "#2d0808"),
    ]

    cls_rows = ""
    for label, skor, risk, desc, color, bg in rows:
        cls_rows += f"""
        <tr style="background:{bg};">
          <td style="padding:7px 12px;border-bottom:1px solid {COLORS['border2']};">
            <span style="color:{color};font-weight:700;font-size:13px;">{label}</span>
          </td>
          <td style="padding:7px 12px;border-bottom:1px solid {COLORS['border2']};
              color:{COLORS['text']};font-size:12px;text-align:center;">{skor}</td>
          <td style="padding:7px 12px;border-bottom:1px solid {COLORS['border2']};
              color:{color};font-size:12px;text-align:center;font-weight:700;">{risk}</td>
          <td style="padding:7px 12px;border-bottom:1px solid {COLORS['border2']};
              color:{COLORS['muted']};font-size:12px;">{desc}</td>
        </tr>"""

    score_params = f"""
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:12px;">
      <div style="flex:1;min-width:180px;background:{COLORS['card2']};border:1px solid {COLORS['border2']};
           border-radius:8px;padding:12px;">
        <div style="color:{COLORS['green']};font-size:11px;font-weight:700;letter-spacing:1px;
             margin-bottom:6px;">TEKNİK SKOR (0–100)</div>
        <div style="color:{COLORS['muted']};font-size:12px;line-height:1.7;">
          EMA21 Pullback Setup: <span style="color:{COLORS['text']};">+25p</span><br>
          BB Squeeze Kırılımı: <span style="color:{COLORS['text']};">+25p</span><br>
          RSI Bullish Divergence: <span style="color:{COLORS['text']};">+20p</span><br>
          RSI 40–60 bölgesi: <span style="color:{COLORS['text']};">+10p</span><br>
          EMA trend hizalaması: <span style="color:{COLORS['text']};">+10p</span><br>
          ADX &gt; 25 güçlü trend: <span style="color:{COLORS['text']};">+10p</span>
        </div>
      </div>
      <div style="flex:1;min-width:180px;background:{COLORS['card2']};border:1px solid {COLORS['border2']};
           border-radius:8px;padding:12px;">
        <div style="color:{COLORS['blue']};font-size:11px;font-weight:700;letter-spacing:1px;
             margin-bottom:6px;">HABER SKORU (–50 / +50)</div>
        <div style="color:{COLORS['muted']};font-size:12px;line-height:1.7;">
          Bilanço pozitif sürpriz: <span style="color:{COLORS['green']};">+25p</span><br>
          Yeni sözleşme / ihale: <span style="color:{COLORS['green']};">+20p</span><br>
          Geri alım programı: <span style="color:{COLORS['green']};">+15p</span><br>
          SPK soruşturması: <span style="color:{COLORS['red']};"> –30p</span><br>
          Bilanço neg. sürpriz: <span style="color:{COLORS['red']};"> –25p</span><br>
          Kaynak ağırlığı: KAP×1.0 / BB×0.8 / Diğer×0.5
        </div>
      </div>
      <div style="flex:1;min-width:180px;background:{COLORS['card2']};border:1px solid {COLORS['border2']};
           border-radius:8px;padding:12px;">
        <div style="color:{COLORS['orange']};font-size:11px;font-weight:700;letter-spacing:1px;
             margin-bottom:6px;">LİKİDİTE SKORU (0–20)</div>
        <div style="color:{COLORS['muted']};font-size:12px;line-height:1.7;">
          Günlük hacim &gt; 250M TL: <span style="color:{COLORS['text']};">+10p</span><br>
          Günlük hacim &gt; 100M TL: <span style="color:{COLORS['text']};">+5p</span><br>
          Piyasa değeri &gt; 5B TL: <span style="color:{COLORS['text']};">+10p</span><br>
          <br>
          <span style="color:{COLORS['text']};font-weight:700;">
            TOPLAM = Teknik + Haber + Likidite
          </span><br>
          <span style="color:{COLORS['muted']};">Aralık: –50 ile 170 puan</span>
        </div>
      </div>
      <div style="flex:1;min-width:180px;background:{COLORS['card2']};border:1px solid {COLORS['border2']};
           border-radius:8px;padding:12px;">
        <div style="color:{COLORS['purple']};font-size:11px;font-weight:700;letter-spacing:1px;
             margin-bottom:6px;">ATR RİSK PARAMETRELERİ</div>
        <div style="color:{COLORS['muted']};font-size:12px;line-height:1.7;">
          Giriş = Kapanış × 1.005 (kayma)<br>
          Stop = Giriş – 2 × ATR(14)<br>
          T1 = Giriş + 2 × ATR(14)<br>
          T2 = Giriş + 4 × ATR(14)<br>
          Portföy = 100.000 TL<br>
          Adet = (Port × risk%) ÷ (Giriş–Stop)
        </div>
      </div>
    </div>"""

    return f"""
    <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
         border-radius:10px;padding:20px;margin-bottom:20px;">
      <h2 style="color:{COLORS['text']};margin:0 0 14px 0;font-size:16px;letter-spacing:0.5px;">
        📖 Sinyal Kılavuzu & Parametre Tablosu
      </h2>

      <table style="width:100%;border-collapse:collapse;border:1px solid {COLORS['border']};
             border-radius:8px;overflow:hidden;margin-bottom:4px;">
        <tr style="background:{COLORS['header_bg']};">
          <th style="padding:7px 12px;text-align:left;color:{COLORS['muted']};
              font-size:11px;letter-spacing:1px;">SİNYAL</th>
          <th style="padding:7px 12px;text-align:center;color:{COLORS['muted']};
              font-size:11px;letter-spacing:1px;">SKOR</th>
          <th style="padding:7px 12px;text-align:center;color:{COLORS['muted']};
              font-size:11px;letter-spacing:1px;">RİSK %</th>
          <th style="padding:7px 12px;text-align:left;color:{COLORS['muted']};
              font-size:11px;letter-spacing:1px;">AÇIKLAMA</th>
        </tr>
        {cls_rows}
      </table>

      {score_params}
    </div>"""


# ---------------------------------------------------------------------------
# Sinyal Kartı (AL ve üzeri için detaylı)
# ---------------------------------------------------------------------------

def _signal_card(sig: CombinedSignal, news_scores: Dict[str, float]) -> str:
    cls   = sig.classification
    color = CLS_COLOR.get(cls, COLORS["muted"])
    bg    = CLS_BG.get(cls, COLORS["card"])
    emoji = CLS_EMOJI.get(cls, "")

    rl    = sig.risk_levels
    close = sig.tech_signal.close
    prev  = sig.tech_signal.prev_close
    pct_chg = (close - prev) / prev * 100 if prev > 0 else 0.0
    chg_color = COLORS["green"] if pct_chg >= 0 else COLORS["red"]
    chg_sign  = "+" if pct_chg >= 0 else ""

    if rl:
        strategy_html = f"""
        <table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:12px;">
          <tr style="color:{COLORS['muted']};">
            <td style="padding:3px 8px 3px 0;">Giriş</td>
            <td style="padding:3px 8px 3px 0;">Stop</td>
            <td style="padding:3px 8px 3px 0;">Hedef 1</td>
            <td style="padding:3px 8px 3px 0;">Hedef 2</td>
            <td style="padding:3px 8px 3px 0;">R/R</td>
            <td style="padding:3px 8px 3px 0;">Adet</td>
            <td style="padding:3px 0;">Risk</td>
          </tr>
          <tr style="color:{COLORS['text']};font-weight:700;">
            <td style="padding:3px 8px 3px 0;">{rl.entry:.2f}</td>
            <td style="padding:3px 8px 3px 0;color:{COLORS['red']};">{rl.stop:.2f}</td>
            <td style="padding:3px 8px 3px 0;color:{COLORS['green']};">{rl.target1:.2f}</td>
            <td style="padding:3px 8px 3px 0;color:{COLORS['green']};">{rl.target2:.2f}</td>
            <td style="padding:3px 8px 3px 0;">{rl.rr_ratio:.1f}:1</td>
            <td style="padding:3px 8px 3px 0;">{rl.position_size:,}</td>
            <td style="padding:3px 0;">{format_tl(rl.risk_amount)}</td>
          </tr>
        </table>"""
    else:
        strategy_html = (
            f'<p style="color:{COLORS["muted"]};font-size:12px;margin:6px 0 0;">'
            f'Yeterli veri yok — risk seviyeleri hesaplanamadı</p>'
        )

    tech_html = "".join(
        f'<li style="color:{COLORS["text"]};font-size:12px;margin:2px 0;">{r}</li>'
        for r in sig.tech_reasons[:6]
    )

    sorted_news = sorted(
        sig.news_items,
        key=lambda cn: abs(news_scores.get(f"{cn.item.source}|{cn.item.title[:40]}", 0)),
        reverse=True,
    )[:5]
    news_rows = "".join(
        _news_row(cn, news_scores.get(f"{cn.item.source}|{cn.item.title[:40]}", 0.0))
        for cn in sorted_news
    )
    news_html = (
        f'<table style="width:100%;border-collapse:collapse;">{news_rows}</table>'
        if news_rows else
        f'<p style="color:{COLORS["muted"]};font-size:12px;">Son 7 günde ilgili haber yok</p>'
    )

    ai_html = ""
    if sig.ai_commentary:
        ai_html = (
            f'<div style="background:#0d1f35;border-left:3px solid {COLORS["blue"]};'
            f'padding:8px 12px;border-radius:0 6px 6px 0;margin-top:8px;">'
            f'<span style="color:{COLORS["blue"]};font-size:11px;font-weight:700;">🤖 AI Yorum</span>'
            f'<p style="color:{COLORS["text"]};font-size:12px;margin:4px 0 0;">'
            f'{sig.ai_commentary}</p></div>'
        )

    veto_html = ""
    if sig.is_vetoed:
        bc = COLORS["red"] if sig.is_sell_warning else COLORS["orange"]
        veto_html = (
            f'<div style="background:{bc}18;border:1px solid {bc};'
            f'border-radius:6px;padding:8px 12px;margin-top:8px;">'
            f'<b style="color:{bc};">'
            f'{"⛔ SAT/DUR UYARISI" if sig.is_sell_warning else "⛔ VETOLU"}</b> — '
            f'<span style="color:{COLORS["text"]};font-size:12px;">{sig.veto_reason}</span>'
            f'</div>'
        )

    flags_html = ""
    if sig.flags:
        items = "".join(
            f'<div style="margin:2px 0;font-size:12px;color:{COLORS["orange"]};">{f}</div>'
            for f in sig.flags
        )
        flags_html = (
            f'<div style="background:#1e1508;border:1px solid {COLORS["orange"]}44;'
            f'border-radius:6px;padding:8px 12px;margin-top:8px;">'
            f'<b style="color:{COLORS["orange"]};font-size:11px;">⚠ Risk Bayrakları</b>'
            f'{items}</div>'
        )

    return f"""
    <div style="background:{bg};border:1px solid {color}33;
         border-radius:10px;padding:18px;margin-bottom:14px;">

      <div style="display:flex;justify-content:space-between;align-items:flex-start;
           flex-wrap:wrap;gap:8px;">
        <div>
          <span style="font-size:26px;font-weight:900;color:{COLORS['text']};
              letter-spacing:-0.5px;">{sig.ticker}</span>
          <span style="color:{COLORS['muted']};font-size:13px;margin-left:8px;">
            {sig.company_name}</span>
          <span style="color:{COLORS['muted']};font-size:11px;margin-left:6px;">
            · {sig.sector}</span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
          {_badge(f"{emoji} {cls}", color, CLS_BG.get(cls, ''))}
          <span style="font-size:28px;font-weight:900;color:{color};
              letter-spacing:-1px;">{sig.total_score:.0f}</span>
        </div>
      </div>

      <div style="margin-top:12px;display:flex;gap:16px;flex-wrap:wrap;align-items:center;">
        <div>
          <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">TEKNİK</div>
          {_bar(sig.tech_score, 100, COLORS['green'])}
        </div>
        <div>
          <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">HABER</div>
          {_bar(sig.news_score + 50, 100,
            COLORS['green'] if sig.news_score >= 0 else COLORS['red'])}
        </div>
        <div>
          <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">LİKİDİTE</div>
          {_bar(sig.liquidity_score, 20, COLORS['blue'], 80)}
        </div>
      </div>

      <div style="margin-top:12px;display:flex;gap:20px;flex-wrap:wrap;">
        <div>
          <span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">KAPANIŞ</span><br>
          <span style="color:{COLORS['text']};font-size:18px;font-weight:700;">{close:.2f} ₺</span>
          <span style="color:{chg_color};font-size:12px;"> {chg_sign}{pct_chg:.2f}%</span>
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">RSI</span><br>
          <span style="color:{COLORS['text']};font-size:16px;">{sig.tech_signal.rsi:.1f}</span>
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">ADX</span><br>
          <span style="color:{COLORS['text']};font-size:16px;">{sig.tech_signal.adx:.1f}</span>
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">HACİM</span><br>
          <span style="color:{COLORS['text']};font-size:16px;">{sig.tech_signal.volume_ratio:.1f}x</span>
        </div>
        <div>
          <span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">HABER</span><br>
          <span style="color:{SENTIMENT_COLOR.get(sig.news_sentiment_label, COLORS['muted'])};
              font-size:13px;">{sig.news_sentiment_label}
            <span style="font-size:11px;">({sig.news_score:+.1f})</span>
          </span>
        </div>
      </div>

      <div style="margin-top:12px;border-top:1px solid {COLORS['border2']};padding-top:12px;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;
             margin-bottom:4px;">STRATEJİ</div>
        {strategy_html}
      </div>

      <div style="margin-top:12px;border-top:1px solid {COLORS['border2']};padding-top:12px;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;
             margin-bottom:4px;">TEKNİK GEREKÇELER</div>
        <ul style="margin:0;padding-left:16px;">{tech_html}</ul>
      </div>

      <div style="margin-top:12px;border-top:1px solid {COLORS['border2']};padding-top:12px;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;
             margin-bottom:4px;">SON HABERLER</div>
        {news_html}
        {ai_html}
      </div>

      {flags_html}
      {veto_html}
    </div>"""


# ---------------------------------------------------------------------------
# BIST30 Tam Tarama Tablosu (tüm hisseler)
# ---------------------------------------------------------------------------

def _full_scan_table(ranked: Dict[str, List[CombinedSignal]]) -> str:
    order = ["GÜÇLÜ AL", "AL", "ALIMA UYGUN", "İZLE", "NÖTR", "ZAYIF", "VETOLU"]
    all_sigs = []
    for cls in order:
        all_sigs.extend(ranked.get(cls, []))

    if not all_sigs:
        return ""

    rows = ""
    prev_cls = None
    for sig in all_sigs:
        cls   = sig.classification
        color = CLS_COLOR.get(cls, COLORS["muted"])
        bg    = CLS_BG.get(cls, COLORS["card"])
        emoji = CLS_EMOJI.get(cls, "")

        # Kategori ayırıcı
        if cls != prev_cls:
            rows += f"""
            <tr style="background:{bg};">
              <td colspan="9" style="padding:6px 12px;
                  border-top:2px solid {color}44;border-bottom:1px solid {color}33;">
                <span style="color:{color};font-size:12px;font-weight:700;
                    letter-spacing:0.5px;">{emoji} {cls}</span>
              </td>
            </tr>"""
            prev_cls = cls

        close = sig.tech_signal.close
        prev  = sig.tech_signal.prev_close
        pct   = (close - prev) / prev * 100 if prev > 0 else 0.0
        pct_color = COLORS["green"] if pct >= 0 else COLORS["red"]

        # Skor rengi (gradient: kırmızıdan yeşile)
        if sig.total_score >= 120:
            sc = COLORS["green2"]
        elif sig.total_score >= 100:
            sc = COLORS["green"]
        elif sig.total_score >= 80:
            sc = COLORS["blue"]
        elif sig.total_score >= 60:
            sc = COLORS["muted"]
        else:
            sc = COLORS["red"]

        veto_mark = " ⛔" if sig.is_vetoed else ""

        rows += f"""
        <tr style="background:{COLORS['card']};border-bottom:1px solid {COLORS['border2']};">
          <td style="padding:7px 8px;font-weight:700;color:{COLORS['text']};
              font-size:13px;">{sig.ticker}</td>
          <td style="padding:7px 8px;color:{COLORS['muted']};font-size:11px;
              max-width:140px;overflow:hidden;">{sig.company_name[:22]}</td>
          <td style="padding:7px 8px;">
            <span style="color:{color};font-size:11px;font-weight:700;
                background:{bg};border-radius:4px;padding:2px 7px;
                white-space:nowrap;">{emoji} {cls}{veto_mark}</span>
          </td>
          <td style="padding:7px 8px;text-align:right;">
            <span style="color:{sc};font-weight:700;font-size:14px;">{sig.total_score:.0f}</span>
          </td>
          <td style="padding:7px 8px;text-align:right;color:{COLORS['text']};
              font-size:12px;">{sig.tech_score:.0f}</td>
          <td style="padding:7px 8px;text-align:right;font-size:12px;">
            <span style="color:{'#3fb950' if sig.news_score >= 0 else '#f85149'};">
              {sig.news_score:+.0f}</span>
          </td>
          <td style="padding:7px 8px;text-align:right;color:{COLORS['text']};
              font-size:12px;">{close:.2f} ₺</td>
          <td style="padding:7px 8px;text-align:right;">
            <span style="color:{pct_color};font-size:12px;">
              {"+" if pct >= 0 else ""}{pct:.2f}%</span>
          </td>
          <td style="padding:7px 8px;text-align:right;color:{COLORS['muted']};
              font-size:11px;">{sig.tech_signal.rsi:.0f}</td>
        </tr>"""

    return f"""
    <h2 style="color:{COLORS['text']};margin:24px 0 12px;font-size:17px;">
      📊 BIST30 Tam Tarama ({len(all_sigs)} hisse)
    </h2>
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;background:{COLORS['card']};
         border:1px solid {COLORS['border']};border-radius:10px;overflow:hidden;
         min-width:600px;">
      <tr style="background:{COLORS['header_bg']};">
        <th style="padding:8px;text-align:left;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">HİSSE</th>
        <th style="padding:8px;text-align:left;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">ŞİRKET</th>
        <th style="padding:8px;text-align:left;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">SİNYAL</th>
        <th style="padding:8px;text-align:right;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">TOPLAM</th>
        <th style="padding:8px;text-align:right;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">TEKNİK</th>
        <th style="padding:8px;text-align:right;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">HABER</th>
        <th style="padding:8px;text-align:right;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">FİYAT</th>
        <th style="padding:8px;text-align:right;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">DEĞ%</th>
        <th style="padding:8px;text-align:right;color:{COLORS['muted']};
            font-size:10px;letter-spacing:1px;">RSI</th>
      </tr>
      {rows}
    </table>
    </div>"""


# ---------------------------------------------------------------------------
# Sektör Dağılımı
# ---------------------------------------------------------------------------

def _sector_bars(ranked: Dict[str, List[CombinedSignal]], total: int) -> str:
    dist: Dict[str, int] = {}
    for cls in ["GÜÇLÜ AL", "AL", "ALIMA UYGUN", "İZLE"]:
        for sig in ranked.get(cls, []):
            dist[sig.sector] = dist.get(sig.sector, 0) + 1
    if not dist or total == 0:
        return "<p style='color:#8b949e;'>Aksiyon alınabilir sinyal yok</p>"

    rows = ""
    for sector, count in sorted(dist.items(), key=lambda x: x[1], reverse=True)[:8]:
        pct = count / max(dist.values()) * 100
        bar_w = int(pct * 1.5)
        rows += (
            f'<div style="margin:4px 0;display:flex;align-items:center;gap:8px;">'
            f'<span style="color:{COLORS["muted"]};font-size:12px;width:140px;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{sector}</span>'
            f'<div style="background:{COLORS["green"]};height:14px;width:{bar_w}px;'
            f'border-radius:3px;min-width:4px;"></div>'
            f'<span style="color:{COLORS["text"]};font-size:12px;">{count}</span>'
            f'</div>'
        )
    return rows


# ---------------------------------------------------------------------------
# Performans (Pazartesi)
# ---------------------------------------------------------------------------

def _performance_section(perf: dict) -> str:
    wr = perf.get("win_rate", 0)
    ar = perf.get("avg_return", 0)
    return f"""
    <h2 style="color:{COLORS['text']};margin-top:24px;font-size:17px;">
      📈 Geçen Hafta Performansı
    </h2>
    <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
         border-radius:10px;padding:16px;display:flex;gap:24px;flex-wrap:wrap;">
      <div><span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">
        TOPLAM SİNYAL</span><br>
        <span style="color:{COLORS['text']};font-size:22px;font-weight:700;">
          {perf.get('total_signals', 0)}</span></div>
      <div><span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">
        T1 İSABET</span><br>
        <span style="color:{COLORS['green']};font-size:22px;font-weight:700;">
          {perf.get('t1_hits', 0)}</span></div>
      <div><span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">
        T2 İSABET</span><br>
        <span style="color:{COLORS['green']};font-size:22px;font-weight:700;">
          {perf.get('t2_hits', 0)}</span></div>
      <div><span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">
        STOP</span><br>
        <span style="color:{COLORS['red']};font-size:22px;font-weight:700;">
          {perf.get('stop_hits', 0)}</span></div>
      <div><span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">
        KAZANMA ORANI</span><br>
        <span style="color:{'#3fb950' if wr >= 50 else '#f85149'};font-size:22px;font-weight:700;">
          %{wr:.1f}</span></div>
      <div><span style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">
        ORT. GETİRİ</span><br>
        <span style="color:{'#3fb950' if ar >= 0 else '#f85149'};font-size:22px;font-weight:700;">
          {'+' if ar >= 0 else ''}{ar:.2f}%</span></div>
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
    now    = now_istanbul()
    ranked = rank_signals(signals)

    strong_buy = ranked["GÜÇLÜ AL"]
    buy        = ranked["AL"]
    suitable   = ranked["ALIMA UYGUN"]
    watch_list = ranked["İZLE"]
    neutral    = ranked["NÖTR"]
    weak       = ranked["ZAYIF"]
    vetoed     = ranked["VETOLU"]
    all_active = strong_buy + buy + suitable

    xu100_close  = market_regime.get("xu100_close", 0)
    ema50_val    = market_regime.get("ema50_val", 0)
    market_ok    = market_regime.get("above_ema50", False)
    market_label = "GÜÇLÜ ▲" if market_ok else "ZAYIF ▼"
    market_color = COLORS["green"] if market_ok else COLORS["red"]
    usdtry_str   = f"{usdtry:.4f}" if usdtry else "—"

    total_sigs = len(signals)

    # Özet kartları
    summary_html = f"""
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;">

      <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
           border-radius:10px;padding:14px 18px;flex:2;min-width:160px;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">BIST100 (XU100)</div>
        <div style="color:{COLORS['text']};font-size:22px;font-weight:700;">
          {xu100_close:,.0f}</div>
        <div style="color:{market_color};font-size:12px;margin-top:2px;">
          {market_label} · EMA50 = {ema50_val:,.0f}</div>
      </div>

      <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
           border-radius:10px;padding:14px 18px;flex:1;min-width:110px;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">USD / TRY</div>
        <div style="color:{COLORS['text']};font-size:22px;font-weight:700;">{usdtry_str}</div>
      </div>

      <div style="background:#0d2818;border:1px solid #00ff8833;
           border-radius:10px;padding:14px 18px;flex:1;min-width:100px;text-align:center;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">⭐ GÜÇLÜ AL</div>
        <div style="color:#00ff88;font-size:28px;font-weight:900;">{len(strong_buy)}</div>
      </div>

      <div style="background:#0d2010;border:1px solid #3fb95033;
           border-radius:10px;padding:14px 18px;flex:1;min-width:100px;text-align:center;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">🟢 AL</div>
        <div style="color:#3fb950;font-size:28px;font-weight:900;">{len(buy)}</div>
      </div>

      <div style="background:#1f1a08;border:1px solid #d2992233;
           border-radius:10px;padding:14px 18px;flex:1;min-width:100px;text-align:center;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">🟡 ALIMA UYGUN</div>
        <div style="color:#d29922;font-size:28px;font-weight:900;">{len(suitable)}</div>
      </div>

      <div style="background:#0d1f3c;border:1px solid #58a6ff33;
           border-radius:10px;padding:14px 18px;flex:1;min-width:100px;text-align:center;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">🔵 İZLE</div>
        <div style="color:#58a6ff;font-size:28px;font-weight:900;">{len(watch_list)}</div>
      </div>

      <div style="background:#2d0808;border:1px solid #ff444433;
           border-radius:10px;padding:14px 18px;flex:1;min-width:100px;text-align:center;">
        <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;">⛔ VETOLU</div>
        <div style="color:#ff4444;font-size:28px;font-weight:900;">{len(vetoed)}</div>
      </div>

    </div>"""

    # Piyasa uyarısı
    market_warn = ""
    if not market_ok:
        market_warn = f"""
        <div style="background:#2d0f0f;border:1px solid {COLORS['red']};
             border-radius:8px;padding:12px 16px;margin-bottom:16px;">
          <b style="color:{COLORS['red']};">⚠ PİYASA UYARISI:</b>
          <span style="color:{COLORS['text']};font-size:13px;"> XU100 EMA50 altında.
            Açık pozisyonlarda stop seviyelerine dikkat et. AL sinyalleri
            yarım pozisyonla değerlendir.</span>
        </div>"""

    # Sektör dağılımı
    sector_html = ""
    sector_content = _sector_bars(ranked, len(all_active))
    if all_active:
        sector_html = f"""
        <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
             border-radius:10px;padding:16px;margin-bottom:20px;">
          <div style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;
               margin-bottom:10px;">AKSIYON SİNYALLERİ — SEKTÖR DAĞILIMI</div>
          {sector_content}
        </div>"""

    # Sinyal kartları bölümleri
    def render_cards(sigs: List[CombinedSignal], title: str, color: str) -> str:
        if not sigs:
            return ""
        cards = "".join(_signal_card(s, news_scores_map) for s in sigs)
        return f"""
        <h2 style="color:{color};margin:24px 0 12px;font-size:17px;">{title}</h2>
        {cards}"""

    cards_html = (
        render_cards(strong_buy, "⭐ GÜÇLÜ AL Sinyalleri",    CLS_COLOR["GÜÇLÜ AL"]) +
        render_cards(buy,        "🟢 AL Sinyalleri",          CLS_COLOR["AL"]) +
        render_cards(suitable,   "🟡 ALIMA UYGUN Sinyalleri", CLS_COLOR["ALIMA UYGUN"]) +
        render_cards(watch_list, "🔵 İZLE — Takip Listesi",   CLS_COLOR["İZLE"])
    )

    if not cards_html.strip():
        cards_html = f"""
        <div style="text-align:center;padding:24px;color:{COLORS['muted']};font-size:14px;">
          Bugün aksiyon alınabilir sinyal yok — tüm tarama tablosuna bak ↓
        </div>"""

    # Vetolu özet
    veto_html = ""
    if vetoed:
        veto_rows = "".join(
            f'<tr><td style="padding:5px 10px;color:{COLORS["text"]};font-weight:700;">'
            f'{s.ticker}</td>'
            f'<td style="padding:5px 10px;color:{COLORS["red"]};font-size:12px;">'
            f'{s.veto_reason}</td></tr>'
            for s in vetoed[:10]
        )
        veto_html = f"""
        <h2 style="color:{COLORS['red']};margin:24px 0 12px;font-size:17px;">
          ⛔ Vetolu / Reddedilenler ({len(vetoed)})
        </h2>
        <table style="width:100%;border-collapse:collapse;background:{COLORS['card']};
             border:1px solid {COLORS['border']};border-radius:10px;">
          <tr style="color:{COLORS['muted']};font-size:10px;letter-spacing:1px;
              border-bottom:1px solid {COLORS['border']};">
            <th style="padding:7px 10px;text-align:left;">HİSSE</th>
            <th style="padding:7px 10px;text-align:left;">VETO SEBEBİ</th>
          </tr>
          {veto_rows}
        </table>"""

    # Performans (Pazartesi)
    perf_html = _performance_section(weekly_perf) if is_monday and weekly_perf else ""

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BIST30 Sinyal Raporu — {now.strftime('%d.%m.%Y')}</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0;padding:0;background:{COLORS['bg']};
          font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
          color:{COLORS['text']}; }}
  a {{ color:{COLORS['blue']};text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  @media(max-width:600px){{
    .flex-wrap {{ flex-direction:column!important; }}
  }}
</style>
</head>
<body>
<div style="max-width:860px;margin:0 auto;padding:16px;">

  <!-- BAŞLIK -->
  <div style="background:linear-gradient(135deg,{COLORS['header_bg']},{COLORS['card2']});
       border:1px solid {COLORS['border']};border-radius:12px;
       padding:24px;margin-bottom:20px;text-align:center;">
    <h1 style="margin:0 0 6px;font-size:22px;color:{COLORS['text']};letter-spacing:-0.3px;">
      📊 BIST30 Swing Trading Sinyal Raporu
    </h1>
    <p style="color:{COLORS['muted']};margin:0;font-size:13px;">
      {now.strftime('%d %B %Y, %A')} · Tarama: {now.strftime('%H:%M')} İstanbul
      · {total_sigs} hisse analiz edildi
    </p>
  </div>

  <!-- ÖZET -->
  {summary_html}

  <!-- PİYASA UYARISI -->
  {market_warn}

  <!-- SEKTÖR DAĞILIMI -->
  {sector_html}

  <!-- SİNYAL KARTLARI -->
  {cards_html}

  <!-- VETOLU -->
  {veto_html}

  <!-- TAM TARAMA TABLOSU -->
  {_full_scan_table(ranked)}

  <!-- PERFORMANS -->
  {perf_html}

  <!-- KILAVUZ -->
  <div style="margin-top:28px;">
    {_legend_section()}
  </div>

  <!-- FOOTER -->
  <div style="margin-top:24px;padding-top:16px;border-top:1px solid {COLORS['border2']};
       text-align:center;">
    <p style="color:{COLORS['muted']};font-size:11px;line-height:1.8;margin:0;">
      ⚠ <b>Bu rapor yatırım tavsiyesi değildir.</b> Sunulan bilgiler yalnızca
      eğitim ve bilgilendirme amaçlıdır. Geçmiş performans gelecek getirileri
      garanti etmez. Tüm yatırım kararlarınızı kendi araştırmanıza ve/veya
      lisanslı bir finansal danışmana danışarak alın.<br>
      Sonraki tarama: <b>Yarın 09:00 TR (iş günü ise)</b> ·
      Sistem: <b>BIST30-Signal v2.0</b>
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
