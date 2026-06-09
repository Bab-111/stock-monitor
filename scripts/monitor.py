#!/usr/bin/env python3
"""
Stock Monitor v4 - Professional Grade
Uses multiple FREE data sources + AI analysis
"""
import yfinance as yf
import feedparser
import requests
import json
import datetime
import time
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

print(f"[Stock Monitor v4] {NOW_TW.strftime('%Y-%m-%d %H:%M TW')} | {len(TICKERS)} stocks\n")

def safe(v, d=2):
    try:
        f = float(v)
        if f != f:  # NaN check
            return None
        return round(f, d)
    except:
        return None

def fmt_large(n):
    """Format large numbers"""
    try:
        n = float(n)
        if n >= 1e12: return f"${n/1e12:.2f}T"
        if n >= 1e9:  return f"${n/1e9:.2f}B"
        if n >= 1e6:  return f"${n/1e6:.2f}M"
        return f"${n:,.0f}"
    except:
        return "—"

def get_rsi(hist, period=14):
    """Calculate RSI from history"""
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
    """Calculate MACD"""
    try:
        close = hist['Close']
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist_macd = macd - signal
        
        macd_val = float(macd.iloc[-1])
        signal_val = float(signal.iloc[-1])
        hist_val = float(hist_macd.iloc[-1])
        
        if hist_val > 0 and hist_val > float(hist_macd.iloc[-2]):
            trend = "📈 Bullish crossover"
        elif hist_val < 0 and hist_val < float(hist_macd.iloc[-2]):
            trend = "📉 Bearish crossover"
        else:
            trend = "➡️ Neutral"
        
        return {"macd": safe(macd_val, 3), "signal": safe(signal_val, 3), "trend": trend}
    except:
        return None

def get_moving_averages(hist, price):
    """Get SMA20, SMA50, SMA200"""
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
    """Extract fundamental metrics"""
    try:
        pe = safe(info.get('trailingPE') or info.get('forwardPE'))
        fpe = safe(info.get('forwardPE'))
        peg = safe(info.get('pegRatio'))
        pb = safe(info.get('priceToBook'))
        ps = safe(info.get('priceToSalesTrailing12Months'))
        ev_ebitda = safe(info.get('enterpriseToEbitda'))
        roe = safe((info.get('returnOnEquity') or 0) * 100, 1)
        roa = safe((info.get('returnOnAssets') or 0) * 100, 1)
        profit_margin = safe((info.get('profitMargins') or 0) * 100, 1)
        revenue_growth = safe((info.get('revenueGrowth') or 0) * 100, 1)
        earnings_growth = safe((info.get('earningsGrowth') or 0) * 100, 1)
        debt_equity = safe(info.get('debtToEquity'))
        current_ratio = safe(info.get('currentRatio'))
        quick_ratio = safe(info.get('quickRatio'))
        fcf = info.get('freeCashflow')
        eps = safe(info.get('trailingEps'))
        beta = safe(info.get('beta'))
        short_ratio = safe(info.get('shortRatio'))
        
        return {
            'pe': pe, 'fpe': fpe, 'peg': peg, 'pb': pb, 'ps': ps,
            'ev_ebitda': ev_ebitda, 'roe': roe, 'roa': roa,
            'profit_margin': profit_margin, 'revenue_growth': revenue_growth,
            'earnings_growth': earnings_growth, 'debt_equity': debt_equity,
            'current_ratio': current_ratio, 'quick_ratio': quick_ratio,
            'fcf': fmt_large(fcf) if fcf else '—',
            'eps': eps, 'beta': beta, 'short_ratio': short_ratio,
        }
    except:
        return {}

def get_earnings(info):
    """Get earnings date"""
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

def get_options_greeks(ticker, price):
    """Get options data"""
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
        atm_put = puts.iloc[(puts['strike'] - price).abs().argsort()[:1]] if len(puts) > 0 else None
        
        result = {
            "exp": str(exps[0]),
            "iv_call": safe(float(atm_call['impliedVolatility'].values[0]) * 100, 1),
            "delta": safe(float(atm_call['delta'].values[0]), 3) if 'delta' in atm_call.columns else None,
            "theta": safe(float(atm_call['theta'].values[0]), 4) if 'theta' in atm_call.columns else None,
            "gamma": safe(float(atm_call['gamma'].values[0]), 4) if 'gamma' in atm_call.columns else None,
        }
        
        # CSP analysis
        csp_strike = safe(price * 0.95)  # 5% OTM
        csp_candidates = puts[puts['strike'] <= price].tail(3)
        if len(csp_candidates) > 0:
            best_csp = csp_candidates.iloc[-1]
            result['csp'] = {
                'strike': safe(best_csp['strike']),
                'premium': safe(best_csp['lastPrice']),
                'iv': safe(float(best_csp['impliedVolatility']) * 100, 1),
                'exp': str(exps[0])
            }
        
        return result
    except:
        return None

def get_institutional_data(ticker, info):
    """Get institutional/insider data from yfinance"""
    try:
        t = yf.Ticker(ticker)
        
        inst_pct = safe((info.get('heldPercentInstitutions') or 0) * 100, 1)
        insider_pct = safe((info.get('heldPercentInsiders') or 0) * 100, 1)
        short_pct = safe((info.get('shortPercentOfFloat') or 0) * 100, 1)
        
        return {
            'institutional': inst_pct,
            'insider': insider_pct,
            'short_pct': short_pct,
        }
    except:
        return {}

def get_news_all_sources(ticker, name):
    """Fetch news from ALL available free sources"""
    items = []
    
    # 1. Yahoo Finance RSS
    try:
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        for e in feed.entries[:4]:
            items.append({
                "title": e.get("title", "")[:100],
                "link": e.get("link", ""),
                "source": "Yahoo Finance",
                "summary": e.get("summary", "")[:200]
            })
    except:
        pass
    
    # 2. Google News RSS (ticker)
    try:
        q = requests.utils.quote(f"{ticker} stock")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
        for e in feed.entries[:3]:
            items.append({
                "title": e.get("title", "")[:100],
                "link": e.get("link", ""),
                "source": "Google News",
                "summary": e.get("summary", "")[:200]
            })
    except:
        pass
    
    # 3. Google News RSS (company name)
    try:
        short_name = name.split()[0] if name else ticker
        q2 = requests.utils.quote(f"{short_name} stock earnings")
        feed2 = feedparser.parse(f"https://news.google.com/rss/search?q={q2}&hl=en-US&gl=US&ceid=US:en")
        for e in feed2.entries[:2]:
            t_exists = any(i['title'] == e.get("title", "")[:100] for i in items)
            if not t_exists:
                items.append({
                    "title": e.get("title", "")[:100],
                    "link": e.get("link", ""),
                    "source": "Google News",
                    "summary": e.get("summary", "")[:200]
                })
    except:
        pass
    
    # 4. Finviz (web scrape)
    try:
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            table = soup.find("table", {"class": "news-table"})
            if table:
                for row in table.findAll('tr')[:4]:
                    cols = row.findAll('td')
                    if len(cols) >= 2:
                        link = cols[1].find('a')
                        if link:
                            t_exists = any(link.text[:50] in i['title'] for i in items)
                            if not t_exists:
                                items.append({
                                    "title": link.text[:100],
                                    "link": link.get('href', ''),
                                    "source": "Finviz",
                                    "summary": ""
                                })
    except:
        pass
    
    # 5. Benzinga via MarketWatch
    try:
        r = requests.get(f"https://www.marketwatch.com/investing/stock/{ticker.lower()}", headers=HEADERS, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            articles = soup.findAll('h3', class_='article__headline')[:3]
            for article in articles:
                a = article.find('a')
                if a:
                    t_exists = any(a.text[:50] in i['title'] for i in items)
                    if not t_exists:
                        items.append({
                            "title": a.text.strip()[:100],
                            "link": "https://www.marketwatch.com" + a.get('href', ''),
                            "source": "MarketWatch",
                            "summary": ""
                        })
    except:
        pass
    
    return items[:15]

def generate_ai_analysis(stock_data):
    """Generate comprehensive AI analysis from collected data"""
    s = stock_data
    fund = s.get('fundamentals', {})
    tech = s.get('technicals', {})
    mas = s.get('moving_averages', {})
    greeks = s.get('greeks', {})
    news = s.get('news', [])
    inst = s.get('institutional', {})
    
    signals = []
    analysis = []
    
    # Price & momentum signals
    chg = s.get('change', 0)
    rsi = tech.get('rsi')
    vol_ratio = s.get('vol_ratio', 1)
    
    # === VOLUME ANALYSIS ===
    if vol_ratio >= 3.0:
        signals.append(f"🔥 EXTREME Volume: {vol_ratio}x average")
    elif vol_ratio >= 2.0:
        signals.append(f"⚡ Volume Spike: {vol_ratio}x average")
    
    # === RSI ANALYSIS ===
    if rsi:
        if rsi >= 75:
            signals.append(f"🔴 Overbought (RSI: {int(rsi)})")
        elif rsi <= 25:
            signals.append(f"🟢 Oversold (RSI: {int(rsi)})")
        elif rsi <= 35:
            signals.append(f"🟡 Near Oversold (RSI: {int(rsi)})")
        elif rsi >= 65:
            signals.append(f"🟠 Near Overbought (RSI: {int(rsi)})")
    
    # === MOVING AVERAGE ANALYSIS ===
    if mas:
        vs50 = mas.get('vs_sma50')
        vs200 = mas.get('vs_sma200')
        if vs50 and vs200:
            if vs50 > 0 and vs200 > 0:
                analysis.append(f"📈 Above both 50d ({vs50:+.1f}%) & 200d ({vs200:+.1f}%) MA - Strong uptrend")
            elif vs50 < 0 and vs200 < 0:
                analysis.append(f"📉 Below both 50d ({vs50:+.1f}%) & 200d ({vs200:+.1f}%) MA - Downtrend")
            elif vs50 < 0 and vs200 > 0:
                analysis.append(f"⚠️ Below 50d MA ({vs50:+.1f}%) but above 200d - Short-term weakness")
    
    # === MACD ANALYSIS ===
    macd = tech.get('macd')
    if macd:
        analysis.append(f"MACD: {macd.get('trend', '')}")
    
    # === FUNDAMENTAL ANALYSIS ===
    pe = fund.get('pe')
    peg = fund.get('peg')
    roe = fund.get('roe')
    
    if pe:
        if pe < 10:
            analysis.append(f"💰 Very cheap P/E: {pe}x (potentially undervalued)")
        elif pe < 15:
            analysis.append(f"📊 Fair value P/E: {pe}x")
        elif pe > 40:
            analysis.append(f"⚠️ Expensive P/E: {pe}x (growth priced in)")
    
    if peg and peg < 1:
        analysis.append(f"✅ PEG ratio {peg} (< 1.0 = undervalued vs growth)")
    
    if roe and roe > 20:
        analysis.append(f"💪 Strong ROE: {roe}% (elite profitability)")
    
    # === EARNINGS ANALYSIS ===
    earnings = s.get('earnings')
    if earnings:
        days = earnings['days']
        if days == 0:
            signals.append(f"🚨 EARNINGS TODAY!")
        elif 0 < days <= 7:
            signals.append(f"📚 Earnings in {days} days ({earnings['date']})")
        elif 0 < days <= 14:
            analysis.append(f"📅 Earnings coming: {earnings['date']} ({days} days)")
    
    # === 52-WEEK POSITION ===
    price = s.get('price', 0)
    h52 = s.get('h52', 1)
    l52 = s.get('l52', 0)
    if h52 and l52 and h52 != l52:
        pct = safe((price - l52) / (h52 - l52) * 100, 0)
        if pct <= 10:
            analysis.append(f"📍 Near 52-week LOW ({pct}% from low) - potential value zone")
        elif pct >= 90:
            analysis.append(f"📍 Near 52-week HIGH ({pct}% from low) - breakout or resistance")
    
    # === SHORT INTEREST ===
    short_pct = inst.get('short_pct')
    if short_pct and short_pct > 15:
        analysis.append(f"⚠️ High short interest: {short_pct}% of float")
    
    # === NEWS SENTIMENT ===
    pos_words = ['beat', 'surge', 'rally', 'buy', 'upgrade', 'bullish', 'strong', 'partnership', 'launch', 'growth', 'record']
    neg_words = ['miss', 'plunge', 'sell', 'downgrade', 'bearish', 'weak', 'cut guidance', 'lawsuit', 'decline', 'loss']
    
    all_titles = ' '.join([n['title'].lower() for n in news[:8]])
    all_summaries = ' '.join([n.get('summary', '').lower() for n in news[:5]])
    all_text = all_titles + ' ' + all_summaries
    
    pos_count = sum(all_text.count(w) for w in pos_words)
    neg_count = sum(all_text.count(w) for w in neg_words)
    
    if pos_count > neg_count + 1:
        analysis.append(f"📰 News sentiment: Bullish ({pos_count} positive signals)")
    elif neg_count > pos_count + 1:
        analysis.append(f"📰 News sentiment: Bearish ({neg_count} negative signals)")
    else:
        analysis.append("📰 News sentiment: Mixed/Neutral")
    
    # === OPTIONS ANALYSIS ===
    if greeks:
        iv = greeks.get('iv_call')
        if iv:
            if iv > 60:
                analysis.append(f"⚡ High IV: {iv}% (expensive options, high uncertainty)")
            elif iv < 20:
                analysis.append(f"😴 Low IV: {iv}% (cheap options, low volatility expected)")
            else:
                analysis.append(f"📊 Normal IV: {iv}%")
        
        csp = greeks.get('csp')
        if csp and csp.get('premium'):
            analysis.append(f"💼 CSP opportunity: ${csp['strike']} strike, ${csp['premium']} premium ({csp['exp']})")
    
    return {
        "signals": signals,
        "analysis": analysis,
        "sentiment": "Bullish" if pos_count > neg_count else "Bearish" if neg_count > pos_count else "Neutral"
    }

def get_stock(ticker):
    """Get complete stock data"""
    try:
        print(f"  Fetching {ticker}...")
        t = yf.Ticker(ticker)
        i = t.info
        
        p = i.get("currentPrice") or i.get("regularMarketPrice") or 0
        prev = i.get("previousClose") or p
        vol = i.get("regularMarketVolume") or 0
        avg_vol = i.get("averageVolume") or vol
        
        chg = safe((p - prev) / prev * 100) if prev else 0
        vol_ratio = safe(vol / avg_vol) if avg_vol else 1.0
        spike = vol_ratio >= 2.0
        
        # Get historical data
        hist = t.history(period="250d")
        
        rsi = get_rsi(hist) if len(hist) >= 14 else None
        macd = get_macd(hist) if len(hist) >= 26 else None
        moving_averages = get_moving_averages(hist, p) if len(hist) >= 20 else {}
        
        fundamentals = get_fundamentals(i)
        earnings = get_earnings(i)
        greeks = get_options_greeks(ticker, p)
        institutional = get_institutional_data(ticker, i)
        
        name = i.get("longName", ticker)
        news = get_news_all_sources(ticker, name)
        
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
            "fundamentals": fundamentals,
            "technicals": {"rsi": rsi, "macd": macd},
            "moving_averages": moving_averages,
            "greeks": greeks,
            "institutional": institutional,
            "news": news,
        }
        
        stock['ai'] = generate_ai_analysis(stock)
        print(f"    ✓ {ticker}: ${p} ({chg:+.2f}%)")
        return stock
        
    except Exception as e:
        print(f"  ⚠️ Error {ticker}: {str(e)[:50]}")
        return None

print("Fetching all stocks...\n")
stocks = [s for s in [get_stock(t) for t in TICKERS] if s]
spikes = [s for s in stocks if s["spike"]]
earnings_week = [s for s in stocks if s["earnings"] and 0 <= s["earnings"]["days"] <= 7]

print(f"\n✓ {len(stocks)} stocks | {len(spikes)} spikes | {len(earnings_week)} earnings this week")
print("Building dashboard...")

def rsi_color(rsi):
    if not rsi: return "#333"
    if rsi >= 75: return "#dc3545"
    if rsi <= 25: return "#28a745"
    if rsi >= 65: return "#fd7e14"
    if rsi <= 35: return "#20c997"
    return "#333"

html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Monitor v4</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; padding: 20px; }}
        .wrap {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.12); overflow: hidden; }}
        header {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 40px; text-align: center; }}
        header h1 {{ font-size: 2.4em; margin-bottom: 8px; font-weight: 700; }}
        .top-alerts {{ background: #fff3cd; border-left: 5px solid #ffc107; padding: 16px 24px; }}
        .top-alert {{ font-weight: 700; margin: 4px 0; font-size: 1.05em; }}
        .content {{ padding: 30px; }}
        .stock {{ background: #f8f9fa; border-left: 6px solid #667eea; padding: 24px; margin-bottom: 24px; border-radius: 10px; }}
        .stock.spike {{ background: #fff5f5; border-left-color: #e53e3e; }}
        .stock.earnings {{ background: #fffff0; border-left-color: #d69e2e; }}
        .stock.oversold {{ background: #f0fff4; border-left-color: #38a169; }}
        .stock-head {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; flex-wrap: wrap; gap: 10px; }}
        .ticker {{ font-size: 1.8em; font-weight: 800; color: #4a5568; }}
        .price-block {{ text-align: right; }}
        .price {{ font-size: 1.5em; font-weight: 700; }}
        .chg {{ font-size: 1.1em; font-weight: 600; }}
        .up {{ color: #38a169; }}
        .down {{ color: #e53e3e; }}
        .company {{ color: #718096; margin-bottom: 16px; font-size: 0.95em; }}
        
        .metrics-grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin: 16px 0; }}
        .metric {{ background: white; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center; }}
        .metric-label {{ font-size: 0.75em; color: #718096; font-weight: 700; text-transform: uppercase; }}
        .metric-value {{ font-size: 1.1em; font-weight: 700; margin-top: 4px; }}
        
        .section {{ margin: 16px 0; }}
        .section-title {{ font-weight: 700; color: #4a5568; margin-bottom: 10px; font-size: 0.95em; text-transform: uppercase; letter-spacing: 0.5px; }}
        
        .fund-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
        .fund-item {{ background: white; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; }}
        .fund-label {{ font-size: 0.75em; color: #718096; font-weight: 600; }}
        .fund-value {{ font-size: 1em; font-weight: 700; margin-top: 2px; color: #2d3748; }}
        
        .signals {{ background: #fff9e6; border-left: 4px solid #f6ad55; padding: 12px 16px; border-radius: 6px; margin: 10px 0; }}
        .signal-item {{ margin: 5px 0; font-weight: 600; }}
        
        .analysis-box {{ background: #ebf8ff; border-left: 4px solid #4299e1; padding: 12px 16px; border-radius: 6px; margin: 10px 0; }}
        .analysis-item {{ margin: 4px 0; font-size: 0.92em; color: #2c5282; }}
        
        .greeks-box {{ background: #f0fff4; border: 1px solid #9ae6b4; padding: 12px 16px; border-radius: 6px; margin: 10px 0; }}
        .greeks-title {{ font-weight: 700; color: #276749; margin-bottom: 8px; }}
        .greek {{ display: inline-block; margin-right: 16px; font-size: 0.9em; }}
        
        .csp-box {{ background: #faf5ff; border: 1px solid #d6bcfa; padding: 12px 16px; border-radius: 6px; margin: 10px 0; }}
        .csp-title {{ font-weight: 700; color: #553c9a; margin-bottom: 8px; }}
        
        .inst-box {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 10px 0; }}
        .inst-item {{ background: white; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; text-align: center; }}
        
        .ma-box {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 10px 0; }}
        .ma-item {{ background: white; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; text-align: center; }}
        .ma-up {{ color: #38a169; }}
        .ma-down {{ color: #e53e3e; }}
        
        .news-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }}
        .news-item {{ background: white; padding: 10px 12px; border-radius: 6px; border: 1px solid #e2e8f0; border-left: 3px solid #667eea; }}
        .news-item a {{ color: #2b6cb0; text-decoration: none; font-weight: 500; font-size: 0.88em; line-height: 1.4; }}
        .news-item a:hover {{ text-decoration: underline; }}
        .news-source {{ font-size: 0.75em; color: #a0aec0; margin-top: 4px; }}
        
        footer {{ background: #2d3748; color: #a0aec0; padding: 24px; text-align: center; font-size: 0.9em; }}
        
        @media (max-width: 768px) {{
            .metrics-grid {{ grid-template-columns: repeat(3, 1fr); }}
            .fund-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .news-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
<div class="wrap">
    <header>
        <h1>📊 Stock Monitor v4</h1>
        <p style="opacity:0.9; margin-top:8px">{NOW_TW.strftime('%A, %B %d, %Y · %H:%M')} Taiwan Time</p>
        <p style="opacity:0.75; font-size:0.9em; margin-top:4px">Volume Alerts • RSI • MACD • Fundamentals • Options Greeks • CSP Analysis • Multi-Source News</p>
    </header>
"""

if spikes or earnings_week:
    html += '<div class="top-alerts">'
    if spikes:
        html += f'<div class="top-alert">🔥 VOLUME SPIKE(s) DETECTED: {", ".join([s["ticker"] for s in spikes])}</div>'
    if earnings_week:
        html += f'<div class="top-alert">📚 EARNINGS THIS WEEK: {", ".join([f"{s[\"ticker\"]} ({s[\"earnings\"][\"days\"]}d)" for s in earnings_week])}</div>'
    html += '</div>'

html += '<div class="content">'

for s in stocks:
    up = s['change'] > 0
    chg_class = "up" if up else "down"
    sign = "+" if up else ""
    rsi = s['technicals']['rsi']
    
    card_class = "stock"
    if s['spike']: card_class += " spike"
    elif s['earnings'] and 0 <= s['earnings']['days'] <= 7: card_class += " earnings"
    elif rsi and rsi <= 30: card_class += " oversold"
    
    l52, h52, p = s['l52'] or 0, s['h52'] or 1, s['price'] or 0
    price_pct = safe((p - l52) / (h52 - l52) * 100) if h52 != l52 else None
    
    html += f'''<div class="{card_class}">
        <div class="stock-head">
            <div>
                <div class="ticker">{s["ticker"]}</div>
                <div class="company">{s["name"]} • {s.get("sector","")} • Cap: {s["market_cap"]}</div>
            </div>
            <div class="price-block">
                <div class="price">{s["currency"]}{s["price"]}</div>
                <div class="chg {chg_class}">{sign}{s["change"]}% today</div>
            </div>
        </div>
        
        <div class="metrics-grid">
            <div class="metric">
                <div class="metric-label">RSI</div>
                <div class="metric-value" style="color:{rsi_color(rsi)}">{int(rsi) if rsi else "—"}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Volume</div>
                <div class="metric-value" style="color:{"#e53e3e" if s["spike"] else "#333"}">{s["vol_ratio"]}x</div>
            </div>
            <div class="metric">
                <div class="metric-label">52w Low</div>
                <div class="metric-value">{s["currency"]}{s["l52"]}</div>
            </div>
            <div class="metric">
                <div class="metric-label">52w High</div>
                <div class="metric-value">{s["currency"]}{s["h52"]}</div>
            </div>
            <div class="metric">
                <div class="metric-label">In Range</div>
                <div class="metric-value">{price_pct}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Beta</div>
                <div class="metric-value">{s["fundamentals"].get("beta","—")}</div>
            </div>
        </div>
'''
    
    # Moving Averages
    mas = s.get('moving_averages', {})
    if mas:
        html += '<div class="section"><div class="section-title">📈 Moving Averages</div><div class="ma-box">'
        if 'sma20' in mas:
            cls = "ma-up" if mas.get('vs_sma20',0) > 0 else "ma-down"
            html += f'<div class="ma-item"><div class="metric-label">SMA 20</div><div class="metric-value {cls}">{s["currency"]}{mas["sma20"]} ({mas.get("vs_sma20",0):+.1f}%)</div></div>'
        if 'sma50' in mas:
            cls = "ma-up" if mas.get('vs_sma50',0) > 0 else "ma-down"
            html += f'<div class="ma-item"><div class="metric-label">SMA 50</div><div class="metric-value {cls}">{s["currency"]}{mas["sma50"]} ({mas.get("vs_sma50",0):+.1f}%)</div></div>'
        if 'sma200' in mas:
            cls = "ma-up" if mas.get('vs_sma200',0) > 0 else "ma-down"
            html += f'<div class="ma-item"><div class="metric-label">SMA 200</div><div class="metric-value {cls}">{s["currency"]}{mas["sma200"]} ({mas.get("vs_sma200",0):+.1f}%)</div></div>'
        html += '</div></div>'
    
    # Fundamentals
    f = s.get('fundamentals', {})
    if any(f.get(k) for k in ['pe','peg','pb','roe']):
        html += '<div class="section"><div class="section-title">💰 Fundamentals</div><div class="fund-grid">'
        fields = [
            ('P/E', 'pe'), ('Fwd P/E', 'fpe'), ('PEG', 'peg'), ('P/B', 'pb'),
            ('ROE%', 'roe'), ('ROA%', 'roa'), ('Margin%', 'profit_margin'),
            ('Rev Growth%', 'revenue_growth'), ('EPS', 'eps'), ('FCF', 'fcf'),
            ('D/E', 'debt_equity'), ('Short%', 'short_ratio')
        ]
        for label, key in fields:
            val = f.get(key, '—')
            if val:
                html += f'<div class="fund-item"><div class="fund-label">{label}</div><div class="fund-value">{val}</div></div>'
        html += '</div></div>'
    
    # Institutional
    inst = s.get('institutional', {})
    if any(inst.get(k) for k in ['institutional','insider','short_pct']):
        html += '<div class="section"><div class="section-title">🏦 Ownership</div><div class="inst-box">'
        html += f'<div class="inst-item"><div class="metric-label">Institutional</div><div class="metric-value">{inst.get("institutional","—")}%</div></div>'
        html += f'<div class="inst-item"><div class="metric-label">Insider</div><div class="metric-value">{inst.get("insider","—")}%</div></div>'
        html += f'<div class="inst-item"><div class="metric-label">Short Float</div><div class="metric-value">{inst.get("short_pct","—")}%</div></div>'
        html += '</div></div>'
    
    # Options Greeks + CSP
    g = s.get('greeks')
    if g:
        html += f'<div class="section"><div class="section-title">📊 Options Greeks (Exp: {g.get("exp","")})</div><div class="greeks-box">'
        if g.get("iv_call"): html += f'<span class="greek"><strong>IV:</strong> {g["iv_call"]}%</span>'
        if g.get("delta"):   html += f'<span class="greek"><strong>Δ Delta:</strong> {g["delta"]}</span>'
        if g.get("theta"):   html += f'<span class="greek"><strong>Θ Theta:</strong> {g["theta"]}</span>'
        if g.get("gamma"):   html += f'<span class="greek"><strong>Γ Gamma:</strong> {g["gamma"]}</span>'
        html += '</div>'
        
        csp = g.get('csp')
        if csp and csp.get('premium'):
            html += f'<div class="csp-box"><div class="csp-title">💼 Cash Secured Put Opportunity</div>'
            html += f'Strike: ${csp["strike"]} | Premium: ${csp["premium"]} | IV: {csp["iv"]}% | Exp: {csp["exp"]}'
            html += '</div>'
        html += '</div>'
    
    # AI Analysis
    ai = s.get('ai', {})
    signals = ai.get('signals', [])
    analysis_points = ai.get('analysis', [])
    
    if signals:
        html += '<div class="signals">'
        for sig in signals:
            html += f'<div class="signal-item">{sig}</div>'
        html += '</div>'
    
    if analysis_points:
        html += '<div class="section"><div class="section-title">🤖 AI Analysis</div><div class="analysis-box">'
        for point in analysis_points:
            html += f'<div class="analysis-item">• {point}</div>'
        html += '</div></div>'
    
    # Earnings
    if s.get('earnings'):
        e = s['earnings']
        days = e['days']
        if days >= 0:
            badge = "🚨 TODAY!" if days == 0 else f"📚 {days} days ({e['date']})"
            html += f'<div class="signals" style="background:#fff0f0"><div class="signal-item">Earnings: {badge}</div></div>'
    
    # News
    if s.get('news'):
        html += f'<div class="section"><div class="section-title">📰 Latest News ({len(s["news"])} sources)</div><div class="news-grid">'
        for n in s['news'][:10]:
            html += f'<div class="news-item"><a href="{n["link"]}" target="_blank">{n["title"]}</a><div class="news-source">{n["source"]}</div></div>'
        html += '</div></div>'
    
    html += '</div>'

html += f'''</div>
<footer>
    <p>🤖 Stock Monitor v4 | RSI • MACD • Moving Averages • Fundamentals • Options Greeks • CSP Analysis</p>
    <p style="margin-top:6px">Sources: Yahoo Finance • Google News • Finviz • MarketWatch | Auto-updates: 4 AM & 4 PM Taiwan Time</p>
    <p style="margin-top:6px; font-size:0.8em">⚠️ Not financial advice. For informational purposes only.</p>
</footer>
</div>
</body>
</html>'''

(DOCS / "index.html").write_text(html)
print("✅ Dashboard generated!")
print(f"   ✓ {len(stocks)} stocks analyzed")
print(f"   ✓ {len(spikes)} volume spikes")
print(f"   ✓ {len(earnings_week)} earnings this week")
