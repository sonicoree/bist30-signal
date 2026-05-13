"""
mailer.py — BIST30 5-Günlük Swing Trading Mail Raporu
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import resend

from config import MAIL_CONFIG, SIGNAL_CLASSES
from news_classifier import ClassifiedNews
from scorer import CombinedSignal, rank_signals
from utils import format_tl, logger, now_istanbul

# ─── Palet ───────────────────────────────────────────────────────────────────

C = {
    "bg":      "#0a0e17",
    "surface": "#111827",
    "card":    "#131c2e",
    "border":  "#1e2d45",
    "dim":     "#2a3a52",
    "text":    "#e2e8f0",
    "sub":     "#94a3b8",
    "muted":   "#4a6080",
    "green":   "#22c55e",
    "green2":  "#4ade80",
    "red":     "#ef4444",
    "yellow":  "#eab308",
    "blue":    "#3b82f6",
    "cyan":    "#06b6d4",
    "purple":  "#8b5cf6",
    "orange":  "#f97316",
    "teal":    "#14b8a6",
}

SIG = {
    "GÜÇLÜ AL":    {"color": "#4ade80", "bg": "#052e16", "ring": "#166534", "emoji": "⭐"},
    "AL":          {"color": "#22c55e", "bg": "#031f0e", "ring": "#14532d", "emoji": "🟢"},
    "ALIMA UYGUN": {"color": "#eab308", "bg": "#1c1400", "ring": "#713f12", "emoji": "🟡"},
    "İZLE":        {"color": "#3b82f6", "bg": "#0c1a35", "ring": "#1e3a8a", "emoji": "🔵"},
    "NÖTR":        {"color": "#64748b", "bg": "#0f172a", "ring": "#1e293b", "emoji": "⚪"},
    "ZAYIF":       {"color": "#ef4444", "bg": "#1c0000", "ring": "#7f1d1d", "emoji": "🔴"},
    "VETOLU":      {"color": "#dc2626", "bg": "#1a0000", "ring": "#991b1b", "emoji": "⛔"},
}


def _s(sig_cls: str) -> dict:
    return SIG.get(sig_cls, SIG["NÖTR"])


# ─── Küçük bileşenler ─────────────────────────────────────────────────────────

def _pill(text: str, cls: str) -> str:
    s = _s(cls)
    return (
        f'<span style="display:inline-block;background:{s["bg"]};color:{s["color"]};'
        f'border:1px solid {s["ring"]};border-radius:999px;'
        f'padding:2px 10px;font-size:11px;font-weight:600;white-space:nowrap;">'
        f'{s["emoji"]} {text}</span>'
    )


def _kpi(label: str, value: str, color: str = "") -> str:
    vc = color or C["text"]
    return (
        f'<div style="text-align:center;">'
        f'<div style="color:{C["sub"]};font-size:10px;letter-spacing:0.08em;'
        f'text-transform:uppercase;margin-bottom:3px;">{label}</div>'
        f'<div style="color:{vc};font-size:20px;font-weight:700;'
        f'letter-spacing:-0.03em;line-height:1;">{value}</div>'
        f'</div>'
    )


def _mini_bar(val: float, lo: float, hi: float, color: str, w: int = 80) -> str:
    pct = max(0.0, min(1.0, (val - lo) / (hi - lo))) if hi > lo else 0.0
    fill = int(w * pct)
    return (
        f'<div style="display:inline-block;vertical-align:middle;'
        f'width:{w}px;height:5px;background:{C["dim"]};border-radius:3px;">'
        f'<div style="width:{fill}px;height:5px;background:{color};border-radius:3px;"></div>'
        f'</div>'
    )


def _ind_cell(label: str, val: str, note: str = "", color: str = "") -> str:
    vc = color or C["text"]
    return (
        f'<td style="padding:8px 12px;border-right:1px solid {C["border"]};">'
        f'<div style="color:{C["muted"]};font-size:9px;letter-spacing:0.08em;'
        f'text-transform:uppercase;margin-bottom:2px;">{label}</div>'
        f'<div style="color:{vc};font-size:14px;font-weight:600;">{val}</div>'
        f'{"<div style=color:" + C["sub"] + ";font-size:10px;>" + note + "</div>" if note else ""}'
        f'</td>'
    )


def _divider(label: str) -> str:
    return (
        f'<div style="display:flex;align-items:center;gap:10px;margin:24px 0 14px;">'
        f'<div style="flex:1;height:1px;background:{C["border"]};"></div>'
        f'<span style="color:{C["muted"]};font-size:10px;letter-spacing:0.12em;'
        f'text-transform:uppercase;white-space:nowrap;">{label}</span>'
        f'<div style="flex:1;height:1px;background:{C["border"]};"></div>'
        f'</div>'
    )


# ─── Trade Planı Kartı ────────────────────────────────────────────────────────

def _trade_card(sig: CombinedSignal, news_scores: Dict[str, float]) -> str:
    ts   = sig.tech_signal
    rl   = sig.risk_levels
    cls  = sig.classification
    s    = _s(cls)

    pct  = (ts.close - ts.prev_close) / ts.prev_close * 100 if ts.prev_close else 0.0
    pct_color = C["green"] if pct >= 0 else C["red"]
    pct_str   = f'{"+" if pct >= 0 else ""}{pct:.2f}%'

    # Aktif setup'lar
    setups = sig.tech_signal.layers.layer3_setup.active_setups()
    setup_str = " · ".join(setups) if setups else "—"

    # MACD yönü
    macd_color = C["green"] if ts.macd_hist >= 0 else C["red"]
    macd_str   = f'{"+" if ts.macd_hist >= 0 else ""}{ts.macd_hist:.3f}'

    # RSI rengi
    rsi_color = (C["red"] if ts.rsi > 70 else
                 C["green"] if ts.rsi < 30 else
                 C["yellow"] if 45 <= ts.rsi <= 65 else C["text"])

    # ADX trendi
    adx_color  = C["green"] if ts.adx > 25 else C["sub"]
    trend_str  = "Güçlü ↑" if (ts.dip > ts.dim and ts.adx > 20) else \
                 "Güçlü ↓" if (ts.dim > ts.dip and ts.adx > 20) else "Yatay"
    trend_col  = C["green"] if "↑" in trend_str else (C["red"] if "↓" in trend_str else C["sub"])

    # Stoch durumu
    stoch_str  = f'{ts.stoch_k:.0f} / {ts.stoch_d:.0f}' if ts.stoch_k else "—"
    stoch_col  = C["red"] if ts.stoch_k > 80 else (C["green"] if ts.stoch_k < 20 else C["sub"])

    # BB durumu
    bb_pos = ""
    if ts.bb_upper and ts.bb_lower and ts.close:
        bb_range = ts.bb_upper - ts.bb_lower
        if bb_range > 0:
            bb_pct = (ts.close - ts.bb_lower) / bb_range * 100
            bb_pos = f'{bb_pct:.0f}%'

    # EMA konumu
    ema_lines = []
    if ts.ema21:
        rel = (ts.close - ts.ema21) / ts.ema21 * 100
        ema_lines.append(f'EMA21 {ts.ema21:.2f} ({rel:+.1f}%)')
    if ts.ema50:
        rel = (ts.close - ts.ema50) / ts.ema50 * 100
        ema_lines.append(f'EMA50 {ts.ema50:.2f} ({rel:+.1f}%)')
    if ts.ema200:
        rel = (ts.close - ts.ema200) / ts.ema200 * 100
        ema_lines.append(f'EMA200 {ts.ema200:.2f} ({rel:+.1f}%)')
    ema_str = " · ".join(ema_lines) if ema_lines else "—"

    # Risk tablosu
    if rl:
        risk_html = f"""
        <table style="width:100%;border-collapse:collapse;margin-top:2px;">
          <tr>
            <td style="padding:0 14px 0 0;">
              <div style="color:{C['muted']};font-size:9px;letter-spacing:0.08em;
                   text-transform:uppercase;">Giriş</div>
              <div style="color:{C['text']};font-size:16px;font-weight:700;">
                {rl.entry:.2f} ₺</div>
            </td>
            <td style="padding:0 14px 0 0;">
              <div style="color:{C['muted']};font-size:9px;letter-spacing:0.08em;
                   text-transform:uppercase;">Stop</div>
              <div style="color:{C['red']};font-size:16px;font-weight:700;">
                {rl.stop:.2f} ₺</div>
              <div style="color:{C['sub']};font-size:10px;">
                -{((rl.entry - rl.stop) / rl.entry * 100):.1f}%</div>
            </td>
            <td style="padding:0 14px 0 0;">
              <div style="color:{C['muted']};font-size:9px;letter-spacing:0.08em;
                   text-transform:uppercase;">Hedef 1</div>
              <div style="color:{C['green']};font-size:16px;font-weight:700;">
                {rl.target1:.2f} ₺</div>
              <div style="color:{C['sub']};font-size:10px;">
                +{((rl.target1 - rl.entry) / rl.entry * 100):.1f}% · ½ çık</div>
            </td>
            <td style="padding:0 14px 0 0;">
              <div style="color:{C['muted']};font-size:9px;letter-spacing:0.08em;
                   text-transform:uppercase;">Hedef 2</div>
              <div style="color:{C['green2']};font-size:16px;font-weight:700;">
                {rl.target2:.2f} ₺</div>
              <div style="color:{C['sub']};font-size:10px;">
                +{((rl.target2 - rl.entry) / rl.entry * 100):.1f}% · kalan çık</div>
            </td>
            <td style="padding:0 16px 0 0;">
              <div style="color:{C['muted']};font-size:9px;letter-spacing:0.08em;
                   text-transform:uppercase;">R / R</div>
              <div style="color:{C['cyan']};font-size:16px;font-weight:700;">
                {rl.rr_ratio:.1f}:1</div>
            </td>
            <td>
              <div style="color:{C['muted']};font-size:9px;letter-spacing:0.08em;
                   text-transform:uppercase;">Pozisyon</div>
              <div style="color:{C['text']};font-size:13px;font-weight:600;">
                {rl.position_size:,} lot</div>
              <div style="color:{C['sub']};font-size:10px;">
                Risk: {format_tl(rl.risk_amount)}</div>
            </td>
          </tr>
        </table>"""

        # Vizüel seviye çizgisi
        lo   = rl.stop * 0.995
        hi   = rl.target2 * 1.005
        rng  = hi - lo
        s_pct  = int((rl.stop    - lo) / rng * 100)
        e_pct  = int((rl.entry   - lo) / rng * 100)
        t1_pct = int((rl.target1 - lo) / rng * 100)
        t2_pct = int((rl.target2 - lo) / rng * 100)

        level_bar = f"""
        <div style="position:relative;height:24px;background:{C['dim']};
             border-radius:4px;margin-top:10px;overflow:hidden;">
          <div style="position:absolute;left:{s_pct}%;width:{e_pct - s_pct}%;
               height:100%;background:{C['red']}22;"></div>
          <div style="position:absolute;left:{e_pct}%;width:{t1_pct - e_pct}%;
               height:100%;background:{C['green']}33;"></div>
          <div style="position:absolute;left:{t1_pct}%;width:{t2_pct - t1_pct}%;
               height:100%;background:{C['green2']}22;"></div>
          <div style="position:absolute;left:{s_pct}%;top:50%;transform:translate(-50%,-50%);
               width:2px;height:70%;background:{C['red']};border-radius:1px;"></div>
          <div style="position:absolute;left:{e_pct}%;top:50%;transform:translate(-50%,-50%);
               width:3px;height:90%;background:{C['text']};border-radius:1px;"></div>
          <div style="position:absolute;left:{t1_pct}%;top:50%;transform:translate(-50%,-50%);
               width:2px;height:70%;background:{C['green']};border-radius:1px;"></div>
          <div style="position:absolute;left:{t2_pct}%;top:50%;transform:translate(-50%,-50%);
               width:2px;height:70%;background:{C['green2']};border-radius:1px;"></div>
          <div style="position:absolute;left:4px;top:50%;transform:translateY(-50%);
               color:{C['red']};font-size:9px;font-weight:700;">STOP</div>
          <div style="position:absolute;left:{e_pct + 1}%;top:50%;transform:translateY(-50%);
               color:{C['text']};font-size:9px;font-weight:700;">GİRİŞ</div>
          <div style="position:absolute;left:{t1_pct + 1}%;top:50%;transform:translateY(-50%);
               color:{C['green']};font-size:9px;font-weight:700;">T1</div>
          <div style="position:absolute;left:{min(t2_pct + 1, 78)}%;top:50%;
               transform:translateY(-50%);color:{C['green2']};font-size:9px;
               font-weight:700;">T2</div>
        </div>"""
    else:
        risk_html  = f'<p style="color:{C["sub"]};font-size:12px;">Risk seviyeleri hesaplanamadı.</p>'
        level_bar  = ""

    # Haberler
    news_rows = ""
    sorted_news = sorted(
        sig.news_items,
        key=lambda cn: abs(news_scores.get(f"{cn.item.source}|{cn.item.title[:40]}", 0)),
        reverse=True,
    )[:4]
    for cn in sorted_news:
        ns = news_scores.get(f"{cn.item.source}|{cn.item.title[:40]}", 0.0)
        days = (now_istanbul() - cn.item.pub_date).days
        age  = "bugün" if days == 0 else f"{days}g"
        nc   = C["green"] if ns > 0 else (C["red"] if ns < 0 else C["sub"])
        url  = cn.item.url or "#"
        news_rows += (
            f'<div style="display:flex;align-items:flex-start;gap:8px;'
            f'padding:6px 0;border-bottom:1px solid {C["border"]};">'
            f'<span style="color:{nc};font-size:11px;font-weight:700;'
            f'min-width:36px;text-align:right;">{"+" if ns > 0 else ""}{ns:.0f}</span>'
            f'<div>'
            f'<span style="color:{C["muted"]};font-size:10px;">{cn.item.source} · {age}</span><br>'
            f'<a href="{url}" style="color:{C["text"]};font-size:12px;line-height:1.4;">'
            f'{cn.item.title[:85]}{"…" if len(cn.item.title) > 85 else ""}</a>'
            f'</div></div>'
        )

    news_section = news_rows or f'<p style="color:{C["muted"]};font-size:12px;margin:0;">Son 7 günde ilgili haber yok.</p>'

    # AI yorum
    ai_html = ""
    if sig.ai_commentary:
        ai_html = (
            f'<div style="background:{C["card"]};border-left:3px solid {C["blue"]};'
            f'border-radius:0 6px 6px 0;padding:10px 14px;margin-top:10px;">'
            f'<div style="color:{C["blue"]};font-size:10px;font-weight:700;'
            f'letter-spacing:0.08em;margin-bottom:4px;">🤖 AI YORUM</div>'
            f'<div style="color:{C["text"]};font-size:12px;line-height:1.6;">'
            f'{sig.ai_commentary}</div></div>'
        )

    # Veto banner
    veto_html = ""
    if sig.is_vetoed:
        bc = C["red"]
        veto_html = (
            f'<div style="background:{bc}15;border:1px solid {bc}55;'
            f'border-radius:6px;padding:8px 14px;margin-top:10px;">'
            f'<b style="color:{bc};">⛔ VETOLU</b> — '
            f'<span style="color:{C["text"]};font-size:12px;">{sig.veto_reason}</span>'
            f'</div>'
        )

    # Flags
    flags_html = ""
    if sig.flags:
        flags_html = (
            f'<div style="background:{C["orange"]}10;border:1px solid {C["orange"]}33;'
            f'border-radius:6px;padding:8px 14px;margin-top:8px;">'
            + "".join(
                f'<div style="color:{C["orange"]};font-size:11px;">⚠ {f}</div>'
                for f in sig.flags
            ) + '</div>'
        )

    return f"""
<div style="background:{s['bg']};border:1px solid {s['ring']};
     border-radius:12px;overflow:hidden;margin-bottom:16px;">

  <!-- Kart Başlığı -->
  <div style="padding:16px 20px 12px;border-bottom:1px solid {s['ring']}30;">
    <div style="display:flex;justify-content:space-between;
         align-items:flex-start;flex-wrap:wrap;gap:8px;">
      <div>
        <span style="font-size:22px;font-weight:800;color:{C['text']};
            letter-spacing:-0.5px;">{sig.ticker}</span>
        <span style="color:{C['sub']};font-size:13px;margin-left:8px;">
          {sig.company_name}</span>
        <span style="color:{C['muted']};font-size:11px;margin-left:6px;">
          · {sig.sector}</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px;">
        {_pill(cls, cls)}
        <span style="font-size:26px;font-weight:800;color:{s['color']};
            letter-spacing:-1px;">{sig.total_score:.0f}</span>
        <div style="text-align:right;">
          <div style="color:{C['text']};font-size:16px;font-weight:700;">
            {ts.close:.2f} ₺</div>
          <div style="color:{pct_color};font-size:12px;">{pct_str}</div>
        </div>
      </div>
    </div>
    <div style="margin-top:8px;color:{C['sub']};font-size:11px;">
      📐 Setup: <b style="color:{s['color']};">{setup_str}</b>
      {"  ·  " + "<b style='color:" + C['red'] + ";'>⛔ " + sig.veto_reason[:60] + "</b>" if sig.is_vetoed else ""}
    </div>
  </div>

  <!-- Trade Planı -->
  <div style="padding:14px 20px;border-bottom:1px solid {C['border']};">
    <div style="color:{C['muted']};font-size:9px;letter-spacing:0.1em;
         text-transform:uppercase;margin-bottom:8px;">Trade Planı · 5 Günlük Swing</div>
    {risk_html}
    {level_bar}
  </div>

  <!-- İndikatörler -->
  <div style="border-bottom:1px solid {C['border']};">
    <div style="color:{C['muted']};font-size:9px;letter-spacing:0.1em;
         text-transform:uppercase;padding:10px 20px 6px;">İndikatörler</div>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="border-bottom:1px solid {C['border']};">
        {_ind_cell("RSI 14", f"{ts.rsi:.1f}", "Aşırı sat<30 / alım>70", rsi_color)}
        {_ind_cell("ADX", f"{ts.adx:.1f}", "Trend güçlü >25", adx_color)}
        {_ind_cell("DI+ / DI−", f"{ts.dip:.1f} / {ts.dim:.1f}", trend_str, trend_col)}
        {_ind_cell("MACD Hist", macd_str, "Momentum yönü", macd_color)}
        {_ind_cell("Hacim", f"{ts.volume_ratio:.1f}x", "20g ortalaması", C['cyan'] if ts.volume_ratio >= 1.5 else C['sub'])}
        {_ind_cell("Stoch K/D", stoch_str, "Aşırı sat<20", stoch_col)}
      </tr>
      <tr>
        {_ind_cell("EMA 21", f"{ts.ema21:.2f}" if ts.ema21 else "—", f'{"▲ üstünde" if ts.close > ts.ema21 > 0 else "▼ altında"}', C['green'] if ts.close > ts.ema21 > 0 else C['red'])}
        {_ind_cell("EMA 50", f"{ts.ema50:.2f}" if ts.ema50 else "—", f'{"▲ üstünde" if ts.close > ts.ema50 > 0 else "▼ altında"}', C['green'] if ts.close > ts.ema50 > 0 else C['red'])}
        {_ind_cell("EMA 200", f"{ts.ema200:.2f}" if ts.ema200 else "—", f'{"▲ üstünde" if ts.close > ts.ema200 > 0 else "▼ altında"}', C['green'] if ts.close > ts.ema200 > 0 else C['red'])}
        {_ind_cell("BB Üst", f"{ts.bb_upper:.2f}" if ts.bb_upper else "—", "Direnç", C['sub'])}
        {_ind_cell("BB Alt", f"{ts.bb_lower:.2f}" if ts.bb_lower else "—", "Destek", C['sub'])}
        {_ind_cell("BB Pozisyon", bb_pos or "—", "Bantta yer", C['yellow'] if bb_pos and int(bb_pos[:-1]) > 80 else C['sub'])}
      </tr>
    </table>
    <div style="padding:6px 20px 10px;color:{C['muted']};font-size:11px;">
      {ema_str} · ATR(14): {ts.atr:.3f}
    </div>
  </div>

  <!-- Haberler -->
  <div style="padding:12px 20px;">
    <div style="color:{C['muted']};font-size:9px;letter-spacing:0.1em;
         text-transform:uppercase;margin-bottom:8px;">
      Haberler
      <span style="color:{'#22c55e' if sig.news_score > 0 else '#ef4444' if sig.news_score < 0 else C['muted']};
          margin-left:6px;font-size:11px;font-weight:700;">
        {sig.news_sentiment_label} ({sig.news_score:+.1f})</span>
    </div>
    {news_section}
    {ai_html}
  </div>

  {('<div style="padding:0 20px 12px;">' + flags_html + veto_html + '</div>') if (flags_html or veto_html) else ''}
</div>"""


# ─── BIST30 Tam Tarama Tablosu ────────────────────────────────────────────────

def _full_table(ranked: Dict[str, List[CombinedSignal]]) -> str:
    order = ["GÜÇLÜ AL", "AL", "ALIMA UYGUN", "İZLE", "NÖTR", "ZAYIF", "VETOLU"]
    all_sigs: List[CombinedSignal] = []
    for cls in order:
        all_sigs.extend(ranked.get(cls, []))

    rows = ""
    prev_cls = None
    for i, sig in enumerate(all_sigs):
        cls   = sig.classification
        s     = _s(cls)
        ts    = sig.tech_signal

        if cls != prev_cls:
            rows += f"""
            <tr>
              <td colspan="12" style="padding:6px 12px;background:{s['bg']};
                  border-top:2px solid {s['ring']};border-bottom:1px solid {s['ring']}30;">
                <span style="color:{s['color']};font-size:11px;font-weight:700;
                    letter-spacing:0.05em;">{s['emoji']} {cls}</span>
              </td>
            </tr>"""
            prev_cls = cls

        pct = (ts.close - ts.prev_close) / ts.prev_close * 100 if ts.prev_close else 0.0
        pct_c = C["green"] if pct >= 0 else C["red"]

        # Skor rengi
        sc = (C["green2"] if sig.total_score >= 120 else
              C["green"]  if sig.total_score >= 100 else
              C["blue"]   if sig.total_score >= 80  else
              C["sub"]    if sig.total_score >= 60  else C["red"])

        # MACD oku
        macd_arrow = "▲" if ts.macd_hist > 0 else "▼"
        macd_c = C["green"] if ts.macd_hist > 0 else C["red"]

        # EMA trend
        above_21  = ts.close > ts.ema21  > 0
        above_50  = ts.close > ts.ema50  > 0
        above_200 = ts.close > ts.ema200 > 0
        ema_dots  = (
            f'<span style="color:{C["green"] if above_21  else C["red"]};">●</span>'
            f'<span style="color:{C["green"] if above_50  else C["red"]};">●</span>'
            f'<span style="color:{C["green"] if above_200 else C["red"]};">●</span>'
        )

        # RSI rengi
        rsi_c = (C["red"]    if ts.rsi > 70 else
                 C["green"]  if ts.rsi < 30 else
                 C["yellow"] if 40 <= ts.rsi <= 60 else C["sub"])

        # ADX rengi
        adx_c = C["green"] if ts.adx > 25 else C["sub"]

        # Hacim
        vol_c = C["cyan"] if ts.volume_ratio >= 1.5 else C["sub"]

        # Setup ikonları
        setups_active = sig.tech_signal.layers.layer3_setup.active_setups()
        setup_icons = ""
        if sig.tech_signal.layers.layer3_setup.setup_a:
            setup_icons += '<span title="Setup A: EMA21 Pullback" style="color:#eab308;font-size:10px;">A</span> '
        if sig.tech_signal.layers.layer3_setup.setup_b:
            setup_icons += '<span title="Setup B: BB Squeeze" style="color:#3b82f6;font-size:10px;">B</span> '
        if sig.tech_signal.layers.layer3_setup.setup_c:
            setup_icons += '<span title="Setup C: RSI Diverjans" style="color:#8b5cf6;font-size:10px;">C</span> '

        rows += f"""
        <tr style="background:{'#0d1520' if i % 2 == 0 else C['surface']};
             border-bottom:1px solid {C['border']};">
          <td style="padding:7px 10px;font-weight:700;color:{C['text']};
              font-size:13px;white-space:nowrap;">{sig.ticker}</td>
          <td style="padding:7px 8px;color:{C['sub']};font-size:11px;
              max-width:120px;overflow:hidden;white-space:nowrap;
              text-overflow:ellipsis;">{sig.company_name[:18]}</td>
          <td style="padding:7px 8px;text-align:right;">
            <span style="color:{sc};font-weight:700;font-size:14px;">{sig.total_score:.0f}</span>
          </td>
          <td style="padding:7px 8px;text-align:right;color:{rsi_c};font-size:12px;
              font-weight:600;">{ts.rsi:.0f}</td>
          <td style="padding:7px 8px;text-align:right;color:{adx_c};font-size:12px;">
            {ts.adx:.0f}</td>
          <td style="padding:7px 8px;text-align:center;font-size:12px;">
            <span style="color:{macd_c};">{macd_arrow}</span>
            <span style="color:{macd_c};font-size:10px;">{ts.macd_hist:+.3f}</span>
          </td>
          <td style="padding:7px 8px;text-align:center;font-size:10px;
              letter-spacing:2px;">{ema_dots}</td>
          <td style="padding:7px 8px;text-align:right;color:{vol_c};font-size:12px;">
            {ts.volume_ratio:.1f}x</td>
          <td style="padding:7px 8px;text-align:right;color:{C['text']};
              font-size:13px;font-weight:600;">{ts.close:.2f} ₺</td>
          <td style="padding:7px 8px;text-align:right;color:{pct_c};font-size:12px;">
            {"+" if pct >= 0 else ""}{pct:.1f}%</td>
          <td style="padding:7px 8px;text-align:right;color:{C['sub']};font-size:12px;">
            {ts.atr:.2f}</td>
          <td style="padding:7px 10px;text-align:center;">{setup_icons or "—"}</td>
        </tr>"""

    th = lambda t: f'<th style="padding:8px;text-align:right;color:{C["muted"]};font-size:9px;letter-spacing:0.08em;text-transform:uppercase;font-weight:600;border-bottom:1px solid {C["border"]};">{t}</th>'
    th_l = lambda t: f'<th style="padding:8px 10px;text-align:left;color:{C["muted"]};font-size:9px;letter-spacing:0.08em;text-transform:uppercase;font-weight:600;border-bottom:1px solid {C["border"]};">{t}</th>'
    th_c = lambda t: f'<th style="padding:8px;text-align:center;color:{C["muted"]};font-size:9px;letter-spacing:0.08em;text-transform:uppercase;font-weight:600;border-bottom:1px solid {C["border"]};">{t}</th>'

    return f"""
<div style="overflow-x:auto;border-radius:10px;border:1px solid {C['border']};">
<table style="width:100%;border-collapse:collapse;min-width:680px;
     background:{C['surface']};">
  <tr style="background:{C['card']};">
    {th_l("Hisse")}
    {th_l("Şirket")}
    {th("Skor")}
    {th("RSI")}
    {th("ADX")}
    {th_c("MACD")}
    {th_c("EMA 21·50·200")}
    {th("Hacim")}
    {th("Fiyat")}
    {th("Değ%")}
    {th("ATR")}
    {th_c("Setup")}
  </tr>
  {rows}
</table>
</div>"""


# ─── Kılavuz ─────────────────────────────────────────────────────────────────

def _guide() -> str:
    rows = [
        ("⭐ GÜÇLÜ AL", "140–170", "%1.5", "Tüm katmanlar geçti. Güçlü momentum + olumlu haber. Tam pozisyon aç.", "#4ade80", "#052e16"),
        ("🟢 AL",       "120–139", "%1.0", "Setup + trigger aktif. Normal pozisyon. Stop takip et.",              "#22c55e", "#031f0e"),
        ("🟡 ALIMA UYGUN","100–119","%0.5","Sinyal var ama eksik katmanlar. Yarım pozisyon, sıkı stop.",          "#eab308", "#1c1400"),
        ("🔵 İZLE",     "80–99",   "—",   "Henüz olgunlaşmamış. Alerte al, kırılım bekleniyor olabilir.",      "#3b82f6", "#0c1a35"),
        ("⚪ NÖTR",     "60–79",   "—",   "Yön belirsiz. Bekle.",                                              "#64748b", "#0f172a"),
        ("🔴 ZAYIF",    "<60",     "—",   "Setup yok. Trend aleyhte.",                                         "#ef4444", "#1c0000"),
        ("⛔ VETOLU",   "—",       "—",   "Haber / piyasa veto kuralı devrede. Dokunma.",                       "#dc2626", "#1a0000"),
    ]
    trs = ""
    for lbl, skor, risk, desc, col, bg in rows:
        trs += f"""
        <tr style="background:{bg};">
          <td style="padding:7px 12px;color:{col};font-weight:600;font-size:13px;
              border-bottom:1px solid {C['border']};white-space:nowrap;">{lbl}</td>
          <td style="padding:7px 12px;color:{C['text']};font-size:12px;
              border-bottom:1px solid {C['border']};text-align:center;">{skor}</td>
          <td style="padding:7px 12px;color:{col};font-size:12px;font-weight:700;
              border-bottom:1px solid {C['border']};text-align:center;">{risk}</td>
          <td style="padding:7px 12px;color:{C['sub']};font-size:12px;
              border-bottom:1px solid {C['border']};">{desc}</td>
        </tr>"""

    param_grid = f"""
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
         gap:12px;margin-top:14px;">
      <div style="background:{C['card']};border:1px solid {C['border']};
           border-radius:8px;padding:12px;">
        <div style="color:{C['green']};font-size:10px;font-weight:700;
             letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px;">
          Teknik Skor (0–100)</div>
        <div style="color:{C['sub']};font-size:11px;line-height:1.8;">
          Setup A — EMA21 Pullback<br>
          Setup B — BB Squeeze Kırılımı<br>
          Setup C — RSI Bullish Diverjans<br>
          RSI 40–60 momentum bölgesi<br>
          EMA hizalaması (9&gt;21&gt;50&gt;200)<br>
          ADX &gt; 25 güçlü trend<br>
          Hacim 1.5x+ onayı
        </div>
      </div>
      <div style="background:{C['card']};border:1px solid {C['border']};
           border-radius:8px;padding:12px;">
        <div style="color:{C['blue']};font-size:10px;font-weight:700;
             letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px;">
          Haber Skoru (−50 / +50)</div>
        <div style="color:{C['sub']};font-size:11px;line-height:1.8;">
          <span style="color:{C['green']};">+25</span> Bilanço pozitif sürpriz<br>
          <span style="color:{C['green']};">+20</span> Yeni sözleşme / ihale<br>
          <span style="color:{C['green']};">+15</span> Geri alım programı<br>
          <span style="color:{C['red']};"> −30</span> SPK soruşturması<br>
          <span style="color:{C['red']};"> −25</span> Bilanço negatif sürpriz<br>
          KAP×1.0 · BloombergHT×0.8 · Diğer×0.5
        </div>
      </div>
      <div style="background:{C['card']};border:1px solid {C['border']};
           border-radius:8px;padding:12px;">
        <div style="color:{C['orange']};font-size:10px;font-weight:700;
             letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px;">
          Likidite Skoru (0–20)</div>
        <div style="color:{C['sub']};font-size:11px;line-height:1.8;">
          +10 Günlük hacim &gt;250M TL<br>
          +5  Günlük hacim &gt;100M TL<br>
          +10 Piyasa değeri &gt;5B TL<br><br>
          <b style="color:{C['text']};">Toplam = Teknik + Haber + Likidite</b><br>
          <span style="color:{C['muted']};">Aralık: −50 ile 170 puan</span>
        </div>
      </div>
      <div style="background:{C['card']};border:1px solid {C['border']};
           border-radius:8px;padding:12px;">
        <div style="color:{C['purple']};font-size:10px;font-weight:700;
             letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px;">
          ATR Risk Formülü</div>
        <div style="color:{C['sub']};font-size:11px;line-height:1.8;">
          Giriş  = Kapanış × 1.005<br>
          Stop   = Giriş − 2 × ATR(14)<br>
          T1     = Giriş + 2 × ATR(14) → ½ çık<br>
          T2     = Giriş + 4 × ATR(14) → kalan çık<br>
          Stop'u T1'de girişe çek<br>
          Portföy: 100.000 ₺ baz
        </div>
      </div>
    </div>"""

    return f"""
<div style="background:{C['surface']};border:1px solid {C['border']};
     border-radius:10px;overflow:hidden;">
  <div style="padding:14px 16px;border-bottom:1px solid {C['border']};">
    <span style="color:{C['text']};font-size:13px;font-weight:700;">
      📖 Sinyal Kılavuzu</span>
  </div>
  <table style="width:100%;border-collapse:collapse;">
    <tr style="background:{C['card']};">
      <th style="padding:7px 12px;text-align:left;color:{C['muted']};font-size:9px;
          letter-spacing:0.1em;text-transform:uppercase;border-bottom:1px solid {C['border']};">Sinyal</th>
      <th style="padding:7px 12px;text-align:center;color:{C['muted']};font-size:9px;
          letter-spacing:0.1em;text-transform:uppercase;border-bottom:1px solid {C['border']};">Skor</th>
      <th style="padding:7px 12px;text-align:center;color:{C['muted']};font-size:9px;
          letter-spacing:0.1em;text-transform:uppercase;border-bottom:1px solid {C['border']};">Risk %</th>
      <th style="padding:7px 12px;text-align:left;color:{C['muted']};font-size:9px;
          letter-spacing:0.1em;text-transform:uppercase;border-bottom:1px solid {C['border']};">Açıklama</th>
    </tr>
    {trs}
  </table>
  <div style="padding:14px 16px;">
    {param_grid}
  </div>
</div>"""


# ─── Ana HTML ─────────────────────────────────────────────────────────────────

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

    strong = ranked["GÜÇLÜ AL"]
    buy    = ranked["AL"]
    suit   = ranked["ALIMA UYGUN"]
    watch  = ranked["İZLE"]
    neutral= ranked["NÖTR"]
    weak   = ranked["ZAYIF"]
    vetoed = ranked["VETOLU"]

    # Kart gösterilecek hisseler: GÜÇLÜ AL + AL + ALIMA UYGUN + İZLE
    card_sigs = strong + buy + suit + watch

    xu100  = market_regime.get("xu100_close", 0)
    ema50  = market_regime.get("ema50_val", 0)
    mok    = market_regime.get("above_ema50", False)
    usd    = f"{usdtry:.4f}" if usdtry else "—"

    # Piyasa banner
    if mok:
        regime_html = (
            f'<div style="background:#052e16;border:1px solid #166534;'
            f'border-radius:8px;padding:10px 16px;margin-bottom:16px;'
            f'display:flex;align-items:center;gap:10px;">'
            f'<span style="font-size:18px;">📈</span>'
            f'<div><b style="color:{C["green"]};">Piyasa Güçlü</b>'
            f'<span style="color:{C["sub"]};font-size:12px;margin-left:8px;">'
            f'XU100 {xu100:,.0f} · EMA50 {ema50:,.0f} ({((xu100/ema50-1)*100):+.1f}%)'
            f'</span></div></div>'
        )
    else:
        regime_html = (
            f'<div style="background:#1c0000;border:1px solid #7f1d1d;'
            f'border-radius:8px;padding:10px 16px;margin-bottom:16px;">'
            f'<b style="color:{C["red"]};">⚠ Piyasa Zayıf — XU100 &lt; EMA50</b>'
            f'<span style="color:{C["sub"]};font-size:12px;margin-left:8px;">'
            f'XU100 {xu100:,.0f} · EMA50 {ema50:,.0f}</span><br>'
            f'<span style="color:{C["sub"]};font-size:12px;">'
            f'Aktif sinyallerde pozisyon yarıya indir. Stop seviyelerine kesinlikle uy.</span>'
            f'</div>'
        )

    # Özet sayaçlar
    def _cnt(n: int, label: str, color: str, bg: str) -> str:
        return (
            f'<div style="background:{bg};border-radius:8px;padding:12px 14px;'
            f'text-align:center;min-width:72px;">'
            f'<div style="color:{C["muted"]};font-size:9px;letter-spacing:0.1em;'
            f'text-transform:uppercase;">{label}</div>'
            f'<div style="color:{color};font-size:24px;font-weight:800;'
            f'letter-spacing:-1px;line-height:1.1;">{n}</div>'
            f'</div>'
        )

    counts_html = (
        f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;">'
        f'{_cnt(len(strong), "⭐ Güçlü Al", C["green2"], "#052e16")}'
        f'{_cnt(len(buy),    "🟢 Al",       C["green"],  "#031f0e")}'
        f'{_cnt(len(suit),   "🟡 Uygun",    C["yellow"], "#1c1400")}'
        f'{_cnt(len(watch),  "🔵 İzle",     C["blue"],   "#0c1a35")}'
        f'{_cnt(len(neutral),"⚪ Nötr",     C["sub"],    "#0f172a")}'
        f'{_cnt(len(weak),   "🔴 Zayıf",    C["red"],    "#1c0000")}'
        f'{_cnt(len(vetoed), "⛔ Vetolu",   "#dc2626",   "#1a0000")}'
        f'<div style="flex:1;min-width:120px;background:{C["card"]};border:1px solid {C["border"]};'
        f'border-radius:8px;padding:12px 14px;">'
        f'<div style="color:{C["muted"]};font-size:9px;letter-spacing:0.1em;'
        f'text-transform:uppercase;">USD/TRY</div>'
        f'<div style="color:{C["text"]};font-size:20px;font-weight:700;">{usd}</div>'
        f'</div>'
        f'</div>'
    )

    # Trade kartları
    if card_sigs:
        cards_html = "".join(_trade_card(s, news_scores_map) for s in card_sigs)
    else:
        cards_html = (
            f'<div style="background:{C["surface"]};border:1px solid {C["border"]};'
            f'border-radius:10px;padding:24px;text-align:center;'
            f'color:{C["muted"]};font-size:14px;margin-bottom:16px;">'
            f'Bugün aksiyon alınabilir setup yok. Piyasayı izlemeye devam et.'
            f'</div>'
        )

    # Performans
    perf_html = ""
    if is_monday and weekly_perf:
        p = weekly_perf
        wr = p.get("win_rate", 0)
        ar = p.get("avg_return", 0)
        perf_html = (
            f'{_divider("Geçen Hafta Performansı")}'
            f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">'
            f'{_kpi("Toplam", str(p.get("total_signals", 0)))}'
            f'{_kpi("T1 İsabet", str(p.get("t1_hits", 0)), C["green"])}'
            f'{_kpi("T2 İsabet", str(p.get("t2_hits", 0)), C["green2"])}'
            f'{_kpi("Stop", str(p.get("stop_hits", 0)), C["red"])}'
            f'{_kpi("Kazanma %", f"%{wr:.1f}", C["green"] if wr >= 50 else C["red"])}'
            f'{_kpi("Ort. Getiri", f"{ar:+.2f}%", C["green"] if ar >= 0 else C["red"])}'
            f'</div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BIST30 · {now.strftime('%d.%m.%Y')}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:{C['bg']};font-family:-apple-system,BlinkMacSystemFont,
       'Segoe UI',system-ui,sans-serif;color:{C['text']};}}
  a{{color:{C['blue']};text-decoration:none;}}
  a:hover{{text-decoration:underline;}}
  td{{vertical-align:top;}}
</style>
</head>
<body>
<div style="max-width:900px;margin:0 auto;padding:16px 12px 32px;">

  <!-- BAŞLIK -->
  <div style="text-align:center;padding:20px 0 18px;">
    <div style="color:{C['muted']};font-size:10px;letter-spacing:0.15em;
         text-transform:uppercase;margin-bottom:6px;">
      {now.strftime('%d %B %Y · %A · %H:%M')} İstanbul
    </div>
    <h1 style="font-size:20px;font-weight:800;color:{C['text']};letter-spacing:-0.5px;">
      BIST30 · 5-Günlük Swing Taraması
    </h1>
    <div style="color:{C['muted']};font-size:12px;margin-top:4px;">
      {len(signals)} hisse analiz edildi · EMA / RSI / MACD / BB / ADX / Stochastic / Hacim
    </div>
  </div>

  <!-- PİYASA -->
  {regime_html}

  <!-- SAYAÇLAR -->
  {counts_html}

  <!-- TRADE KARTLARI -->
  {_divider(f"Detaylı Trade Planları · {len(card_sigs)} Hisse")}
  {cards_html}

  <!-- TAM TARAMA -->
  {_divider(f"BIST30 Tam Tarama · {len(signals)} Hisse")}
  {_full_table(ranked)}

  <!-- PERFORMANS -->
  {perf_html}

  <!-- KILAVUZ -->
  {_divider("Sinyal Kılavuzu & Parametreler")}
  {_guide()}

  <!-- FOOTER -->
  <div style="margin-top:28px;padding-top:16px;border-top:1px solid {C['border']};
       text-align:center;">
    <p style="color:{C['muted']};font-size:10px;line-height:1.8;">
      ⚠ Bu rapor <b>yatırım tavsiyesi değildir</b>. Yalnızca eğitim ve araştırma amaçlıdır.<br>
      Geçmiş performans gelecek getirileri garantilemez. Her sinyali kendi analizinizle doğrulayın.<br>
      Sonraki tarama: <b>Yarın 09:00 TR</b> · BIST30-Signal v3.0
    </p>
  </div>

</div>
</body>
</html>"""

    return html


# ─── Resend Gönderme ──────────────────────────────────────────────────────────

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
                logger.warning("Mail gönderilemedi (%d. deneme): %s, %ds bekleniyor",
                               attempt, exc, cfg["retry_delay"])
                time.sleep(cfg["retry_delay"])
            else:
                logger.error("Mail 3 denemede gönderilemedi: %s", exc)
    return False
