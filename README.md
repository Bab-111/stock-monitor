# 📊 Stock Monitor v4 - Professional Grade

AI-powered stock monitoring system with earnings alerts, volume spikes, and intelligent news summaries. **100% FREE** - runs on GitHub Actions with GitHub Models API.

## ✨ Features

### 🎯 Core Features
- **Volume Alerts** 🔴 - Detects 2x+ volume spikes vs 5-day average
- **Earnings Calendar** 📅 - Alerts for earnings this/next week
- **Multi-Source News** 📰 - Yahoo Finance + Google News aggregation
- **AI Summaries** 🧠 - FREE Claude 3.5 via GitHub Models API
- **Options Greeks** 📊 - IV, Delta, Theta tracking (major tickers)
- **Trading Signals** ⚡ - Automated buy/sell signals

### 🎨 Design
- Beautiful responsive HTML dashboard
- Real-time alerts banner
- Color-coded cards (volume spikes 🔴, earnings 📙)
- Mobile-friendly layout
- Dark theme with gradients

## 💰 Cost: $0

| Feature | Service | Cost |
|---------|---------|------|
| Stock data | yfinance | FREE ✅ |
| Earnings data | yfinance | FREE ✅ |
| News feeds | Yahoo/Google | FREE ✅ |
| Options data | yfinance | FREE ✅ |
| AI summaries | GitHub Models API | 100K tokens/month FREE ✅ |
| Execution | GitHub Actions | 6,000 min/month FREE ✅ |
| Hosting | GitHub Pages | FREE ✅ |
| **TOTAL** | | **$0** 🚀 |

## 🚀 Quick Start

### Step 1: Clone & Setup
```bash
git clone https://github.com/Bab-111/stock-monitor.git
cd stock-monitor
mkdir -p .github/workflows scripts docs/history
```

### Step 2: Create Token
Go to https://github.com/settings/tokens and create a new token with `repo` scope

### Step 3: Add Secret
Go to Settings → Secrets → Actions → New repository secret
- Name: `GITHUB_TOKEN`
- Value: Your token

### Step 4: Configure Tickers
Edit `stocks.json` and change the tickers to what you want to monitor

### Step 5: Deploy
```bash
git add -A
git commit -m "🚀 Deploy Stock Monitor v4"
git push origin main
```

### Step 6: Enable GitHub Pages
1. Go to Settings → Pages
2. Source: Deploy from a branch
3. Branch: gh-pages / root
4. Save

Your dashboard is now live at: `https://YOUR-USERNAME.github.io/stock-monitor`

## 📊 What Each Metric Means

### Volume Alerts 🔴
- **2x+:** Unusual trading activity detected
- **Compared to:** 5-day rolling average
- **Why it matters:** Often precedes significant price moves

### RSI (Relative Strength Index)
- **> 75:** Overbought (🔴 pullback likely)
- **< 25:** Oversold (🟢 bounce opportunity)
- **25-75:** Normal range

### Earnings 📅
- **THIS week:** Yellow highlight
- **7+ days:** Shows in calendar
- **TBD:** Not available for all tickers

### Options Greeks (Major tickers only)
- **IV (Implied Volatility):** Market expectation of price swings
- **Delta (Δ):** Option price sensitivity to stock moves
- **Theta (Θ):** Time decay per day

## 🤖 AI Analysis

Stock Monitor uses **GitHub Models API** (FREE Claude 3.5 Sonnet) to:
✅ Summarize news without hallucinations
✅ Extract key facts (earnings, product launches, partnerships)
✅ Note sentiment (Positive/Negative/Neutral)
✅ Flag conflicting information
✅ Fact-check across multiple sources

**Max 100K tokens/month FREE** = ~50,000 stock analyses

## 📰 News Sources

1. **Yahoo Finance** (RSS Feed) - 3 latest articles
2. **Google News** (RSS Feed) - 2 latest articles

Each article includes:
- Title & link
- Source
- Publication date
- Summary (first 200 chars)

## 🛠️ Project Structure
