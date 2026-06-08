#!/usr/bin/env python3
import yfinance as yf
import feedparser
import requests
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
STOCKS_FILE = ROOT / "stocks.json"
DOCS.mkdir(exist_ok=True)

TAIWAN_TZ = ZoneInfo("Asia/Taipei")
NOW_TW = datetime.datetime.now(TAIWAN_TZ)

with open(STOCKS_FILE) as f:
    config = json.load(f)
TICKERS = config.get("tickers", [])

print(f"[Monitor v4] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks\n")

def safe(v, d=2):
    try:
        return round(float(v), d)
    except:
        return None

def calc_rsi(ticker, period=14):
    """Calculate RSI properly"""
    try:
        data = yf.download(ticker, period="60d", progress=False)
        if len(data) < period:
            return None
        
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 0)
    except:
        return None

def get_earnings(ticker):
    """Get earnings from multiple sources"""
    try:
        info = yf.Ticker(ticker).info
        ed = info.get("earningsDate")
        if ed:
            if isinstance(ed, (list, tuple)) and len(ed) > 0:
                ed = ed[0]
            if isinstance(ed, (int, float)):
                from datetime import datetime as dt
                date = dt.fromtimestamp(ed, tz=TAIWAN_TZ)
                days = (date.date() - NOW_TW.date()).days
                return {"date": date.strftime('%Y-%m-%d'), "days": days}
    except:
        pass
    return None

def get_options_greeks(ticker):
    """Get options IV, Delta, Theta"""
    try:
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps:
            return None
        
        chain = t.option_chain(exps[0])
        calls = chain.calls
        if len(calls) == 0:
            return None
        
        price = t.info.get("currentPrice") or t.info.get("regularMarketPrice")
        if not price:
            return None
        
        # Find ATM call
        atm = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]
        
        return {
            "iv": safe(atm['impliedVolatility'].values[0] * 100, 1),
            "delta": safe(atm['delta'].values[0], 3),
            "theta": safe(atm['theta'].values[0], 4),
            "exp": exps[0]
        }
    except:
        return None

def fetch_news(ticker):
    """Get news from multiple sources"""
    items = []
    
    # Yahoo Finance
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        for e in feed.entries[:3]:
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "source": "Yahoo Finance",
                "summary": e.get("summary", "")[:150]
            })
    except:
        pass
    
    # MarketWatch
    try:
        feed = feedparser.parse(f"https://feeds.marketwatch.com/marketwatch/topstories/")
        for e in feed.entries:
            if ticker.lower() in e.get("title", "").lower():
                items.append({
                    "title": e.get("title", ""),
                    "link": e.get("link", ""),
                    "source": "MarketWatch",
                    "summary": e.get("summary", "")[:150]
                })
                if len(items) >= 8:
                    break
    except:
        pass
    
    # Seeking Alpha (via RSS)
    try:
        feed = feedparser.parse(f"https://seekingalpha.com/symbol/{ticker}/news")
        for e in feed.entries[:2]:
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "source": "Seeking Alpha",
                "summary": e.get("summary", "")[:150]
            })
    except:
        pass
    
    # Bloomberg/Reuters via Google News
    try:
        q = requests.utils.quote(f"{ticker} stock")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        for e in feed.entries[:3]:
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "source": "Google News",
                "summary": e.get("summary", "")[:150]
            })
    except:
        pass
    
    return items[:10]

def ai_summarize(ticker, news_items):
    """Use free AI API for summaries"""
    if not news_items:
        return None
    
    # Try using Hugging Face Inference API (free)
    try:
        news_text = "\n".join([f"- {n['title']}" for n in news_items[:5]])
        
        payload = {
            "inputs": f"Summarize this financial news for {ticker} in 2-3 sentences:\n{news_text}"
        }
        
        # Using a free inference endpoint
        response = requests.post(
            "https://api-inference.huggingface.co/models/facebook/bart-large-cnn",
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                return result[0].get("summary_text", "")
    except:
        pass
    
    # Fallback: keyword-based summary
    try:
        keywords = ['earnings', 'beat', 'miss', 'surge', 'plunge', 'announce', 'launch', 'acquisition', 'partnership', 'ai', 'patent']
        relevant = []
        for n in news_items[:5]:
            title = n['title'].lower()
            if any(k in title for k in keywords):
                relevant.append(n['title'])
        
        if relevant:
            return f"Key news: {' | '.join(relevant[:3])}"
    except:
        pass
    
    return None

def get_stock(ticker):
    """Fetch complete stock data"""
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
        
        rsi = calc_rsi(ticker)
        earnings = get_earnings(ticker)
        greeks = get_options_greeks(ticker)
        news = fetch_news(ticker)
        summary = ai_summarize(ticker, news)
        
        return {
            "ticker": ticker,
            "name": i.get("longName", ticker),
            "price": safe(p),
            "change": chg,
            "vol_ratio": vol_ratio,
            "spike": spike,
            "rsi": rsi,
            "h52": safe(i.get("fiftyTwoWeekHigh") or p),
            "l52": safe(i.get("fiftyTwoWeekLow") or p),
            "currency": i.get("currency", "USD"),
            "earnings": earnings,
            "greeks": greeks,
            "news": news,
            "summary": summary,
        }
    except Exception as e:
        print(f"  ⚠️ {ticker}: {str(e)[:50]}")
        return None

print("Fetching stocks...")
stocks = [s for s in [get_stock(t) for t in TICKERS] if s]
spikes = [s for s in stocks if s["spike"]]
earnings_week = [s for s in stocks if s["earnings"] and 0 <= s["earnings"]["days"] <= 7]

html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Monitor v4</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, sans-serif; background: #f0f0f0; padding: 20px; }}
        .wrap {{ max-width: 1100px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 15px rgba(0,0,0,0.1); }}
        header {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 35px; text-align: center; }}
        header h1 {{ font-size: 2.2em; margin-bottom: 8px; }}
        .alerts {{ background: #fff3cd; border-left: 5px solid #ffc107; padding: 15px 20px; margin: 0; }}
        .alert-item {{ font-weight: 600; margin: 5px 0; }}
        .content {{ padding: 30px; }}
        .stock {{ background: #f9f9f9; border-left: 5px solid #667eea; padding: 20px; margin-bottom: 20px; border-radius: 8px; }}
        .stock.spike {{ background: #ffe0e0; border-left-color: #ff6b6b; }}
        .stock.earnings {{ background: #fff8e1; border-left-color: #ffc107; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
        .ticker {{ font-size: 1.5em; font-weight: bold; color: #667eea; }}
        .price {{ font-size: 1.2em; }}
        .up {{ color: #28a745; }}
        .down {{ color: #dc3545; }}
        .meta {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 15px 0; }}
        .box {{ background: white; padding: 12px; border-radius: 6px; border: 1px solid #ddd; }}
        .box-label {{ color: #666; font-size: 0.8em; font-weight: 600; text-transform: uppercase; }}
        .box-value {{ font-size: 1.15em; font-weight: bold; margin-top: 4px; color: #333; }}
        .alerts-sec {{ background: #fff9e6; border-left: 4px solid #f39c12; padding: 12px; margin: 10px 0; border-radius: 6px; color: #d68910; font-weight: 500; }}
        .ai-box {{ background: #e8f4f8; border-left: 4px solid #2196F3; padding: 12px; margin: 10px 0; border-radius: 6px; color: #1565c0; }}
        .greeks {{ background: #f0f4ff; border: 1px solid #667eea; padding: 12px; margin: 10px 0; border-radius: 6px; }}
        .greeks-title {{ font-weight: bold; color: #667eea; margin-bottom: 8px; font-size: 0.9em; }}
        .greek-item {{ display: inline-block; margin-right: 15px; margin-bottom: 5px; font-size: 0.9em; }}
        .news {{ margin-top: 15px; }}
        .news h4 {{ font-size: 0.95em; margin-bottom: 8px; }}
        .news-item {{ background: white; padding: 10px; margin: 6px 0; border-radius: 4px; border: 1px solid #e0e0e0; }}
        .news-item a {{ color: #667eea; text-decoration: none; font-weight: 500; font-size: 0.9em; }}
        .news-item a:hover {{ text-decoration: underline; }}
        .source {{ font-size: 0.8em; color: #999; margin-top: 3px; }}
        footer {{ background: #f5f5f5; padding: 20px; text-align: center; color: #666; font-size: 0.9em; border-top: 1px solid #ddd; }}
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>📊 Stock Monitor v4</h1>
            <p>{NOW_TW.strftime('%a, %b %d, %Y · %H:%M')} Taiwan Time</p>
            <p style="font-size: 0.9em; opacity: 0.9;">AI-Powered • Volume Alerts • Earnings Calendar • Options Greeks</p>
        </header>
"""

if spikes or earnings_week:
    html += '<div class="alerts">'
    if spikes:
        html += f'<div class="alert-item">🔥 {len(spikes)} VOLUME SPIKE(s): {", ".join([s["ticker"] for s in spikes])}</div>'
    if earnings_week:
        html += f'<div class="alert-item">📚 {len(earnings_week)} EARNINGS THIS WEEK: {", ".join([s["ticker"] for s in earnings_week])}</div>'
    html += '</div>'

html += '<div class="content">'

for s in stocks:
    change_class = "up" if s["change"] > 0 else "down"
    change_sign = "+" if s["change"] > 0 else ""
    
    card_class = "stock"
    if s["spike"]:
        card_class += " spike"
    if s["earnings"] and 0 <= s["earnings"]["days"] <= 7:
        card_class += " earnings"
    
    html += f'''<div class="{card_class}">
        <div class="header">
            <span class="ticker">{s["ticker"]}</span>
            <span class="price">{s["currency"]}{s["price"]} <span class="{change_class}">({change_sign}{s["change"]}%)</span></span>
        </div>
        <div><strong>{s["name"]}</strong></div>
        
        <div class="meta">
            <div class="box">
                <div class="box-label">RSI</div>
                <div class="box-value">{s["rsi"] if s["rsi"] else "—"}</div>
            </div>
            <div class="box">
                <div class="box-label">Volume</div>
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
                <div class="box-label">Price %</div>
                <div class="box-value">{safe((s["price"] - s["l52"]) / (s["h52"] - s["l52"]) * 100 if s["h52"] != s["l52"] else 50)}%</div>
            </div>
        </div>
'''
    
    # Alerts
    if s["spike"] or (s["earnings"] and 0 <= s["earnings"]["days"] <= 7) or (s["rsi"] and (s["rsi"] > 75 or s["rsi"] < 25)):
        html += '<div class="alerts-sec">'
        if s["spike"]:
            html += f'🔥 VOLUME SPIKE: {s["vol_ratio"]}x average volume<br>'
        if s["earnings"] and 0 <= s["earnings"]["days"] <= 7:
            days = s["earnings"]["days"]
            html += f'📚 Earnings in {days} days ({s["earnings"]["date"]})<br>'
        if s["rsi"]:
            if s["rsi"] > 75:
                html += f'🔴 OVERBOUGHT (RSI={s["rsi"]})<br>'
            elif s["rsi"] < 25:
                html += f'🟢 OVERSOLD (RSI={s["rsi"]})<br>'
        html = html.rstrip('<br>')
        html += '</div>'
    
    # Options Greeks
    if s["greeks"]:
        g = s["greeks"]
        html += f'''<div class="greeks">
            <div class="greeks-title">📊 Options Greeks (Exp: {g["exp"]})</div>
            <div class="greek-item"><strong>IV:</strong> {g["iv"]}%</div>
            <div class="greek-item"><strong>Δ:</strong> {g["delta"]}</div>
            <div class="greek-item"><strong>Θ:</strong> {g["theta"]}</div>
        </div>'''
    
    # AI Summary
    if s["summary"]:
        html += f'<div class="ai-box"><strong>🤖 AI Summary:</strong><br>{s["summary"]}</div>'
    
    # News
    if s["news"]:
        html += f'<div class="news"><h4>📰 Latest News ({len(s["news"])} sources)</h4>'
        for n in s["news"][:8]:
            html += f'<div class="news-item"><a href="{n["link"]}" target="_blank">{n["title"][:80]}...</a><div class="source">{n["source"]}</div></div>'
        html += '</div>'
    
    html += '</div>'

html += f'''</div>
    <footer>
        <p>🤖 Stock Monitor v4 • AI-Powered • Free Data Sources</p>
        <p>Sources: Yahoo Finance, MarketWatch, Seeking Alpha, Google News | Updates: 4 AM & 4 PM Taiwan Time</p>
    </footer>
    </div>
</body>
</html>'''

try:
    (DOCS / "index.html").write_text(html)
    print("\n✅ Dashboard generated successfully!")
    print(f"   - {len(stocks)} stocks analyzed")
    print(f"   - {len(spikes)} volume spikes detected")
    print(f"   - {len(earnings_week)} earnings this week")
except Exception as e:
    print(f"❌ Error: {e}")
