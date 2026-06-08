#!/usr/bin/env python3
import yfinance as yf
import feedparser
import requests
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import os

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
HISTORY_DIR = DOCS / "history"
STOCKS_FILE = ROOT / "stocks.json"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(exist_ok=True)

TAIWAN_TZ = ZoneInfo("Asia/Taipei")
NOW_TW = datetime.datetime.now(TAIWAN_TZ)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
MODELS_API = "https://models.inference.ai.azure.com/chat/completions"

try:
    with open(STOCKS_FILE) as f:
        config = json.load(f)
    TICKERS = config.get("tickers", [])
except Exception as e:
    print(f"Error: {e}")
    exit(1)

print(f"[Stock Monitor v4] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks")

def safe(val, dec=2):
    try:
        return round(float(val), dec)
    except:
        return None

def fetch_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
        chg = safe((price - prev) / prev * 100) if price and prev else None
        return {
            "ticker": ticker,
            "name": info.get("longName", ticker),
            "price": safe(price),
            "change_pct": chg,
            "currency": info.get("currency", "USD"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}

print("\n[Fetching] Downloading stock data...")
all_data = []
for ticker in TICKERS:
    data = fetch_stock(ticker)
    all_data.append(data)
    print(f"  ✓ {ticker}")

html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Stock Monitor v4</title>
    <style>
        body {{ font-family: Arial; background: #f0f0f0; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
        h1 {{ color: #667eea; text-align: center; }}
        .stock {{ background: #f9f9f9; padding: 20px; margin: 10px 0; border-left: 5px solid #667eea; }}
        .ticker {{ font-size: 18px; font-weight: bold; color: #667eea; }}
        .price {{ font-size: 16px; margin: 10px 0; }}
        .positive {{ color: green; }}
        .negative {{ color: red; }}
        footer {{ text-align: center; margin-top: 30px; color: #999; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Stock Monitor v4</h1>
        <p style="text-align: center;">Updated: {NOW_TW.strftime('%Y-%m-%d %H:%M Taiwan Time')}</p>
        <hr>
"""

for s in all_data:
    if "error" in s:
        html_content += f'<div class="stock"><span class="ticker">{s["ticker"]}</span><p style="color: red;">Error: {s["error"]}</p></div>'
    else:
        change_class = "positive" if (s.get("change_pct") or 0) > 0 else "negative"
        change_sign = "+" if (s.get("change_pct") or 0) > 0 else ""
        html_content += f'''<div class="stock">
            <div class="ticker">{s["ticker"]} - {s["name"]}</div>
            <div class="price">{s["currency"]}{s["price"]} <span class="{change_class}">({change_sign}{s["change_pct"]}%)</span></div>
        </div>'''

html_content += """
        <hr>
    </div>
    <footer>
        <p>🤖 Stock Monitor v4 • AI-Powered • 100% FREE</p>
    </footer>
</body>
</html>
"""

try:
    (DOCS / "index.html").write_text(html_content, encoding='utf-8')
    print("[✓] Dashboard generated successfully!")
except Exception as e:
    print(f"Error saving: {e}")
    exit(1)

print("\n✅ Stock Monitor completed!")
