"""
Live Market & SG Rates Dashboard (Streamlit)
=============================================
Deploy this on Streamlit Community Cloud (free) to get a public link you can
open from your phone. See DEPLOY.md for the 3-minute setup.

Data refreshes automatically every 5 minutes (adjustable via CACHE_TTL below).
"""

import datetime
import re

import requests
import pandas as pd
import streamlit as st
import yfinance as yf
import feedparser

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

CACHE_TTL = 300  # seconds between live re-fetches (5 min)

TICKERS = {
    "S&P 500":            "^GSPC",
    "Nasdaq 100":         "^NDX",
    "Dow Jones":          "^DJI",
    "VIX":                "^VIX",
    "10Y Treasury Yield":  "^TNX",
    "STI (Singapore)":    "^STI",
    "CSI 300 (China)":    "000300.SS",
    "Nifty 50 (India)":   "^NSEI",
}

NEWS_FEEDS = {
    "Singapore":     "https://news.google.com/rss/search?q=Singapore+STI+stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
    "United States": "https://news.google.com/rss/search?q=stock+market+US+when:1d&hl=en-US&gl=US&ceid=US:en",
    "China":         "https://news.google.com/rss/search?q=China+stock+market+CSI300+when:1d&hl=en-US&gl=US&ceid=US:en",
    "India":         "https://news.google.com/rss/search?q=India+stock+market+Sensex+Nifty+when:1d&hl=en-US&gl=US&ceid=US:en",
}
HEADLINES_PER_MARKET = 3

MAS_CPI_PRESS_PAGE = "https://www.mas.gov.sg/monetary-policy/consumer-price-developments"
DATA_GOV_CPI_API = (
    "https://data.gov.sg/api/action/datastore_search"
    "?resource_id=d_bdaff844e3ef89d39fceb962ff8f0791&limit=1&sort=month desc"
)
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketTrackerBot/1.0)"}


# ---------------------------------------------------------------------------
# DATA FETCHING (all cached so the app doesn't hammer sources on every click)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL)
def fetch_index_data():
    rows = []
    for label, symbol in TICKERS.items():
        try:
            info = yf.Ticker(symbol).fast_info
            last, prev = info["lastPrice"], info["previousClose"]
            pct = (last - prev) / prev * 100 if prev else 0.0
            if label == "10Y Treasury Yield":
                last, prev = last / 10, prev / 10
                display = f"{last:.3f}%"
            else:
                display = f"{last:,.2f}"
            rows.append({"label": label, "value": display, "change_pct": pct})
        except Exception as e:
            rows.append({"label": label, "value": "N/A", "change_pct": None, "error": str(e)})
    return rows


@st.cache_data(ttl=CACHE_TTL)
def fetch_inflation():
    headline = "unavailable"
    try:
        r = requests.get(DATA_GOV_CPI_API, headers=REQUEST_HEADERS, timeout=10)
        r.raise_for_status()
        records = r.json()["result"]["records"]
        all_items = next(
            (rec for rec in records if "all items" in str(rec.get("level_1", "")).lower()),
            records[0] if records else None,
        )
        if all_items:
            headline = f"{all_items.get('value', 'N/A')} (index, {all_items.get('month', 'N/A')})"
    except Exception as e:
        headline = f"unavailable ({e})"

    core = "unavailable"
    try:
        r = requests.get(MAS_CPI_PRESS_PAGE, headers=REQUEST_HEADERS, timeout=10)
        r.raise_for_status()
        match = re.search(r"MAS Core Inflation[^.]{0,200}?(\d+\.\d+)\s*%", r.text, re.IGNORECASE)
        core = f"{match.group(1)}% (y/y)" if match else "figure not found on page"
    except Exception as e:
        core = f"unavailable ({e})"

    return headline, core


@st.cache_data(ttl=CACHE_TTL)
def fetch_news():
    news = {}
    for market, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            news[market] = [e.title for e in feed.entries[:HEADLINES_PER_MARKET]] or ["No headlines found."]
        except Exception as e:
            news[market] = [f"Error: {e}"]
    return news


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Market Tracker", page_icon="📈", layout="wide")
st.title("📈 Market Tracker")
st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%A, %d %b %Y %H:%M')} "
           f"· Auto-refreshes every {CACHE_TTL // 60} min")

if st.button("🔄 Refresh now"):
    st.cache_data.clear()

st.subheader("Global Indices")
cols = st.columns(3)
for i, row in enumerate(fetch_index_data()):
    with cols[i % 3]:
        if row.get("change_pct") is None:
            st.metric(row["label"], row["value"])
        else:
            st.metric(row["label"], row["value"], f"{row['change_pct']:+.2f}%")

st.subheader("📰 Live Market News — SG, US, China, India")
news = fetch_news()
tabs = st.tabs(list(news.keys()))
for tab, (market, headlines) in zip(tabs, news.items()):
    with tab:
        for h in headlines:
            st.markdown(f"- {h}")

st.divider()
st.caption(
    "Data sources: Yahoo Finance (indices/VIX/yields), data.gov.sg (CPI), "
    "MAS website (Core Inflation), Google News RSS (headlines). "
    "This is informational only, not financial advice."
)
