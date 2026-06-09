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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

print("[Stock Monitor v4] " + NOW_TW.strftime('%Y-%m-%d %H:%M TW') + " | " + str(len(TICKERS)) + " stocks")

def safe(v, d=2):
    try:
        f = float(v)
        if f != f:
            return None
        return round(f, d)
    except:
        return None

def fmt_large(n):
    try:
        n = float(n)
        if n >= 1e12: return str(round(n/1e12, 2)) + "T"
        if n >= 1e9:  return str(round(n/1e9, 2)) + "B"
        if n >= 1e6:  return str(round(n/1e6, 2)) + "M"
        return str(round(n, 0))
    except:
        return "—"

def get_rsi(hist, period=14):
    try:
        if len(hist) < period + 1:
            return None
        delta = hist['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        if hasattr(val, 'item'):
            val = val.item()
        return safe(val, 0)
    except:
        return None

def get_macd(hist):
    try:
        close = hist['Close']
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist_macd = macd - signal
        hist_val = float(hist_macd.iloc[-1])
        prev_val = float(hist_macd.iloc[-2])
        if hist_val > 0 and hist_val > prev_val:
            trend = "Bullish crossover"
        elif hist_val < 0 and hist_val < prev_val:
            trend = "Bearish crossover"
        else:
            trend = "Neutral"
        return {"macd": safe(float(macd.iloc[-1]), 3), "signal": safe(float(signal.iloc[-1]), 3), "trend": trend}
    except:
        return None

def get_moving_averages(hist, price):
    try:
        close = hist['Close']
        result = {}
        if len(close) >= 20:
            sma20 = float(close.rolling(20).mean().iloc[-1])
            result['sma20'] = safe(sma20)
            result['vs_sma20'] = safe((price - sma20) / sma20 * 100, 1)
        if len(close) >= 50:
            sma50 = float(close.rolling(50).mean().iloc[-1])
            result['sma50'] = safe(sma50)
            result['vs_sma50'] = safe((price - sma50) / sma50 * 100, 1)
        if len(close) >= 200:
            sma200 = float(close.rolling(200).mean().iloc[-1])
            result['sma200'] = safe(sma200)
            result['vs_sma200'] = safe((price - sma200) / sma200 * 100, 1)
        return result
    except:
        return {}

def get_fundamentals(info):
    try:
        return {
            'pe':             safe(info.get('trailingPE')),
            'fpe':            safe(info.get('forwardPE')),
            'peg':            safe(info.get('pegRatio')),
            'pb':             safe(info.get('priceToBook')),
            'ps':             safe(info.get('priceToSalesTrailing12Months')),
            'ev_ebitda':      safe(info.get('enterpriseToEbitda')),
            'roe':            safe((info.get('returnOnEquity') or 0) * 100, 1),
            'roa':            safe((info.get('returnOnAssets') or 0) * 100, 1),
            'profit_margin':  safe((info.get('profitMargins') or 0) * 100, 1),
            'revenue_growth': safe((info.get('revenueGrowth') or 0) * 100, 1),
            'earnings_growth':safe((info.get('earningsGrowth') or 0) * 100, 1),
            'debt_equity':    safe(info.get('debtToEquity')),
            'current_ratio':  safe(info.get('currentRatio')),
            'fcf':            fmt_large(info.get('freeCashflow')) if info.get('freeCashflow') else '—',
            'eps':            safe(info.get('trailingEps')),
            'beta':           safe(info.get('beta')),
            'short_ratio':    safe(info.get('shortRatio')),
            'inst_own':       safe((info.get('heldPercentInstitutions') or 0) * 100, 1),
            'insider_own':    safe((info.get('heldPercentInsiders') or 0) * 100, 1),
            'short_float':    safe((info.get('shortPercentOfFloat') or 0) * 100, 1),
        }
    except:
        return {}

def get_earnings(info):
    try:
        ed = info.get("earningsDate")
        if ed and isinstance(ed, (list, tuple)) and len(ed) > 0:
            from datetime import datetime as dt
            date = dt.fromtimestamp(ed[0], tz=TAIWAN_TZ)
            days = (date.date() - NOW_TW.date()).days
            return {"date": date.strftime('%Y-%m-%d'), "days": days}
    except:
        pass
    return None

def get_options(ticker, price):
    try:
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps:
            return None
        chain = t.option_chain(exps[0])
        calls = chain.calls
        puts = chain.puts
        if len(calls) == 0:
            return None
        atm_call = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]
        result = {
            "exp": str(exps[0]),
            "iv": safe(float(atm_call['impliedVolatility'].values[0]) * 100, 1),
            "delta": safe(float(atm_call['delta'].values[0]), 3) if 'delta' in atm_call.columns else None,
            "theta": safe(float(atm_call['theta'].values[0]), 4) if 'theta' in atm_call.columns else None,
            "gamma": safe(float(atm_call['gamma'].values[0]), 4) if 'gamma' in atm_call.columns else None,
        }
        if len(puts) > 0:
            csp_puts = puts[puts['strike'] <= price].tail(3)
            if len(csp_puts) > 0:
                best = csp_puts.iloc[-1]
                result['csp'] = {
                    'strike': safe(best['strike']),
                    'premium': safe(best['lastPrice']),
                    'iv': safe(float(best['impliedVolatility']) * 100, 1),
                    'exp': str(exps[0])
                }
        return result
    except:
        return None

def get_news(ticker, name):
    items = []
    seen = set()

    try:
        feed = feedparser.parse("https://feeds.finance.yahoo.com/rss/2.0/headline?s=" + ticker + "&region=US&lang=en-US")
        for e in feed.entries[:4]:
            t = e.get("title", "")[:100]
            if t not in seen:
                seen.add(t)
                items.append({"title": t, "link": e.get("link", ""), "source": "Yahoo Finance", "summary": e.get("summary", "")[:200]})
    except:
        pass

    try:
        q = requests.utils.quote(ticker + " stock")
        feed = feedparser.parse("https://news.google.com/rss/search?q=" + q + "&hl=en-US&gl=US&ceid=US:en")
        for e in feed.entries[:4]:
            t = e.get("title", "")[:100]
            if t not in seen:
                seen.add(t)
                items.append({"title": t, "link": e.get("link", ""), "source": "Google News", "summary": e.get("summary", "")[:200]})
    except:
        pass

    try:
        short_name = name.split()[0] if name else ticker
        q2 = requests.utils.quote(short_name + " stock earnings")
        feed2 = feedparser.parse("https://news.google.com/rss/search?q=" + q2 + "&hl=en-US&gl=US&ceid=US:en")
        for e in feed2.entries[:3]:
            t = e.get("title", "")[:100]
            if t not in seen:
                seen.add(t)
                items.append({"title": t, "link": e.get("link", ""), "source": "Google News", "summary": e.get("summary", "")[:200]})
    except:
        pass

    try:
        url = "https://finviz.com/quote.ashx?t=" + ticker
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            table = soup.find("table", {"class": "news-table"})
            if table:
                for row in table.findAll('tr')[:5]:
                    cols = row.findAll('td')
                    if len(cols) >= 2:
                        link = cols[1].find('a')
                        if link:
                            t = link.text[:100]
                            if t not in seen:
                                seen.add(t)
                                items.append({"title": t, "link": link.get('href', ''), "source": "Finviz", "summary": ""})
    except:
        pass

    try:
        r = requests.get("https://www.marketwatch.com/investing/stock/" + ticker.lower(), headers=HEADERS, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            for article in soup.findAll('h3', class_='article__headline')[:4]:
                a = article.find('a')
                if a:
                    t = a.text.strip()[:100]
                    if t not in seen:
                        seen.add(t)
                        href = a.get('href', '')
                        if not href.startswith('http'):
                            href = 'https://www.marketwatch.com' + href
                        items.append({"title": t, "link": href, "source": "MarketWatch", "summary": ""})
    except:
        pass

    return items[:15]

def analyze(s):
    signals = []
    analysis = []
    fund = s.get('fundamentals', {})
    mas = s.get('moving_averages', {})
    greeks = s.get('greeks', {})
    news = s.get('news', [])
    rsi = s.get('technicals', {}).get('rsi')
    macd = s.get('technicals', {}).get('macd')
    vol_ratio = s.get('vol_ratio', 1)
    chg = s.get('change', 0)
    price = s.get('price', 0)
    h52 = s.get('h52', 1)
    l52 = s.get('l52', 0)

    if vol_ratio >= 3.0:
        signals.append("🔥 EXTREME Volume: " + str(vol_ratio) + "x average - major event likely")
    elif vol_ratio >= 2.0:
        signals.append("⚡ Volume Spike: " + str(vol_ratio) + "x average - unusual activity")

    if rsi:
        if rsi >= 75:
            signals.append("🔴 OVERBOUGHT - RSI: " + str(int(rsi)) + " (pullback likely)")
        elif rsi <= 25:
            signals.append("🟢 OVERSOLD - RSI: " + str(int(rsi)) + " (bounce opportunity)")
        elif rsi <= 35:
            signals.append("🟡 Near Oversold - RSI: " + str(int(rsi)))
        elif rsi >= 65:
            signals.append("🟠 Near Overbought - RSI: " + str(int(rsi)))

    if chg >= 7:
        signals.append("🚀 Strong rally: +" + str(chg) + "%")
    elif chg <= -7:
        signals.append("📉 Heavy drop: " + str(chg) + "%")

    earnings = s.get('earnings')
    if earnings:
        days = earnings['days']
        if days == 0:
            signals.append("🚨 EARNINGS TODAY!")
        elif 0 < days <= 7:
            signals.append("📚 Earnings in " + str(days) + " days (" + earnings['date'] + ")")
        elif 0 < days <= 14:
            analysis.append("📅 Earnings coming: " + earnings['date'] + " (" + str(days) + " days)")

    if mas:
        vs50 = mas.get('vs_sma50')
        vs200 = mas.get('vs_sma200')
        sma50 = mas.get('sma50')
        sma200 = mas.get('sma200')
        if vs50 is not None and vs200 is not None:
            if vs50 > 0 and vs200 > 0:
                analysis.append("📈 Above both 50d & 200d MA - Strong uptrend")
            elif vs50 < 0 and vs200 < 0:
                analysis.append("📉 Below both 50d & 200d MA - Downtrend confirmed")
            elif vs50 < 0 and vs200 > 0:
                analysis.append("⚠️ Below 50d MA but above 200d - Short-term weakness")

    if macd:
        analysis.append("MACD: " + macd.get('trend', ''))

    pe = fund.get('pe')
    peg = fund.get('peg')
    roe = fund.get('roe')
    if pe:
        if pe < 10:
            analysis.append("💰 Very cheap P/E: " + str(pe) + "x - potentially undervalued")
        elif pe > 40:
            analysis.append("⚠️ Expensive P/E: " + str(pe) + "x - growth premium")
    if peg and peg < 1.0:
        analysis.append("✅ PEG ratio " + str(peg) + " - undervalued vs growth rate")
    if roe and roe > 20:
        analysis.append("💪 Strong ROE: " + str(roe) + "% - elite profitability")

    if h52 and l52 and h52 != l52:
        pct = safe((price - l52) / (h52 - l52) * 100, 0)
        if pct is not None:
            if pct <= 10:
                analysis.append("📍 Near 52-week LOW (" + str(pct) + "% from low) - value zone")
            elif pct >= 90:
                analysis.append("📍 Near 52-week HIGH (" + str(pct) + "% from low) - breakout or resistance")

    short_float = fund.get('short_float')
    if short_float and short_float > 15:
        analysis.append("⚠️ High short interest: " + str(short_float) + "% of float")

    if greeks:
        iv = greeks.get('iv')
        if iv:
            if iv > 60:
                analysis.append("⚡ High IV: " + str(iv) + "% - expensive options, high uncertainty")
            elif iv < 20:
                analysis.append("😴 Low IV: " + str(iv) + "% - cheap options, calm market")
        csp = greeks.get('csp')
        if csp and csp.get('premium'):
            analysis.append("💼 CSP opportunity: $" + str(csp['strike']) + " strike, $" + str(csp['premium']) + " premium exp " + str(csp['exp']))

    pos_words = ['beat', 'surge', 'rally', 'buy', 'upgrade', 'bullish', 'strong', 'partnership', 'launch', 'growth', 'record', 'profit']
    neg_words = ['miss', 'plunge', 'sell', 'downgrade', 'bearish', 'weak', 'cut', 'lawsuit', 'decline', 'loss', 'fall', 'drop']
    all_text = ' '.join([n['title'].lower() for n in news[:8]] + [n.get('summary', '').lower() for n in news[:5]])
    pos_count = sum(all_text.count(w) for w in pos_words)
    neg_count = sum(all_text.count(w) for w in neg_words)

    if pos_count > neg_count + 1:
        analysis.append("📰 News: Bullish sentiment (" + str(pos_count) + " positive signals)")
    elif neg_count > pos_count + 1:
        analysis.append("📰 News: Bearish sentiment (" + str(neg_count) + " negative signals)")
    else:
        analysis.append("📰 News: Mixed/Neutral sentiment")

    return {"signals": signals, "analysis": analysis}

def get_stock(ticker):
    try:
        print("  Fetching " + ticker + "...")
        t = yf.Ticker(ticker)
        i = t.info
        p = i.get("currentPrice") or i.get("regularMarketPrice") or 0
        prev = i.get("previousClose") or p
        vol = i.get("regularMarketVolume") or 0
        avg_vol = i.get("averageVolume") or vol
        chg = safe((p - prev) / prev * 100) if prev else 0
        vol_ratio = safe(vol / avg_vol) if avg_vol else 1.0
        spike = vol_ratio >= 2.0
        hist = t.history(period="250d")
        rsi = get_rsi(hist) if len(hist) >= 14 else None
        macd = get_macd(hist) if len(hist) >= 26 else None
        mas = get_moving_averages(hist, p) if len(hist) >= 20 else {}
        fund = get_fundamentals(i)
        earnings = get_earnings(i)
        greeks = get_options(ticker, p)
        name = i.get("longName", ticker)
        news = get_news(ticker, name)
        stock = {
            "ticker": ticker,
            "name": name,
            "price": safe(p),
            "change": chg,
            "vol_ratio": vol_ratio,
            "spike": spike,
            "h52": safe(i.get("fiftyTwoWeekHigh") or p),
            "l52": safe(i.get("fiftyTwoWeekLow") or p),
            "market_cap": fmt_large(i.get("marketCap")),
            "currency": i.get("currency", "USD"),
            "sector": i.get("sector", ""),
            "earnings": earnings,
            "fundamentals": fund,
            "technicals": {"rsi": rsi, "macd": macd},
            "moving_averages": mas,
            "greeks": greeks,
            "news": news,
        }
        stock['ai'] = analyze(stock)
        print("    OK " + ticker + " $" + str(safe(p)) + " (" + str(chg) + "%)")
        return stock
    except Exception as e:
        print("  ERROR " + ticker + ": " + str(e)[:60])
        return None

print("\nFetching all stocks...")
stocks = [s for s in [get_stock(t) for t in TICKERS] if s]
spikes = [s for s in stocks if s["spike"]]
earnings_week = [s for s in stocks if s.get("earnings") and s["earnings"]["days"] >= 0 and s["earnings"]["days"] <= 7]

print("Building dashboard...")

def rsi_color(rsi):
    if not rsi: return "#333"
    if rsi >= 75: return "#dc3545"
    if rsi <= 25: return "#28a745"
    if rsi >= 65: return "#fd7e14"
    if rsi <= 35: return "#20c997"
    return "#333"

spike_tickers = ", ".join([s["ticker"] for s in spikes])
earn_list = ", ".join([s["ticker"] + "(" + str(s["earnings"]["days"]) + "d)" for s in earnings_week])

header_section = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Monitor v4</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; padding: 20px; }
        .wrap { max-width: 1200px; margin: 0 auto; background: white; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.12); overflow: hidden; }
        header { background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 40px; text-align: center; }
        header h1 { font-size: 2.4em; margin-bottom: 8px; font-weight: 700; }
        .top-alerts { background: #fff3cd; border-left: 5px solid #ffc107; padding: 16px 24px; }
        .top-alert { font-weight: 700; margin: 4px 0; font-size: 1.05em; }
        .content { padding: 30px; }
        .stock { background: #f8f9fa; border-left: 6px solid #667eea; padding: 24px; margin-bottom: 24px; border-radius: 10px; }
        .stock.spike { background: #fff5f5; border-left-color: #e53e3e; }
        .stock.earn { background: #fffff0; border-left-color: #d69e2e; }
        .stock.oversold { background: #f0fff4; border-left-color: #38a169; }
        .stock-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; flex-wrap: wrap; gap: 10px; }
        .ticker { font-size: 1.8em; font-weight: 800; color: #4a5568; }
        .price { font-size: 1.5em; font-weight: 700; }
        .chg { font-size: 1.1em; font-weight: 600; }
        .up { color: #38a169; }
        .down { color: #e53e3e; }
        .company { color: #718096; margin-bottom: 16px; font-size: 0.95em; }
        .metrics-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin: 16px 0; }
        .metric { background: white; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center; }
        .metric-label { font-size: 0.75em; color: #718096; font-weight: 700; text-transform: uppercase; }
        .metric-value { font-size: 1.1em; font-weight: 700; margin-top: 4px; }
        .section { margin: 16px 0; }
        .section-title { font-weight: 700; color: #4a5568; margin-bottom: 10px; font-size: 0.9em; text-transform: uppercase; letter-spacing: 0.5px; }
        .fund-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
        .fund-item { background: white; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; }
        .fund-label { font-size: 0.75em; color: #718096; font-weight: 600; }
        .fund-value { font-size: 1em; font-weight: 700; margin-top: 2px; color: #2d3748; }
        .signals { background: #fff9e6; border-left: 4px solid #f6ad55; padding: 12px 16px; border-radius: 6px; margin: 10px 0; }
        .signal-item { margin: 5px 0; font-weight: 600; }
        .analysis-box { background: #ebf8ff; border-left: 4px solid #4299e1; padding: 12px 16px; border-radius: 6px; margin: 10px 0; }
        .analysis-item { margin: 4px 0; font-size: 0.92em; color: #2c5282; }
        .ma-box { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
        .ma-item { background: white; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; text-align: center; }
        .ma-up { color: #38a169; }
        .ma-down { color: #e53e3e; }
        .greeks-box { background: #f0fff4; border: 1px solid #9ae6b4; padding: 12px 16px; border-radius: 6px; margin: 10px 0; }
        .greeks-title { font-weight: 700; color: #276749; margin-bottom: 8px; }
        .greek { display: inline-block; margin-right: 16px; font-size: 0.9em; }
        .csp-box { background: #faf5ff; border: 1px solid #d6bcfa; padding: 12px 16px; border-radius: 6px; margin: 10px 0; }
        .csp-title { font-weight: 700; color: #553c9a; margin-bottom: 8px; }
        .inst-box { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 10px 0; }
        .inst-item { background: white; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; text-align: center; }
        .news-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
        .news-item { background: white; padding: 10px 12px; border-radius: 6px; border: 1px solid #e2e8f0; border-left: 3px solid #667eea; }
        .news-item a { color: #2b6cb0; text-decoration: none; font-weight: 500; font-size: 0.88em; line-height: 1.4; }
        .news-item a:hover { text-decoration: underline; }
        .news-source { font-size: 0.75em; color: #a0aec0; margin-top: 4px; }
        footer { background: #2d3748; color: #a0aec0; padding: 24px; text-align: center; font-size: 0.9em; }
        @media (max-width: 768px) {
            .metrics-grid { grid-template-columns: repeat(3, 1fr); }
            .fund-grid { grid-template-columns: repeat(2, 1fr); }
            .news-grid { grid-template-columns: 1fr; }
            .ma-box { grid-template-columns: 1fr 1fr; }
        }
    </style>
</head>
<body>
<div class="wrap">"""

html = header_section

html += "<header><h1>📊 Stock Monitor v4</h1>"
html += "<p style='opacity:0.9; margin-top:8px'>" + NOW_TW.strftime('%A, %B %d, %Y · %H:%M') + " Taiwan Time</p>"
html += "<p style='opacity:0.75; font-size:0.9em; margin-top:4px'>RSI • MACD • Moving Averages • Fundamentals • Options Greeks • CSP Analysis</p>"
html += "</header>"

if spikes or earnings_week:
    html += "<div class='top-alerts'>"
    if spikes:
        html += "<div class='top-alert'>🔥 VOLUME SPIKE(s): " + spike_tickers + "</div>"
    if earnings_week:
        html += "<div class='top-alert'>📚 EARNINGS THIS WEEK: " + earn_list + "</div>"
    html += "</div>"

html += "<div class='content'>"

for s in stocks:
    up = s['change'] > 0
    chg_class = "up" if up else "down"
    sign = "+" if up else ""
    rsi = s['technicals']['rsi']
    l52 = s['l52'] or 0
    h52 = s['h52'] or 1
    p = s['price'] or 0

    card_class = "stock"
    if s['spike']:
        card_class = "stock spike"
    elif s.get('earnings') and s['earnings']['days'] >= 0 and s['earnings']['days'] <= 7:
        card_class = "stock earn"
    elif rsi and rsi <= 30:
        card_class = "stock oversold"

    price_pct = safe((p - l52) / (h52 - l52) * 100) if h52 != l52 else None
    price_pct_str = str(price_pct) + "%" if price_pct else "—"

    html += "<div class='" + card_class + "'>"
    html += "<div class='stock-head'>"
    html += "<div><div class='ticker'>" + s['ticker'] + "</div>"
    html += "<div class='company'>" + s['name'] + " | " + s.get('sector','') + " | Cap: " + s['market_cap'] + "</div></div>"
    html += "<div style='text-align:right'>"
    html += "<div class='price'>" + s['currency'] + str(s['price']) + "</div>"
    html += "<div class='chg " + chg_class + "'>" + sign + str(s['change']) + "% today</div>"
    html += "</div></div>"

    rsi_col = rsi_color(rsi)
    rsi_str = str(int(rsi)) if rsi else "—"
    html += "<div class='metrics-grid'>"
    html += "<div class='metric'><div class='metric-label'>RSI</div><div class='metric-value' style='color:" + rsi_col + "'>" + rsi_str + "</div></div>"
    html += "<div class='metric'><div class='metric-label'>Volume</div><div class='metric-value'>" + str(s['vol_ratio']) + "x</div></div>"
    html += "<div class='metric'><div class='metric-label'>52w Low</div><div class='metric-value'>" + s['currency'] + str(s['l52']) + "</div></div>"
    html += "<div class='metric'><div class='metric-label'>52w High</div><div class='metric-value'>" + s['currency'] + str(s['h52']) + "</div></div>"
    html += "<div class='metric'><div class='metric-label'>In Range</div><div class='metric-value'>" + price_pct_str + "</div></div>"
    html += "<div class='metric'><div class='metric-label'>Beta</div><div class='metric-value'>" + str(s['fundamentals'].get('beta','—')) + "</div></div>"
    html += "</div>"

    mas = s.get('moving_averages', {})
    if mas:
        html += "<div class='section'><div class='section-title'>📈 Moving Averages</div><div class='ma-box'>"
        if 'sma20' in mas:
            cls = "ma-up" if (mas.get('vs_sma20') or 0) > 0 else "ma-down"
            html += "<div class='ma-item'><div class='metric-label'>SMA 20</div><div class='metric-value " + cls + "'>" + s['currency'] + str(mas['sma20']) + " (" + str(mas.get('vs_sma20',0)) + "%)</div></div>"
        if 'sma50' in mas:
            cls = "ma-up" if (mas.get('vs_sma50') or 0) > 0 else "ma-down"
            html += "<div class='ma-item'><div class='metric-label'>SMA 50</div><div class='metric-value " + cls + "'>" + s['currency'] + str(mas['sma50']) + " (" + str(mas.get('vs_sma50',0)) + "%)</div></div>"
        if 'sma200' in mas:
            cls = "ma-up" if (mas.get('vs_sma200') or 0) > 0 else "ma-down"
            html += "<div class='ma-item'><div class='metric-label'>SMA 200</div><div class='metric-value " + cls + "'>" + s['currency'] + str(mas['sma200']) + " (" + str(mas.get('vs_sma200',0)) + "%)</div></div>"
        html += "</div></div>"

    f = s.get('fundamentals', {})
    fund_fields = [('P/E','pe'),('Fwd P/E','fpe'),('PEG','peg'),('P/B','pb'),('ROE%','roe'),('ROA%','roa'),('Margin%','profit_margin'),('Rev Gr%','revenue_growth'),('EPS','eps'),('FCF','fcf'),('D/E','debt_equity'),('Beta','beta')]
    fund_items = [(lbl, f.get(key,'—')) for lbl,key in fund_fields if f.get(key) is not None]
    if fund_items:
        html += "<div class='section'><div class='section-title'>💰 Fundamentals</div><div class='fund-grid'>"
        for lbl, val in fund_items:
            html += "<div class='fund-item'><div class='fund-label'>" + lbl + "</div><div class='fund-value'>" + str(val) + "</div></div>"
        html += "</div></div>"

    inst_own = f.get('inst_own')
    insider_own = f.get('insider_own')
    short_float = f.get('short_float')
    if inst_own or insider_own or short_float:
        html += "<div class='section'><div class='section-title'>🏦 Ownership</div><div class='inst-box'>"
        html += "<div class='inst-item'><div class='metric-label'>Institutional</div><div class='metric-value'>" + str(inst_own or '—') + "%</div></div>"
        html += "<div class='inst-item'><div class='metric-label'>Insider</div><div class='metric-value'>" + str(insider_own or '—') + "%</div></div>"
        html += "<div class='inst-item'><div class='metric-label'>Short Float</div><div class='metric-value'>" + str(short_float or '—') + "%</div></div>"
        html += "</div></div>"

    g = s.get('greeks')
    if g:
        html += "<div class='section'><div class='section-title'>📊 Options Greeks (Exp: " + str(g.get('exp','')) + ")</div>"
        html += "<div class='greeks-box'>"
        if g.get('iv'):    html += "<span class='greek'><strong>IV:</strong> " + str(g['iv']) + "%</span>"
        if g.get('delta'): html += "<span class='greek'><strong>Δ Delta:</strong> " + str(g['delta']) + "</span>"
        if g.get('theta'): html += "<span class='greek'><strong>Θ Theta:</strong> " + str(g['theta']) + "</span>"
        if g.get('gamma'): html += "<span class='greek'><strong>Γ Gamma:</strong> " + str(g['gamma']) + "</span>"
        html += "</div>"
        csp = g.get('csp')
        if csp and csp.get('premium'):
            html += "<div class='csp-box'><div class='csp-title'>💼 Cash Secured Put Opportunity</div>"
            html += "Strike: $" + str(csp['strike']) + " | Premium: $" + str(csp['premium']) + " | IV: " + str(csp['iv']) + "% | Exp: " + str(csp['exp'])
            html += "</div>"
        html += "</div>"

    ai = s.get('ai', {})
    signals = ai.get('signals', [])
    analysis_pts = ai.get('analysis', [])

    if signals:
        html += "<div class='signals'>"
        for sig in signals:
            html += "<div class='signal-item'>" + sig + "</div>"
        html += "</div>"

    if analysis_pts:
        html += "<div class='section'><div class='section-title'>🤖 AI Analysis</div><div class='analysis-box'>"
        for pt in analysis_pts:
            html += "<div class='analysis-item'>• " + pt + "</div>"
        html += "</div></div>"

    if s.get('earnings'):
        e = s['earnings']
        days = e['days']
        if days >= 0:
            badge = "🚨 TODAY!" if days == 0 else "📚 " + str(days) + " days (" + e['date'] + ")"
            html += "<div class='signals' style='background:#fff0f0'><div class='signal-item'>Earnings: " + badge + "</div></div>"

    if s.get('news'):
        html += "<div class='section'><div class='section-title'>📰 Latest News (" + str(len(s['news'])) + " sources)</div><div class='news-grid'>"
        for n in s['news'][:12]:
            html += "<div class='news-item'><a href='" + n['link'] + "' target='_blank'>" + n['title'] + "</a><div class='news-source'>" + n['source'] + "</div></div>"
        html += "</div></div>"

    html += "</div>"

html += "</div>"
html += "<footer><p>🤖 Stock Monitor v4 | RSI • MACD • Moving Averages • Fundamentals • Options • CSP Analysis</p>"
html += "<p style='margin-top:6px'>Sources: Yahoo Finance • Google News • Finviz • MarketWatch | 4 AM & 4 PM Taiwan Time</p>"
html += "<p style='margin-top:6px; font-size:0.8em'>Not financial advice. For informational purposes only.</p>"
html += "</footer></div></body></html>"

(DOCS / "index.html").write_text(html)
print("Dashboard saved!")
print("Stocks: " + str(len(stocks)))
print("Spikes: " + str(len(spikes)))
print("Earnings: " + str(len(earnings_week)))
