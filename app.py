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
}

NEWS_FEEDS = {
    "United States": "https://news.google.com/rss/search?q=stock+market+US+when:1d&hl=en-US&gl=US&ceid=US:en",
    "China":         "https://news.google.com/rss/search?q=China+stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
    "India":         "https://news.google.com/rss/search?q=India+stock+market+Sensex+Nifty+when:1d&hl=en-US&gl=US&ceid=US:en",
    "Singapore":     "https://news.google.com/rss/search?q=Singapore+STI+stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
}
HEADLINES_PER_MARKET = 3

MAS_SORA_API = (
    "https://eservices.mas.gov.sg/api/action/datastore/search.json"
    "?resource_id=9a0bf149-308c-4bd2-832d-76c8e6cb47ed&limit=1&sort=end_of_day desc"
)
MAS_TBILL_AUCTIONS_PAGE = "https://eservices.mas.gov.sg/statistics/fdanet/TreasuryBillAuctions.aspx"
MAS_SSB_PAGE = "https://www.mas.gov.sg/bonds-and-bills/singapore-savings-bonds"
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
def fetch_sora():
    try:
        r = requests.get(MAS_SORA_API, headers=REQUEST_HEADERS, timeout=10)
        r.raise_for_status()
        rec = r.json()["result"]["records"][0]
        return {
            "date": rec.get("end_of_day", "N/A"),
            "sora": rec.get("sora", "N/A"),
            "comp_1m": rec.get("comp_sora_1m", "N/A"),
            "comp_3m": rec.get("comp_sora_3m", "N/A"),
        }
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=CACHE_TTL)
def fetch_tbill_rates():
    try:
        r = requests.get(MAS_TBILL_AUCTIONS_PAGE, headers=REQUEST_HEADERS, timeout=10)
        r.raise_for_status()
        tables = pd.read_html(r.text)
        df = max(tables, key=len)
        return df.head(3)
    except Exception as e:
        return str(e)


@st.cache_data(ttl=CACHE_TTL)
def fetch_ssb_rates():
    try:
        r = requests.get(MAS_SSB_PAGE, headers=REQUEST_HEADERS, timeout=10)
        r.raise_for_status()
        tables = pd.read_html(r.text)
        df = max(tables, key=len)
        return df.head(3)
    except Exception as e:
        return str(e)


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

st.subheader("🇸🇬 Singapore Rates & Inflation")
sora = fetch_sora()
c1, c2, c3, c4 = st.columns(4)
with c1:
    if "error" in sora:
        st.metric("SORA", "N/A")
    else:
        st.metric("SORA", f"{sora['sora']}%", help=f"As at {sora['date']}")
with c2:
    if "error" not in sora:
        st.metric("1M Compounded SORA", f"{sora['comp_1m']}%")
with c3:
    headline, core = fetch_inflation()
    st.metric("Headline CPI", headline)
with c4:
    st.metric("MAS Core Inflation", core)

col_a, col_b = st.columns(2)
with col_a:
    st.markdown("**T-bill auction results (latest)**")
    tbills = fetch_tbill_rates()
    if isinstance(tbills, str):
        st.caption(f"Unavailable via scraper: {tbills}")
        st.link_button("Check manually on MAS", MAS_TBILL_AUCTIONS_PAGE)
    else:
        st.dataframe(tbills, use_container_width=True, hide_index=True)

with col_b:
    st.markdown("**Singapore Savings Bond (SSB) rates (latest)**")
    ssb = fetch_ssb_rates()
    if isinstance(ssb, str):
        st.caption(f"Unavailable via scraper: {ssb}")
        st.link_button("Check manually on MAS", MAS_SSB_PAGE)
    else:
        st.dataframe(ssb, use_container_width=True, hide_index=True)

st.subheader("📰 Headline News by Market")
news = fetch_news()
tabs = st.tabs(list(news.keys()))
for tab, (market, headlines) in zip(tabs, news.items()):
    with tab:
        for h in headlines:
            st.markdown(f"- {h}")

st.divider()
st.caption(
    "Data sources: Yahoo Finance (indices/VIX/yields), MAS eServices API (SORA), "
    "MAS website (T-bills, SSB), data.gov.sg (CPI), Google News RSS (headlines). "
    "This is informational only, not financial advice."
)
