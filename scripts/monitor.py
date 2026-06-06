#!/usr/bin/env python3
"""
Stock Monitor — 100% free, no API keys needed.
Runs via GitHub Actions, outputs to GitHub Pages.
"""

import yfinance as yf
import feedparser
import requests
import json, os, re, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT        = Path(__file__).parent.parent
DOCS        = ROOT / "docs"
HISTORY_DIR = DOCS / "history"
STOCKS_FILE = ROOT / "stocks.json"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(exist_ok=True)

TAIWAN_TZ = ZoneInfo("Asia/Taipei")
NOW_TW    = datetime.datetime.now(TAIWAN_TZ)
NOW_UTC   = datetime.datetime.now(datetime.timezone.utc)

with open(STOCKS_FILE) as f:
    config = json.load(f)

TICKERS = config.get("tickers", [])
print(f"[Monitor] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | Tracking: {TICKERS}")

def safe(val, decimals=2):
    try:    return round(float(val), decimals)
    except: return None

def serialize(v):
    if hasattr(v, "item"):      return v.item()
    if hasattr(v, "isoformat"): return str(v)
    return v

def fetch_stock_data(ticker: str) -> dict:
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        price   = info.get("currentPrice") or info.get("regularMarketPrice")
        prev    = info.get("previousClose") or info.get("regularMarketPreviousClose")
        volume  = info.get("regularMarketVolume") or info.get("volume")
        avg_vol = info.get("averageVolume") or info.get("averageVolume10days")
        change_pct   = safe((price - prev) / prev * 100) if price and prev else None
        volume_ratio = safe(volume / avg_vol)             if volume and avg_vol else None
        top_inst = []
        try:
            inst = stock.institutional_holders
            if inst is not None and not inst.empty:
                for row in inst.head(3).to_dict("records"):
                    top_inst.append({k: serialize(v) for k, v in row.items()})
        except Exception:
            pass
        return {
            "ticker":            ticker,
            "name":              info.get("longName") or info.get("shortName", ticker),
            "price":             safe(price),
            "change_pct":        change_pct,
            "volume":            volume,
            "avg_volume":        avg_vol,
            "volume_ratio":      volume_ratio,
            "market_cap":        info.get("marketCap"),
            "week_52_high":      safe(info.get("fiftyTwoWeekHigh")),
            "week_52_low":       safe(info.get("fiftyTwoWeekLow")),
            "institutional_pct": safe(info.get("heldPercentInstitutions"), 4),
            "top_institutions":  top_inst,
            "sector":            info.get("sector"),
            "currency":          info.get("currency", "USD"),
        }
    except Exception as e:
        print(f"  [!] {ticker} error: {e}")
        return {"ticker": ticker, "error": str(e)}

def fetch_news(ticker: str, name: str = "") -> list:
    items = []
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        for e in feed.entries[:5]:
            items.append({"title": e.get("title",""), "link": e.get("link",""), "published": e.get("published",""), "source": "Yahoo Finance"})
    except Exception:
        pass
    try:
        q = requests.utils.quote(f"{ticker} stock {name}")
        gfeed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        for e in gfeed.entries[:4]:
            items.append({"title": e.get("title",""), "link": e.get("link",""), "published": e.get("published",""), "source": "Google News"})
    except Exception:
        pass
    seen, unique = set(), []
    for item in items:
        t = item["title"]
        if t and t not in seen:
            seen.add(t)
            unique.append(item)
    return unique[:8]

POSITIVE_WORDS = {"beat","surge","rally","gain","record","growth","profit","upgrade","buy","bullish","strong","rise","jumped","soared","partnership","deal","launch"}
NEGATIVE_WORDS = {"miss","fall","drop","loss","cut","downgrade","sell","bearish","weak","decline","layoff","recall","investigation","lawsuit","warning","crash","plunge"}

def news_sentiment(news_list):
    pos = neg = 0
    for n in news_list:
        words = set(n.get("title","").lower().split())
        pos += len(words & POSITIVE_WORDS)
        neg += len(words & NEGATIVE_WORDS)
    if pos > neg + 1: return "positive"
    if neg > pos + 1: return "negative"
    return "neutral"

def generate_analysis(data):
    alerts, per_stock, gainers, losers, vol_spikes = [], {}, [], [], []
    for s in data:
        if "error" in s: continue
        ticker = s["ticker"]
        notes  = []
        chg = s.get("change_pct")
        if chg is not None:
            if chg >= 5:   notes.append(f"Up {chg:.1f}% today — significant move up"); gainers.append(f"{ticker} +{chg:.1f}%")
            elif chg <= -5: notes.append(f"Down {chg:.1f}% today — significant drop"); losers.append(f"{ticker} {chg:.1f}%")
        vr = s.get("volume_ratio")
        if vr:
            if vr >= 3:   notes.append(f"Volume {vr:.1f}x average — very unusual activity"); alerts.append(f"{ticker}: volume {vr:.1f}x avg"); vol_spikes.append(ticker)
            elif vr >= 2: notes.append(f"Volume {vr:.1f}x average — worth watching"); vol_spikes.append(ticker)
            elif vr >= 1.5: notes.append(f"Volume {vr:.1f}x average — slightly elevated")
        hi, lo, p = s.get("week_52_high"), s.get("week_52_low"), s.get("price")
        if hi and lo and p:
            from_hi = (p - hi) / hi * 100
            from_lo = (p - lo) / lo * 100
            if from_hi >= -3: notes.append(f"Near 52-week HIGH ({from_hi:+.1f}%) — breakout zone"); alerts.append(f"{ticker}: near 52w high")
            elif from_lo <= 3: notes.append(f"Near 52-week LOW ({from_lo:+.1f}%) — watch for support"); alerts.append(f"{ticker}: near 52w low")
        sentiment = news_sentiment(s.get("news", []))
        if sentiment == "positive": notes.append("News tone: mostly positive")
        elif sentiment == "negative": notes.append("News tone: mostly negative — read headlines carefully")
        per_stock[ticker] = notes if notes else ["No unusual signals today"]
    parts = []
    if gainers:    parts.append(f"Notable gainers: {', '.join(gainers)}")
    if losers:     parts.append(f"Notable drops: {', '.join(losers)}")
    if vol_spikes: parts.append(f"Unusual volume in: {', '.join(vol_spikes)}")
    if not parts:  parts.append("No major price moves or volume spikes today")
    good = sum(1 for s in data if "error" not in s and (s.get("change_pct") or 0) >= 0)
    bad  = sum(1 for s in data if "error" not in s and (s.get("change_pct") or 0) < 0)
    mood = "mixed" if good and bad else ("mostly up" if good > bad else "mostly down")
    summary = f"Today's watchlist is {mood} — {good} stocks positive, {bad} negative. " + " · ".join(parts) + "."
    return {"summary": summary, "alerts": alerts, "per_stock": per_stock}

all_data = []
for ticker in TICKERS:
    print(f"  Fetching {ticker} ...")
    sd = fetch_stock_data(ticker)
    sd["news"] = fetch_news(ticker, sd.get("name", ""))
    all_data.append(sd)

analysis = generate_analysis(all_data)

history_entry = {"timestamp_utc": NOW_UTC.isoformat(), "timestamp_tw": NOW_TW.isoformat(), "stocks": all_data, "analysis": analysis}
history_file = HISTORY_DIR / f"{NOW_TW.strftime('%Y-%m-%d_%H%M')}.json"
with open(history_file, "w") as f:
    json.dump(history_entry, f, indent=2, default=str)
print(f"[Monitor] History saved: {history_file.name}")

cutoff = NOW_TW - datetime.timedelta(days=7)
for hf in sorted(HISTORY_DIR.glob("*.json")):
    try:
        file_date = datetime.datetime.strptime(hf.stem[:10], "%Y-%m-%d").replace(tzinfo=TAIWAN_TZ)
        if file_date < cutoff:
            hf.unlink()
    except Exception:
        pass

history_list = []
for hf in sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:14]:
    try:
        with open(hf) as f:
            h = json.load(f)
        history_list.append({"ts": h.get("timestamp_tw","")[:16].replace("T"," "), "file": hf.name})
    except Exception:
        pass

def fmt_change(val):
    if val is None: return '<span style="color:#888">-</span>'
    c = "#16a34a" if val >= 0 else "#dc2626"
    a = "up" if val >= 0 else "down"
    return f'<span style="color:{c};font-weight:600">{a} {abs(val):.2f}%</span>'

def fmt_vol(ratio):
    if ratio is None: return '<span style="color:#888">-</span>'
    if ratio >= 2.0: return f'<span style="color:#b45309;font-weight:700">{ratio}x (unusual!)</span>'
    if ratio >= 1.5: return f'<span style="color:#d97706;font-weight:600">{ratio}x (elevated)</span>'
    return f'<span>{ratio}x normal</span>'

def fmt_num(n):
    if n is None: return "-"
    if n >= 1e12: return f"${n/1e12:.2f}T"
    if n >= 1e9:  return f"${n/1e9:.2f}B"
    if n >= 1e6:  return f"${n/1e6:.1f}M"
    return str(n)

cards_html = ""
for s in all_data:
    if "error" in s:
        cards_html += f'<div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:12px;padding:16px;margin-bottom:12px"><b style="color:#dc2626">{s["ticker"]}</b><p style="font-size:12px;color:#b91c1c">{s["error"]}</p></div>'
        continue
    flags = analysis["per_stock"].get(s["ticker"], [])
    flags_html = "".join(f'<li style="font-size:13px;margin:3px 0">{f}</li>' for f in flags)
    news_items = ""
    for n in s.get("news", [])[:4]:
        news_items += f'<li style="margin:5px 0;font-size:12px"><a href="{n["link"]}" target="_blank" style="color:#2563eb">{n["title"]}</a></li>'
    lo, hi, p = s.get("week_52_low"), s.get("week_52_high"), s.get("price")
    bar = ""
    if hi and lo and p and hi != lo:
        pct = max(0, min(100, (p - lo) / (hi - lo) * 100))
        bar = f'<div style="margin:8px 0"><div style="display:flex;justify-content:space-between;font-size:11px;color:#888;margin-bottom:3px"><span>${lo} low</span><span>${hi} high</span></div><div style="height:5px;background:#e5e7eb;border-radius:3px"><div style="height:5px;width:{pct:.0f}%;background:#3b82f6;border-radius:3px"></div></div></div>'
    vr = s.get("volume_ratio") or 0
    border = "#f59e0b" if vr >= 2 else "#e5e7eb"
    cur = s.get("currency","$")
    cards_html += f'<div style="border:1.5px solid {border};border-radius:14px;padding:18px;margin-bottom:14px"><div style="display:flex;justify-content:space-between;margin-bottom:10px"><div><span style="font-size:20px;font-weight:700">{s["ticker"]}</span> <span style="color:#888;font-size:13px">{s.get("name","")}</span></div><div style="text-align:right"><div style="font-size:24px;font-weight:700">{cur}{s.get("price","-")}</div><div>{fmt_change(s.get("change_pct"))}</div></div></div>{bar}<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px"><div style="background:#f9fafb;border-radius:8px;padding:8px;font-size:12px"><div style="color:#888;margin-bottom:2px">VOLUME</div>{fmt_vol(s.get("volume_ratio"))}</div><div style="background:#f9fafb;border-radius:8px;padding:8px;font-size:12px"><div style="color:#888;margin-bottom:2px">MARKET CAP</div>{fmt_num(s.get("market_cap"))}</div></div><div style="margin-bottom:8px"><div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;margin-bottom:4px">Signals</div><ul style="margin:0;padding-left:18px">{flags_html}</ul></div><div><div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;margin-bottom:4px">Latest News</div><ul style="margin:0;padding-left:18px">{news_items or "<li style='font-size:12px;color:#888'>No headlines found</li>"}</ul></div></div>'

alert_html = ""
for a in analysis["alerts"]:
    alert_html += f'<span style="background:#fef3c7;color:#92400e;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:500;margin:3px">{a}</span>'

hist_html = "".join(f'<a href="history/{h["file"]}" target="_blank" style="display:block;padding:5px 0;border-bottom:1px solid #e5e7eb;font-size:12px;color:#2563eb">{h["ts"]}</a>' for h in history_list) or "<p style='font-size:12px;color:#888'>No history yet</p>"

page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock Monitor</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;color:#111827;margin:0;padding:0}}
*{{box-sizing:border-box}} a{{text-decoration:none}} ul{{list-style:disc}}
</style></head><body>
<div style="max-width:1100px;margin:0 auto;padding:32px 16px">
<h1 style="font-size:24px;font-weight:700;margin-bottom:4px">Stock Monitor</h1>
<p style="color:#6b7280;font-size:13px;margin-bottom:20px">Updated: {NOW_TW.strftime('%Y-%m-%d %H:%M')} Taiwan Time · {len(TICKERS)} stocks · runs 4 PM &amp; 10 PM daily</p>
<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:20px">
<p style="font-size:14px;line-height:1.6;margin-bottom:10px">{analysis['summary']}</p>
{('<div>' + alert_html + '</div>') if alert_html else ''}
</div>
<div style="display:flex;gap:20px;align-items:flex-start">
<div style="flex:1;min-width:0">{cards_html}</div>
<div style="width:180px;flex-shrink:0"><div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;position:sticky;top:20px">
<h3 style="font-size:13px;font-weight:700;margin-bottom:8px">History (7 days)</h3>{hist_html}</div></div>
</div></div></body></html>"""

out = DOCS / "index.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
(DOCS / ".nojekyll").touch()
print("[Monitor] Done!")
