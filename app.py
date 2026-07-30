"""
Live Market Dashboard (Streamlit)
=============================================
Deploy this on Streamlit Community Cloud (free) to get a public link you can
open from your phone. See DEPLOY.md for the 3-minute setup.

Data refreshes automatically every 5 minutes (adjustable via CACHE_TTL below).
"""

import datetime
import re
import time
from urllib.parse import quote_plus

import feedparser
import yfinance as yf
import streamlit as st

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

# Commodities section — live benchmark prices sourced from the same Yahoo
# Finance feed already used for indices and currencies above, so these
# refresh on the same CACHE_TTL cycle rather than being a static figure.
# "BZ=F" (ICE Brent Crude) and "GC=F"/"SI=F" (COMEX Gold/Silver) are
# near-month futures contracts — the standard, reliably-quoted live proxy
# for these commodities' prices (this is what most market trackers display
# as "spot" gold/silver, since Yahoo Finance's dedicated spot tickers
# XAUUSD=X/XAGUSD=X frequently return no usable last/previous-close data
# through fast_info and were dropping out on refresh).
COMMODITIES = {
    "Brent Crude":  {"ticker": "BZ=F", "unit": "/bbl"},
    "Gold Spot":    {"ticker": "GC=F", "unit": "/oz"},
    "Silver Spot":  {"ticker": "SI=F", "unit": "/oz"},
}

# Curated set of large, liquid constituents from each market's major index,
# used to surface the day's top performers. Not the full index membership
# (some indexes, e.g. CSI 300, run to hundreds of names) — this is a
# representative slate of the bigger, more liquid names in each.
TOP_STOCKS_UNIVERSE = {
    "United States": {  # S&P 500 blue chips
        "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "GOOGL": "Alphabet",
        "AMZN": "Amazon", "META": "Meta Platforms", "TSLA": "Tesla", "BRK-B": "Berkshire Hathaway",
        "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard", "UNH": "UnitedHealth",
        "JNJ": "Johnson & Johnson", "XOM": "ExxonMobil", "PG": "Procter & Gamble",
        "HD": "Home Depot", "COST": "Costco", "AVGO": "Broadcom", "ORCL": "Oracle",
        "KO": "Coca-Cola", "PEP": "PepsiCo", "DIS": "Disney", "NFLX": "Netflix",
        "AMD": "AMD", "CRM": "Salesforce", "BAC": "Bank of America", "ABBV": "AbbVie",
        "WMT": "Walmart", "ADBE": "Adobe", "PFE": "Pfizer",
    },
    "China": {  # CSI 300 heavyweights
        "600519.SS": "Kweichow Moutai", "601318.SS": "Ping An Insurance",
        "000858.SZ": "Wuliangye", "600036.SS": "China Merchants Bank",
        "300750.SZ": "CATL", "601899.SS": "Zijin Mining", "601398.SS": "ICBC",
        "000333.SZ": "Midea Group", "601288.SS": "Agricultural Bank of China",
        "600030.SS": "CITIC Securities", "601988.SS": "Bank of China",
        "600276.SS": "Hengrui Medicine", "002594.SZ": "BYD", "601088.SS": "China Shenhua",
        "600809.SS": "Shanxi Fenjiu", "601166.SS": "Industrial Bank",
        "300059.SZ": "East Money Information", "601328.SS": "Bank of Communications",
        "600887.SS": "Yili Group", "000651.SZ": "Gree Electric",
    },
    "India": {  # Nifty 50 heavyweights
        "RELIANCE.NS": "Reliance Industries", "TCS.NS": "Tata Consultancy Services",
        "HDFCBANK.NS": "HDFC Bank", "ICICIBANK.NS": "ICICI Bank", "INFY.NS": "Infosys",
        "HINDUNILVR.NS": "Hindustan Unilever", "ITC.NS": "ITC", "SBIN.NS": "State Bank of India",
        "BHARTIARTL.NS": "Bharti Airtel", "KOTAKBANK.NS": "Kotak Mahindra Bank",
        "LT.NS": "Larsen & Toubro", "BAJFINANCE.NS": "Bajaj Finance",
        "ASIANPAINT.NS": "Asian Paints", "MARUTI.NS": "Maruti Suzuki", "AXISBANK.NS": "Axis Bank",
        "SUNPHARMA.NS": "Sun Pharma", "TITAN.NS": "Titan Company", "ULTRACEMCO.NS": "UltraTech Cement",
        "WIPRO.NS": "Wipro", "NTPC.NS": "NTPC", "TATAMOTORS.NS": "Tata Motors",
        "ADANIENT.NS": "Adani Enterprises", "HCLTECH.NS": "HCL Technologies",
        "M&M.NS": "Mahindra & Mahindra", "POWERGRID.NS": "Power Grid Corp",
    },
    "Singapore": {  # Straits Times Index (STI) constituents
        "D05.SI": "DBS Group", "O39.SI": "OCBC Bank", "U11.SI": "UOB",
        "C6L.SI": "Singapore Airlines", "Z74.SI": "Singtel", "S68.SI": "SGX",
        "C38U.SI": "CapitaLand Integrated Comm. Trust", "A17U.SI": "Ascendas REIT",
        "C31.SI": "CapitaLand Investment", "F34.SI": "Wilmar International",
        "Y92.SI": "Thai Beverage", "G13.SI": "Genting Singapore", "BN4.SI": "Keppel Ltd",
        "N2IU.SI": "Mapletree Pan Asia Comm. Trust", "ME8U.SI": "Mapletree Industrial Trust",
        "M44U.SI": "Mapletree Logistics Trust", "9CI.SI": "CapitaLand China Trust",
        "V03.SI": "Venture Corporation", "S63.SI": "ST Engineering", "U96.SI": "Sembcorp Industries",
    },
}
# Manufacturing & Services PMI (Purchasing Managers' Index) — United States
# only. There's no free real-time numeric API for PMI (ISM/S&P Global/NBS
# all license the raw data commercially), so instead of a fixed snapshot we
# treat this the same way the News section already does: poll Google News
# RSS for the latest reputable-outlet headline reporting each release, and
# parse the figure straight out of that headline. Because it's re-fetched on
# every cache cycle, a new PMI print shows up here automatically as soon as
# a reputable outlet reports it — no manual updates needed. If a headline's
# wording can't be parsed into a number, we still surface the headline
# itself (with a link back to the source) rather than guessing.
#
# Each entry below is a *list* of plain search-term variants (no boolean
# operators/parentheses — Google News RSS handles those inconsistently) tried
# in order; we also scan several matching headlines per variant, since a
# narrative-style headline (e.g. "Factory activity expands for a third
# month") often omits the actual number even when it's a perfectly good
# reputable source, while a data-provider press release usually states it
# plainly (e.g. "Manufacturing PMI at 53.3%"). `when:35d` keeps the window
# wide enough to span a monthly release cycle even if a source reports late.
# Primary reputable compiler: Institute for Supply Management (ISM).
PMI_QUERY_VARIANTS = {
    ("United States", "Manufacturing"): ['"ISM Manufacturing PMI"'],
    ("United States", "Services"):      ['"ISM Services PMI"'],
}
PMI_CANDIDATES_TO_SCAN = 8  # how many headlines per query variant to check for a parseable number

# Unemployment rate & Non-Farm Payrolls — United States only, same
# live-headline approach as PMI above: there's no free real-time numeric API
# for these either, so we poll Google News RSS for the latest reputable-
# outlet headline reporting each release and parse the figure out of it.
# Re-fetched every cache cycle, so a new print appears automatically as soon
# as a reputable outlet reports it.
# Primary reputable compiler: U.S. Bureau of Labor Statistics (BLS).
EMPLOYMENT_METRICS = {
    ("United States", "Unemployment Rate"): {
        "kind": "rate",
        "window": "35d",
        "variants": ['"unemployment rate" BLS jobs report', "US unemployment rate"],
    },
    ("United States", "Non-Farm Payrolls"): {
        "kind": "payrolls",
        "window": "35d",
        "variants": ['"nonfarm payrolls" BLS', "US jobs report payrolls added"],
    },
}
EMPLOYMENT_CANDIDATES_TO_SCAN = 12  # how many headlines per query variant to check for a parseable number
# Headlines containing any of these are skipped for rate parsing even if they
# have a percent figure — they report a related-but-different, much more
# volatile sub-metric (youth unemployment runs far higher than the overall
# rate) that would otherwise get misattributed as the headline figure.
EMPLOYMENT_RATE_EXCLUDE_TERMS = ["youth", "graduate", "young people"]

TOP_PERFORMERS_COUNT = 10  # how many top gainers to show per market
BIG_MOVER_THRESHOLD_PCT = 10.0  # abs(change %) at/above which a ticker counts as a "big mover"

# Currency each market's share prices are quoted in (for display purposes).
MARKET_CURRENCY = {
    "United States": "USD",
    "China": "CNY",
    "India": "INR",
    "Singapore": "SGD",
}

NEWS_FEEDS = {
    "Singapore":     "https://news.google.com/rss/search?q=Singapore+STI+stock+market+when:1d&hl=en-US&gl=US&ceid=US:en",
    "United States": "https://news.google.com/rss/search?q=stock+market+US+when:1d&hl=en-US&gl=US&ceid=US:en",
    "China":         "https://news.google.com/rss/search?q=China+stock+market+CSI300+when:1d&hl=en-US&gl=US&ceid=US:en",
    "India":         "https://news.google.com/rss/search?q=India+stock+market+Sensex+Nifty+when:1d&hl=en-US&gl=US&ceid=US:en",
}
HEADLINES_PER_MARKET = 5  # target number of headlines from reputable outlets
MIN_HEADLINES_PER_MARKET = 5  # absolute floor - backfilled from other outlets if needed
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
    # Official newswires that data publishers (ISM, BLS, etc.) use to
    # distribute their own primary-source press releases — these are the
    # release itself, not secondhand commentary, so they belong here even
    # though they're wire services rather than editorial outlets.
    "PR Newswire", "Business Wire", "GlobeNewswire",
]


# Google News RSS is fronted by Google and can return an empty feed (no
# exception, just zero entries) instead of an HTTP error when it doesn't
# like the request — most commonly because (a) the request has no/odd
# User-Agent, which feedparser's default urllib fetch doesn't set to
# anything browser-like, or (b) too many requests arrive in a short burst
# from the same IP, which is exactly what the PMI and Employment sections
# do (up to ~30 sequential RSS calls each cache cycle, vs. 4 for the News
# section) — and Streamlit Community Cloud apps share a small pool of
# outbound IPs across many free-tier apps, making that burst limit easier
# to hit than on a home connection. `_fetch_feed_with_retry` below adds a
# browser-like User-Agent, a short jittered pause before each request, and
# one retry on an empty/erroring response to make this failure mode much
# less likely without changing what actually gets displayed.
NEWS_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
_MIN_SECONDS_BETWEEN_NEWS_REQUESTS = 0.35  # keeps request rate polite
_last_news_request_ts = [0.0]  # mutable single-item container, shared across calls


def _fetch_feed_with_retry(url, retries=2, backoff=1.2):
    """feedparser.parse(url) with a browser-like User-Agent, light request
    pacing, and a retry on empty/erroring results. Returns the parsed feed
    (possibly still empty if every attempt failed/found nothing — that's a
    real "no headlines" outcome, not swallowed here)."""
    last_feed = None
    for attempt in range(retries + 1):
        elapsed = time.monotonic() - _last_news_request_ts[0]
        if elapsed < _MIN_SECONDS_BETWEEN_NEWS_REQUESTS:
            time.sleep(_MIN_SECONDS_BETWEEN_NEWS_REQUESTS - elapsed)
        _last_news_request_ts[0] = time.monotonic()
        feed = feedparser.parse(url, request_headers=NEWS_REQUEST_HEADERS)
        last_feed = feed
        got_entries = bool(getattr(feed, "entries", None))
        # bozo=1 means feedparser hit a parse/HTTP-level problem (e.g. a
        # non-200 or non-XML response, which is what a block/rate-limit
        # typically looks like here).
        looked_blocked = bool(getattr(feed, "bozo", 0)) and not got_entries
        if got_entries or not looked_blocked:
            return feed
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    return last_feed


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


@st.cache_data(ttl=CACHE_TTL)
def fetch_commodity_data():
    """Live Brent crude / gold spot / silver spot prices from Yahoo Finance,
    same live-refresh approach as fetch_currency_data above. Falls back to
    recent daily bars via .history() if fast_info doesn't have a usable
    last/previous-close pair for a given ticker (this happens occasionally
    for futures contracts around rollover), so a tile doesn't go blank just
    because one particular field was momentarily unavailable."""
    rows = []
    for label, meta in COMMODITIES.items():
        try:
            ticker_obj = yf.Ticker(meta["ticker"])
            last, prev = None, None
            try:
                info = ticker_obj.fast_info
                last, prev = info["lastPrice"], info["previousClose"]
            except Exception:
                last, prev = None, None
            if not last or not prev:
                hist = ticker_obj.history(period="5d")
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
                elif len(closes) == 1:
                    last, prev = float(closes.iloc[-1]), None
            if not last:
                raise ValueError("no usable price data returned")
            pct = (last - prev) / prev * 100 if prev else None
            display = f"${last:,.2f}{meta['unit']}"
            rows.append({"label": label, "value": display, "change_pct": pct})
        except Exception as e:
            rows.append({"label": label, "value": "N/A", "change_pct": None, "error": str(e)})
    return rows


@st.cache_data(ttl=CACHE_TTL)
def _fetch_universe_data():
    """For each market, fetch day-change % for every ticker in its curated
    universe of major-index constituents. This is the single shared data
    pull that both fetch_top_performers() and fetch_big_movers() derive
    from, so refreshing doesn't hit Yahoo Finance twice for the same names."""
    results = {}
    for market, universe in TOP_STOCKS_UNIVERSE.items():
        rows = []
        for ticker, name in universe.items():
            try:
                info = yf.Ticker(ticker).fast_info
                last, prev = info["lastPrice"], info["previousClose"]
                if not prev:
                    continue
                pct = (last - prev) / prev * 100
                rows.append({"ticker": ticker, "name": name, "price": last, "change_pct": pct})
            except Exception:
                continue
        results[market] = rows
    return results


def fetch_top_performers():
    """For each market, return the top gainers and top losers from the
    shared universe data, each sorted most-extreme-first."""
    results = {}
    for market, rows in _fetch_universe_data().items():
        gainers = sorted(rows, key=lambda r: r["change_pct"], reverse=True)[:TOP_PERFORMERS_COUNT]
        losers = sorted(rows, key=lambda r: r["change_pct"])[:TOP_PERFORMERS_COUNT]
        results[market] = {"gainers": gainers, "losers": losers}
    return results


def fetch_big_movers(threshold=BIG_MOVER_THRESHOLD_PCT):
    """Flatten every market's universe into a single list of tickers whose
    day change is at/beyond +/- threshold percent, sorted by magnitude of
    the swing (largest first). Each row is tagged with its market so they
    can all be shown together."""
    movers = []
    for market, rows in _fetch_universe_data().items():
        for row in rows:
            if abs(row["change_pct"]) >= threshold:
                movers.append({**row, "market": market})
    movers.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    return movers


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
    # Google News RSS often puts a short blurb in <summary>/<description> that
    # restates the headline with a bit more detail — sometimes including the
    # actual figure even when the headline itself is narrative-only (e.g.
    # "China factory activity expands again" with no number, but the summary
    # says "...PMI rose to 53.3..."). Captured here so parsing can fall back
    # to it instead of the number silently going undisplayed.
    summary = entry.get("summary", "") or ""
    summary = re.sub(r"<[^>]+>", " ", summary)  # strip any embedded HTML tags
    return {
        "title": clean_title,
        "link": link,
        "source": source,
        "published": entry.get("published", ""),
        "summary": summary,
    }


def _parse_pmi_value(title, keyword=None):
    """Best-effort extraction of (value, previous_value) from a PMI headline.
    Returns (value, prev) with either possibly None if not confidently parsed.
    Handles the common financial-news phrasings, e.g.:
      "...PMI rose to 51.3 in June 2026 from 51.0 in May"   -> (51.3, 51.0)
      "...PMI eased to 54.2 in June from 55.0 in May"       -> (54.2, 55.0)
      "Manufacturing PMI at 53.3%; June 2026 ISM Report"    -> (53.3, None)

    `keyword` (e.g. "services" or "manufacturing") disambiguates headlines
    that report BOTH figures at once, e.g. "India factory PMI at 58.4 as
    services PMI eases to 60.5" — without this, whichever figure appears
    first in the title would get picked up regardless of type. When a
    pattern has more than one match in the title, we pick whichever match
    sits closest to the keyword's position rather than always taking the
    first — this avoids the earlier bug of truncating the title down to a
    small window around the keyword, which could cut off the number
    entirely when it's not immediately adjacent to the keyword.
    """
    keyword_pos = None
    if keyword:
        km = re.search(re.escape(keyword), title, re.IGNORECASE)
        if km:
            keyword_pos = km.start()

    def _best(matches):
        if not matches:
            return None
        if keyword_pos is None or len(matches) == 1:
            return matches[0]
        return min(matches, key=lambda mm: abs(mm.start() - keyword_pos))

    # Pattern 1: two numbers linked by "... from ..." (gives current + prior)
    matches = list(re.finditer(
        r"(\d{2,3}(?:\.\d+)?)\s*%?[^.\n]{0,45}?\bfrom\b\s*(\d{2,3}(?:\.\d+)?)",
        title, re.IGNORECASE,
    ))
    m = _best(matches)
    if m:
        return float(m.group(1)), float(m.group(2))
    # Pattern 2: a single "NN.N%" figure
    matches = list(re.finditer(r"(\d{2,3}(?:\.\d+)?)\s*%", title))
    m = _best(matches)
    if m:
        return float(m.group(1)), None
    # Pattern 3: "PMI ... <number>" without a percent sign
    matches = list(re.finditer(r"PMI\D{0,25}(\d{2,3}(?:\.\d+)?)", title, re.IGNORECASE))
    m = _best(matches)
    if m:
        return float(m.group(1)), None
    return None, None


def _pmi_news_query_url(query, window="45d"):
    return (f"https://news.google.com/rss/search?q={quote_plus(query)}"
            f"+when:{window}&hl=en-US&gl=US&ceid=US:en")


def _fetch_pmi_candidates(query):
    """Fetch one query's headlines, split into reputable vs. other, each
    already cleaned up via _build_item."""
    feed = _fetch_feed_with_retry(_pmi_news_query_url(query))
    reputable, fallback = [], []
    for e in feed.entries:
        source = _source_name(e)
        item = _build_item(e, source)
        (reputable if _is_reputable(source) else fallback).append(item)
    return reputable, fallback


# A PMI reading this far outside the normal range is essentially always a
# misparse (grabbed a year, a percentage change, an unrelated stat, etc.)
# rather than a real reading — modern PMI prints basically never go below
# ~25 or above ~75 even in extreme conditions (e.g. China's manufacturing
# PMI bottomed near 35 in Feb 2020). Used as a last-resort sanity check, not
# a substitute for correct parsing.
PMI_VALID_RANGE = (20.0, 80.0)

# Terms that confirm a headline is actually ABOUT the given PMI type. A
# query like "China non-manufacturing PMI" can still return a headline
# that's really about manufacturing (Google News' matching isn't strict
# phrase-only), and when that headline only states one number, keyword-
# proximity disambiguation can't help — there's nothing to disambiguate
# between. Requiring one of these terms to actually appear in the title
# before trusting its number prevents that cross-type mixup (e.g. the same
# manufacturing figure getting shown under both Manufacturing and Services).
_PMI_KIND_TERMS = {
    "manufacturing": ["manufacturing", "factory"],
    "services": ["services", "service sector", "non-manufacturing", "whole economy", "private sector"],
}


def _title_matches_pmi_kind(title, kind):
    terms = _PMI_KIND_TERMS.get(kind.lower(), [kind.lower()])
    return any(re.search(re.escape(t), title, re.IGNORECASE) for t in terms)


@st.cache_data(ttl=CACHE_TTL)
def fetch_pmi_data():
    """For each (country, PMI type), try each configured query variant in
    turn and scan several of the resulting headlines for one whose wording
    we can actually parse a PMI value out of (see _parse_pmi_value) — many
    perfectly reputable headlines are narrative-only and never state the
    figure, so just taking entry #1 isn't reliable. If nothing parseable
    turns up anywhere, we fall back to the single best headline we found so
    the person can still click through and read the number at the source.
    Re-run every cache cycle, so a fresh release shows up automatically as
    soon as a reputable outlet reports it.

    Accuracy safeguards: a number is only ever extracted from a REPUTABLE
    outlet's headline that actually mentions the requested PMI type (see
    _title_matches_pmi_kind — prevents e.g. a manufacturing-only headline's
    figure from being shown under Services just because it also matched
    that query); and any parsed value outside PMI_VALID_RANGE is treated as
    a failed parse rather than displayed, since a number that far off is
    far more likely a misparse than a real reading."""
    results = {}
    for (country, kind), variants in PMI_QUERY_VARIANTS.items():
        results.setdefault(country, {})
        best_fallback_item = None
        parsed_item = None
        any_entries_seen = False
        try:
            for query in variants:
                reputable, fallback = _fetch_pmi_candidates(query)
                if reputable or fallback:
                    any_entries_seen = True
                # Headline display (incl. fallback for the "no parse" case)
                # can use any source; but a NUMBER is only ever trusted from
                # a reputable one that's actually about this PMI type.
                display_candidates = (reputable or fallback)[:PMI_CANDIDATES_TO_SCAN]
                if display_candidates and best_fallback_item is None:
                    best_fallback_item = display_candidates[0]
                for item in reputable[:PMI_CANDIDATES_TO_SCAN]:
                    matches_kind = _title_matches_pmi_kind(item["title"], kind) or \
                        _title_matches_pmi_kind(item.get("summary", ""), kind)
                    if not matches_kind:
                        continue
                    value, prev = _parse_pmi_value(item["title"], keyword=kind)
                    if value is None or not (PMI_VALID_RANGE[0] <= value <= PMI_VALID_RANGE[1]):
                        # Headline alone didn't yield a trustworthy number —
                        # try the RSS summary blurb, which often states the
                        # figure explicitly even when the headline itself is
                        # narrative-only (e.g. "China factory activity picks
                        # up" vs. summary "...PMI rose to 53.3 in June...").
                        value, prev = _parse_pmi_value(item.get("summary", ""), keyword=kind)
                    if value is not None and PMI_VALID_RANGE[0] <= value <= PMI_VALID_RANGE[1]:
                        parsed_item = {**item, "value": value, "prev": prev}
                        break
                if parsed_item:
                    break

            if parsed_item:
                results[country][kind] = parsed_item
            elif best_fallback_item:
                results[country][kind] = {**best_fallback_item, "value": None, "prev": None}
            elif any_entries_seen:
                # We got headlines back but none matched this PMI type
                # closely enough to trust — a real (if unhelpful) result.
                results[country][kind] = None
            else:
                # Every single query variant came back with zero RSS
                # entries — with several differently-worded queries all
                # striking out, that's almost always Google News RSS
                # blocking/rate-limiting the request rather than there
                # genuinely being no coverage anywhere. Flagged distinctly
                # so it reads as "try refreshing" rather than "nothing to
                # report".
                results[country][kind] = {
                    "title": "", "link": "", "source": "", "published": "",
                    "value": None, "prev": None, "fetch_blocked": True,
                }
        except Exception as e:
            results[country][kind] = {"title": f"Error: {e}", "link": "", "source": "",
                                       "published": "", "value": None, "prev": None}
    return results


def _parse_rate_value(title):
    """Best-effort extraction of (value, previous_value) percent figures from
    an unemployment-rate headline, e.g.:
      "US unemployment rate rises to 4.2% in June from 4.0% in May" -> (4.2, 4.0)
      "China's jobless rate holds at 5.0%"                          -> (5.0, None)
      "India unemployment rate eases to 7.1 in June"                -> (7.1, None)
    """
    m = re.search(
        r"(\d{1,2}(?:\.\d+)?)\s*%?[^.\n]{0,45}?\bfrom\b\s*(\d{1,2}(?:\.\d+)?)",
        title, re.IGNORECASE,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"(\d{1,2}(?:\.\d+)?)\s*%", title)
    if m:
        return float(m.group(1)), None
    # Pattern 3: "unemployment/jobless rate ... <number>" without a percent
    # sign, e.g. "India's unemployment rate at 7.1 in June" (Indian outlets
    # often quote the CMIE/PLFS figure this way).
    m = re.search(r"(?:unemployment|jobless)\D{0,25}rate\D{0,15}(\d{1,2}(?:\.\d+)?)\b", title, re.IGNORECASE)
    if m:
        return float(m.group(1)), None
    return None, None


def _parse_payroll_value(title):
    """Best-effort extraction of the monthly change in US Non-Farm Payrolls
    (in jobs added/lost) from a headline, e.g.:
      "US adds 147,000 jobs in June, payrolls beat forecasts" -> 147000.0
      "Nonfarm payrolls rose by 150K in May"                  -> 150000.0
      "US economy sheds 20,000 jobs"                          -> -20000.0
    """
    lost = bool(re.search(r"\b(sheds|lost|fell|drop(?:s|ped)?|declin\w*)\b", title, re.IGNORECASE))
    m = re.search(r"([\d]{1,3}(?:,\d{3})+)\s*(?:jobs|payrolls)", title, re.IGNORECASE)
    if not m:
        m = re.search(
            r"(?:added|adds|gained|gains|rose(?:\s+by)?|rises(?:\s+by)?|increased(?:\s+by)?|"
            r"up(?:\s+by)?|fell(?:\s+by)?|drops?(?:\s+by)?|lost|sheds)\s+"
            r"([\d]{1,3}(?:,\d{3})+|\d+K)\b",
            title, re.IGNORECASE,
        )
    if not m:
        m = re.search(r"payrolls?\D{0,20}?([\d]{1,3}(?:,\d{3})+|\d+K)\b", title, re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    value = float(raw[:-1]) * 1000 if raw.upper().endswith("K") else float(raw)
    return -value if lost else value


def _employment_news_query_url(query, window):
    return (f"https://news.google.com/rss/search?q={quote_plus(query)}"
            f"+when:{window}&hl=en-US&gl=US&ceid=US:en")


def _fetch_employment_candidates(query, window):
    """Fetch one query's headlines, split into reputable vs. other, each
    already cleaned up via _build_item."""
    feed = _fetch_feed_with_retry(_employment_news_query_url(query, window))
    reputable, fallback = [], []
    for e in feed.entries:
        source = _source_name(e)
        item = _build_item(e, source)
        (reputable if _is_reputable(source) else fallback).append(item)
    return reputable, fallback


# A parsed unemployment rate or payrolls change this far outside plausible
# territory is essentially always a misparse (grabbed a year, an unrelated
# percentage, a different country's figure, etc.) rather than a real
# reading. Used as a last-resort sanity check, not a substitute for correct
# parsing. Rate bound is generous (covers even COVID-era spikes to ~15-25%
# in some economies); payrolls bound covers the largest one-month swings on
# record (US lost ~20M jobs in Apr 2020, gained ~4.8M in Jun 2020).
RATE_VALID_RANGE = (0.0, 30.0)
PAYROLL_VALID_RANGE = (-25_000_000, 6_000_000)

# --- Official-source path for US metrics (FRED / Bureau of Labor Statistics) ---
# Headline-parsing is inherently best-effort — narrative news wording varies
# too much to guarantee an accurate extraction every time. For the US,
# there's a genuinely free, official, no-scraping alternative: the Federal
# Reserve's FRED API serves the real BLS data directly as a numeric time
# series, so we use that instead whenever a (free) FRED API key is
# configured. UNRATE and PAYEMS are both long-standing, stable FRED series
# IDs (unemployment rate and total nonfarm payroll employment level,
# respectively) that have been unchanged for decades.
#
# To enable this, get a free key at https://fred.stlouisfed.org/docs/api/api_key.html
# and add it to your Streamlit secrets as:
#   FRED_API_KEY = "your-key-here"
# Without a key configured, the US tiles simply fall back to the same
# headline-parsing approach used for China/India/Singapore (no error, no
# broken behavior — just less authoritative).
FRED_SERIES_IDS = {
    ("United States", "Unemployment Rate"): "UNRATE",
    ("United States", "Non-Farm Payrolls"): "PAYEMS",
}


def _get_fred_api_key():
    try:
        return st.secrets.get("FRED_API_KEY")
    except Exception:
        return None


def _fetch_fred_observations(series_id, api_key, limit=2):
    import json
    import urllib.parse
    import urllib.request
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode({
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "sort_order": "desc", "limit": limit,
    })
    with urllib.request.urlopen(url, timeout=8) as resp:
        data = json.loads(resp.read().decode())
    return [o for o in data.get("observations", []) if o.get("value") not in (None, ".")]


def _fetch_fred_item(country, metric, cfg):
    """Try fetching this metric directly from FRED instead of parsing a news
    headline. Returns None (caller falls back to headline-scraping) if no
    series is mapped for this (country, metric), no API key is configured,
    or the request fails for any reason — this must never raise."""
    series_id = FRED_SERIES_IDS.get((country, metric))
    api_key = _get_fred_api_key()
    if not series_id or not api_key:
        return None
    try:
        obs = _fetch_fred_observations(series_id, api_key, limit=2)
        if not obs:
            return None
        latest = float(obs[0]["value"])
        prev = float(obs[1]["value"]) if len(obs) > 1 else None
        link = f"https://fred.stlouisfed.org/series/{series_id}"
        source = "FRED (U.S. Bureau of Labor Statistics)"
        if cfg["kind"] == "rate":
            return {"value": latest, "prev": prev, "kind": "rate", "title": "",
                    "link": link, "source": source, "published": obs[0]["date"]}
        # payrolls: FRED gives the employment LEVEL in thousands; report the
        # month-over-month CHANGE in jobs, which is the conventional way
        # Non-Farm Payrolls is quoted.
        if prev is None:
            return None
        change = (latest - prev) * 1000
        return {"value": change, "prev": None, "kind": "payrolls", "title": "",
                "link": link, "source": source, "published": obs[0]["date"]}
    except Exception:
        return None


@st.cache_data(ttl=CACHE_TTL)
def fetch_employment_data():
    """For each (country, metric): for US metrics, try FRED's official data
    first (see _fetch_fred_item). Otherwise — and as a fallback if FRED
    isn't configured — try each configured news-query variant in turn and
    scan several headlines for one whose wording we can parse a figure out
    of, same approach as fetch_pmi_data. Falls back to the best headline
    found (with a source link) if nothing parses cleanly. Re-run every
    cache cycle, so a fresh release shows up automatically as soon as it's
    available.

    Accuracy safeguards on the headline-parsing path: a number is only ever
    extracted from a REPUTABLE outlet's headline; headlines about a
    different, more volatile sub-metric (youth/graduate unemployment) are
    excluded so they can't get misread as the general rate; and any parsed
    value outside the sanity ranges above is treated as a failed parse
    rather than displayed."""
    results = {}
    for (country, metric), cfg in EMPLOYMENT_METRICS.items():
        results.setdefault(country, {})

        fred_item = _fetch_fred_item(country, metric, cfg)
        if fred_item:
            results[country][metric] = fred_item
            continue

        best_fallback_item = None
        parsed_item = None
        any_entries_seen = False
        try:
            for query in cfg["variants"]:
                reputable, fallback = _fetch_employment_candidates(query, cfg["window"])
                if reputable or fallback:
                    any_entries_seen = True
                display_candidates = (reputable or fallback)[:EMPLOYMENT_CANDIDATES_TO_SCAN]
                parse_candidates = reputable[:EMPLOYMENT_CANDIDATES_TO_SCAN]
                if cfg["kind"] == "rate":
                    # Drop headlines about a different, more volatile
                    # sub-metric (youth/graduate unemployment) that would
                    # otherwise get misread as the general rate.
                    display_candidates = [
                        c for c in display_candidates
                        if not any(term in c["title"].lower() for term in EMPLOYMENT_RATE_EXCLUDE_TERMS)
                    ]
                    parse_candidates = [
                        c for c in parse_candidates
                        if not any(term in c["title"].lower() for term in EMPLOYMENT_RATE_EXCLUDE_TERMS)
                    ]
                if display_candidates and best_fallback_item is None:
                    best_fallback_item = display_candidates[0]
                for item in parse_candidates:
                    if cfg["kind"] == "rate":
                        value, prev = _parse_rate_value(item["title"])
                        valid = value is not None and RATE_VALID_RANGE[0] <= value <= RATE_VALID_RANGE[1]
                        if not valid:
                            # Headline text alone often omits the number
                            # (narrative-only wording); the RSS summary
                            # blurb frequently states it explicitly, e.g.
                            # "...unemployment rate held at 5.5% in June...".
                            summary_text = item.get("summary", "")
                            if summary_text and not any(
                                term in summary_text.lower() for term in EMPLOYMENT_RATE_EXCLUDE_TERMS
                            ):
                                value, prev = _parse_rate_value(summary_text)
                                valid = value is not None and RATE_VALID_RANGE[0] <= value <= RATE_VALID_RANGE[1]
                    else:
                        value, prev = _parse_payroll_value(item["title"]), None
                        valid = value is not None and PAYROLL_VALID_RANGE[0] <= value <= PAYROLL_VALID_RANGE[1]
                        if not valid:
                            summary_text = item.get("summary", "")
                            if summary_text:
                                value, prev = _parse_payroll_value(summary_text), None
                                valid = value is not None and PAYROLL_VALID_RANGE[0] <= value <= PAYROLL_VALID_RANGE[1]
                    if valid:
                        parsed_item = {**item, "value": value, "prev": prev}
                        break
                if parsed_item:
                    break

            if parsed_item:
                results[country][metric] = {**parsed_item, "kind": cfg["kind"]}
            elif best_fallback_item:
                results[country][metric] = {**best_fallback_item, "value": None, "prev": None, "kind": cfg["kind"]}
            elif any_entries_seen:
                results[country][metric] = None
            else:
                # Every query variant came back with zero RSS entries —
                # with multiple differently-worded queries all striking
                # out, that's almost always Google News RSS blocking/
                # rate-limiting the request rather than genuinely no
                # coverage anywhere.
                results[country][metric] = {
                    "title": "", "link": "", "source": "", "published": "",
                    "value": None, "prev": None, "kind": cfg["kind"], "fetch_blocked": True,
                }
        except Exception as e:
            results[country][metric] = {"title": f"Error: {e}", "link": "", "source": "",
                                         "published": "", "value": None, "prev": None, "kind": cfg["kind"]}
    return results


@st.cache_data(ttl=CACHE_TTL)
def fetch_news():
    news = {}
    for market, url in NEWS_FEEDS.items():
        try:
            feed = _fetch_feed_with_retry(url)
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

            items = [item for _, item in chosen]
            news[market] = items or None
        except Exception as e:
            news[market] = [{"title": f"Error: {e}", "link": "", "source": "", "published": ""}]
    return news


def _render_ticker(index_rows, currency_rows, commodity_rows=None):
    """Render a sleek, continuously-scrolling right-to-left ticker banner
    summarizing every index, currency, and commodity on the page."""
    rows = list(index_rows) + list(currency_rows) + list(commodity_rows or [])
    items_html = []
    for row in rows:
        pct = row.get("change_pct")
        if pct is None:
            change_html = '<span class="chg flat">—</span>'
        else:
            arrow = "▲" if pct >= 0 else "▼"
            css_class = "up" if pct >= 0 else "down"
            change_html = f'<span class="chg {css_class}">{arrow} {pct:+.2f}%</span>'
        items_html.append(
            f'<span class="tick-item">'
            f'<span class="tick-label">{row["label"]}</span>'
            f'<span class="tick-value">{row["value"]}</span>'
            f'{change_html}'
            f'</span><span class="tick-sep">•</span>'
        )
    # Duplicate the sequence so the CSS animation can loop seamlessly at -50%.
    strip = "".join(items_html)
    html = f"""
    <style>
    .tick-wrap {{
        width: 100%;
        overflow: hidden;
        background: linear-gradient(90deg, #0d1117 0%, #12161f 50%, #0d1117 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 10px 0;
        margin-bottom: 1.4rem;
        box-shadow: inset 0 0 20px rgba(0,0,0,0.25);
    }}
    .tick-track {{
        display: inline-flex;
        white-space: nowrap;
        animation: tick-scroll 45s linear infinite;
    }}
    .tick-wrap:hover .tick-track {{
        animation-play-state: paused;
    }}
    @keyframes tick-scroll {{
        0%   {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
    }}
    .tick-item {{
        display: inline-flex;
        align-items: center;
        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        font-size: 0.82rem;
        padding: 0 0.9rem;
    }}
    .tick-label {{
        color: #8b96a5;
        font-weight: 600;
        letter-spacing: 0.03em;
        margin-right: 0.5rem;
        text-transform: uppercase;
        font-size: 0.72rem;
    }}
    .tick-value {{
        color: #f0f3f7;
        font-weight: 700;
        margin-right: 0.5rem;
    }}
    .chg {{ font-weight: 600; }}
    .chg.up {{ color: #3ddc84; }}
    .chg.down {{ color: #ff5c5c; }}
    .chg.flat {{ color: #6b7684; }}
    .tick-sep {{
        color: #333c48;
        padding: 0 0.6rem;
    }}
    </style>
    <div class="tick-wrap">
        <div class="tick-track">{strip}{strip}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


NEWS_MARKET_FLAGS = {
    "United States": "🇺🇸",
    "China": "🇨🇳",
    "India": "🇮🇳",
    "Singapore": "🇸🇬",
}


def _render_headline_banner(news):
    """Render a compact secondary banner, directly under the main ticker,
    showing the single top live headline for each tracked market (US, China,
    India, Singapore) — same reputable-outlet-prioritized data as the News
    section below, just surfaced at a glance without opening a tab."""
    import html as _html

    cards = []
    for market in ("United States", "China", "India", "Singapore"):
        items = news.get(market) or []
        flag = NEWS_MARKET_FLAGS.get(market, "")
        if not items:
            cards.append(
                f'<div class="headline-card"><div class="headline-market">{flag} {market}</div>'
                f'<div class="headline-text">No headline available right now.</div></div>'
            )
            continue
        top = items[0]
        title = _html.escape(top.get("title") or "Untitled")
        source = _html.escape(top.get("source") or "")
        published = _html.escape(top.get("published") or "")
        link = top.get("link") or ""
        headline_html = f'<a href="{_html.escape(link)}" target="_blank">{title}</a>' if link else title
        meta = " · ".join(x for x in (source, published) if x)
        cards.append(
            f'<div class="headline-card">'
            f'<div class="headline-market">{flag} {market}</div>'
            f'<div class="headline-text">{headline_html}</div>'
            f'<div class="headline-source">{meta}</div>'
            f'</div>'
        )
    html_out = f"""
    <style>
    .headline-banner {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 0.7rem;
        margin-bottom: 1.4rem;
    }}
    .headline-card {{
        background: linear-gradient(160deg, #12161f 0%, #0d1117 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 0.75rem 0.95rem;
        min-height: 100px;
    }}
    .headline-market {{
        color: #8b96a5;
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 0.4rem;
    }}
    .headline-text a {{
        color: #f0f3f7;
        text-decoration: none;
    }}
    .headline-text a:hover {{ text-decoration: underline; }}
    .headline-text {{
        font-size: 0.86rem;
        font-weight: 600;
        line-height: 1.35;
        color: #f0f3f7;
    }}
    .headline-source {{
        color: #6b7684;
        font-size: 0.72rem;
        margin-top: 0.5rem;
    }}
    @media (max-width: 900px) {{
        .headline-banner {{ grid-template-columns: repeat(2, 1fr); }}
    }}
    </style>
    <div class="headline-banner">{''.join(cards)}</div>
    """
    st.markdown(html_out, unsafe_allow_html=True)


def _render_metric_tile(label, item, unit_suffix=""):
    """Render a single US economic-indicator tile (PMI, unemployment rate, or
    payrolls). Shows a live metric with period-over-period delta when a
    number was parsed; otherwise falls back to the actual headline text (not
    just a bare label) with a source link, so a failed parse never just
    looks like missing data."""
    if not item:
        st.markdown(f"**{label}**")
        st.caption("_no data available right now._")
        return
    if item.get("fetch_blocked"):
        st.markdown(f"**{label}**")
        st.caption("_couldn't reach the news source just now (likely rate-limited) — try 🔄 Refresh in a minute._")
        return
    if item["value"] is not None:
        if item.get("kind") == "payrolls":
            st.metric(label, f"{item['value']:+,.0f} jobs")
        else:
            delta = f"{item['value'] - item['prev']:+.1f}" if item.get("prev") is not None else None
            st.metric(label, f"{item['value']:.1f}{unit_suffix}", delta)
    else:
        st.markdown(f"**{label}**")
        if item.get("title"):
            st.caption(item["title"])
    if item["link"]:
        st.caption(f"[{item['source'] or 'source'}]({item['link']}) · {item['published']}")
    elif not item["value"] and not item.get("title"):
        st.caption("_no parseable figure found — try 🔄 Refresh._")


def _render_us_economic_indicators(pmi_data, employment_data):
    """Render Manufacturing PMI, Services PMI, Unemployment Rate, and
    Non-Farm Payrolls together in one section — all four are United States
    figures now, so they share a single row instead of being split across
    two sections."""
    cols = st.columns(4)
    with cols[0]:
        _render_metric_tile("Manufacturing PMI", pmi_data.get("United States", {}).get("Manufacturing"))
    with cols[1]:
        _render_metric_tile("Services PMI", pmi_data.get("United States", {}).get("Services"))
    with cols[2]:
        _render_metric_tile(
            "Unemployment Rate",
            employment_data.get("United States", {}).get("Unemployment Rate"),
            unit_suffix="%",
        )
    with cols[3]:
        _render_metric_tile(
            "Non-Farm Payrolls",
            employment_data.get("United States", {}).get("Non-Farm Payrolls"),
        )



# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Market Tracker", page_icon="📈", layout="wide")
st.title("📈 Market Tracker")
st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%A, %d %b %Y %H:%M')} "
           f"· Auto-refreshes every {CACHE_TTL // 60} min")

if st.button("🔄 Refresh now"):
    st.cache_data.clear()

_render_ticker(fetch_index_data(), fetch_currency_data(), fetch_commodity_data())

# Fetched once here and reused below for the News section too — fetch_news()
# is @st.cache_data'd, so calling it again later costs nothing extra.
news = fetch_news()
_render_headline_banner(news)

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

st.subheader("🛢️ Commodities")
st.caption(
    "Live prices from Yahoo Finance, the same live feed used for indices and "
    "currencies above. Brent Crude is the ICE near-month futures contract — "
    "the standard live benchmark quote; Gold Spot and Silver Spot are "
    "Yahoo Finance's live spot-vs-USD tickers."
)
commodity_cols = st.columns(3)
for i, row in enumerate(fetch_commodity_data()):
    with commodity_cols[i % 3]:
        if row.get("change_pct") is None:
            st.metric(row["label"], row["value"])
        else:
            st.metric(row["label"], row["value"], f"{row['change_pct']:+.2f}%")

st.markdown("##### 🏭 US Economic Indicators — PMI, Unemployment & Payrolls")
st.caption(
    "Manufacturing/Services PMI (a reading above 50 signals expansion, below 50 signals "
    "contraction), Unemployment Rate, and Non-Farm Payrolls, all for the United States. "
    "There's no free real-time numeric API for PMI (ISM licenses the raw data commercially), "
    "so it's parsed live from the latest *reputable-outlet* headline reporting each release — "
    "a number is never extracted from an unvetted source, and never displayed if it falls "
    "outside a plausible range, so a misparse shows as 'no data' rather than a wrong figure. "
    "Unemployment Rate and Non-Farm Payrolls pull directly from FRED — the Federal Reserve's "
    "official data API serving real Bureau of Labor Statistics numbers — when a free FRED API "
    "key is configured (see the code comment near FRED_SERIES_IDS); otherwise they use the "
    "same live-headline approach as PMI. All four are only released monthly, so a tile only "
    "changes when a new report actually comes out. Sources: Institute for Supply Management "
    "(ISM) and U.S. Bureau of Labor Statistics (BLS)."
)
_render_us_economic_indicators(fetch_pmi_data(), fetch_employment_data())

st.subheader("📰 Live Market News — SG, US, China, India")
st.caption(f"Prioritizes reputable outlets (Reuters, Bloomberg, CNBC, FT, WSJ, AP, BBC, and similar); "
           f"backfilled with other outlets so each tab always shows at least {MIN_HEADLINES_PER_MARKET} headlines.")
# `news` was already fetched above (for the headline banner); fetch_news()
# is cached, so reusing that same call here costs nothing extra.
tabs = st.tabs(list(news.keys()))
for tab, (market, items) in zip(tabs, news.items()):
    with tab:
        if not items:
            st.markdown("_No headlines found right now._")
            continue
        for item in items:
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

_UP_COLOR = "#16a34a"    # green-600
_DOWN_COLOR = "#dc2626"  # red-600


def _mover_card_html(rank_label, name, ticker, price, currency, pct, bar_pct, extra_badge=""):
    """Build one styled HTML row: colored side-bar, name/ticker, price,
    a pill showing the %, and a small magnitude bar so the size of the move
    is visible at a glance, not just its sign."""
    is_up = pct >= 0
    color = _UP_COLOR if is_up else _DOWN_COLOR
    bg = "rgba(22,163,74,0.08)" if is_up else "rgba(220,38,38,0.08)"
    arrow = "▲" if is_up else "▼"
    bar_pct = max(4, min(100, bar_pct))
    price_str = f"{price:,.2f} {currency}".strip()
    return f"""
    <div style="display:flex;align-items:center;gap:14px;padding:10px 14px;margin-bottom:6px;
                border-radius:10px;background:{bg};border-left:4px solid {color};">
        <div style="flex:0 0 30px;font-weight:700;color:#94a3b8;font-size:0.85em;">{rank_label}</div>
        <div style="flex:1;min-width:0;">
            <div style="font-weight:600;font-size:1em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                {name}{extra_badge}
            </div>
            <div style="font-size:0.78em;color:#94a3b8;font-family:monospace;">{ticker}</div>
        </div>
        <div style="flex:0 0 120px;text-align:right;font-variant-numeric:tabular-nums;font-size:0.92em;">
            {price_str}
        </div>
        <div style="flex:0 0 130px;text-align:right;">
            <div style="display:inline-block;padding:3px 10px;border-radius:999px;background:{color};
                        color:white;font-weight:700;font-size:0.88em;white-space:nowrap;">
                {arrow} {pct:+.2f}%
            </div>
            <div style="height:4px;border-radius:2px;background:rgba(148,163,184,0.3);margin-top:5px;overflow:hidden;">
                <div style="height:100%;width:{bar_pct:.0f}%;background:{color};margin-left:auto;"></div>
            </div>
        </div>
    </div>
    """


def _render_performer_rows(rows, market):
    if not rows:
        st.markdown("_No data available right now._")
        return
    currency = MARKET_CURRENCY.get(market, "")
    max_abs = max((abs(r["change_pct"]) for r in rows), default=1.0) or 1.0
    html = "".join(
        _mover_card_html(
            f"#{rank}", row["name"], row["ticker"], row["price"], currency,
            row["change_pct"], abs(row["change_pct"]) / max_abs * 100,
        )
        for rank, row in enumerate(rows, start=1)
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_big_movers(movers, threshold):
    """Flat, magnitude-sorted list of every ticker (across all tracked
    markets) whose day change is at/beyond +/- threshold percent."""
    if not movers:
        st.success(f"✅ No ticker in the tracked universe has swung ±{threshold:.0f}% or more today.")
        return
    max_abs = max(abs(r["change_pct"]) for r in movers)
    html = "".join(
        _mover_card_html(
            "🚨", row["name"], row["ticker"], row["price"],
            MARKET_CURRENCY.get(row["market"], ""), row["change_pct"],
            abs(row["change_pct"]) / max_abs * 100,
            extra_badge=(
                f'<span style="margin-left:8px;padding:1px 8px;border-radius:999px;'
                f'background:rgba(148,163,184,0.25);color:#94a3b8;font-size:0.72em;'
                f'font-weight:600;vertical-align:middle;">{row["market"]}</span>'
            ),
        )
        for row in movers
    )
    st.markdown(html, unsafe_allow_html=True)


st.subheader("📈 Top 10 Gainers Today")
st.caption(
    f"Top {TOP_PERFORMERS_COUNT} gainers today from a curated set of large, liquid constituents "
    "of each market's major index (S&P 500 · CSI 300 · Nifty 50 · STI). Prices shown in each "
    "market's local currency."
)
top_performers = fetch_top_performers()
gainer_tabs = st.tabs(list(top_performers.keys()))
for tab, (market, data) in zip(gainer_tabs, top_performers.items()):
    with tab:
        _render_performer_rows(data["gainers"], market)

st.subheader("📉 Top 10 Losers Today")
st.caption(
    f"Top {TOP_PERFORMERS_COUNT} losers today from the same curated set of constituents. "
    "Prices shown in each market's local currency."
)
loser_tabs = st.tabs(list(top_performers.keys()))
for tab, (market, data) in zip(loser_tabs, top_performers.items()):
    with tab:
        _render_performer_rows(data["losers"], market)

st.subheader("🚨 Big Movers — ±10% Swings")
st.caption(
    f"Every ticker across the tracked universe (S&P 500 · CSI 300 · Nifty 50 · STI constituents) "
    f"whose price has swung {BIG_MOVER_THRESHOLD_PCT:.0f}% or more today, up or down, sorted by the "
    "size of the move. Pulls from the same curated constituent list and live data as the gainers/"
    "losers sections above, so it costs no extra API calls."
)
big_movers = fetch_big_movers()
_render_big_movers(big_movers, BIG_MOVER_THRESHOLD_PCT)

st.caption(
    "Data sources: Yahoo Finance (indices/currencies/commodities/VIX/yields/top performers), Google News RSS "
    "(headlines, and US PMI/unemployment/payrolls readings, prioritizing reputable outlets — ISM, BLS). "
    "This is informational only, not financial advice."
)
