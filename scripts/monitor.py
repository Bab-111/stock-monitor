#!/usr/bin/env python3
"""
Stock Monitor v4 - Professional Grade
Features:
- Volume alerts (2x spike detection)
- Earnings calendar
- Multi-source news (Yahoo, Google, yfinance)
- AI-powered summaries (GitHub Models API - FREE Claude 3.5)
- Options Greeks (for major tickers)
- Beautiful HTML dashboard
"""

import yfinance as yf
import feedparser
import requests
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import re

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

# GitHub Models API (FREE)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
MODELS_API = "https://models.inference.ai.azure.com/chat/completions"

# Load config
try:
    with open(STOCKS_FILE) as f:
        config = json.load(f)
    TICKERS = config.get("tickers", [])
except Exception as e:
    print(f"❌ Error loading stocks.json: {e}")
    exit(1)

print(f"[Stock Monitor v4] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks")

# ════════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════════
def safe(val, dec=2):
    try:
        return round(float(val), dec)
    except:
        return None

def get_five_day_avg_volume(ticker):
    """Get 5-day average volume for comparison"""
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
    """Get next earnings date if available"""
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
    """Fetch stock data with volume spike detection"""
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
        
        greeks = get_options_greeks(ticker)
        
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
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency", "USD"),
            "earnings": get_earnings_date(ticker),
            "greeks": greeks,
        }
    except Exception as e:
        print(f"⚠️ Error fetching {ticker}: {e}")
        return {"ticker": ticker, "error": str(e)}

def get_options_greeks(ticker):
    """Fetch options Greeks (IV, delta, theta) - only for major tickers"""
    try:
        stock = yf.Ticker(ticker)
        expirations = stock.options
        if not expirations:
            return None
        
        opts = stock.option_chain(expirations[0])
        calls = opts.calls
        
        if len(calls) == 0:
            return None
        
        price = stock.info.get("currentPrice") or stock.info.get("regularMarketPrice")
        atm_call = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]
        
        if len(atm_call) == 0:
            return None
        
        return {
            "iv": safe(atm_call['impliedVolatility'].values[0] * 100, 2),
            "delta": safe(atm_call['delta'].values[0], 3),
            "theta": safe(atm_call['theta'].values[0], 4),
            "expiration": expirations[0],
        }
    except:
        return None

def fetch_news(ticker):
    """Fetch news from multiple sources"""
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
    """Use GitHub Models API (FREE Claude 3.5) to summarize news intelligently."""
    
    if not news_items or not GITHUB_TOKEN:
        return None
    
    news_text = "\n".join([f"- [{item['source']}] {item['title']}\n  {item['summary']}" for item in news_items])
    
    stock_context = f"""
Current Stock Data:
- Price: {stock_data['price']} ({stock_data['change_pct']}%)
- Volume Spike: {'YES (2x+)' if stock_data.get('volume_spike') else 'No'}
- Earnings: {stock_data.get('earnings', {}).get('date', 'Not scheduled') if stock_data.get('earnings') else 'N/A'}
"""
    
    prompt = f"""
Analyze ONLY the provided news for ticker {ticker}. Follow these rules strictly:

1. ONLY use facts from the news below - NO speculation or assumption
2. Highlight: Earnings dates, regulatory changes, product launches, insider trades, partnerships
3. Note sentiment: Positive, Negative, or Neutral
4. Keep summary BRIEF (max 3-4 bullet points)
5. Include sources for each claim
6. Flag if any conflicting information exists

{stock_context}

News Items:
{news_text}

Provide a concise, fact-based summary:
"""
    
    try:
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a financial analyst. Summarize ONLY using provided facts. No speculation."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "top_p": 0.1,
            "max_tokens": 300,
        }
        
        response = requests.post(MODELS_API, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            summary = result["choices"][0]["message"]["content"].strip()
            return summary
        else:
            print(f"⚠️ AI API error {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"⚠️ AI summarization failed: {e}")
        return None

def analyze_stock(s):
    """Generate trading signal from data"""
    chg = s.get("change_pct") or 0
    vol = s.get("five_day_vol_ratio") or 1
    rsi = s.get("rsi") or 50
    
    signals = []
    
    if vol >= 2.5:
        signals.append("🔥 EXTREME volume spike (2.5x+) - major news likely")
    elif vol >= 2.0:
        signals.append("⚡ VOLUME SPIKE (2x+) - unusual activity")
    elif vol >= 1.5:
        signals.append("📊 Elevated volume - above average interest")
    
    if chg >= 7:
        signals.append("🚀 Strong rally - momentum buy")
    elif chg >= 4:
        signals.append("📈 Gaining momentum")
    elif chg <= -7:
        signals.append("📉 Heavy selling - potential bounce zone")
    elif chg <= -4:
        signals.append("⬇️ Losing momentum")
    
    if rsi > 75:
        signals.append("🔴 Overbought (RSI>75) - pullback likely")
    elif rsi < 25:
        signals.append("🟢 Oversold (RSI<25) - bounce opportunity")
    
    if s.get("earnings") and s["earnings"].get("days_away"):
        days = s["earnings"]["days_away"]
        if 0 <= days <= 7:
            signals.append(f"📚 EARNINGS in {days} days - expect volatility")
    
    return signals[0] if signals else "Normal trading pattern"

# ════════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ════════════════════════════════════════════════════════════════════════════════
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

# ════════════════════════════════════════════════════════════════════════════════
# BUILD HTML
# ════════════════════════════════════════════════════════════════════════════════
print("\n[Generating] Creating HTML dashboard...")

volume_spikes = [s for s in all_data if s.get("volume_spike") and "error" not in s]
earnings_soon = [s for s in all_data if s.get("earnings") and s["earnings"].get("days_away") and 0 <= s["earnings"]["days_away"] <= 7 and "error" not in s]

html_head = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Daily Stock Brief v4</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }}
        .container {{
            max-width: 1200px;
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
            font-size: 1em;
            opacity: 0.9;
            margin-bottom: 15px;
        }}
        .alerts-banner {{
            background: #fff3cd;
            border-bottom: 3px solid #ffc107;
            padding: 15px 30px;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}
        .alert-box {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 600;
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
            padding: 25px;
            margin-bottom: 25px;
            border-radius: 8px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .stock-card.volume-spike {{
            border-left-color: #ff6b6b;
            background: #ffe0e0;
        }}
        .stock-card.earnings-alert {{
            border-left-color: #ffc107;
            background: #fff8e1;
        }}
        .stock-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.2);
        }}
        .stock-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}
        .ticker {{
            font-size: 1.6em;
            font-weight: bold;
            color: #667eea;
        }}
        .price {{
            font-size: 1.3em;
            font-weight: 600;
        }}
        .change.positive {{
            color: #28a745;
        }}
        .change.negative {{
            color: #dc3545;
        }}
        .alerts {{
            background: #fff9e6;
            border: 1px solid #ffc107;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 15px;
            font-weight: 500;
            color: #e67e22;
        }}
        .alert-item {{
            margin: 5px 0;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 15px;
        }}
        .metric {{
            background: white;
            padding: 12px;
            border-radius: 6px;
            border: 1px solid #e0e0e0;
        }}
        .metric-label {{
            color: #666;
            font-weight: 600;
            font-size: 0.9em;
        }}
        .metric-value {{
            color: #333;
            font-size: 1.2em;
            margin-top: 4px;
            font-weight: 600;
        }}
        .volume-spike-badge {{
            display: inline-block;
            background: #ff6b6b;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 0.85em;
        }}
        .ai-summary {{
            background: #e8f4f8;
            border-left: 4px solid #2196F3;
            padding: 15px;
            margin-top: 15px;
            border-radius: 4px;
            font-size: 0.95em;
            line-height: 1.6;
            color: #1565c0;
        }}
        .news {{
            margin-top: 15px;
            font-size: 0.9em;
        }}
        .news-item {{
            margin: 10px 0;
            padding: 10px;
            background: white;
            border-radius: 4px;
            border: 1px solid #e0e0e0;
        }}
        .news-item a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 500;
        }}
        .news-item a:hover {{
            text-decoration: underline;
        }}
        .source {{
            font-size: 0.8em;
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
        }}
        .signal-box h3 {{
            margin-bottom: 10px;
            font-size: 1.2em;
        }}
        .signal-list {{
            list-style: none;
        }}
        .signal-list li {{
            margin: 8px 0;
            padding-left: 20px;
            position: relative;
        }}
        .signal-list li:before {{
            content: "✓";
            position: absolute;
            left: 0;
            font-weight: bold;
        }}
        .greeks {{
            background: #f0f4ff;
            border: 1px solid #667eea;
            padding: 12px;
            border-radius: 6px;
            font-size: 0.9em;
            margin-top: 10px;
        }}
        .greeks-title {{
            font-weight: bold;
            color: #667eea;
            margin-bottom: 8px;
        }}
        .greek-item {{
            display: inline-block;
            margin-right: 15px;
            margin-bottom: 5px;
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
            .alerts-banner {{
                flex-direction: column;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Daily Stock Brief v4</h1>
            <div class="timestamp">
                {NOW_TW.strftime('%a, %b %d, %Y · %H:%M')} Taiwan Time<br>
                <small>AI-Powered • Fact-Checked • Volume Alerts • Earnings Calendar</small>
            </div>
        </header>
"""

if volume_spikes or earnings_soon:
    html_head += '<div class="alerts-banner">'
    if volume_spikes:
        html_head += f'<div class="alert-box">🔥 {len(volume_spikes)} VOLUME SPIKE(s): {", ".join([s["ticker"] for s in volume_spikes])}</div>'
    if earnings_soon:
        html_head += f'<div class="alert-box">📚 {len(earnings_soon)} EARNINGS COMING: {", ".join([s["ticker"] for s in earnings_soon])}</div>'
    html_head += '</div>'

html_head += '<div class="content">'

signal_gainers = [s for s in all_data if "error" not in s and (s.get("change_pct") or -999) > 3]
signal_losers = [s for s in all_data if "error" not in s and (s.get("change_pct") or 999) < -3]
signal_volume = [s for s in all_data if s.get("volume_spike") and "error" not in s]

html_signals = '<div class="section"><h2>🎯 Quick Signals</h2><div class="quick-signals">'
if signal_gainers:
    html_signals += '<div class="signal-box"><h3>🚀 Gainers</h3><ul class="signal-list">'
    for s in signal_gainers:
        html_signals += f'<li><strong>{s["ticker"]}</strong>: +{s["change_pct"]}%</li>'
    html_signals += '</ul></div>'
if signal_losers:
    html_signals += '<div class="signal-box"><h3>📉 Losers</h3><ul class="signal-list">'
    for s in signal_losers:
        html_signals += f'<li><strong>{s["ticker"]}</strong>: {s["change_pct"]}%</li>'
    html_signals += '</ul></div>'
if signal_volume:
    html_signals += '<div class="signal-box"><h3>⚡ Volume Spike</h3><ul class="signal-list">'
    for s in signal_volume:
        ratio = s.get("five_day_vol_ratio", "N/A")
        html_signals += f'<li><strong>{s["ticker"]}</strong>: {ratio}x avg</li>'
    html_signals += '</ul></div>'
html_signals += '</div></div>'

html_stocks = '<div class="section"><h2>📈 Stock Analysis</h2>'

for s in all_data:
    if "error" in s:
        html_stocks += f'<div class="stock-card"><div class="stock-header"><span class="ticker">{s["ticker"]}</span></div><div style="color: #dc3545;">⚠️ {s["error"]}</div></div>'
        continue
    
    ticker = s["ticker"]
    change_class = "positive" if (s['change_pct'] or 0) > 0 else "negative"
    change_sign = "+" if (s['change_pct'] or 0) > 0 else ""
    
    card_class = "stock-card"
    if s.get("volume_spike"):
        card_class += " volume-spike"
    if s.get("earnings") and s["earnings"].get("days_away") and 0 <= s["earnings"]["days_away"] <= 7:
        card_class += " earnings-alert"
    
    html_stocks += f'<div class="{card_class}">'
    
    html_stocks += f'<div class="stock-header"><span class="ticker">{ticker}'
    if s.get("volume_spike"):
        html_stocks += ' <span class="volume-spike-badge">VOLUME 2x+</span>'
    html_stocks += f'</span><span class="price">{s["currency"]}{s["price"]} <span class="change {change_class}">({change_sign}{s["change_pct"]}%)</span></span></div>'
    
    html_stocks += f'<div><strong>{s["name"]}</strong></div>'
    
    alerts = []
    if s.get("volume_spike"):
        alerts.append(f"🔥 Volume Spike: {s['five_day_vol_ratio']}x (5-day avg)")
    if s.get("earnings") and s["earnings"].get("days_away"):
        days = s["earnings"]["days_away"]
        if days == 0:
            alerts.append("📚 EARNINGS TODAY!")
        elif 0 < days <= 7:
            alerts.append(f"📚 Earnings in {days} days ({s['earnings']['date']})")
    
    if alerts:
        html_stocks += '<div class="alerts">'
        for alert in alerts:
            html_stocks += f'<div class="alert-item">{alert}</div>'
        html_stocks += '</div>'
    
    html_stocks += '<div class="metrics">'
    html_stocks += f'<div class="metric"><div class="metric-label">Volume (5-day)</div><div class="metric-value">{s["five_day_vol_ratio"]}x avg</div></div>'
    html_stocks += f'<div class="metric"><div class="metric-label">RSI</div><div class="metric-value">{s["rsi"] or "N/A"}</div></div>'
    html_stocks += f'<div class="metric"><div class="metric-label">52w Low</div><div class="metric-value">{s["currency"]}{s["week_52_low"]}</div></div>'
    html_stocks += f'<div class="metric"><div class="metric-label">52w High</div><div class="metric-value">{s["currency"]}{s["week_52_high"]}</div></div>'
    html_stocks += '</div>'
    
    html_stocks += f'<div class="ai-summary" style="background: #fff9e6; border-left-color: #f39c12; color: #d68910;">📌 <strong>Signal:</strong> {analyze_stock(s)}</div>'
    
    if s.get("greeks"):
        greeks = s["greeks"]
        html_stocks += '<div class="greeks"><div class="greeks-title">📊 Options Greeks</div>'
        html_stocks += f'<div class="greek-item"><strong>IV:</strong> {greeks["iv"]}%</div>'
        html_stocks += f'<div class="greek-item"><strong>Δ:</strong> {greeks["delta"]}</div>'
        html_stocks += f'<div class="greek-item"><strong>Θ:</strong> {greeks["theta"]}</div>'
        html_stocks += f'<div class="greek-item"><small>Exp: {greeks["expiration"]}</small></div>'
        html_stocks += '</div>'
    
    if s.get("ai_summary"):
        html_stocks += f'<div class="ai-summary"><strong>🤖 AI Analysis:</strong><br>{s["ai_summary"]}</div>'
    
    if s.get("news"):
        html_stocks += '<div class="news"><strong>📰 Latest News:</strong>'
        for n in s["news"][:4]:
            title = n['title'][:100]
            html_stocks += f'<div class="news-item"><a href="{n["link"]}" target="_blank" rel="noopener">{title}</a><div class="source">{n["source"]} • {n["published"]}</div></div>'
        html_stocks += '</div>'
    
    html_stocks += '</div>'

html_stocks += '</div>'

next_update = (NOW_TW + datetime.timedelta(hours=12)).strftime('%a %H:%M TW')

html_footer = f"""
            <div style="background: #f0f4ff; border-left: 4px solid #667eea; padding: 15px; border-radius: 6px; margin-top: 20px;">
                <h4 style="color: #667eea; margin-bottom: 10px;">📊 Key Metrics Explained</h4>
                <ul style="color: #667eea; font-size: 0.9em;">
                    <li><strong>Volume 2x+:</strong> Spike detected vs 5-day average = unusual activity</li>
                    <li><strong>RSI > 70:</strong> Overbought (pullback likely) 🔴</li>
                    <li><strong>RSI < 30:</strong> Oversold (bounce opportunity) 🟢</li>
                    <li><strong>IV (Implied Vol):</strong> Options market volatility expectation</li>
                    <li><strong>Delta (Δ):</strong> Price sensitivity to underlying moves</li>
                    <li><strong>Theta (Θ):</strong> Time decay per day (negative = losing value)</li>
                </ul>
            </div>
        </div>
        
        <footer>
            <p>🤖 AI-Powered Stock Monitor • Powered by GitHub Models API (Claude 3.5)</p>
            <p>Updated: 4 AM & 4 PM Taiwan Time (Daily) | Next: {next_update}</p>
            <p><small>Data sources: yfinance, Yahoo Finance, Google News | Fact-checked analysis</small></p>
        </footer>
    </div>
</body>
</html>
"""

html_content = html_head + html_signals + html_stocks + html_footer

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

print("\n✅ v4 Report generated successfully!")
print("\n📚 Summary:")
print(f"  - Stocks analyzed: {len(all_data)}")
print(f"  - Volume spikes detected: {len(volume_spikes)}")
print(f"  - Earnings alerts: {len(earnings_soon)}")
print(f"  - AI summaries generated: {sum(1 for s in all_data if s.get('ai_summary'))}")
