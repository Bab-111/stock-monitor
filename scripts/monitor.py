#!/usr/bin/env python3
import yfinance as yf
import feedparser
import requests
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import warnings
warnings.filterwarnings('ignore')

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
STOCKS_FILE = ROOT / "stocks.json"
DOCS.mkdir(exist_ok=True)

TAIWAN_TZ = ZoneInfo("Asia/Taipei")
NOW_TW = datetime.datetime.now(TAIWAN_TZ)

with open(STOCKS_FILE) as f:
    config = json.load(f)
TICKERS = config.get("tickers", [])

print(f"[Stock Monitor v4] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks\n")

def safe(v, d=2):
    try:
        return round(float(v), d)
    except:
        return None

def get_stock_data(ticker):
    """Get complete stock data from yfinance"""
    try:
        t = yf.Ticker(ticker)
        i = t.info
        
        # Basic price data
        p = i.get("currentPrice") or i.get("regularMarketPrice") or 0
        prev = i.get("previousClose") or i.get("regularMarketPreviousClose") or p
        vol = i.get("regularMarketVolume") or 0
        avg_vol = i.get("averageVolume") or vol
        
        chg = safe((p - prev) / prev * 100) if prev else 0
        vol_ratio = safe(vol / avg_vol) if avg_vol else 1.0
        spike = vol_ratio >= 2.0
        
        # Get historical data for RSI
        hist = t.history(period="60d")
        rsi = None
        if len(hist) >= 14:
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_vals = 100 - (100 / (1 + rs))
            rsi = safe(rsi_vals.iloc[-1], 0)
        
        # Earnings date
        earnings = None
        try:
            ed = i.get("earningsDate")
            if ed and isinstance(ed, (list, tuple)) and len(ed) > 0:
                from datetime import datetime as dt
                date = dt.fromtimestamp(ed[0], tz=TAIWAN_TZ)
                days = (date.date() - NOW_TW.date()).days
                earnings = {"date": date.strftime('%Y-%m-%d'), "days": days}
        except:
            pass
        
        # Options Greeks
        greeks = None
        try:
            exps = t.options
            if exps and len(exps) > 0:
                chain = t.option_chain(exps[0])
                calls = chain.calls
                if len(calls) > 0 and p:
                    atm = calls.iloc[(calls['strike'] - p).abs().argsort()[:1]]
                    greeks = {
                        "iv": safe(float(atm['impliedVolatility'].values[0]) * 100, 1),
                        "delta": safe(float(atm['delta'].values[0]), 3),
                        "theta": safe(float(atm['theta'].values[0]), 4),
                        "exp": str(exps[0])
                    }
        except:
            pass
        
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
        }
    except Exception as e:
        print(f"  Error {ticker}: {str(e)[:40]}")
        return None

def get_news(ticker):
    """Get news from multiple FREE sources"""
    items = []
    
    # Yahoo Finance
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        for e in feed.entries[:3]:
            items.append({"title": e.get("title", "")[:85], "link": e.get("link", ""), "source": "Yahoo Finance"})
    except:
        pass
    
    # Google News
    try:
        q = requests.utils.quote(f"{ticker} stock")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        for e in feed.entries[:3]:
            items.append({"title": e.get("title", "")[:85], "link": e.get("link", ""), "source": "Google News"})
    except:
        pass
    
    # MarketWatch
    try:
        feed = feedparser.parse("https://feeds.marketwatch.com/marketwatch/topstories/")
        for e in feed.entries[:5]:
            if ticker.lower() in e.get("title", "").lower():
                items.append({"title": e.get("title", "")[:85], "link": e.get("link", ""), "source": "MarketWatch"})
                if len(items) >= 10:
                    break
    except:
        pass
    
    # Finviz (free news)
    try:
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            news_table = soup.find("table", {"class": "news-table"})
            if news_table:
                for row in news_table.findAll('tr')[:3]:
                    cols = row.findAll('td')
                    if len(cols) >= 2:
                        link = cols[1].find('a')
                        if link:
                            items.append({
                                "title": link.text[:85],
                                "link": link.get('href', ''),
                                "source": "Finviz"
                            })
    except:
        pass
    
    return items[:12]

def summarize_news(ticker, news_items):
    """Create summary from news keywords"""
    if not news_items:
        return None
    
    keywords = {
        'positive': ['beat', 'surge', 'rally', 'jump', 'gain', 'bullish', 'strong', 'upgrade', 'partnership', 'acquisition', 'launch', 'breakthrough'],
        'negative': ['miss', 'plunge', 'crash', 'downgrade', 'decline', 'bearish', 'weak', 'loss', 'cut', 'recall', 'lawsuit'],
        'earnings': ['earnings', 'revenue', 'profit', 'guidance', 'quarter', 'fy'],
    }
    
    pos_count = 0
    neg_count = 0
    earn_found = False
    
    titles = [n['title'].lower() for n in news_items[:5]]
    all_text = ' '.join(titles)
    
    for word in keywords['positive']:
        pos_count += all_text.count(word)
    for word in keywords['negative']:
        neg_count += all_text.count(word)
    for word in keywords['earnings']:
        if word in all_text:
            earn_found = True
    
    summary = []
    if earn_found:
        summary.append("📊 Earnings/Financial news detected")
    if pos_count > neg_count:
        summary.append(f"📈 Bullish sentiment ({pos_count} positive mentions)")
    elif neg_count > pos_count:
        summary.append(f"📉 Bearish sentiment ({neg_count} negative mentions)")
    else:
        summary.append("➡️ Mixed/Neutral sentiment")
    
    top_news = news_items[0]['title'] if news_items else ""
    if top_news:
        summary.append(f"Latest: {top_news[:60]}...")
    
    return " | ".join(summary)

print("Fetching complete data...")
stocks = []
for ticker in TICKERS:
    data = get_stock_data(ticker)
    if data:
        data["news"] = get_news(ticker)
        data["summary"] = summarize_news(ticker, data["news"])
        stocks.append(data)
        print(f"  ✓ {ticker}")

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
        .box-label {{ color: #666; font-size: 0.8em; font-weight: 600; }}
        .box-value {{ font-size: 1.15em; font-weight: bold; margin-top: 4px; color: #333; }}
        .alerts-sec {{ background: #fff9e6; border-left: 4px solid #f39c12; padding: 12px; margin: 10px 0; border-radius: 6px; color: #d68910; font-weight: 500; }}
        .summary {{ background: #e8f4f8; border-left: 4px solid #2196F3; padding: 12px; margin: 10px 0; border-radius: 6px; color: #1565c0; }}
        .greeks {{ background: #f0f4ff; border: 1px solid #667eea; padding: 12px; margin: 10px 0; border-radius: 6px; }}
        .greeks-title {{ font-weight: bold; color: #667eea; margin-bottom: 8px; }}
        .greek-item {{ display: inline-block; margin-right: 15px; margin-bottom: 5px; }}
        .news {{ margin-top: 15px; }}
        .news h4 {{ font-size: 0.95em; margin-bottom: 8px; }}
        .news-item {{ background: white; padding: 10px; margin: 6px 0; border-radius: 4px; border: 1px solid #e0e0e0; }}
        .news-item a {{ color: #667eea; text-decoration: none; font-weight: 500; font-size: 0.9em; }}
        .source {{ font-size: 0.8em; color: #999; margin-top: 3px; }}
        footer {{ background: #f5f5f5; padding: 20px; text-align: center; color: #666; font-size: 0.9em; border-top: 1px solid #ddd; }}
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>📊 Stock Monitor v4</h1>
            <p>{NOW_TW.strftime('%a, %b %d, %Y · %H:%M')} Taiwan Time</p>
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
    
    rsi_display = f"{int(s['rsi'])}" if s["rsi"] else "—"
    
    html += f'<div class="{card_class}"><div class="header"><span class="ticker">{s["ticker"]}</span><span class="price">{s["currency"]}{s["price"]} <span class="{change_class}">({change_sign}{s["change"]}%)</span></span></div><div><strong>{s["name"]}</strong></div>'
    
    html += f'<div class="meta"><div class="box"><div class="box-label">RSI</div><div class="box-value">{rsi_display}</div></div><div class="box"><div class="box-label">Volume</div><div class="box-value">{s["vol_ratio"]}x</div></div><div class="box"><div class="box-label">52w Low</div><div class="box-value">{s["currency"]}{s["l52"]}</div></div><div class="box"><div class="box-label">52w High</div><div class="box-value">{s["currency"]}{s["h52"]}</div></div><div class="box"><div class="box-label">Price %</div><div class="box-value">{safe((s["price"] - s["l52"]) / (s["h52"] - s["l52"]) * 100) if s["h52"] != s["l52"] else "—"}%</div></div></div>'
    
    if s["spike"] or (s["earnings"] and 0 <= s["earnings"]["days"] <= 7) or (s["rsi"] and (s["rsi"] > 75 or s["rsi"] < 25)):
        html += '<div class="alerts-sec">'
        alerts = []
        if s["spike"]:
            alerts.append(f'🔥 VOLUME SPIKE: {s["vol_ratio"]}x')
        if s["earnings"] and 0 <= s["earnings"]["days"] <= 7:
            alerts.append(f'📚 EARNINGS: {s["earnings"]["days"]} days ({s["earnings"]["date"]})')
        if s["rsi"]:
            if s["rsi"] > 75:
                alerts.append(f'🔴 OVERBOUGHT: RSI {int(s["rsi"])}')
            elif s["rsi"] < 25:
                alerts.append(f'🟢 OVERSOLD: RSI {int(s["rsi"])}')
        html += ' | '.join(alerts)
        html += '</div>'
    
    if s["summary"]:
        html += f'<div class="summary"><strong>📊 Summary:</strong> {s["summary"]}</div>'
    
    if s["greeks"]:
        g = s["greeks"]
        html += f'<div class="greeks"><div class="greeks-title">📊 Options Greeks (Exp: {g["exp"]})</div><div class="greek-item"><strong>IV:</strong> {g["iv"]}%</div><div class="greek-item"><strong>Δ:</strong> {g["delta"]}</div><div class="greek-item"><strong>Θ:</strong> {g["theta"]}</div></div>'
    
    if s["news"]:
        html += f'<div class="news"><h4>📰 Latest News ({len(s["news"])} sources)</h4>'
        for n in s["news"][:10]:
            html += f'<div class="news-item"><a href="{n["link"]}" target="_blank">{n["title"]}</a><div class="source">{n["source"]}</div></div>'
        html += '</div>'
    
    html += '</div>'

html += f'</div><footer><p>🤖 Stock Monitor v4 • Volume Alerts • Earnings • RSI • Options Greeks • FREE Data Sources</p><p>Sources: Yahoo Finance, Google News, MarketWatch, Finviz | Updates: 4 AM & 4 PM Taiwan Time</p></footer></div></body></html>'

(DOCS / "index.html").write_text(html)
print("\n✅ Dashboard generated successfully!")
print(f"   ✓ {len(stocks)} stocks")
print(f"   ✓ {len(spikes)} volume spikes")
print(f"   ✓ {len(earnings_week)} earnings alerts")
