#!/usr/bin/env python3
import yfinance as yf
import feedparser
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
STOCKS_FILE = ROOT / "stocks.json"
DOCS.mkdir(exist_ok=True)

TAIWAN_TZ = ZoneInfo("Asia/Taipei")
NOW_TW = datetime.datetime.now(TAIWAN_TZ)

with open(STOCKS_FILE) as f:
    config = json.load(f)
TICKERS = config.get("tickers", [])

print(f"[Monitor] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks\n")

def safe(v, d=2):
    try:
        return round(float(v), d)
    except:
        return None

def get_stock(ticker):
    try:
        t = yf.Ticker(ticker)
        i = t.info
        p = i.get("currentPrice") or i.get("regularMarketPrice") or 0
        prev = i.get("previousClose") or i.get("regularMarketPreviousClose") or p
        vol = i.get("regularMarketVolume") or 0
        avg_vol = i.get("averageVolume") or vol
        
        chg = safe((p - prev) / prev * 100) if prev else 0
        vol_ratio = safe(vol / avg_vol) if avg_vol else 1.0
        spike = vol_ratio >= 2.0
        
        h52 = i.get("fiftyTwoWeekHigh") or p
        l52 = i.get("fiftyTwoWeekLow") or p
        
        # Get news
        news = []
        try:
            feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
            for e in feed.entries[:5]:
                news.append({"title": e.get("title", ""), "link": e.get("link", "")})
        except:
            pass
        
        return {
            "ticker": ticker,
            "name": i.get("longName", ticker),
            "price": safe(p),
            "change": chg,
            "vol_ratio": vol_ratio,
            "spike": spike,
            "h52": safe(h52),
            "l52": safe(l52),
            "currency": i.get("currency", "USD"),
            "news": news,
        }
    except Exception as e:
        print(f"  Error: {ticker} - {e}")
        return None

print("Fetching stocks...")
stocks = []
for ticker in TICKERS:
    s = get_stock(ticker)
    if s:
        stocks.append(s)
        print(f"  ✓ {ticker}")

spikes = [s for s in stocks if s["spike"]]

html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Monitor</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, sans-serif; background: #f5f5f5; padding: 20px; }}
        .wrap {{ max-width: 1000px; margin: 0 auto; background: white; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        header {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 30px; text-align: center; }}
        header h1 {{ font-size: 2em; margin-bottom: 5px; }}
        header p {{ opacity: 0.9; }}
        .alert {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px 20px; margin: 0; font-weight: 600; }}
        .content {{ padding: 30px; }}
        .stock {{ background: #f9f9f9; border-left: 4px solid #667eea; padding: 20px; margin-bottom: 20px; border-radius: 6px; }}
        .stock.spike {{ background: #ffe0e0; border-left-color: #ff6b6b; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
        .ticker {{ font-size: 1.4em; font-weight: bold; color: #667eea; }}
        .price {{ font-size: 1.2em; }}
        .up {{ color: #28a745; }}
        .down {{ color: #dc3545; }}
        .meta {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 15px 0; }}
        .box {{ background: white; padding: 10px; border-radius: 4px; border: 1px solid #ddd; }}
        .box-label {{ color: #666; font-size: 0.85em; font-weight: 600; }}
        .box-value {{ font-size: 1.1em; font-weight: 600; margin-top: 3px; }}
        .signal {{ background: #fff9e6; border-left: 4px solid #f39c12; padding: 10px; margin: 10px 0; font-weight: 500; color: #d68910; }}
        .news {{ margin-top: 15px; }}
        .news h4 {{ margin-bottom: 8px; font-size: 0.95em; }}
        .news-item {{ background: white; padding: 10px; margin: 5px 0; border-radius: 4px; border: 1px solid #e0e0e0; }}
        .news-item a {{ color: #667eea; text-decoration: none; font-weight: 500; font-size: 0.9em; }}
        .news-item a:hover {{ text-decoration: underline; }}
        footer {{ background: #f5f5f5; padding: 15px; text-align: center; color: #666; font-size: 0.9em; border-top: 1px solid #ddd; }}
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>📊 Stock Monitor v4</h1>
            <p>{NOW_TW.strftime('%a, %b %d, %Y · %H:%M')} Taiwan Time</p>
        </header>
"""

if spikes:
    html += f'<div class="alert">🔥 {len(spikes)} VOLUME SPIKE(s) DETECTED</div>'

html += '<div class="content">'

for s in stocks:
    change_class = "up" if s["change"] > 0 else "down"
    change_sign = "+" if s["change"] > 0 else ""
    card_class = "stock spike" if s["spike"] else "stock"
    
    html += f'''<div class="{card_class}">
        <div class="header">
            <span class="ticker">{s["ticker"]}</span>
            <span class="price">{s["currency"]}{s["price"]} <span class="{change_class}">({change_sign}{s["change"]}%)</span></span>
        </div>
        <div><strong>{s["name"]}</strong></div>
        
        <div class="meta">
            <div class="box">
                <div class="box-label">Volume Ratio</div>
                <div class="box-value">{s["vol_ratio"]}x</div>
            </div>
            <div class="box">
                <div class="box-label">52w Low</div>
                <div class="box-value">{s["currency"]}{s["l52"]}</div>
            </div>
            <div class="box">
                <div class="box-label">52w High</div>
                <div class="box-value">{s["currency"]}{s["h52"]}</div>
            </div>
            <div class="box">
                <div class="box-label">Price Range</div>
                <div class="box-value">{safe((s["price"] - s["l52"]) / (s["h52"] - s["l52"]) * 100 if s["h52"] != s["l52"] else 50)}%</div>
            </div>
        </div>
'''
    
    # Signal
    if s["spike"]:
        html += f'<div class="signal">🔥 VOLUME SPIKE: {s["vol_ratio"]}x average volume</div>'
    if s["change"] >= 5:
        html += f'<div class="signal">🚀 Strong gains: +{s["change"]}%</div>'
    elif s["change"] <= -5:
        html += f'<div class="signal">📉 Sharp drop: {s["change"]}%</div>'
    
    # News
    if s["news"]:
        html += f'<div class="news"><h4>📰 Latest News ({len(s["news"])} items)</h4>'
        for n in s["news"][:5]:
            html += f'<div class="news-item"><a href="{n["link"]}" target="_blank">{n["title"][:75]}...</a></div>'
        html += '</div>'
    
    html += '</div>'

html += f'''</div>
    <footer>
        <p>🤖 Stock Monitor v4 • Real-time Data • 100% FREE</p>
        <p>Updated every 4 AM & 4 PM Taiwan Time</p>
    </footer>
    </div>
</body>
</html>'''

(DOCS / "index.html").write_text(html)
print("\n✅ Dashboard generated!")
