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

def get_five_day_avg_volume(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        if len(hist) == 0:
            return None
        avg = hist['Volume'].mean()
        return safe(avg)
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

def get_earnings_date(ticker):
    try:
        info = yf.Ticker(ticker).info
        earnings_date = info.get("earningsDate")
        if earnings_date:
            if isinstance(earnings_date, (list, tuple)) and len(earnings_date) > 0:
                earnings_date = earnings_date[0]
            try:
                from datetime import datetime as dt
                if isinstance(earnings_date, (int, float)):
                    ed = dt.fromtimestamp(earnings_date, tz=TAIWAN_TZ)
                else:
                    ed = datetime.datetime.fromisoformat(str(earnings_date))
                days_away = (ed.date() - NOW_TW.date()).days
                return {"date": ed.strftime('%Y-%m-%d'), "days_away": days_away}
            except:
                pass
    except:
        pass
    return None

def fetch_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
        vol = info.get("regularMarketVolume")
        avg_vol = info.get("averageVolume")
        
        five_day_avg = get_five_day_avg_volume(ticker)
        vol_ratio = safe(vol / avg_vol) if vol and avg_vol else None
        five_day_ratio = safe(vol / five_day_avg) if vol and five_day_avg else None
        
        volume_spike = False
        if five_day_ratio and five_day_ratio >= 2.0:
            volume_spike = True
        
        chg = safe((price - prev) / prev * 100) if price and prev else None
        rsi = calc_rsi(ticker)
        
        return {
            "ticker": ticker,
            "name": info.get("longName", ticker),
            "price": safe(price),
            "change_pct": chg,
            "volume_ratio": vol_ratio,
            "five_day_vol_ratio": five_day_ratio,
            "volume_spike": volume_spike,
            "rsi": rsi,
            "week_52_high": safe(info.get("fiftyTwoWeekHigh")),
            "week_52_low": safe(info.get("fiftyTwoWeekLow")),
            "currency": info.get("currency", "USD"),
            "earnings": get_earnings_date(ticker),
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return {"ticker": ticker, "error": str(e)}

def fetch_news(ticker):
    items = []
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        for e in feed.entries[:3]:
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "source": "Yahoo Finance",
                "published": e.get("published", "N/A"),
                "summary": e.get("summary", "")[:200]
            })
    except:
        pass
    try:
        q = requests.utils.quote(f"{ticker} stock")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        for e in feed.entries[:2]:
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "source": "Google News",
                "published": e.get("published", "N/A"),
                "summary": e.get("summary", "")[:200]
            })
    except:
        pass
    return items[:5]

def ai_summarize_news(ticker, news_items, stock_data):
    if not news_items or not GITHUB_TOKEN:
        return None
    
    news_text = "\n".join([f"- [{item['source']}] {item['title']}\n  {item['summary']}" for item in news_items])
    
    prompt = f"""Analyze ONLY the provided news for {ticker}. Be brief and factual.
    
News:
{news_text}

Summary (max 3 bullet points):"""
    
    try:
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a financial analyst. Summarize ONLY using provided facts."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "top_p": 0.1,
            "max_tokens": 200,
        }
        
        response = requests.post(MODELS_API, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            summary = result["choices"][0]["message"]["content"].strip()
            return summary
        else:
            return None
    except:
        return None

def analyze_stock(s):
    chg = s.get("change_pct") or 0
    vol = s.get("five_day_vol_ratio") or 1
    rsi = s.get("rsi") or 50
    
    signals = []
    
    if vol >= 2.0:
        signals.append(f"🔥 VOLUME SPIKE: {vol}x average")
    if chg >= 5:
        signals.append(f"🚀 Strong rally: +{chg}%")
    elif chg <= -5:
        signals.append(f"📉 Heavy drop: {chg}%")
    if rsi > 75:
        signals.append("🔴 Overbought (RSI>75)")
    elif rsi < 25:
        signals.append("🟢 Oversold (RSI<25)")
    if s.get("earnings") and s["earnings"].get("days_away"):
        days = s["earnings"]["days_away"]
        if 0 <= days <= 7:
            signals.append(f"📚 EARNINGS in {days} days")
    
    return " | ".join(signals) if signals else "Normal"

print("\n[Fetching] Downloading stock data...")
all_data = []
for ticker in TICKERS:
    data = fetch_stock(ticker)
    data["news"] = fetch_news(ticker)
    
    if data.get("news") and not data.get("error"):
        print(f"  [AI] Summarizing {ticker}...")
        data["ai_summary"] = ai_summarize_news(ticker, data["news"], data)
    
    all_data.append(data)
    print(f"  ✓ {ticker}")

volume_spikes = [s for s in all_data if s.get("volume_spike") and "error" not in s]
earnings_soon = [s for s in all_data if s.get("earnings") and s["earnings"].get("days_away") and 0 <= s["earnings"]["days_away"] <= 7 and "error" not in s]

html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Monitor v4</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; color: #333; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); overflow: hidden; }}
        header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px 30px; text-align: center; }}
        header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        .timestamp {{ font-size: 1em; opacity: 0.9; margin-bottom: 15px; }}
        .alerts-banner {{ background: #fff3cd; border-bottom: 3px solid #ffc107; padding: 15px 30px; display: flex; gap: 20px; flex-wrap: wrap; }}
        .alert-box {{ display: flex; align-items: center; gap: 10px; font-weight: 600; }}
        .content {{ padding: 40px; }}
        .section {{ margin-bottom: 40px; }}
        .section h2 {{ font-size: 1.8em; margin-bottom: 20px; color: #667eea; border-bottom: 3px solid #667eea; padding-bottom: 10px; }}
        .stock-card {{ background: #f8f9fa; border-left: 5px solid #667eea; padding: 25px; margin-bottom: 25px; border-radius: 8px; }}
        .stock-card.volume-spike {{ border-left-color: #ff6b6b; background: #ffe0e0; }}
        .stock-card.earnings-alert {{ border-left-color: #ffc107; background: #fff8e1; }}
        .stock-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
        .ticker {{ font-size: 1.6em; font-weight: bold; color: #667eea; }}
        .price {{ font-size: 1.3em; font-weight: 600; }}
        .change.positive {{ color: #28a745; }}
        .change.negative {{ color: #dc3545; }}
        .alerts {{ background: #fff9e6; border: 1px solid #ffc107; padding: 12px; border-radius: 6px; margin-bottom: 15px; font-weight: 500; color: #e67e22; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 15px; }}
        .metric {{ background: white; padding: 12px; border-radius: 6px; border: 1px solid #e0e0e0; }}
        .metric-label {{ color: #666; font-weight: 600; font-size: 0.9em; }}
        .metric-value {{ color: #333; font-size: 1.2em; margin-top: 4px; font-weight: 600; }}
        .ai-summary {{ background: #e8f4f8; border-left: 4px solid #2196F3; padding: 15px; margin-top: 15px; border-radius: 4px; font-size: 0.95em; line-height: 1.6; color: #1565c0; }}
        .signal {{ background: #fff9e6; border-left: 4px solid #f39c12; padding: 12px; margin-top: 10px; border-radius: 4px; color: #d68910; font-weight: 500; }}
        .news {{ margin-top: 15px; font-size: 0.9em; }}
        .news-item {{ margin: 10px 0; padding: 10px; background: white; border-radius: 4px; border: 1px solid #e0e0e0; }}
        .news-item a {{ color: #667eea; text-decoration: none; font-weight: 500; }}
        .source {{ font-size: 0.8em; color: #999; margin-top: 4px; }}
        footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; font-size: 0.9em; border-top: 1px solid #e0e0e0; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Stock Monitor v4</h1>
            <div class="timestamp">
                Updated: {NOW_TW.strftime('%a, %b %d, %Y · %H:%M')} Taiwan Time<br>
                <small>AI-Powered • Volume Alerts • Earnings Calendar • News Summary</small>
            </div>
        </header>
"""

if volume_spikes or earnings_soon:
    html_content += '<div class="alerts-banner">'
    if volume_spikes:
        html_content += f'<div class="alert-box">🔥 {len(volume_spikes)} VOLUME SPIKE(s)</div>'
    if earnings_soon:
        html_content += f'<div class="alert-box">📚 {len(earnings_soon)} EARNINGS THIS WEEK</div>'
    html_content += '</div>'

html_content += '<div class="content"><div class="section"><h2>📈 Stock Analysis</h2>'

for s in all_data:
    if "error" in s:
        html_content += f'<div class="stock-card"><span class="ticker">{s["ticker"]}</span><p style="color: red;">Error: {s["error"]}</p></div>'
        continue
    
    change_class = "positive" if (s.get("change_pct") or 0) > 0 else "negative"
    change_sign = "+" if (s.get("change_pct") or 0) > 0 else ""
    
    card_class = "stock-card"
    if s.get("volume_spike"):
        card_class += " volume-spike"
    if s.get("earnings") and s["earnings"].get("days_away") and 0 <= s["earnings"]["days_away"] <= 7:
        card_class += " earnings-alert"
    
    html_content += f'<div class="{card_class}">'
    html_content += f'<div class="stock-header"><span class="ticker">{s["ticker"]}</span><span class="price">{s["currency"]}{s["price"]} <span class="change {change_class}">({change_sign}{s["change_pct"]}%)</span></span></div>'
    html_content += f'<div><strong>{s["name"]}</strong></div>'
    
    alerts = []
    if s.get("volume_spike"):
        alerts.append(f"🔥 Volume: {s['five_day_vol_ratio']}x average")
    if s.get("earnings") and s["earnings"].get("days_away"):
        days = s["earnings"]["days_away"]
        if days == 0:
            alerts.append("📚 EARNINGS TODAY!")
        elif 0 < days <= 7:
            alerts.append(f"📚 Earnings in {days} days ({s['earnings']['date']})")
    
    if alerts:
        html_content += '<div class="alerts">' + '<br>'.join(alerts) + '</div>'
    
    html_content += '<div class="metrics">'
    html_content += f'<div class="metric"><div class="metric-label">RSI</div><div class="metric-value">{s.get("rsi", "N/A")}</div></div>'
    html_content += f'<div class="metric"><div class="metric-label">52w Low</div><div class="metric-value">{s["currency"]}{s["week_52_low"]}</div></div>'
    html_content += f'<div class="metric"><div class="metric-label">52w High</div><div class="metric-value">{s["currency"]}{s["week_52_high"]}</div></div>'
    html_content += '</div>'
    
    html_content += f'<div class="signal">{analyze_stock(s)}</div>'
    
    if s.get("ai_summary"):
        html_content += f'<div class="ai-summary"><strong>🤖 AI Analysis:</strong><br>{s["ai_summary"]}</div>'
    
    if s.get("news"):
        html_content += '<div class="news"><strong>📰 Latest News:</strong>'
        for n in s["news"][:3]:
            title = n['title'][:80]
            html_content += f'<div class="news-item"><a href="{n["link"]}" target="_blank">{title}</a><div class="source">{n["source"]}</div></div>'
        html_content += '</div>'
    
    html_content += '</div>'

html_content += '</div></div><footer><p>🤖 Stock Monitor v4 • AI-Powered • Fact-Checked • 100% FREE</p></footer></div></body></html>'

try:
    (DOCS / "index.html").write_text(html_content, encoding='utf-8')
    print("[✓] Dashboard generated successfully!")
except Exception as e:
    print(f"Error: {e}")
    exit(1)

print("\n✅ Stock Monitor completed!")
