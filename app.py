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
import requests
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
    "KOSPI (South Korea)": "^KS11",
}

# Currency pairs shown in their own "Currencies" section. `invert` means the
# Yahoo Finance ticker actually quotes USD per 1 unit of the other currency
# (or vice-versa), so we flip it to display the pair the way it's labeled.
CURRENCIES = {
    "US Dollar Index (DXY)": {"ticker": "DX-Y.NYB", "invert": False},
    "SGD/USD":               {"ticker": "SGD=X",    "invert": True},   # SGD=X quotes USD->SGD
    "AUD/USD":                {"ticker": "AUDUSD=X", "invert": False},  # already AUD->USD
    "CAD/USD":                {"ticker": "CAD=X",    "invert": True},   # CAD=X quotes USD->CAD
    "NZD/USD":                {"ticker": "NZDUSD=X", "invert": False},  # already NZD->USD
}

NEWS_FEEDS = {
    "Singapore":     "https://news.google.com/rss/search?q=Singapore+STI+stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
    "United States": "https://news.google.com/rss/search?q=stock+market+US+when:1d&hl=en-US&gl=US&ceid=US:en",
    "China":         "https://news.google.com/rss/search?q=China+stock+market+CSI300+when:1d&hl=en-US&gl=US&ceid=US:en",
    "India":         "https://news.google.com/rss/search?q=India+stock+market+Sensex+Nifty+when:1d&hl=en-US&gl=US&ceid=US:en",
}
HEADLINES_PER_MARKET = 3  # target number of headlines from reputable outlets
MIN_HEADLINES_PER_MARKET = 3  # absolute floor - backfilled from other outlets if needed
# Google News RSS returns many outlets of wildly varying quality. We prefer
# headlines whose <source> matches one of these reputable, well-known
# financial/general news outlets (case-insensitive substring match). If a
# market doesn't have enough reputable headlines, we backfill with other
# outlets so every tab always shows at least MIN_HEADLINES_PER_MARKET items.
REPUTABLE_SOURCES = [
    "Reuters", "Bloomberg", "CNBC", "The Wall Street Journal", "WSJ",
    "Financial Times", "Associated Press", "AP News", "BBC",
    "The Straits Times", "Channel News Asia", "CNA", "The Business Times",
    "MarketWatch", "Barron's", "The Economist", "Forbes", "Nikkei Asia",
    "South China Morning Post", "The Economic Times", "Livemint",
]

# Live S&P 500 sector heat map, embedded directly from Finviz (updates on their end).
FINVIZ_SP500_MAP_URL = "https://finviz.com/map.ashx?t=sec_all"

_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketTrackerBot/1.0)"}


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
def fetch_currency_data():
    rows = []
    for label, meta in CURRENCIES.items():
        try:
            info = yf.Ticker(meta["ticker"]).fast_info
            last, prev = info["lastPrice"], info["previousClose"]
            if meta["invert"]:
                last, prev = (1 / last if last else 0.0), (1 / prev if prev else 0.0)
            pct = (last - prev) / prev * 100 if prev else 0.0
            display = f"{last:,.2f}" if label.startswith("US Dollar Index") else f"{last:,.4f}"
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


@st.cache_data(ttl=CACHE_TTL)
def _validate_image(url):
    """Return the url only if it actually resolves to a loadable image, else None."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=4, stream=True, headers=_HTTP_HEADERS)
        content_type = resp.headers.get("Content-Type", "")
        if resp.status_code == 200 and content_type.startswith("image"):
            return url
    except Exception:
        pass
    return None


@st.cache_data(ttl=CACHE_TTL)
def _fetch_og_image(article_url):
    """Fallback: follow the article link and pull its og:image meta tag."""
    if not article_url:
        return None
    try:
        resp = requests.get(article_url, timeout=5, headers=_HTTP_HEADERS, allow_redirects=True)
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            resp.text, re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                resp.text, re.IGNORECASE,
            )
        if match:
            return _validate_image(match.group(1))
    except Exception:
        pass
    return None


def _resolve_image(entry, link):
    """Get a verified-viewable image URL for a headline, or None if none can be found."""
    img = _validate_image(_extract_image(entry))
    if not img:
        img = _fetch_og_image(link)
    return img


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


def _build_item(entry, source):
    title = entry.get("title", "Untitled")
    clean_title = re.sub(r"\s*-\s*" + re.escape(source) + r"\s*$", "", title) if source else title
    link = entry.get("link", "")
    return {
        "title": clean_title,
        "link": link,
        "source": source,
        "image": None,  # resolved lazily, only for headlines we actually keep
        "published": entry.get("published", ""),
    }


@st.cache_data(ttl=CACHE_TTL)
def fetch_news():
    news = {}
    for market, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            reputable, fallback = [], []
            for e in feed.entries:
                source = _source_name(e)
                item = _build_item(e, source)
                if _is_reputable(source):
                    reputable.append((e, item))
                else:
                    fallback.append((e, item))

            chosen = reputable[:HEADLINES_PER_MARKET]
            if len(chosen) < MIN_HEADLINES_PER_MARKET:
                needed = MIN_HEADLINES_PER_MARKET - len(chosen)
                chosen += fallback[:needed]

            items = []
            for e, item in chosen:
                item["image"] = _resolve_image(e, item["link"])
                items.append(item)
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

st.subheader("💱 Currencies")
currency_cols = st.columns(3)
for i, row in enumerate(fetch_currency_data()):
    with currency_cols[i % 3]:
        if row.get("change_pct") is None:
            st.metric(row["label"], row["value"])
        else:
            st.metric(row["label"], row["value"], f"{row['change_pct']:+.2f}%")

st.subheader("📰 Live Market News — SG, US, China, India")
st.caption(f"Prioritizes reputable outlets (Reuters, Bloomberg, CNBC, FT, WSJ, AP, BBC, and similar); "
           f"backfilled with other outlets so each tab always shows at least {MIN_HEADLINES_PER_MARKET} headlines.")
news = fetch_news()
tabs = st.tabs(list(news.keys()))
for tab, (market, items) in zip(tabs, news.items()):
    with tab:
        if not items:
            st.markdown("_No headlines found right now._")
            continue
        for item in items:
            if item["image"]:
                card_cols = st.columns([1, 3])
                with card_cols[0]:
                    st.image(item["image"], use_container_width=True)
                text_col = card_cols[1]
            else:
                text_col = st.container()
            with text_col:
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
    "Data sources: Yahoo Finance (indices/currencies/VIX/yields), Google News RSS "
    "(headlines, prioritizing reputable outlets), Finviz (S&P 500 heat map). "
    "This is informational only, not financial advice."
)
