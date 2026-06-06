#!/usr/bin/env python3
"""Stock Monitor — 100% free. Runs via GitHub Actions, outputs to GitHub Pages."""

import yfinance as yf
import feedparser
import requests
import json, re, datetime
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

# ── 1. FETCH STOCK DATA ───────────────────────────────────────────────────────
def safe(val, dec=2):
    try:    return round(float(val), dec)
    except: return None

def serialize(v):
    if hasattr(v, "item"):      return v.item()
    if hasattr(v, "isoformat"): return str(v)
    return v

def fetch_stock_data(ticker):
    try:
        stock   = yf.Ticker(ticker)
        info    = stock.info
        price   = info.get("currentPrice") or info.get("regularMarketPrice")
        prev    = info.get("previousClose") or info.get("regularMarketPreviousClose")
        volume  = info.get("regularMarketVolume") or info.get("volume")
        avg_vol = info.get("averageVolume") or info.get("averageVolume10days")
        change_pct   = safe((price - prev) / prev * 100) if price and prev else None
        volume_ratio = safe(volume / avg_vol) if volume and avg_vol else None
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

# ── 2. FETCH NEWS ─────────────────────────────────────────────────────────────
def fetch_news(ticker, name=""):
    items = []
    try:
        feed = feedparser.parse(
            "https://feeds.finance.yahoo.com/rss/2.0/headline"
            f"?s={ticker}&region=US&lang=en-US"
        )
        for e in feed.entries[:5]:
            items.append({"title": e.get("title",""), "link": e.get("link",""), "source": "Yahoo Finance"})
    except Exception:
        pass
    try:
        q     = requests.utils.quote(f"{ticker} stock {name}")
        gfeed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        for e in gfeed.entries[:4]:
            items.append({"title": e.get("title",""), "link": e.get("link",""), "source": "Google News"})
    except Exception:
        pass
    seen, unique = set(), []
    for item in items:
        t = item["title"]
        if t and t not in seen:
            seen.add(t)
            unique.append(item)
    return unique[:8]

# ── 3. RULE-BASED ANALYSIS ────────────────────────────────────────────────────
POSITIVE = {"beat","surge","rally","gain","record","growth","profit","upgrade",
            "buy","bullish","strong","rise","jumped","soared","deal","launch"}
NEGATIVE = {"miss","fall","drop","loss","cut","downgrade","sell","bearish",
            "weak","decline","layoff","recall","lawsuit","warning","crash","plunge"}

def sentiment(news_list):
    pos = neg = 0
    for n in news_list:
        words = set(n.get("title","").lower().split())
        pos += len(words & POSITIVE)
        neg += len(words & NEGATIVE)
    if pos > neg + 1: return "positive"
    if neg > pos + 1: return "negative"
    return "neutral"

def analyse(data):
    alerts, per_stock, gainers, losers, spikes = [], {}, [], [], []
    for s in data:
        if "error" in s:
            continue
        ticker = s["ticker"]
        notes  = []
        chg = s.get("change_pct")
        if chg is not None:
            if chg >= 5:
                notes.append("Up " + str(chg) + "% today — big move up")
                gainers.append(ticker + " +" + str(chg) + "%")
            elif chg <= -5:
                notes.append("Down " + str(abs(chg)) + "% today — significant drop")
                losers.append(ticker + " " + str(chg) + "%")
        vr = s.get("volume_ratio")
        if vr:
            if vr >= 3:
                notes.append("Volume " + str(vr) + "x average — very unusual activity")
                alerts.append(ticker + ": volume " + str(vr) + "x avg")
                spikes.append(ticker)
            elif vr >= 2:
                notes.append("Volume " + str(vr) + "x average — worth watching")
                spikes.append(ticker)
            elif vr >= 1.5:
                notes.append("Volume " + str(vr) + "x average — slightly elevated")
        hi = s.get("week_52_high")
        lo = s.get("week_52_low")
        p  = s.get("price")
        if hi and lo and p:
            from_hi = round((p - hi) / hi * 100, 1)
            from_lo = round((p - lo) / lo * 100, 1)
            if from_hi >= -3:
                notes.append("Near 52-week HIGH (" + str(from_hi) + "%) — breakout zone")
                alerts.append(ticker + ": near 52w high")
            elif from_lo <= 3:
                notes.append("Near 52-week LOW (+" + str(from_lo) + "%) — watch for support")
                alerts.append(ticker + ": near 52w low")
        tone = sentiment(s.get("news", []))
        if tone == "positive": notes.append("News tone: mostly positive")
        if tone == "negative": notes.append("News tone: mostly negative — read carefully")
        per_stock[ticker] = notes if notes else ["No unusual signals today"]
    parts = []
    if gainers: parts.append("Gainers: " + ", ".join(gainers))
    if losers:  parts.append("Drops: "   + ", ".join(losers))
    if spikes:  parts.append("Unusual volume: " + ", ".join(spikes))
    if not parts: parts.append("No major moves or volume spikes today")
    good = sum(1 for s in data if "error" not in s and (s.get("change_pct") or 0) >= 0)
    bad  = sum(1 for s in data if "error" not in s and (s.get("change_pct") or 0) < 0)
    mood = "mixed" if good and bad else ("mostly up" if good > bad else "mostly down")
    summary = "Watchlist is " + mood + " — " + str(good) + " up, " + str(bad) + " down. " + " · ".join(parts) + "."
    return {"summary": summary, "alerts": alerts, "per_stock": per_stock}

# ── 4. COLLECT ────────────────────────────────────────────────────────────────
all_data = []
for ticker in TICKERS:
    print("  Fetching " + ticker + " ...")
    sd = fetch_stock_data(ticker)
    sd["news"] = fetch_news(ticker, sd.get("name", ""))
    all_data.append(sd)

analysis = analyse(all_data)

# ── 5. SAVE HISTORY ───────────────────────────────────────────────────────────
entry = {"timestamp_utc": NOW_UTC.isoformat(), "timestamp_tw": NOW_TW.isoformat(),
         "stocks": all_data, "analysis": analysis}
hfile = HISTORY_DIR / (NOW_TW.strftime("%Y-%m-%d_%H%M") + ".json")
with open(hfile, "w") as f:
    json.dump(entry, f, indent=2, default=str)
print("[Monitor] Saved: " + hfile.name)

cutoff = NOW_TW - datetime.timedelta(days=7)
for hf in sorted(HISTORY_DIR.glob("*.json")):
    try:
        fd = datetime.datetime.strptime(hf.stem[:10], "%Y-%m-%d").replace(tzinfo=TAIWAN_TZ)
        if fd < cutoff:
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

# ── 6. HTML HELPERS ───────────────────────────────────────────────────────────
def fmt_cap(n):
    if n is None: return "—"
    if n >= 1e12: return "$" + str(round(n/1e12, 2)) + "T"
    if n >= 1e9:  return "$" + str(round(n/1e9, 2))  + "B"
    if n >= 1e6:  return "$" + str(round(n/1e6, 1))  + "M"
    return str(n)

def fmt_change(chg):
    if chg is None:
        return '<span style="color:#888">—</span>'
    color = "#16a34a" if chg >= 0 else "#dc2626"
    arrow = "▲" if chg >= 0 else "▼"
    val   = str(abs(chg))
    return '<span style="color:' + color + ';font-weight:600">' + arrow + " " + val + '%</span>'

def fmt_vol(vr):
    if vr is None:
        return '<span style="color:#888">—</span>'
    s = str(vr)
    if vr >= 2.0:
        return '<span style="color:#b45309;font-weight:700">' + s + 'x  unusual!</span>'
    if vr >= 1.5:
        return '<span style="color:#d97706">' + s + 'x elevated</span>'
    return '<span>' + s + 'x normal</span>'

def make_52w_bar(lo, hi, price):
    if not (hi and lo and price and hi != lo):
        return ""
    pct = max(0, min(100, (price - lo) / (hi - lo) * 100))
    p   = str(round(pct, 0))[:-2] if str(round(pct,0)).endswith(".0") else str(round(pct))
    return (
        '<div style="margin:8px 0">'
        '<div style="display:flex;justify-content:space-between;font-size:11px;color:#888;margin-bottom:3px">'
        '<span>$' + str(lo) + ' low</span>'
        '<span>$' + str(hi) + ' high</span></div>'
        '<div style="height:5px;background:#e5e7eb;border-radius:3px">'
        '<div style="height:5px;width:' + str(round(pct)) + '%;background:#3b82f6;border-radius:3px"></div>'
        '</div></div>'
    )

def make_card(s):
    if "error" in s:
        return (
            '<div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:12px;padding:16px;margin-bottom:12px">'
            '<b style="color:#dc2626">' + s["ticker"] + '</b>'
            '<p style="font-size:12px;color:#b91c1c;margin:6px 0 0">' + s["error"] + '</p>'
            '</div>'
        )
    ticker   = s["ticker"]
    name     = s.get("name", "")
    price    = s.get("price", "—")
    currency = s.get("currency", "$")
    vr       = s.get("volume_ratio")
    border   = "#f59e0b" if (vr or 0) >= 2 else "#e5e7eb"

    bar = make_52w_bar(s.get("week_52_low"), s.get("week_52_high"), s.get("price"))

    flags = analysis["per_stock"].get(ticker, ["No unusual signals today"])
    signals_html = "".join(
        '<li style="font-size:13px;margin:3px 0">' + fl + '</li>' for fl in flags
    )

    news_parts = []
    for n in s.get("news", [])[:4]:
        news_parts.append(
            '<li style="margin:5px 0;font-size:12px">'
            '<a href="' + n["link"] + '" target="_blank" style="color:#2563eb">' + n["title"] + '</a>'
            ' <span style="font-size:10px;color:#888">' + n["source"] + '</span></li>'
        )
    news_html = "".join(news_parts) if news_parts else '<li style="font-size:12px;color:#888">No headlines found</li>'

    return (
        '<div style="border:1.5px solid ' + border + ';border-radius:14px;padding:18px;margin-bottom:14px">'
        '<div style="display:flex;justify-content:space-between;margin-bottom:10px">'
        '<div>'
        '<span style="font-size:20px;font-weight:700">' + ticker + '</span>'
        ' <span style="color:#888;font-size:13px">' + name + '</span>'
        '</div>'
        '<div style="text-align:right">'
        '<div style="font-size:24px;font-weight:700">' + str(currency) + str(price) + '</div>'
        '<div>' + fmt_change(s.get("change_pct")) + '</div>'
        '</div></div>'
        + bar +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">'
        '<div style="background:#f9fafb;border-radius:8px;padding:8px;font-size:12px">'
        '<div style="color:#888;margin-bottom:2px">VOLUME VS AVG</div>'
        + fmt_vol(vr) +
        '</div>'
        '<div style="background:#f9fafb;border-radius:8px;padding:8px;font-size:12px">'
        '<div style="color:#888;margin-bottom:2px">MARKET CAP</div>'
        + fmt_cap(s.get("market_cap")) +
        '</div></div>'
        '<div style="margin-bottom:10px">'
        '<div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;margin-bottom:4px">Signals</div>'
        '<ul style="margin:0;padding-left:18px">' + signals_html + '</ul>'
        '</div>'
        '<div>'
        '<div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;margin-bottom:4px">Latest News</div>'
        '<ul style="margin:0;padding-left:18px">' + news_html + '</ul>'
        '</div>'
        '</div>'
    )

# ── 7. BUILD PAGE ─────────────────────────────────────────────────────────────
cards_html   = "".join(make_card(s) for s in all_data)
alert_badges = "".join(
    '<span style="background:#fef3c7;color:#92400e;padding:3px 10px;border-radius:20px;font-size:12px;margin:3px;display:inline-block">'
    + a + '</span>'
    for a in analysis["alerts"]
)
history_html = "".join(
    '<a href="history/' + h["file"] + '" target="_blank"'
    ' style="display:block;padding:5px 0;border-bottom:1px solid #e5e7eb;font-size:12px;color:#2563eb">'
    + h["ts"] + '</a>'
    for h in history_list
) or '<p style="font-size:12px;color:#888">No history yet</p>'

updated    = NOW_TW.strftime("%Y-%m-%d %H:%M")
num_stocks = str(len(TICKERS))
summary    = analysis["summary"]

page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock Monitor</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;color:#111827;margin:0;padding:0}
*{box-sizing:border-box} a{text-decoration:none} ul{list-style:disc}
</style>
</head>
<body>
<div style="max-width:1100px;margin:0 auto;padding:32px 16px">
<h1 style="font-size:24px;font-weight:700;margin-bottom:4px">Stock Monitor</h1>
<p style="color:#6b7280;font-size:13px;margin-bottom:20px">
  Updated: <b>""" + updated + """</b> Taiwan Time &nbsp;·&nbsp;
  """ + num_stocks + """ stocks tracked &nbsp;·&nbsp; runs 4 PM &amp; 10 PM weekdays
</p>
<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:20px">
  <p style="font-size:14px;line-height:1.6;margin-bottom:10px">""" + summary + """</p>
  """ + (('<div style="display:flex;flex-wrap:wrap;gap:4px">' + alert_badges + '</div>') if alert_badges else '') + """
</div>
<div style="display:flex;gap:20px;align-items:flex-start">
  <div style="flex:1;min-width:0">""" + cards_html + """</div>
  <div style="width:180px;flex-shrink:0">
    <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;position:sticky;top:20px">
      <h3 style="font-size:13px;font-weight:700;margin-bottom:8px">History (7 days)</h3>
      """ + history_html + """
    </div>
  </div>
</div>
</div>
</body>
</html>"""

out = DOCS / "index.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
(DOCS / ".nojekyll").touch()
print("[Monitor] Done! Report written to " + str(out))
