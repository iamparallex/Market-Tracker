"""
Live Market Dashboard (Streamlit)
=============================================
Deploy this on Streamlit Community Cloud (free) to get a public link you can
open from your phone. See DEPLOY.md for the 3-minute setup.

Data refreshes automatically every 5 minutes (adjustable via CACHE_TTL below).
"""

import datetime
import re

import feedparser
import yfinance as yf
import streamlit as st
import streamlit.components.v1 as components

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
    "Nikkei 225 (Japan)": "^N225",
    "Hang Seng (HSI)":    "^HSI",
    "US Dollar Index (DXY)": "DX-Y.NYB",
}

NEWS_FEEDS = {
    "Singapore":     "https://news.google.com/rss/search?q=Singapore+STI+stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
    "United States": "https://news.google.com/rss/search?q=stock+market+US+when:1d&hl=en-US&gl=US&ceid=US:en",
    "China":         "https://news.google.com/rss/search?q=China+stock+market+CSI300+when:1d&hl=en-US&gl=US&ceid=US:en",
    "India":         "https://news.google.com/rss/search?q=India+stock+market+Sensex+Nifty+when:1d&hl=en-US&gl=US&ceid=US:en",
}
HEADLINES_PER_MARKET = 3
# Google News RSS returns many outlets of wildly varying quality. We only
# keep headlines whose <source> matches one of these reputable, well-known
# financial/general news outlets (case-insensitive substring match).
REPUTABLE_SOURCES = [
    "Reuters", "Bloomberg", "CNBC", "The Wall Street Journal", "WSJ",
    "Financial Times", "Associated Press", "AP News", "BBC",
    "The Straits Times", "Channel News Asia", "CNA", "The Business Times",
    "MarketWatch", "Barron's", "The Economist", "Forbes", "Nikkei Asia",
    "South China Morning Post", "The Economic Times", "Livemint",
]

# Live S&P 500 sector heat map, embedded directly from Finviz (updates on their end).
FINVIZ_SP500_MAP_URL = "https://finviz.com/map.ashx?t=sec_all"


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


def _extract_image(entry):
    """Best-effort extraction of a thumbnail/preview image URL from an RSS entry."""
    # media:thumbnail / media:content (some feeds include these)
    for attr in ("media_thumbnail", "media_content"):
        media = getattr(entry, attr, None)
        if media:
            url = media[0].get("url")
            if url:
                return url
    # Fall back to scanning the HTML summary/description for an <img> tag
    html = entry.get("summary", "") or entry.get("description", "")
    match = re.search(r'<img[^>]+src="([^"]+)"', html)
    if match:
        return match.group(1)
    return None


def _source_name(entry):
    src = getattr(entry, "source", None)
    if src is not None:
        title = getattr(src, "title", None)
        if not title and isinstance(src, dict):
            title = src.get("title")
        if title:
            return title
    # Google News titles are usually formatted "Headline - Source Name"
    title = entry.get("title", "")
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return ""


def _is_reputable(source_name):
    if not source_name:
        return False
    lname = source_name.lower()
    return any(rep.lower() in lname for rep in REPUTABLE_SOURCES)


@st.cache_data(ttl=CACHE_TTL)
def fetch_news():
    news = {}
    for market, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            items = []
            for e in feed.entries:
                source = _source_name(e)
                if not _is_reputable(source):
                    continue
                title = e.get("title", "Untitled")
                # Strip the trailing " - Source Name" Google News appends
                clean_title = re.sub(r"\s*-\s*" + re.escape(source) + r"\s*$", "", title) if source else title
                items.append({
                    "title": clean_title,
                    "link": e.get("link", ""),
                    "source": source,
                    "image": _extract_image(e),
                    "published": e.get("published", ""),
                })
                if len(items) >= HEADLINES_PER_MARKET:
                    break
            news[market] = items or None
        except Exception as e:
            news[market] = [{"title": f"Error: {e}", "link": "", "source": "", "image": None, "published": ""}]
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
st.caption("Only showing headlines from reputable outlets (Reuters, Bloomberg, CNBC, FT, WSJ, AP, BBC, and similar).")
news = fetch_news()
tabs = st.tabs(list(news.keys()))
for tab, (market, items) in zip(tabs, news.items()):
    with tab:
        if not items:
            st.markdown("_No headlines from reputable sources found right now._")
            continue
        for item in items:
            card_cols = st.columns([1, 3])
            with card_cols[0]:
                if item["image"]:
                    st.image(item["image"], use_container_width=True)
            with card_cols[1]:
                if item["link"]:
                    st.markdown(f"**[{item['title']}]({item['link']})**")
                else:
                    st.markdown(f"**{item['title']}**")
                meta = item["source"] or ""
                if item["published"]:
                    meta = f"{meta} · {item['published']}" if meta else item["published"]
                if meta:
                    st.caption(meta)
            st.divider()

st.subheader("🗺️ S&P 500 Heat Map")
st.caption("Live sector/stock heat map, embedded directly from Finviz — colors and sizes update on their end in real time.")
components.iframe(FINVIZ_SP500_MAP_URL, height=650, scrolling=True)
st.link_button("Open full map on Finviz ↗", FINVIZ_SP500_MAP_URL)

st.caption(
    "Data sources: Yahoo Finance (indices/VIX/yields/DXY), Google News RSS "
    "(headlines, filtered to reputable outlets), Finviz (S&P 500 heat map). "
    "This is informational only, not financial advice."
)
