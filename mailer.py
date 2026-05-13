"""
mailer.py — BIST30 Swing Trading Mail Raporu v4
Hero UI · 5-Günlük Trade Planı · Haber Akışı · Tam İndikatör Tablosu
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Any

import resend

from config import MAIL_CONFIG
from news_classifier import ClassifiedNews
from scorer import CombinedSignal, rank_signals
from utils import format_tl, logger, now_istanbul

# ─── Renk sistemi ─────────────────────────────────────────────────────────────

P = {
    "bg":       "#070c16",
    "surface":  "#0d1526",
    "card":     "#111f35",
    "glass":    "#141f33",
    "border":   "#1a2d4a",
    "rim":      "#243a5e",
    "text":     "#e8f0fe",
    "sub":      "#7ea3cc",
    "muted":    "#3d5a7a",
    "green":    "#10b981",
    "green2":   "#34d399",
    "green3":   "#6ee7b7",
    "red":      "#ef4444",
    "red2":     "#f87171",
    "yellow":   "#f59e0b",
    "blue":     "#3b82f6",
    "blue2":    "#60a5fa",
    "cyan":     "#06b6d4",
    "purple":   "#8b5cf6",
    "orange":   "#f97316",
    "indigo":   "#6366f1",
}

SIG = {
    "GÜÇLÜ AL":    {"c": "#34d399", "bg": "#022c22", "bd": "#065f46", "e": "⭐"},
    "AL":          {"c": "#10b981", "bg": "#011f17", "bd": "#047857", "e": "🟢"},
    "ALIMA UYGUN": {"c": "#f59e0b", "bg": "#1c1000", "bd": "#92400e", "e": "🟡"},
    "İZLE":        {"c": "#3b82f6", "bg": "#0a1628", "bd": "#1e40af", "e": "🔵"},
    "NÖTR":        {"c": "#64748b", "bg": "#0d1526", "bd": "#334155", "e": "⚪"},
    "ZAYIF":       {"c": "#ef4444", "bg": "#1a0505", "bd": "#7f1d1d", "e": "🔴"},
    "VETOLU":      {"c": "#dc2626", "bg": "#150303", "bd": "#991b1b", "e": "⛔"},
}

TIER_LABEL = {1: "KAP", 2: "Tier-2", 3: "Tier-3"}
TIER_COLOR = {1: "#f59e0b", 2: "#3b82f6", 3: "#64748b"}

def sg(cls: str) -> dict:
    return SIG.get(cls, SIG["NÖTR"])


# ─── Temel bileşenler ─────────────────────────────────────────────────────────

def pill(text: str, color: str, bg: str, border: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f'background:{bg};color:{color};border:1px solid {border};'
        f'font-size:11px;font-weight:700;white-space:nowrap;">{text}</span>'
    )

def source_badge(source: str, tier: int) -> str:
    c = TIER_COLOR.get(tier, P["muted"])
    return (
        f'<span style="display:inline-block;padding:1px 7px;border-radius:4px;'
        f'background:{c}18;color:{c};border:1px solid {c}44;'
        f'font-size:10px;font-weight:700;letter-spacing:0.03em;">{source}</span>'
    )

def score_chip(val: float, lo: float = -50, hi: float = 170) -> str:
    pct = (val - lo) / (hi - lo) if hi > lo else 0.5
    if pct > 0.7:   c = P["green2"]
    elif pct > 0.5: c = P["green"]
    elif pct > 0.35: c = P["yellow"]
    else:           c = P["red"]
    return f'<span style="color:{c};font-size:16px;font-weight:800;">{val:.0f}</span>'

def rsi_color(v: float) -> str:
    if v >= 70: return P["red"]
    if v <= 30: return P["green2"]
    if 40 <= v <= 60: return P["yellow"]
    return P["sub"]

def td(content: str, align: str = "right", pad: str = "8px 10px") -> str:
    return f'<td style="padding:{pad};text-align:{align};vertical-align:middle;">{content}</td>'

def th(label: str, align: str = "right") -> str:
    return (
        f'<th style="padding:6px 10px;text-align:{align};color:{P["muted"]};'
        f'font-size:9px;font-weight:700;letter-spacing:0.1em;'
        f'text-transform:uppercase;border-bottom:1px solid {P["border"]};'
        f'white-space:nowrap;">{label}</th>'
    )

def sep(label: str = "") -> str:
    if label:
        return (
            f'<div style="display:flex;align-items:center;gap:12px;'
            f'margin:28px 0 16px;">'
            f'<div style="flex:1;height:1px;background:{P["border"]};"></div>'
            f'<span style="color:{P["muted"]};font-size:10px;font-weight:700;'
            f'letter-spacing:0.12em;text-transform:uppercase;">{label}</span>'
            f'<div style="flex:1;height:1px;background:{P["border"]};"></div>'
            f'</div>'
        )
    return f'<div style="height:1px;background:{P["border"]};margin:20px 0;"></div>'


# ─── Hero bölümü ──────────────────────────────────────────────────────────────

def _hero(
    now,
    signals: List[CombinedSignal],
    ranked: Dict[str, List],
    market_regime: dict,
    usdtry: Optional[float],
) -> str:
    xu100 = market_regime.get("xu100_close", 0)
    ema50 = market_regime.get("ema50_val", 0)
    mok   = market_regime.get("above_ema50", False)
    diff_pct = ((xu100 / ema50) - 1) * 100 if ema50 else 0
    usd = f"{usdtry:.4f}" if usdtry else "—"

    n_strong = len(ranked["GÜÇLÜ AL"])
    n_buy    = len(ranked["AL"])
    n_suit   = len(ranked["ALIMA UYGUN"])
    n_watch  = len(ranked["İZLE"])
    n_veto   = len(ranked["VETOLU"])

    market_line = (
        f'<span style="color:{P["green"]};font-weight:700;">▲ EMA50 +{diff_pct:.1f}% ÜSTÜNDE · PİYASA GÜÇLÜ</span>'
        if mok else
        f'<span style="color:{P["red"]};font-weight:700;">▼ EMA50 {diff_pct:.1f}% ALTINDA · PİYASA ZAYIF</span>'
    )

    def stat(val, label, color):
        return (
            f'<div style="text-align:center;padding:0 4px;">'
            f'<div style="font-size:28px;font-weight:900;color:{color};'
            f'letter-spacing:-1.5px;line-height:1;">{val}</div>'
            f'<div style="color:{P["muted"]};font-size:9px;letter-spacing:0.1em;'
            f'text-transform:uppercase;margin-top:3px;">{label}</div>'
            f'</div>'
        )

    return f"""
<div style="background:linear-gradient(160deg,#0a1628 0%,#060d1c 60%,#0a1221 100%);
     border:1px solid {P["rim"]};border-radius:16px;overflow:hidden;margin-bottom:20px;">

  <!-- Top bar -->
  <div style="background:{P["glass"]};border-bottom:1px solid {P["border"]};
       padding:10px 24px;display:flex;align-items:center;justify-content:space-between;
       flex-wrap:wrap;gap:8px;">
    <span style="color:{P["muted"]};font-size:11px;letter-spacing:0.08em;">
      {now.strftime('%d %B %Y · %A').upper()} · {now.strftime('%H:%M')} İSTANBUL
    </span>
    <span style="color:{P["sub"]};font-size:11px;">
      {len(signals)} hisse · EMA / RSI / MACD / BB / ADX / Stoch / Hacim
    </span>
  </div>

  <!-- Başlık -->
  <div style="padding:28px 24px 20px;text-align:center;">
    <div style="color:{P["muted"]};font-size:10px;letter-spacing:0.2em;
         text-transform:uppercase;margin-bottom:8px;">BIST30 · 5-Günlük Swing Trading</div>
    <h1 style="font-size:28px;font-weight:900;color:{P["text"]};margin:0 0 4px;
         letter-spacing:-1px;">Günlük Sinyal Raporu</h1>
    <div style="font-size:13px;margin-top:8px;">{market_line}</div>
  </div>

  <!-- Piyasa metrikleri -->
  <div style="padding:0 24px 20px;">
    <div style="background:{P["surface"]};border:1px solid {P["border"]};
         border-radius:12px;padding:16px 20px;">
      <div style="display:flex;align-items:center;justify-content:space-between;
           flex-wrap:wrap;gap:16px;">

        <!-- XU100 -->
        <div>
          <div style="color:{P["muted"]};font-size:9px;letter-spacing:0.12em;
               text-transform:uppercase;margin-bottom:4px;">BIST100 XU100</div>
          <div style="color:{P["text"]};font-size:32px;font-weight:900;
               letter-spacing:-1.5px;line-height:1;">{xu100:,.0f}</div>
          <div style="color:{P["green"] if mok else P["red"]};font-size:12px;margin-top:3px;">
            EMA50: {ema50:,.0f} · {f"+{diff_pct:.1f}%" if diff_pct >= 0 else f"{diff_pct:.1f}%"}
          </div>
        </div>

        <!-- Divider -->
        <div style="width:1px;height:50px;background:{P["border"]};"></div>

        <!-- USD/TRY -->
        <div>
          <div style="color:{P["muted"]};font-size:9px;letter-spacing:0.12em;
               text-transform:uppercase;margin-bottom:4px;">USD / TRY</div>
          <div style="color:{P["text"]};font-size:28px;font-weight:800;
               letter-spacing:-1px;">{usd}</div>
        </div>

        <!-- Divider -->
        <div style="width:1px;height:50px;background:{P["border"]};"></div>

        <!-- Sinyal sayaçları -->
        <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:center;">
          {stat(n_strong, "⭐ Güçlü Al", P["green2"])}
          {stat(n_buy,    "🟢 Al",       P["green"])}
          {stat(n_suit,   "🟡 Uygun",    P["yellow"])}
          {stat(n_watch,  "🔵 İzle",     P["blue"])}
          {stat(n_veto,   "⛔ Veto",     P["red"])}
        </div>

      </div>
    </div>
  </div>

  {"<!-- Zayıf piyasa uyarısı -->" + f'<div style="margin:0 24px 20px;background:{P["red"]}15;border:1px solid {P["red"]}44;border-radius:8px;padding:10px 16px;"><span style="color:{P["red"]};font-weight:700;">⚠ Piyasa Zayıf</span> <span style="color:{P["sub"]};font-size:12px;">— XU100, EMA50 altında. Aktif AL sinyallerinde pozisyon boyutunu yarıya indir. Stop seviyelerine sıkı uy.</span></div>' if not mok else ""}

</div>"""


# ─── Haber akışı ──────────────────────────────────────────────────────────────

def _news_feed(
    all_classified_news: List[ClassifiedNews],
    news_scores_map: Dict[str, float],
    sentiment_by_ticker: Dict[str, Any],
) -> str:
    if not all_classified_news:
        return ""

    # Skoru hesaplanmış haberleri topla
    scored: List[tuple] = []
    for cn in all_classified_news:
        key   = f"{cn.item.source}|{cn.item.title[:40]}"
        score = news_scores_map.get(key, 0.0)
        scored.append((cn, score))

    # Önemli haberleri filtrele (skor != 0 veya tier 1)
    important = [(cn, s) for cn, s in scored if abs(s) >= 3 or cn.item.tier == 1]
    important.sort(key=lambda x: abs(x[1]), reverse=True)

    if not important:
        # Skor bağımsız, en yeni 15 haberi göster
        important = sorted(scored, key=lambda x: x[0].item.pub_date, reverse=True)[:15]

    # Pozitif / negatif / nötr ayır
    pos = [(cn, s) for cn, s in important if s > 0][:10]
    neg = [(cn, s) for cn, s in important if s < 0][:8]
    neu = [(cn, s) for cn, s in important if s == 0][:7]

    def _row(cn: ClassifiedNews, score: float, idx: int) -> str:
        days = (now_istanbul() - cn.item.pub_date).days
        age  = "bugün" if days == 0 else (f"{days}g önce" if days < 7 else cn.item.pub_date.strftime("%d.%m"))
        url  = cn.item.url or "#"
        sc   = P["green"] if score > 0 else (P["red"] if score < 0 else P["muted"])
        tick_str = " · ".join(cn.item.tickers[:3]) if cn.item.tickers else ""
        is_rumor_str = ' <span style="color:{P[\'yellow\']};font-size:9px;">[söylenti]</span>' if cn.is_rumor else ""
        event_str = f'<span style="color:{P["sub"]};font-size:10px;"> [{cn.event_category}]</span>' if cn.event_category else ""
        row_bg = P["surface"] if idx % 2 == 0 else P["card"]

        score_badge = (
            f'<div style="background:{sc}15;border:1px solid {sc}40;'
            f'border-radius:6px;padding:2px 8px;text-align:center;min-width:44px;">'
            f'<span style="color:{sc};font-size:12px;font-weight:800;">'
            f'{"+" if score > 0 else ""}{score:.0f}</span></div>'
        ) if score != 0 else ""

        return f"""
        <tr style="background:{row_bg};border-bottom:1px solid {P["border"]};">
          <td style="padding:10px 12px;vertical-align:top;width:52px;">
            {score_badge}
          </td>
          <td style="padding:10px 4px;vertical-align:top;white-space:nowrap;">
            {source_badge(cn.item.source, cn.item.tier)}
            {"<br><span style='color:" + P['blue2'] + ";font-size:10px;font-weight:600;'>" + tick_str + "</span>" if tick_str else ""}
          </td>
          <td style="padding:10px 12px 10px 8px;vertical-align:top;">
            <a href="{url}" style="color:{P['text']};font-size:13px;line-height:1.5;
               font-weight:500;">{cn.item.title}</a>
            {event_str}
            <div style="color:{P['muted']};font-size:10px;margin-top:3px;">{age}</div>
          </td>
        </tr>"""

    def _block(title: str, color: str, items: list) -> str:
        if not items:
            return ""
        rows = "".join(_row(cn, s, i) for i, (cn, s) in enumerate(items))
        return f"""
        <div style="margin-bottom:16px;">
          <div style="font-size:12px;font-weight:700;color:{color};
               letter-spacing:0.05em;padding:8px 12px;
               background:{color}12;border-left:3px solid {color};
               border-radius:0 6px 6px 0;margin-bottom:2px;">{title}</div>
          <table style="width:100%;border-collapse:collapse;">{rows}</table>
        </div>"""

    total_shown = len(pos) + len(neg) + len(neu)
    return f"""
<div style="background:{P["surface"]};border:1px solid {P["border"]};
     border-radius:12px;overflow:hidden;">
  <div style="padding:14px 16px;border-bottom:1px solid {P["border"]};
       display:flex;align-items:center;justify-content:space-between;">
    <span style="color:{P["text"]};font-size:14px;font-weight:700;">
      📰 Piyasa Haber Akışı
    </span>
    <span style="color:{P["muted"]};font-size:11px;">
      {total_shown} önemli haber · kaynaklara göre ağırlıklı
    </span>
  </div>
  <div style="padding:12px 12px 8px;">
    {_block("▲ Pozitif Haberler", P["green"], pos)}
    {_block("▼ Negatif Haberler", P["red"], neg)}
    {_block("● Genel / Sektör Haberleri", P["sub"], neu)}
  </div>
</div>"""


# ─── 5-Günlük Trade Planı ─────────────────────────────────────────────────────

def _five_day_plan(sig: CombinedSignal) -> str:
    ts  = sig.tech_signal
    rl  = sig.risk_levels
    cls = sig.classification
    s   = sg(cls)

    if not rl:
        return f'<p style="color:{P["muted"]};font-size:12px;">Risk seviyeleri hesaplanamadı.</p>'

    # Setup tipine göre özelleştirilmiş plan
    has_a = ts.layers.layer3_setup.setup_a
    has_b = ts.layers.layer3_setup.setup_b
    has_c = ts.layers.layer3_setup.setup_c

    if has_b:
        setup_tip  = "BB Squeeze Kırılımı — volatilite patlaması"
        entry_note = "Kırılım günü hacim 1.5x+ ise giriş yap. Gap-up durumunda ilk retesti bekle."
        d2_d3_note = "Kırılımın devamını izle. BB üst bandı destek olarak çalışmalı. Günlük kapanış BB orta bandının altına düşerse pozisyonu kapat."
        exit_note  = "T1'de %50 çık, stop'u girişe çek. T2 için ADX > 25 şartını koru."
    elif has_a:
        setup_tip  = "EMA21 Pullback — ana trend geri çekilmesi"
        entry_note = "EMA21 üstünde kapanışı onayla, sabah 10:30 sonrası giriş yap (açılış gürültüsünden kaçın)."
        d2_d3_note = "EMA21'i yakından izle. Kapanış EMA21 altında ise çık. RSI 40 altına düşerse savunmaya geç."
        exit_note  = "T1'de %50 çık ve stop'u girişe çek. EMA21 kırılıncaya kadar ya da T2'ye ulaşana kadar tut."
    elif has_c:
        setup_tip  = "RSI Bullish Diverjans — momentum dönüşü"
        entry_note = "Stoch K, D'yi yukarı kestikten sonra giriş yap. Hacim ortalamanın üstünde olmalı."
        d2_d3_note = "RSI 50 üstünde tutunuyor mu kontrol et. Stoch aşırı alım (>80) bölgesine girdiyse dikkatli ol."
        exit_note  = "Diverjans timleri genelde kısa ömürlüdür. T1'de %60 çık, T2 için bekleme."
    else:
        setup_tip  = "Momentum / Teknik Güç"
        entry_note = "Piyasa açılışından sonraki ilk saat içinde seviyeleri değerlendir."
        d2_d3_note = "Ana EMA seviyeleri ve RSI'yi günlük takip et."
        exit_note  = "Hedeflere ulaştığında kısmi kar al, stop'u güncelle."

    stop_pct  = (rl.entry - rl.stop)    / rl.entry * 100
    t1_pct    = (rl.target1 - rl.entry) / rl.entry * 100
    t2_pct    = (rl.target2 - rl.entry) / rl.entry * 100

    def day_row(day: str, icon: str, color: str, content: str) -> str:
        return f"""
        <div style="display:flex;gap:12px;padding:10px 0;
             border-bottom:1px solid {P['border']};">
          <div style="flex-shrink:0;width:64px;text-align:right;">
            <span style="color:{color};font-size:10px;font-weight:700;
                letter-spacing:0.06em;">{day}</span><br>
            <span style="font-size:16px;">{icon}</span>
          </div>
          <div style="flex:1;color:{P['sub']};font-size:12px;line-height:1.6;">
            {content}
          </div>
        </div>"""

    return f"""
<div style="background:{P['glass']};border:1px solid {P['border']};
     border-radius:10px;padding:16px;margin-top:2px;">
  <div style="color:{P['muted']};font-size:9px;font-weight:700;letter-spacing:0.12em;
       text-transform:uppercase;margin-bottom:2px;">Setup</div>
  <div style="color:{s['c']};font-size:13px;font-weight:600;margin-bottom:12px;">
    {setup_tip}
  </div>

  {day_row("GÜN 1", "🎯", P["blue2"],
    f'<b style="color:{P["text"]};">Giriş:</b> {rl.entry:.2f} ₺ (limit emir önerilir)<br>'
    f'{entry_note}<br>'
    f'<span style="color:{P["red"]};">Stop başlangıç: {rl.stop:.2f} ₺ (−{stop_pct:.1f}%)</span>'
  )}

  {day_row("GÜN 2–3", "👁", P["yellow"],
    f'<b style="color:{P["text"]};">Pozisyon yönetimi:</b><br>'
    f'{d2_d3_note}<br>'
    f'RSI: {ts.rsi:.1f} · ADX: {ts.adx:.1f} · Hacim: {ts.volume_ratio:.1f}x ort.'
  )}

  {day_row("GÜN 4–5", "✅", P["green2"],
    f'<b style="color:{P["green2"]};">Hedef 1: {rl.target1:.2f} ₺ (+{t1_pct:.1f}%)</b> — %50 pozisyonu kapat, stop\'u {rl.entry:.2f}\'e çek<br>'
    f'<b style="color:{P["green3"]};">Hedef 2: {rl.target2:.2f} ₺ (+{t2_pct:.1f}%)</b> — kalan pozisyonu kapat<br>'
    f'{exit_note}'
  )}

  <div style="margin-top:10px;padding:8px 12px;background:{P['surface']};
       border-radius:6px;color:{P['muted']};font-size:11px;line-height:1.6;">
    <b style="color:{P['sub']};">R/R:</b> {rl.rr_ratio:.1f}:1 ·
    <b style="color:{P['sub']};">Pozisyon:</b> {rl.position_size:,} lot ·
    <b style="color:{P['sub']};">Risk:</b> {format_tl(rl.risk_amount)} ·
    <b style="color:{P['sub']};">ATR(14):</b> {ts.atr:.3f}
  </div>
</div>"""


# ─── Trade kartı ──────────────────────────────────────────────────────────────

def _trade_card(sig: CombinedSignal, news_scores: Dict[str, float]) -> str:
    ts  = sig.tech_signal
    rl  = sig.risk_levels
    cls = sig.classification
    s   = sg(cls)

    pct = (ts.close - ts.prev_close) / ts.prev_close * 100 if ts.prev_close else 0.0
    pct_c = P["green"] if pct >= 0 else P["red"]

    # Seviye görsel bar
    level_bar = ""
    if rl:
        lo  = rl.stop   * 0.993
        hi  = rl.target2 * 1.007
        rng = hi - lo
        def ppos(v): return max(2, min(96, int((v - lo) / rng * 100)))
        sp  = ppos(rl.stop)
        ep  = ppos(rl.entry)
        t1p = ppos(rl.target1)
        t2p = ppos(rl.target2)

        level_bar = f"""
        <div style="position:relative;height:28px;background:{P['glass']};
             border-radius:6px;margin:12px 0 4px;border:1px solid {P['border']};">
          <div style="position:absolute;left:{sp}%;width:{ep-sp}%;height:100%;
               background:{P['red']}20;border-radius:6px 0 0 6px;"></div>
          <div style="position:absolute;left:{ep}%;width:{t1p-ep}%;height:100%;
               background:{P['green']}18;"></div>
          <div style="position:absolute;left:{t1p}%;width:{t2p-t1p}%;height:100%;
               background:{P['green2']}12;border-radius:0 6px 6px 0;"></div>
          {"".join([
            f'<div style="position:absolute;left:{x}%;top:15%;height:70%;width:2px;'
            f'background:{c};border-radius:1px;transform:translateX(-50%);"></div>'
            f'<div style="position:absolute;left:{x}%;bottom:-16px;font-size:9px;'
            f'color:{c};font-weight:700;transform:translateX(-50%);white-space:nowrap;">{lbl}</div>'
            for x, c, lbl in [
                (sp,  P["red"],    f"Stop {rl.stop:.2f}"),
                (ep,  P["text"],   f"Giriş {rl.entry:.2f}"),
                (t1p, P["green"],  f"T1 {rl.target1:.2f}"),
                (t2p, P["green2"], f"T2 {rl.target2:.2f}"),
            ]
          ])}
        </div>
        <div style="height:18px;"></div>"""

    # İndikatör satırı
    def ind(label: str, val: str, note: str = "", color: str = P["text"]) -> str:
        return (
            f'<div style="padding:8px 10px;border-right:1px solid {P["border"]};'
            f'min-width:70px;">'
            f'<div style="color:{P["muted"]};font-size:9px;letter-spacing:0.08em;'
            f'text-transform:uppercase;margin-bottom:2px;">{label}</div>'
            f'<div style="color:{color};font-size:14px;font-weight:700;">{val}</div>'
            f'{"<div style=color:" + P["sub"] + ";font-size:10px;>" + note + "</div>" if note else ""}'
            f'</div>'
        )

    mc = P["green"] if ts.macd_hist >= 0 else P["red"]
    ema21_c = P["green"] if ts.close > ts.ema21 > 0 else P["red"]
    ema50_c = P["green"] if ts.close > ts.ema50 > 0 else P["red"]
    ema200_c= P["green"] if ts.close > ts.ema200 > 0 else P["red"]

    trend_dir = ("↑ Bull" if ts.dip > ts.dim and ts.adx > 20 else
                 "↓ Bear" if ts.dim > ts.dip and ts.adx > 20 else "→ Yatay")
    trend_c = P["green"] if "Bull" in trend_dir else (P["red"] if "Bear" in trend_dir else P["sub"])

    bb_pos_str = ""
    if ts.bb_upper and ts.bb_lower and ts.close:
        rng = ts.bb_upper - ts.bb_lower
        if rng > 0:
            bb_pos_str = f"{(ts.close - ts.bb_lower) / rng * 100:.0f}%"

    ind_row1 = (
        ind("RSI 14", f"{ts.rsi:.1f}", "alım <30" if ts.rsi < 30 else ("sat >70" if ts.rsi > 70 else ""), rsi_color(ts.rsi)) +
        ind("ADX",    f"{ts.adx:.1f}", "güçlü >25", P["green"] if ts.adx > 25 else P["sub"]) +
        ind("DI+/DI−", f"{ts.dip:.0f}/{ts.dim:.0f}", trend_dir, trend_c) +
        ind("MACD",   f'{"+" if ts.macd_hist >= 0 else ""}{ts.macd_hist:.4f}', "hist", mc) +
        ind("Hacim",  f"{ts.volume_ratio:.1f}x", "20g ort.", P["cyan"] if ts.volume_ratio >= 1.5 else P["sub"]) +
        ind("Stoch K", f"{ts.stoch_k:.0f}", f"D:{ts.stoch_d:.0f}", P["red"] if ts.stoch_k > 80 else (P["green"] if ts.stoch_k < 20 else P["sub"]))
    )
    ind_row2 = (
        ind("EMA 21",  f"{ts.ema21:.2f}" if ts.ema21 else "—", f'{"▲ üstünde" if ts.close > ts.ema21 > 0 else "▼ altında"}', ema21_c) +
        ind("EMA 50",  f"{ts.ema50:.2f}" if ts.ema50 else "—", f'{"▲ üstünde" if ts.close > ts.ema50 > 0 else "▼ altında"}', ema50_c) +
        ind("EMA 200", f"{ts.ema200:.2f}" if ts.ema200 else "—", f'{"▲ üstünde" if ts.close > ts.ema200 > 0 else "▼ altında"}', ema200_c) +
        ind("BB Üst",  f"{ts.bb_upper:.2f}" if ts.bb_upper else "—", "direnç", P["sub"]) +
        ind("BB Alt",  f"{ts.bb_lower:.2f}" if ts.bb_lower else "—", "destek", P["sub"]) +
        ind("BB Pos.", bb_pos_str or "—", "bantta yer", P["yellow"] if bb_pos_str and int(bb_pos_str[:-1]) > 80 else P["sub"])
    )

    # Haberler
    sorted_news = sorted(
        sig.news_items,
        key=lambda cn: abs(news_scores.get(f"{cn.item.source}|{cn.item.title[:40]}", 0)),
        reverse=True,
    )[:5]
    news_html = ""
    for cn in sorted_news:
        ns = news_scores.get(f"{cn.item.source}|{cn.item.title[:40]}", 0.0)
        days = (now_istanbul() - cn.item.pub_date).days
        age  = "bugün" if days == 0 else f"{days}g"
        nc   = P["green"] if ns > 0 else (P["red"] if ns < 0 else P["sub"])
        url  = cn.item.url or "#"
        news_html += (
            f'<div style="padding:7px 0;border-bottom:1px solid {P["border"]};'
            f'display:flex;gap:10px;align-items:flex-start;">'
            f'<div style="min-width:38px;text-align:right;'
            f'color:{nc};font-size:11px;font-weight:700;padding-top:1px;">'
            f'{"+" if ns > 0 else ""}{ns:.0f}</div>'
            f'<div>'
            f'{source_badge(cn.item.source, cn.item.tier)}'
            f'<span style="color:{P["muted"]};font-size:10px;margin-left:6px;">{age}</span><br>'
            f'<a href="{url}" style="color:{P["text"]};font-size:12px;line-height:1.5;">'
            f'{cn.item.title[:90]}{"…" if len(cn.item.title) > 90 else ""}</a>'
            f'</div></div>'
        )
    if not news_html:
        news_html = f'<p style="color:{P["muted"]};font-size:12px;margin:0;">Son 7 günde ilgili haber yok.</p>'

    ai_html = ""
    if sig.ai_commentary:
        ai_html = (
            f'<div style="background:{P["indigo"]}12;border-left:3px solid {P["indigo"]};'
            f'border-radius:0 6px 6px 0;padding:10px 14px;margin-top:10px;">'
            f'<div style="color:{P["indigo"]};font-size:9px;font-weight:700;'
            f'letter-spacing:0.1em;margin-bottom:4px;">🤖 AI YORUM</div>'
            f'<div style="color:{P["text"]};font-size:12px;line-height:1.6;">'
            f'{sig.ai_commentary}</div></div>'
        )

    veto_html = ""
    if sig.is_vetoed:
        veto_html = (
            f'<div style="background:{P["red"]}12;border:1px solid {P["red"]}44;'
            f'border-radius:6px;padding:8px 14px;margin-top:10px;">'
            f'<b style="color:{P["red"]};">⛔ VETO</b> — '
            f'<span style="color:{P["text"]};font-size:12px;">{sig.veto_reason}</span>'
            f'</div>'
        )

    setups = ts.layers.layer3_setup.active_setups()
    setup_str = " · ".join(setups) if setups else "—"

    return f"""
<div style="background:{s['bg']};border:1px solid {s['bd']};
     border-radius:14px;overflow:hidden;margin-bottom:16px;">

  <!-- Kart üst şerit -->
  <div style="height:3px;background:linear-gradient(90deg,{s['c']},{s['c']}44);"></div>

  <!-- Başlık -->
  <div style="padding:16px 20px 12px;border-bottom:1px solid {P['border']};">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;
         flex-wrap:wrap;gap:10px;">
      <div>
        <span style="font-size:24px;font-weight:900;color:{P['text']};
            letter-spacing:-0.5px;">{sig.ticker}</span>
        <span style="color:{P['sub']};font-size:13px;margin-left:10px;">
          {sig.company_name}</span>
        <span style="color:{P['muted']};font-size:11px;"> · {sig.sector}</span>
        <div style="margin-top:5px;">
          {pill(f"{sg(cls)['e']} {cls}", s['c'], s['bg'], s['bd'])}
          <span style="color:{P['muted']};font-size:11px;margin-left:8px;">
            Setup: <b style="color:{s['c']};">{setup_str}</b></span>
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:30px;font-weight:900;color:{s['c']};
            letter-spacing:-1.5px;line-height:1;">{sig.total_score:.0f}</div>
        <div style="color:{P['text']};font-size:18px;font-weight:700;margin-top:2px;">
          {ts.close:.2f} ₺</div>
        <div style="color:{pct_c};font-size:13px;">
          {"+" if pct >= 0 else ""}{pct:.2f}%</div>
      </div>
    </div>
  </div>

  <!-- Skor şeridi -->
  <div style="padding:10px 20px;border-bottom:1px solid {P['border']};
       background:{P['glass']};display:flex;gap:20px;flex-wrap:wrap;">
    <div>
      <span style="color:{P['muted']};font-size:9px;letter-spacing:0.1em;">TEKNİK</span>
      <span style="color:{P['green']};font-size:15px;font-weight:700;margin-left:8px;">{sig.tech_score}</span>
      <span style="color:{P['muted']};font-size:11px;">/100</span>
    </div>
    <div>
      <span style="color:{P['muted']};font-size:9px;letter-spacing:0.1em;">HABER</span>
      <span style="color:{P['green'] if sig.news_score > 0 else P['red'] if sig.news_score < 0 else P['sub']};
          font-size:15px;font-weight:700;margin-left:8px;">
        {"+" if sig.news_score > 0 else ""}{sig.news_score:.1f}</span>
      <span style="color:{P['muted']};font-size:11px;margin-left:4px;">
        {sig.news_sentiment_label}</span>
    </div>
    <div>
      <span style="color:{P['muted']};font-size:9px;letter-spacing:0.1em;">LİKİDİTE</span>
      <span style="color:{P['cyan']};font-size:15px;font-weight:700;margin-left:8px;">{sig.liquidity_score}</span>
      <span style="color:{P['muted']};font-size:11px;">/20</span>
    </div>
  </div>

  <!-- Trade Planı -->
  <div style="padding:14px 20px;border-bottom:1px solid {P['border']};">
    <div style="color:{P['muted']};font-size:9px;font-weight:700;letter-spacing:0.12em;
         text-transform:uppercase;margin-bottom:8px;">5-Günlük Trade Planı</div>
    {level_bar}
    {_five_day_plan(sig)}
  </div>

  <!-- İndikatörler -->
  <div style="border-bottom:1px solid {P['border']};">
    <div style="color:{P['muted']};font-size:9px;font-weight:700;letter-spacing:0.12em;
         text-transform:uppercase;padding:10px 20px 4px;">İndikatörler</div>
    <div style="display:flex;flex-wrap:wrap;border-top:1px solid {P['border']};">
      {ind_row1}
    </div>
    <div style="display:flex;flex-wrap:wrap;border-top:1px solid {P['border']};">
      {ind_row2}
    </div>
    <div style="padding:6px 20px 10px;color:{P['muted']};font-size:11px;">
      ATR(14): <b style="color:{P['sub']};">{ts.atr:.3f}</b>
      {"  ·  EMA9: " + f'<b style="color:{P["sub"]};">{ts.ema9:.2f}</b>' if ts.ema9 else ""}
    </div>
  </div>

  <!-- Haberler -->
  <div style="padding:12px 20px;">
    <div style="color:{P['muted']};font-size:9px;font-weight:700;letter-spacing:0.12em;
         text-transform:uppercase;margin-bottom:8px;">Şirket Haberleri</div>
    {news_html}
    {ai_html}
    {veto_html}
    {"".join(f"<div style='color:{P['orange']};font-size:11px;margin-top:4px;'>⚠ {f}</div>" for f in sig.flags)}
  </div>

</div>"""


# ─── BIST30 Tam Tarama Tablosu ────────────────────────────────────────────────

def _full_table(ranked: Dict[str, List[CombinedSignal]]) -> str:
    order  = ["GÜÇLÜ AL","AL","ALIMA UYGUN","İZLE","NÖTR","ZAYIF","VETOLU"]
    all_s: List[CombinedSignal] = []
    for cls in order:
        all_s.extend(ranked.get(cls, []))

    rows = ""
    prev_cls = None
    for i, sig in enumerate(all_s):
        cls = sig.classification
        s   = sg(cls)
        ts  = sig.tech_signal

        if cls != prev_cls:
            rows += (
                f'<tr><td colspan="12" style="padding:5px 10px;background:{s["bg"]};'
                f'border-top:2px solid {s["bd"]};border-bottom:1px solid {s["bd"]}30;">'
                f'<span style="color:{s["c"]};font-size:11px;font-weight:700;">'
                f'{s["e"]} {cls}</span></td></tr>'
            )
            prev_cls = cls

        pct = (ts.close - ts.prev_close) / ts.prev_close * 100 if ts.prev_close else 0.0
        pct_c = P["green"] if pct >= 0 else P["red"]

        if sig.total_score >= 120: sc = P["green2"]
        elif sig.total_score >= 100: sc = P["green"]
        elif sig.total_score >= 80: sc = P["blue"]
        elif sig.total_score >= 60: sc = P["sub"]
        else: sc = P["red"]

        ema_dots = (
            f'<span style="color:{P["green"] if ts.close > ts.ema21 > 0 else P["red"]};">'
            f'●</span><span style="color:{P["green"] if ts.close > ts.ema50 > 0 else P["red"]};">'
            f'●</span><span style="color:{P["green"] if ts.close > ts.ema200 > 0 else P["red"]};">'
            f'●</span>'
        )

        setup_icons = (
            ('<span style="color:#f59e0b;font-size:10px;font-weight:700;">A</span> ' if ts.layers.layer3_setup.setup_a else '') +
            ('<span style="color:#3b82f6;font-size:10px;font-weight:700;">B</span> ' if ts.layers.layer3_setup.setup_b else '') +
            ('<span style="color:#8b5cf6;font-size:10px;font-weight:700;">C</span>'  if ts.layers.layer3_setup.setup_c else '')
        ) or '<span style="color:#3d5a7a;">—</span>'

        macd_c = P["green"] if ts.macd_hist > 0 else P["red"]
        vol_c  = P["cyan"]  if ts.volume_ratio >= 1.5 else P["sub"]
        row_bg = P["card"] if i % 2 == 0 else P["surface"]

        rows += f"""
        <tr style="background:{row_bg};border-bottom:1px solid {P['border']};">
          {td(f'<b style="color:{P["text"]};font-size:13px;">{sig.ticker}</b>', "left", "7px 10px")}
          {td(f'<span style="color:{P["sub"]};font-size:11px;">{sig.company_name[:17]}</span>', "left", "7px 8px")}
          {td(f'<span style="color:{sc};font-weight:800;font-size:14px;">{sig.total_score:.0f}</span>')}
          {td(f'<span style="color:{rsi_color(ts.rsi)};font-weight:600;">{ts.rsi:.0f}</span>')}
          {td(f'<span style="color:{P["green"] if ts.adx > 25 else P["sub"]};">{ts.adx:.0f}</span>')}
          {td(f'<span style="color:{macd_c};">{"▲" if ts.macd_hist > 0 else "▼"} {ts.macd_hist:+.3f}</span>')}
          {td(ema_dots, "center")}
          {td(f'<span style="color:{vol_c};">{ts.volume_ratio:.1f}x</span>')}
          {td(f'<b style="color:{P["text"]};">{ts.close:.2f} ₺</b>')}
          {td(f'<span style="color:{pct_c};">{"+" if pct >= 0 else ""}{pct:.1f}%</span>')}
          {td(f'<span style="color:{P["muted"]};font-size:11px;">{ts.atr:.2f}</span>')}
          {td(setup_icons, "center")}
        </tr>"""

    return f"""
<div style="overflow-x:auto;border-radius:12px;border:1px solid {P['border']};">
<table style="width:100%;border-collapse:collapse;min-width:700px;">
  <tr style="background:{P['card']};">
    {th("Hisse", "left")}{th("Şirket", "left")}
    {th("Skor")}{th("RSI")}{th("ADX")}
    {th("MACD ▲▼", "center")}{th("EMA 21·50·200", "center")}
    {th("Hacim")}{th("Fiyat")}{th("Değ%")}
    {th("ATR")}{th("Setup", "center")}
  </tr>
  {rows}
</table>
</div>"""


# ─── Kılavuz ─────────────────────────────────────────────────────────────────

def _guide() -> str:
    rows_data = [
        ("⭐ GÜÇLÜ AL",    "140–170", "%1.5", "Tüm katman ve setup'lar geçti. Tam pozisyon.", P["green2"], "#022c22"),
        ("🟢 AL",          "120–139", "%1.0", "Güçlü setup + trigger aktif. Normal pozisyon.",P["green"],  "#011f17"),
        ("🟡 ALIMA UYGUN", "100–119", "%0.5", "Sinyal var, eksik katman. Yarım pozisyon.",    P["yellow"], "#1c1000"),
        ("🔵 İZLE",        "80–99",   "—",    "Olgunlaşmamış, kırılım bekleniyor.",           P["blue"],   "#0a1628"),
        ("⚪ NÖTR",        "60–79",   "—",    "Yön belirsiz. Bekle.",                         P["sub"],    "#0d1526"),
        ("🔴 ZAYIF",       "<60",     "—",    "Setup yok. Trend aleyhte.",                    P["red"],    "#1a0505"),
        ("⛔ VETOLU",      "—",       "—",    "Haber veya piyasa veto kuralı devrede.",       "#dc2626",   "#150303"),
    ]
    trs = "".join(f"""
    <tr style="background:{bg};">
      <td style="padding:7px 12px;color:{c};font-weight:700;font-size:13px;
          border-bottom:1px solid {P['border']};">{lbl}</td>
      <td style="padding:7px 12px;color:{P['text']};font-size:12px;
          border-bottom:1px solid {P['border']};text-align:center;">{skor}</td>
      <td style="padding:7px 12px;color:{c};font-size:12px;font-weight:700;
          border-bottom:1px solid {P['border']};text-align:center;">{risk}</td>
      <td style="padding:7px 12px;color:{P['sub']};font-size:12px;
          border-bottom:1px solid {P['border']};">{desc}</td>
    </tr>"""
    for lbl, skor, risk, desc, c, bg in rows_data)

    params = f"""
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));
         gap:10px;margin-top:12px;">
      {"".join([
        f'<div style="background:{P["card"]};border:1px solid {P["border"]};'
        f'border-radius:8px;padding:12px;">'
        f'<div style="color:{hdr_c};font-size:9px;font-weight:700;letter-spacing:0.1em;'
        f'text-transform:uppercase;margin-bottom:8px;">{title}</div>'
        f'<div style="color:{P["sub"]};font-size:11px;line-height:1.8;">{body}</div>'
        f'</div>'
        for title, hdr_c, body in [
          ("Teknik Skor 0–100", P["green"],
           "Setup A: EMA21 Pullback<br>Setup B: BB Squeeze Kırılımı<br>Setup C: RSI Diverjans<br>"
           "ADX > 25 güçlü trend<br>Hacim 1.5x+ tetikleyici<br>EMA hizalaması 9&gt;21&gt;50"),
          ("Haber Skoru −50/+50", P["blue"],
           f'<span style="color:{P["green"]};">+25</span> Bilanço pozitif sürpriz<br>'
           f'<span style="color:{P["green"]};">+20</span> Yeni sözleşme/ihale<br>'
           f'<span style="color:{P["green"]};">+15</span> Geri alım / yabancı alım<br>'
           f'<span style="color:{P["red"]};">  −30</span> SPK soruşturması<br>'
           f'<span style="color:{P["red"]};">  −25</span> Bilanço neg. sürpriz<br>'
           f'KAP×1.0 · BB×0.8 · Diğer×0.5'),
          ("Likidite Skoru 0–20", P["orange"],
           "+10 Hacim &gt;250M TL/gün<br>+5 Hacim &gt;100M TL/gün<br>+10 Piyasa değeri &gt;5B TL<br><br>"
           f'<b style="color:{P["text"]};">Toplam = Teknik + Haber + Likidite</b>'),
          ("ATR Risk Formülü", P["purple"],
           "Giriş = Kapanış × 1.005<br>Stop = Giriş − 2×ATR<br>T1 = Giriş + 2×ATR → ½ çık<br>"
           "T2 = Giriş + 4×ATR → kalan çık<br>Stop'u T1'de girişe çek<br>Baz portföy: 100.000 ₺"),
        ]
      ])}
    </div>"""

    return f"""
<div style="background:{P['surface']};border:1px solid {P['border']};
     border-radius:12px;overflow:hidden;">
  <div style="padding:12px 16px;border-bottom:1px solid {P['border']};">
    <span style="color:{P['text']};font-size:14px;font-weight:700;">📖 Sinyal Kılavuzu & Parametreler</span>
  </div>
  <table style="width:100%;border-collapse:collapse;">
    <tr style="background:{P['card']};">
      {th("Sinyal", "left")}{th("Skor","center")}{th("Risk %","center")}{th("Açıklama","left")}
    </tr>
    {trs}
  </table>
  <div style="padding:14px 16px;">{params}</div>
</div>"""


# ─── Ana build fonksiyonu ─────────────────────────────────────────────────────

def build_html_email(
    signals: List[CombinedSignal],
    market_regime: dict,
    usdtry: Optional[float],
    news_scores_map: Dict[str, float],
    all_classified_news: Optional[List[ClassifiedNews]] = None,
    sentiment_by_ticker: Optional[Dict[str, Any]] = None,
    weekly_perf: Optional[dict] = None,
    is_monday: bool = False,
) -> str:
    now    = now_istanbul()
    ranked = rank_signals(signals)

    strong = ranked["GÜÇLÜ AL"]
    buy    = ranked["AL"]
    suit   = ranked["ALIMA UYGUN"]
    watch  = ranked["İZLE"]
    card_sigs = strong + buy + suit + watch

    # Trade kartları
    if card_sigs:
        cards_html = "".join(_trade_card(s, news_scores_map) for s in card_sigs)
    else:
        cards_html = (
            f'<div style="background:{P["surface"]};border:1px solid {P["border"]};'
            f'border-radius:10px;padding:28px;text-align:center;'
            f'color:{P["muted"]};font-size:14px;margin-bottom:16px;">'
            f'Bugün aksiyon alınabilir setup yok. Tam tarama tablosuna bak ↓'
            f'</div>'
        )

    # Haber akışı
    news_feed_html = ""
    if all_classified_news:
        news_feed_html = _news_feed(all_classified_news, news_scores_map, sentiment_by_ticker or {})

    # Performans (Pazartesi)
    perf_html = ""
    if is_monday and weekly_perf:
        p  = weekly_perf
        wr = p.get("win_rate", 0)
        ar = p.get("avg_return", 0)
        def stat2(v, lbl, c):
            return (f'<div style="text-align:center;padding:0 10px;">'
                    f'<div style="color:{P["muted"]};font-size:9px;letter-spacing:0.1em;'
                    f'text-transform:uppercase;">{lbl}</div>'
                    f'<div style="color:{c};font-size:22px;font-weight:800;">{v}</div></div>')
        perf_html = (
            sep("Geçen Hafta Performansı") +
            f'<div style="background:{P["surface"]};border:1px solid {P["border"]};'
            f'border-radius:10px;padding:16px;display:flex;flex-wrap:wrap;'
            f'justify-content:center;gap:8px;">'
            + stat2(p.get("total_signals",0), "Toplam", P["text"])
            + stat2(p.get("t1_hits",0), "T1 İsabet", P["green"])
            + stat2(p.get("t2_hits",0), "T2 İsabet", P["green2"])
            + stat2(p.get("stop_hits",0), "Stop", P["red"])
            + stat2(f"%{wr:.1f}", "Kazanma", P["green"] if wr >= 50 else P["red"])
            + stat2(f"{ar:+.2f}%", "Ort. Getiri", P["green"] if ar >= 0 else P["red"])
            + '</div>'
        )

    n_cards = len(card_sigs)

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BIST30 · {now.strftime('%d.%m.%Y')}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:{P['bg']};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
       Roboto,system-ui,sans-serif;color:{P['text']};-webkit-font-smoothing:antialiased;}}
  a{{color:{P['blue2']};text-decoration:none;}}
  a:hover{{text-decoration:underline;}}
</style>
</head>
<body>
<div style="max-width:920px;margin:0 auto;padding:16px 12px 40px;">

  {_hero(now, signals, ranked, market_regime, usdtry)}

  {sep(f"Trade Planları · {n_cards} Hisse")}
  {cards_html}

  {sep(f"Piyasa Haber Akışı")}
  {news_feed_html if news_feed_html else f'<div style="color:{P["muted"]};text-align:center;padding:16px;">Haber çekilemedi.</div>'}

  {sep(f"BIST30 Tam Tarama · {len(signals)} Hisse")}
  {_full_table(ranked)}

  {perf_html}

  {sep("Sinyal Kılavuzu")}
  {_guide()}

  <div style="margin-top:28px;padding-top:16px;border-top:1px solid {P['border']};
       text-align:center;">
    <p style="color:{P['muted']};font-size:10px;line-height:1.9;">
      ⚠ Bu rapor <b>yatırım tavsiyesi değildir</b>. Yalnızca eğitim ve araştırma amaçlıdır.<br>
      Her sinyali kendi analizinizle doğrulayın. Stop seviyelerine kesinlikle uyun.<br>
      Sonraki tarama: <b style="color:{P['sub']};">Yarın 09:00 İstanbul (iş günü ise)</b>
      · BIST30-Signal v4.0
    </p>
  </div>

</div>
</body>
</html>"""


# ─── Resend gönderme ──────────────────────────────────────────────────────────

def send_email(
    html_body: str,
    subject: str,
    from_addr: str,
    to_addr: str,
    api_key: str,
) -> bool:
    cfg = MAIL_CONFIG
    resend.api_key = api_key
    for attempt in range(1, cfg["retry_count"] + 1):
        try:
            resend.Emails.send({"from": from_addr, "to": [to_addr],
                                "subject": subject, "html": html_body})
            logger.info("Mail gönderildi → %s", to_addr)
            return True
        except Exception as exc:
            if attempt < cfg["retry_count"]:
                logger.warning("Mail gönderilemedi (%d. deneme): %s, %ds bekleniyor",
                               attempt, exc, cfg["retry_delay"])
                time.sleep(cfg["retry_delay"])
            else:
                logger.error("Mail 3 denemede gönderilemedi: %s", exc)
    return False
