#!/usr/bin/env python3
"""
Stock Monitor v3 — Simple & Reliable
Runs entirely on GitHub Actions. No local setup needed.
"""

import yfinance as yf
import feedparser
import requests
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Setup paths
ROOT        = Path(__file__).parent.parent
DOCS        = ROOT / "docs"
HISTORY_DIR = DOCS / "history"
STOCKS_FILE = ROOT / "stocks.json"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(exist_ok=True)

# Timezone setup
TAIWAN_TZ = ZoneInfo("Asia/Taipei")
NOW_TW    = datetime.datetime.now(TAIWAN_TZ)
NOW_UTC   = datetime.datetime.now(datetime.timezone.utc)

# Load config
try:
    with open(STOCKS_FILE) as f:
        config = json.load(f)
    TICKERS = config.get("tickers", [])
except Exception as e:
    print(f"❌ Error loading stocks.json: {e}")
    exit(1)

print(f"[Stock Monitor] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks")

# ════════════════════════════════════════════════════════════════
# 1. FETCH STOCK DATA
# ════════════════════════════════════════════════════════════════
def safe(val, dec=2):
    try:
        return round(float(val), dec)
    except:
        return None

def calc_rsi(ticker, period=14):
    try:
        hist = yf.Ticker(ticker).history(period=period+1)
        if len(hist) < period + 1:
            return None
        deltas = hist['Close'].diff()
        gains = deltas.where(deltas > 0, 0).rolling(period).mean()
        losses = -deltas.where(deltas < 0, 0).rolling(period).mean()
        rs = gains / losses
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 0)
    except:
        return None

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
        print(f"⚠️ Error fetching {ticker}: {e}")
        return {"ticker": ticker, "error": str(e)}

# ════════════════════════════════════════════════════════════════
# 2. FETCH NEWS
# ════════════════════════════════════════════════════════════════
def fetch_news(ticker):
    items = []
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        for e in feed.entries[:2]:
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "source": "Yahoo"
            })
    except:
        pass
    
    try:
        q = requests.utils.quote(f"{ticker} stock news")
        gfeed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        for e in gfeed.entries[:1]:
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "source": "Google"
            })
    except:
        pass
    
    return items[:3]

# ════════════════════════════════════════════════════════════════
# 3. SMART ANALYSIS
# ════════════════════════════════════════════════════════════════
def analyze_stock(s):
    """Generate actionable insight from data."""
    chg = s.get("change_pct") or 0
    vol = s.get("volume_ratio") or 1
    rsi = s.get("rsi") or 50
    price = s.get("price")
    high52 = s.get("week_52_high")
    low52 = s.get("week_52_low")
    
    signals = []
    
    # Volume analysis
    if vol >= 2.5:
        signals.append("🔥 Extreme volume spike — major news likely")
    elif vol >= 2.0:
        signals.append("⚡ Unusual volume — watch closely")
    elif vol >= 1.5:
        signals.append("📊 Elevated volume — above average interest")
    
    # Price movement
    if chg >= 7:
        signals.append("🚀 Strong rally — momentum buy")
    elif chg >= 4:
        signals.append("📈 Gaining momentum")
    elif chg <= -7:
        signals.append("📉 Heavy selling — potential bounce zone")
    elif chg <= -4:
        signals.append("⬇️ Losing momentum")
    
    # RSI extremes
    if rsi > 75:
        signals.append("🔴 Overbought (RSI>75) — expect pullback")
    elif rsi < 25:
        signals.append("🟢 Oversold (RSI<25) — watch for bounce")
    
    # 52-week position
    if price and high52 and low52:
        from_high = (price - high52) / high52 * 100
        from_low = (price - low52) / low52 * 100
        if from_high >= -3:
            signals.append("🎯 Near 52w HIGH — strong momentum")
        elif from_low <= 3:
            signals.append("🎯 Near 52w LOW — test support level")
    
    return signals[0] if signals else "Normal trading pattern"

# ════════════════════════════════════════════════════════════════
# 4. COLLECT DATA
# ════════════════════════════════════════════════════════════════
print("\n[Fetching] Downloading stock data...")
all_data = []
for ticker in TICKERS:
    data = fetch_stock(ticker)
    data["news"] = fetch_news(ticker)
    all_data.append(data)
    print(f"  ✓ {ticker}")

# ════════════════════════════════════════════════════════════════
# 5. GENERATE BRIEF
# ════════════════════════════════════════════════════════════════
print("\n[Generating] Creating report...")

brief = f"""# 📊 Daily Stock Brief

**{NOW_TW.strftime('%a %b %d, %Y')} · {NOW_TW.strftime('%H:%M')} Taiwan Time**

---

## 🎯 Quick Signals

"""

gainers = [s for s in all_data if "error" not in s and (s.get("change_pct") or -999) > 3]
losers  = [s for s in all_data if "error" not in s and (s.get("change_pct") or 999) < -3]
movers  = [s for s in all_data if "error" not in s and (s.get("volume_ratio") or 0) > 1.5]

if gainers:
    brief += "\n**🚀 Strong Gainers:**\n"
    for s in gainers:
        brief += f"- **{s['ticker']}**: +{s['change_pct']}% | vol {s['volume_ratio']}x\n"

if losers:
    brief += "\n**📉 Big Drops:**\n"
    for s in losers:
        brief += f"- **{s['ticker']}**: {s['change_pct']}% | vol {s['volume_ratio']}x\n"

if movers:
    brief += "\n**⚡ Unusual Volume:**\n"
    for s in movers:
        brief += f"- **{s['ticker']}**: {s['volume_ratio']}x average\n"

brief += "\n---\n\n## 📈 Stock Analysis\n"

for s in all_data:
    if "error" in s:
        brief += f"\n### {s['ticker']}\n⚠️ Data unavailable ({s['error']})\n"
        continue
    
    ticker = s["ticker"]
    brief += f"\n### {ticker} — {s['name']}\n\n"
    brief += f"**Price:** {s['currency']}{s['price']} ({s['change_pct']}%)\n"
    brief += f"**Volume:** {s['volume_ratio']}x avg | RSI: {s['rsi']}\n"
    brief += f"**52w range:** {s['currency']}{s['week_52_low']} - {s['currency']}{s['week_52_high']}\n\n"
    brief += f"📌 **{analyze_stock(s)}**\n"
    
    if s.get("news"):
        brief += "\n**📰 Latest News:**\n"
        for n in s["news"][:2]:
            title = n['title'][:70]
            brief += f"- [{title}...]({n['link']}) _{n['source']}_\n"

brief += f"\n---\n\n## 📊 Key Metrics Explained\n\n"
brief += """- **RSI > 70**: Overbought (pullback likely) 🔴
- **RSI < 30**: Oversold (bounce opportunity) 🟢
- **Volume 2x+**: Unusual activity ⚡
- **52w high**: Strong momentum zone 🚀
- **52w low**: Support level test 📉

---

*🤖 Automated stock monitoring on GitHub Actions*  
*Updated: 4 PM & 10 PM Taiwan Time (Mon-Fri)*  
*Next update: {(NOW_TW + datetime.timedelta(hours=6)).strftime('%a %H:%M TW')}*
"""

# ════════════════════════════════════════════════════════════════
# 6. SAVE FILES
# ════════════════════════════════════════════════════════════════
try:
    (ROOT / "README.md").write_text(brief, encoding='utf-8')
    print("[✓] README.md updated")
except Exception as e:
    print(f"❌ Error saving README.md: {e}")
    exit(1)

try:
    entry = {"ts": NOW_TW.isoformat(), "stocks": all_data}
    hfile = HISTORY_DIR / (NOW_TW.strftime("%Y-%m-%d_%H%M") + ".json")
    hfile.write_text(json.dumps(entry, indent=2, default=str), encoding='utf-8')
    print("[✓] History saved")
except Exception as e:
    print(f"❌ Error saving history: {e}")
    exit(1)

try:
    (DOCS / ".nojekyll").touch()
except:
    pass

print("\n✅ Brief generated successfully!")
