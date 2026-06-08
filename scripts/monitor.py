#!/usr/bin/env python3
import yfinance as yf
import feedparser
import requests
import json
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
HISTORY_DIR = DOCS / "history"
STOCKS_FILE = ROOT / "stocks.json"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(exist_ok=True)

TAIWAN_TZ = ZoneInfo("Asia/Taipei")
NOW_TW = datetime.datetime.now(TAIWAN_TZ)

try:
    with open(STOCKS_FILE) as f:
        config = json.load(f)
    TICKERS = config.get("tickers", [])
except Exception as e:
    print(f"Error: {e}")
    exit(1)

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

def get_options_greeks(ticker):
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

def fetch_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
        vol = info.get("regularMarketVolume")
        avg_vol = info.get("averageVolume")
        
        five_day_avg = get_five_day_avg_volume(ticker)
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
            "five_day_vol_ratio": five_day_ratio,
            "volume_spike": volume_spike,
            "rsi": rsi,
            "week_52_high": safe(info.get("fiftyTwoWeekHigh")),
            "week_52_low": safe(info.get("fiftyTwoWeekLow")),
            "currency": info.get("currency", "USD"),
            "earnings": get_earnings_date(ticker),
            "greeks": greeks,
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return {"ticker": ticker, "error": str(e)}

def fetch_news(ticker):
    items = []
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        for e in feed.entries[:5]:
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "source": "Yahoo Finance",
                "published": e.get("published", "N/A"),
            })
    except:
        pass
    return items

def get_news_sentiment(title):
    title_lower = title.lower()
    positive = ['surge', 'rally', 'beat', 'rise', 'gain', 'up', 'strong', 'excellent', 'soar', 'bullish']
    negative = ['crash', 'plunge', 'miss', 'fall', 'drop', 'down', 'weak', 'terrible', 'plummet', 'bearish']
    
    pos_count = sum(1 for word in positive if word in title_lower)
    neg_count = sum(1 for word in negative if word in title_lower)
    
    if pos_count > neg_count:
        return "📈 Bullish"
    elif neg_count > pos_count:
        return "📉 Bearish"
    else:
        return "➡️ Neutral"

print(f"[Stock Monitor v4] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks")
print("\n[Fetching] Downloading stock data...")
all_data = []
for ticker in TICKERS:
    data = fetch_stock(ticker)
    data["news"] = fetch_news(ticker)
    all_data.append(data)
    print(f"  ✓ {ticker}")

volume_spikes = [s for s in all_data if s.get("volume_spike") and "error" not in s]
earnings_soon = [s for s in all_data if s.get("earnings") and s["earnings"].get("days_away") and 0 <= s["earnings"]["days_away"] <= 7 and "error" not in s]

html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Monitor v4</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }}
        header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px; text-align: center; }}
        header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        .alerts-banner {{ background: #fff3cd; border-bottom: 3px solid #ffc107; padding: 15px 30px; }}
        .alert-box {{ font-weight: 600; }}
        .content {{ padding: 40px; }}
        .section h2 {{ font-size: 1.8em; color: #667eea; margin-bottom: 20px; border-bottom: 3px solid #667eea; padding-bottom: 10px; }}
        .stock-card {{ background: #f8f9fa; border-left: 5px solid #667eea; padding: 20px; margin-bottom: 20px; border-radius: 8px; }}
        .stock-card.spike {{ border-left-color: #ff6b6b; background: #ffe0e0; }}
        .stock-card.earnings {{ border-left-color: #ffc107; background: #fff8e1; }}
        .stock-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
        .ticker {{ font-size: 1.5em; font-weight: bold; color: #667eea; }}
        .price {{ font-size: 1.2em; }}
        .pos {{ color: #28a745; }}
        .neg {{ color: #dc3545; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 15px 0; }}
        .metric {{ background: white; padding: 12px; border-radius: 6px; border: 1px solid #e0e0e0; }}
        .metric-label {{ color: #666; font-size: 0.85em; font-weight: 600; }}
        .metric-value {{ color: #333; font-size: 1.1em; font-weight: 600; margin-top: 4px; }}
        .signal {{ background: #fff9e6; border-left: 4px solid #f39c12; padding: 12px; margin: 12px 0; border-radius: 4px; color: #d68910; font-weight: 500; }}
        .alerts {{ background: #fff9e6; border: 1px solid #ffc107; padding: 12px; margin: 12px 0; border-radius: 6px; color: #e67e22; font-weight: 500; }}
        .alert-item {{ margin: 5px 0; }}
        .greek {{ background: #f0f4ff; border: 1px solid #667eea; padding: 12px; margin: 12px 0; border-radius: 6px; }}
        .greek-title {{ font-weight: bold; color: #667eea; margin-bottom: 8px; }}
        .greek-item {{ display: inline-block; margin-right: 20px; margin-bottom: 5px; }}
        .news {{ margin-top: 15px; }}
        .news-item {{ background: white; border: 1px solid #e0e0e0; padding: 12px; margin: 10px 0; border-radius: 4px; }}
        .news-item a {{ color: #667eea; text-decoration: none; font-weight: 500; }}
        .news-sentiment {{ font-size: 0.85em; color: #666; margin-top: 4px; }}
        footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; border-top: 1px solid #e0e0e0; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Stock Monitor v4</h1>
            <div style="opacity: 0.9;">{NOW_TW.strftime('%a, %b %d, %Y · %H:%M')} Taiwan Time</div>
        </header>
"""

if volume_spikes or earnings_soon:
    html += '<div class="alerts-banner">'
    if volume_spikes:
        html += f'<div class="alert-box">🔥 {len(volume_spikes)} VOLUME SPIKE(s)</div>'
    if earnings_soon:
        html += f'<div class="alert-box">📚 {len(earnings_soon)} EARNINGS THIS WEEK</div>'
    html += '</div>'

html += '<div class="content"><div class="section"><h2>📈 Stock Analysis</h2>'

for s in all_data:
    if "error" in s:
        html += f'<div class="stock-card"><span class="ticker">{s["ticker"]}</span><p style="color: red;">Error: {s["error"]}</p></div>'
        continue
    
    change_class = "pos" if (s.get("change_pct") or 0) > 0 else "neg"
    change_sign = "+" if (s.get("change_pct") or 0) > 0 else ""
    
    card_class = "stock-card"
    if s.get("volume_spike"):
        card_class += " spike"
    if s.get("earnings") and s["earnings"].get("days_away") and 0 <= s["earnings"]["days_away"] <= 7:
        card_class += " earnings"
    
    html += f'<div class="{card_class}">'
    html += f'<div class="stock-header"><span class="ticker">{s["ticker"]}</span><span class="price">{s["currency"]}{s["price"]} <span class="{change_class}">({change_sign}{s["change_pct"]}%)</span></span></div>'
    html += f'<div><strong>{s["name"]}</strong></div>'
    
    alerts = []
    if s.get("volume_spike"):
        alerts.append(f"🔥 Volume Spike: {s['five_day_vol_ratio']}x average")
    if s.get("earnings") and s["earnings"].get("days_away"):
        days = s["earnings"]["days_away"]
        if days == 0:
            alerts.append("📚 EARNINGS TODAY!")
        elif 0 < days <= 7:
            alerts.append(f"📚 Earnings in {days} days ({s['earnings']['date']})")
    
    if alerts:
        html += '<div class="alerts">' + ''.join([f'<div class="alert-item">{a}</div>' for a in alerts]) + '</div>'
    
    html += '<div class="metrics">'
    html += f'<div class="metric"><div class="metric-label">RSI</div><div class="metric-value">{s.get("rsi", "—")}</div></div>'
    html += f'<div class="metric"><div class="metric-label">Volume Ratio</div><div class="metric-value">{s.get("five_day_vol_ratio", "—")}x</div></div>'
    html += f'<div class="metric"><div class="metric-label">52w Low</div><div class="metric-value">{s["currency"]}{s["week_52_low"]}</div></div>'
    html += f'<div class="metric"><div class="metric-label">52w High</div><div class="metric-value">{s["currency"]}{s["week_52_high"]}</div></div>'
    html += '</div>'
    
    # Signal
    chg = s.get("change_pct") or 0
    vol = s.get("five_day_vol_ratio") or 1
    rsi = s.get("rsi") or 50
    
    signals = []
    if vol >= 2.0:
        signals.append(f"🔥 VOLUME SPIKE ({vol}x)")
    if chg >= 7:
        signals.append("🚀 Strong rally")
    elif chg <= -7:
        signals.append("📉 Heavy drop")
    if rsi > 75:
        signals.append("🔴 Overbought")
    elif rsi < 25:
        signals.append("🟢 Oversold")
    
    if signals:
        html += f'<div class="signal">📌 {" | ".join(signals)}</div>'
    
    # Options Greeks
    if s.get("greeks"):
        g = s["greeks"]
        html += f'<div class="greek"><div class="greek-title">📊 Options (Exp: {g["expiration"]})</div>'
        html += f'<div class="greek-item"><strong>IV:</strong> {g["iv"]}%</div>'
        html += f'<div class="greek-item"><strong>Δ:</strong> {g["delta"]}</div>'
        html += f'<div class="greek-item"><strong>Θ:</strong> {g["theta"]}</div>'
        html += '</div>'
    
    # News
    if s.get("news"):
        html += '<div class="news"><strong>📰 Latest News:</strong>'
        for n in s["news"][:5]:
            sentiment = get_news_sentiment(n["title"])
            html += f'<div class="news-item"><a href="{n["link"]}" target="_blank">{n["title"][:80]}...</a><div class="news-sentiment">{sentiment} • Yahoo Finance</div></div>'
        html += '</div>'
    
    html += '</div>'

html += '</div></div><footer><p>🤖 Stock Monitor v4 • Volume Alerts • Earnings Calendar • News Summary • 100% FREE</p></footer></div></body></html>'

try:
    (DOCS / "index.html").write_text(html, encoding='utf-8')
    print("[✓] Dashboard generated!")
except Exception as e:
    print(f"Error: {e}")
    exit(1)

print("\n✅ Complete!")
