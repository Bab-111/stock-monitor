#!/usr/bin/env python3
"""
Stock Monitor — Free LLM Edition (Llama 3.1)
Optimized for max free tokens, minimal consumption
GitHub Models API: https://models.inference.ai.azure.com
"""

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
print(f"[Monitor] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks")

# ══════════════════════════════════════════════════════════════════════════════
# GITHUB MODELS API — Llama 3.1 (Free, efficient, optimized)
# ══════════════════════════════════════════════════════════════════════════════
def call_llama(prompt):
    """Call Llama 3.1 via GitHub Models (free, ~1/3 tokens of GPT-4o-mini)."""
    token = __import__('os').environ.get('GITHUB_TOKEN', '')
    if not token:
        print("[!] GITHUB_TOKEN missing")
        return None
    
    try:
        resp = requests.post(
            "https://models.inference.ai.azure.com/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "model": "Llama-3.1-70b-Instruct",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,  # Shorter = fewer tokens
                "temperature": 0.5,  # More focused, deterministic
            },
            timeout=25
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        else:
            print(f"[!] LLM error {resp.status_code}")
            return None
    except Exception as e:
        print(f"[!] Error: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# 1. FETCH STOCK DATA
# ══════════════════════════════════════════════════════════════════════════════
def safe(val, dec=2):
    try:    return round(float(val), dec)
    except: return None

def calc_rsi(ticker, period=14):
    try:
        hist = yf.Ticker(ticker).history(period=period+1)
        if len(hist) < period + 1: return None
        deltas = hist['Close'].diff()
        gains = deltas.where(deltas > 0, 0).rolling(period).mean()
        losses = -deltas.where(deltas < 0, 0).rolling(period).mean()
        rs = gains / losses
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 0)
    except: return None

def fetch_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
        vol = info.get("regularMarketVolume")
        avg_vol = info.get("averageVolume")
        
        chg = safe((price - prev) / prev * 100) if price and prev else None
        vol_ratio = safe(vol / avg_vol) if vol and avg_vol else None
        rsi = calc_rsi(ticker)
        
        return {
            "ticker": ticker,
            "name": info.get("longName", ticker),
            "price": safe(price),
            "change_pct": chg,
            "volume_ratio": vol_ratio,
            "rsi": rsi,
            "week_52_high": safe(info.get("fiftyTwoWeekHigh")),
            "week_52_low": safe(info.get("fiftyTwoWeekLow")),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency", "USD"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}

# ══════════════════════════════════════════════════════════════════════════════
# 2. FETCH NEWS (Minimal text for low token consumption)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_news(ticker):
    items = []
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        for e in feed.entries[:2]:
            items.append({"title": e.get("title", ""), "link": e.get("link", ""), "source": "YF"})
    except: pass
    
    try:
        q = requests.utils.quote(f"{ticker} stock")
        gfeed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        for e in gfeed.entries[:1]:
            items.append({"title": e.get("title", ""), "link": e.get("link", ""), "source": "GN"})
    except: pass
    
    return items[:3]

# ══════════════════════════════════════════════════════════════════════════════
# 3. COLLECT DATA
# ══════════════════════════════════════════════════════════════════════════════
print("\n[📊] Fetching data...")
all_data = []
for ticker in TICKERS:
    data = fetch_stock(ticker)
    data["news"] = fetch_news(ticker)
    all_data.append(data)
    print(f"  ✓ {ticker}")

# ══════════════════════════════════════════════════════════════════════════════
# 4. BATCH AI ANALYSIS (Lower token consumption)
# ══════════════════════════════════════════════════════════════════════════════
print("\n[🤖] Llama 3.1 analysis...")

# Build compact data summary for ONE efficient prompt
data_summary = ""
for s in all_data:
    if "error" in s:
        continue
    news_str = " | ".join([f"{n['title'][:40]}" for n in s.get("news", [])])
    data_summary += f"{s['ticker']}: {s['price']} ({s['change_pct']}%), vol {s['volume_ratio']}x, RSI {s['rsi']}, 52w ${s['week_52_low']}-${s['week_52_high']}. News: {news_str}\n"

# ONE prompt for all stocks = massive token savings
prompt = f"""Analyze these stocks. For EACH stock, write ONE short sentence with actionable insight.

DATA:
{data_summary}

Format (one line per stock):
TICKER: [Action/Signal]

Example:
AAPL: Volume 2.5x with 15% gain = strong buy signal, watch for pullback
NVDA: RSI 75 overbought = take profits or wait for dip
TSLA: Below 52w low with no unusual news = caution, possible support test"""

summary = call_llama(prompt)

if summary:
    lines = summary.strip().split('\n')
    summaries = {}
    for line in lines:
        if ':' in line:
            parts = line.split(':', 1)
            ticker = parts[0].strip()
            analysis = parts[1].strip() if len(parts) > 1 else "N/A"
            summaries[ticker] = analysis
else:
    summaries = {s["ticker"]: "Analysis pending..." for s in all_data if "error" not in s}

# ══════════════════════════════════════════════════════════════════════════════
# 5. GENERATE BRIEF
# ══════════════════════════════════════════════════════════════════════════════
brief = f"""# 📊 Daily Stock Brief
**{NOW_TW.strftime('%a %b %d, %Y')} · {NOW_TW.strftime('%H:%M')} TW**

---

## 🎯 Quick Signals
"""

for s in all_data:
    if "error" in s:
        continue
    
    ticker = s["ticker"]
    price = f"{s['currency']}{s['price']}"
    chg = s["change_pct"]
    vr = s["volume_ratio"]
    rsi = s["rsi"]
    
    # Color coding
    chg_emoji = "🚀" if (chg or -999) > 5 else "📉" if (chg or 999) < -5 else "⚪"
    vr_emoji = "⚡" if (vr or 0) > 2 else "📊"
    rsi_emoji = "🔴" if (rsi or 50) > 70 else "🟢" if (rsi or 50) < 30 else "⚪"
    
    brief += f"\n**{ticker}** {chg_emoji}\n"
    brief += f"  Price: {price} ({chg}%) {vr_emoji}vol {vr}x {rsi_emoji}RSI {rsi}\n"
    brief += f"  📌 {summaries.get(ticker, 'N/A')}\n"

brief += f"\n---\n\n## 📈 Key Metrics Explained\n"
brief += """- **RSI > 70**: Overbought (may pull back) 🔴
- **RSI < 30**: Oversold (may bounce) 🟢
- **Volume 2x+**: Unusual activity ⚡
- **52-week high**: Momentum zone 🚀
- **52-week low**: Support test 📉

---

*Next update: 10 PM TW | Powered by Llama 3.1 on GitHub Models API*"""

# ══════════════════════════════════════════════════════════════════════════════
# 6. SAVE
# ══════════════════════════════════════════════════════════════════════════════
(ROOT / "README.md").write_text(brief, encoding='utf-8')
print(f"✓ Brief saved")

entry = {"ts": NOW_TW.isoformat(), "stocks": all_data, "summaries": summaries}
hfile = HISTORY_DIR / (NOW_TW.strftime("%Y-%m-%d_%H%M") + ".json")
hfile.write_text(json.dumps(entry, indent=2, default=str), encoding='utf-8')
print(f"✓ History saved")

(DOCS / ".nojekyll").touch()
print(f"\n✅ Done! Check README.md for today's brief")
