#!/usr/bin/env python3
"""
Stock Monitor v3 — Simple & Reliable
Runs entirely on GitHub Actions. No local setup needed.
Generates HTML for GitHub Pages.
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
# 5. GENERATE HTML
# ════════════════════════════════════════════════════════════════
print("\n[Generating] Creating HTML report...")

gainers = [s for s in all_data if "error" not in s and (s.get("change_pct") or -999) > 3]
losers  = [s for s in all_data if "error" not in s and (s.get("change_pct") or 999) < -3]
movers  = [s for s in all_data if "error" not in s and (s.get("volume_ratio") or 0) > 1.5]

html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Daily Stock Brief</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }}
        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        .timestamp {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        .content {{
            padding: 40px;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .section h2 {{
            font-size: 1.8em;
            margin-bottom: 20px;
            color: #667eea;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }}
        .stock-card {{
            background: #f8f9fa;
            border-left: 5px solid #667eea;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 8px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .stock-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.2);
        }}
        .stock-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}
        .ticker {{
            font-size: 1.4em;
            font-weight: bold;
            color: #667eea;
        }}
        .price {{
            font-size: 1.2em;
            font-weight: 600;
        }}
        .change.positive {{
            color: #28a745;
        }}
        .change.negative {{
            color: #dc3545;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 12px;
            font-size: 0.95em;
        }}
        .metric {{
            background: white;
            padding: 10px;
            border-radius: 6px;
            border: 1px solid #e0e0e0;
        }}
        .metric-label {{
            color: #666;
            font-weight: 600;
        }}
        .metric-value {{
            color: #333;
            font-size: 1.1em;
            margin-top: 4px;
        }}
        .analysis {{
            background: #e7f3ff;
            border-left: 4px solid #2196F3;
            padding: 12px;
            margin-top: 12px;
            border-radius: 4px;
            font-style: italic;
            color: #1565c0;
        }}
        .news {{
            margin-top: 12px;
            font-size: 0.9em;
        }}
        .news-item {{
            margin: 8px 0;
            padding: 8px;
            background: white;
            border-radius: 4px;
            border: 1px solid #e0e0e0;
        }}
        .news-item a {{
            color: #667eea;
            text-decoration: none;
        }}
        .news-item a:hover {{
            text-decoration: underline;
        }}
        .source {{
            font-size: 0.85em;
            color: #999;
            margin-top: 4px;
        }}
        .quick-signals {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .signal-box {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .signal-box h3 {{
            margin-bottom: 10px;
            font-size: 1.2em;
        }}
        .signal-list {{
            text-align: left;
        }}
        .signal-list li {{
            margin: 5px 0;
            list-style: none;
            padding-left: 20px;
            position: relative;
        }}
        .signal-list li:before {{
            content: "✓";
            position: absolute;
            left: 0;
            font-weight: bold;
        }}
        .metrics-info {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            border-radius: 6px;
            margin-top: 20px;
            font-size: 0.9em;
        }}
        .metrics-info h4 {{
            margin-bottom: 10px;
            color: #856404;
        }}
        .metrics-info ul {{
            list-style-position: inside;
            color: #856404;
        }}
        footer {{
            background: #f8f9fa;
            padding: 20px;
            text-align: center;
            color: #666;
            font-size: 0.9em;
            border-top: 1px solid #e0e0e0;
        }}
        @media (max-width: 768px) {{
            header h1 {{
                font-size: 1.8em;
            }}
            .content {{
                padding: 20px;
            }}
            .stock-header {{
                flex-direction: column;
                align-items: flex-start;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Daily Stock Brief</h1>
            <div class="timestamp">{NOW_TW.strftime('%a, %b %d, %Y · %H:%M')} Taiwan Time</div>
        </header>
        
        <div class="content">
            {f'<div class="section"><h2>🎯 Quick Signals</h2><div class="quick-signals">'
            + (f'<div class="signal-box"><h3>🚀 Strong Gainers</h3><ul class="signal-list">{"".join([f"<li><strong>{s['ticker']}</strong>: +{s['change_pct']}%</li>" for s in gainers])}</ul></div>' if gainers else '')
            + (f'<div class="signal-box"><h3>📉 Big Drops</h3><ul class="signal-list">{"".join([f"<li><strong>{s['ticker']}</strong>: {s['change_pct']}%</li>" for s in losers])}</ul></div>' if losers else '')
            + (f'<div class="signal-box"><h3>⚡ Unusual Volume</h3><ul class="signal-list">{"".join([f"<li><strong>{s['ticker']}</strong>: {s['volume_ratio']}x</li>" for s in movers])}</ul></div>' if movers else '')
            + '</div></div>'}
            
            <div class="section">
                <h2>📈 Stock Analysis</h2>
"""

for s in all_data:
    if "error" in s:
        html_content += f'<div class="stock-card" style="border-left-color: #dc3545;"><div class="stock-header"><span class="ticker">{s["ticker"]}</span></div><div style="color: #dc3545;">⚠️ Data unavailable ({s["error"]})</div></div>'
        continue
    
    ticker = s["ticker"]
    change_class = "positive" if (s['change_pct'] or 0) > 0 else "negative"
    change_sign = "+" if (s['change_pct'] or 0) > 0 else ""
    
    html_content += f"""
    <div class="stock-card">
        <div class="stock-header">
            <span class="ticker">{ticker}</span>
            <span class="price">{s['currency']}{s['price']} <span class="change {change_class}">({change_sign}{s['change_pct']}%)</span></span>
        </div>
        <div>
            <strong>{s['name']}</strong>
        </div>
        <div class="metrics">
            <div class="metric">
                <div class="metric-label">Volume</div>
                <div class="metric-value">{s['volume_ratio']}x avg</div>
            </div>
            <div class="metric">
                <div class="metric-label">RSI</div>
                <div class="metric-value">{s['rsi'] or 'N/A'}</div>
            </div>
            <div class="metric">
                <div class="metric-label">52w Low</div>
                <div class="metric-value">{s['currency']}{s['week_52_low']}</div>
            </div>
            <div class="metric">
                <div class="metric-label">52w High</div>
                <div class="metric-value">{s['currency']}{s['week_52_high']}</div>
            </div>
        </div>
        <div class="analysis">📌 {analyze_stock(s)}</div>
"""
    
    if s.get("news"):
        html_content += '<div class="news"><strong>📰 Latest News:</strong>'
        for n in s["news"][:2]:
            title = n['title'][:80]
            html_content += f'<div class="news-item"><a href="{n["link"]}" target="_blank">{title}...</a><div class="source">{n["source"]}</div></div>'
        html_content += '</div>'
    
    html_content += '</div>'

html_content += """
            </div>
            
            <div class="metrics-info">
                <h4>📊 Key Metrics Explained</h4>
                <ul>
                    <li><strong>RSI > 70:</strong> Overbought (pullback likely) 🔴</li>
                    <li><strong>RSI < 30:</strong> Oversold (bounce opportunity) 🟢</li>
                    <li><strong>Volume 2x+:</strong> Unusual activity ⚡</li>
                    <li><strong>52w high:</strong> Strong momentum zone 🚀</li>
                    <li><strong>52w low:</strong> Support level test 📉</li>
                </ul>
            </div>
        </div>
        
        <footer>
            <p>🤖 Automated stock monitoring on GitHub Actions</p>
            <p>Updated: 4 PM & 10 PM Taiwan Time (Mon-Fri) | Next update: """ + (NOW_TW + datetime.timedelta(hours=6)).strftime('%a %H:%M TW') + """</p>
        </footer>
    </div>
</body>
</html>
"""

# ════════════════════════════════════════════════════════════════
# 6. SAVE FILES
# ════════════════════════════════════════════════════════════════
try:
    (DOCS / "index.html").write_text(html_content, encoding='utf-8')
    print("[✓] index.html generated")
except Exception as e:
    print(f"❌ Error saving index.html: {e}")
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

print("\n✅ Report generated successfully!")
