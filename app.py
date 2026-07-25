"""
Live Market Dashboard (Streamlit)
=============================================
Deploy this on Streamlit Community Cloud (free) to get a public link you can
open from your phone. See DEPLOY.md for the 3-minute setup.

Data refreshes automatically every 5 minutes (adjustable via CACHE_TTL below).
"""

import datetime
import re
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
# Manufacturing & Services PMI (Purchasing Managers' Index) for a curated set
# of markets. There's no free real-time numeric API for PMI (ISM/S&P
# Global/NBS all license the raw data commercially), so instead of a fixed
# snapshot we treat this the same way the News section already does: poll
# Google News RSS for the latest reputable-outlet headline reporting each
# release, and parse the figure straight out of that headline. Because it's
# re-fetched on every cache cycle, a new PMI print shows up here automatically
# as soon as a reputable outlet reports it — no manual updates needed. If a
# headline's wording can't be parsed into a number, we still surface the
# headline itself (with a link back to the source) rather than guessing.
#
# Each entry below is a *list* of plain search-term variants (no boolean
# operators/parentheses — Google News RSS handles those inconsistently) tried
# in order; we also scan several matching headlines per variant, since a
# narrative-style headline (e.g. "China's factory activity expands for a
# third month") often omits the actual number even when it's a perfectly good
# reputable source, while a data-provider press release usually states it
# plainly (e.g. "Manufacturing PMI at 53.3%"). `when:35d` keeps the window
# wide enough to span a monthly release cycle even if a source reports late.
# Primary reputable compilers behind each series:
#   - United States: Institute for Supply Management (ISM)
#   - China:         National Bureau of Statistics of China (NBS, official)
#   - India:         S&P Global (branded "HSBC India PMI" in most headlines)
#   - Singapore:     SIPMM for manufacturing; S&P Global for services/whole-economy
#                    (Singapore has no separate dedicated services PMI of its own)
PMI_QUERY_VARIANTS = {
    ("United States", "Manufacturing"): ['"ISM Manufacturing PMI"'],
    ("United States", "Services"):      ['"ISM Services PMI"'],
    ("China", "Manufacturing"):         ["China manufacturing PMI", "China factory activity PMI NBS"],
    ("China", "Services"):              ["China non-manufacturing PMI", "China services PMI NBS"],
    ("India", "Manufacturing"):         ["HSBC India Manufacturing PMI", "India Manufacturing PMI S&P Global"],
    ("India", "Services"):              [
        "HSBC India Services PMI", "India Services PMI S&P Global",
        "India services PMI", "India services activity PMI",
    ],
    ("Singapore", "Manufacturing"):     ["Singapore Manufacturing PMI SIPMM"],
    ("Singapore", "Services"):          ["Singapore PMI S&P Global", "Singapore private sector PMI"],
}
PMI_CANDIDATES_TO_SCAN = 8  # how many headlines per query variant to check for a parseable number

# Unemployment rate & (US) Non-Farm Payrolls, same live-headline approach as
# PMI above: there's no free real-time numeric API for these either, so we
# poll Google News RSS for the latest reputable-outlet headline reporting
# each release and parse the figure out of it. Re-fetched every cache cycle,
# so a new print appears automatically as soon as a reputable outlet reports
# it. "Non-Farm Payrolls" is a US-specific report (from the same monthly BLS
# jobs release as the unemployment rate) — China, India, and Singapore don't
# publish an equivalent payrolls figure, so only their unemployment rate is
# tracked. `window` is widened for Singapore since MOM only reports labour
# market data quarterly, not monthly.
# Primary reputable compilers behind each series:
#   - United States: Bureau of Labor Statistics (BLS)
#   - China:         National Bureau of Statistics of China (NBS) — surveyed urban unemployment rate
#   - India:         Ministry of Statistics & Programme Implementation (MoSPI) / CMIE
#   - Singapore:     Ministry of Manpower (MOM)
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
    ("China", "Unemployment Rate"): {
        "kind": "rate",
        "window": "35d",
        "variants": ["China surveyed urban unemployment rate NBS", "China unemployment rate"],
    },
    ("India", "Unemployment Rate"): {
        "kind": "rate",
        "window": "35d",
        "variants": ["India unemployment rate CMIE", "India unemployment rate MoSPI"],
    },
    ("Singapore", "Unemployment Rate"): {
        "kind": "rate",
        "window": "100d",
        "variants": ["Singapore unemployment rate MOM", "Singapore unemployment rate Ministry of Manpower"],
    },
}
EMPLOYMENT_CANDIDATES_TO_SCAN = 6  # how many headlines per query variant to check for a parseable number

TOP_PERFORMERS_COUNT = 10  # how many top gainers to show per market

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
def fetch_top_performers():
    """For each market, fetch day-change % for a curated set of major-index
    constituents and return the top gainers and top losers, each sorted
    most-extreme-first."""
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
        gainers = sorted(rows, key=lambda r: r["change_pct"], reverse=True)[:TOP_PERFORMERS_COUNT]
        losers = sorted(rows, key=lambda r: r["change_pct"])[:TOP_PERFORMERS_COUNT]
        results[market] = {"gainers": gainers, "losers": losers}
    return results


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
        "published": entry.get("published", ""),
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
    services PMI eases to 60.5" — without this, the manufacturing figure
    would be picked up first and wrongly attributed to services (or vice
    versa). When both PMI-type words appear in the title, we first narrow
    the search to the text around `keyword` before falling back to the
    whole title.
    """
    search_text = title
    if keyword:
        other_terms = {"manufacturing", "services", "non-manufacturing"} - {keyword.lower()}
        km = re.search(re.escape(keyword), title, re.IGNORECASE)
        mentions_other = any(re.search(re.escape(t), title, re.IGNORECASE) for t in other_terms)
        if km and mentions_other:
            # Scope to a window around the keyword so the "other" type's
            # number (which may appear earlier/later in the same headline)
            # isn't picked up instead.
            start = max(0, km.start() - 15)
            end = km.end() + 60
            search_text = title[start:end]

    # Pattern 1: two numbers linked by "... from ..." (gives current + prior)
    m = re.search(
        r"(\d{2,3}(?:\.\d+)?)\s*%?[^.\n]{0,45}?\bfrom\b\s*(\d{2,3}(?:\.\d+)?)",
        search_text, re.IGNORECASE,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    # Pattern 2: a single "NN.N%" figure
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*%", search_text)
    if m:
        return float(m.group(1)), None
    # Pattern 3: "PMI ... <number>" without a percent sign
    m = re.search(r"PMI\D{0,15}(\d{2,3}(?:\.\d+)?)", search_text, re.IGNORECASE)
    if m:
        return float(m.group(1)), None
    return None, None


def _pmi_news_query_url(query, window="45d"):
    return (f"https://news.google.com/rss/search?q={quote_plus(query)}"
            f"+when:{window}&hl=en-US&gl=US&ceid=US:en")


def _fetch_pmi_candidates(query):
    """Fetch one query's headlines, split into reputable vs. other, each
    already cleaned up via _build_item."""
    feed = feedparser.parse(_pmi_news_query_url(query))
    reputable, fallback = [], []
    for e in feed.entries:
        source = _source_name(e)
        item = _build_item(e, source)
        (reputable if _is_reputable(source) else fallback).append(item)
    return reputable, fallback


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
    soon as a reputable outlet reports it."""
    results = {}
    for (country, kind), variants in PMI_QUERY_VARIANTS.items():
        results.setdefault(country, {})
        best_fallback_item = None
        parsed_item = None
        try:
            for query in variants:
                reputable, fallback = _fetch_pmi_candidates(query)
                candidates = (reputable or fallback)[:PMI_CANDIDATES_TO_SCAN]
                if candidates and best_fallback_item is None:
                    best_fallback_item = candidates[0]
                for item in candidates:
                    value, prev = _parse_pmi_value(item["title"], keyword=kind)
                    if value is not None:
                        parsed_item = {**item, "value": value, "prev": prev}
                        break
                if parsed_item:
                    break

            if parsed_item:
                results[country][kind] = parsed_item
            elif best_fallback_item:
                results[country][kind] = {**best_fallback_item, "value": None, "prev": None}
            else:
                results[country][kind] = None
        except Exception as e:
            results[country][kind] = {"title": f"Error: {e}", "link": "", "source": "",
                                       "published": "", "value": None, "prev": None}
    return results


def _parse_rate_value(title):
    """Best-effort extraction of (value, previous_value) percent figures from
    an unemployment-rate headline, e.g.:
      "US unemployment rate rises to 4.2% in June from 4.0% in May" -> (4.2, 4.0)
      "China's jobless rate holds at 5.0%"                          -> (5.0, None)
    """
    m = re.search(
        r"(\d{1,2}(?:\.\d+)?)\s*%[^.\n]{0,45}?\bfrom\b\s*(\d{1,2}(?:\.\d+)?)",
        title, re.IGNORECASE,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"(\d{1,2}(?:\.\d+)?)\s*%", title)
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
    feed = feedparser.parse(_employment_news_query_url(query, window))
    reputable, fallback = [], []
    for e in feed.entries:
        source = _source_name(e)
        item = _build_item(e, source)
        (reputable if _is_reputable(source) else fallback).append(item)
    return reputable, fallback


@st.cache_data(ttl=CACHE_TTL)
def fetch_employment_data():
    """For each (country, metric), try each configured query variant in turn
    and scan several headlines for one whose wording we can parse a figure
    out of — same approach as fetch_pmi_data. Falls back to the best headline
    found (with a source link) if nothing parses cleanly. Re-run every cache
    cycle, so a fresh release shows up automatically as soon as a reputable
    outlet reports it."""
    results = {}
    for (country, metric), cfg in EMPLOYMENT_METRICS.items():
        results.setdefault(country, {})
        best_fallback_item = None
        parsed_item = None
        try:
            for query in cfg["variants"]:
                reputable, fallback = _fetch_employment_candidates(query, cfg["window"])
                candidates = (reputable or fallback)[:EMPLOYMENT_CANDIDATES_TO_SCAN]
                if candidates and best_fallback_item is None:
                    best_fallback_item = candidates[0]
                for item in candidates:
                    if cfg["kind"] == "rate":
                        value, prev = _parse_rate_value(item["title"])
                    else:
                        value, prev = _parse_payroll_value(item["title"]), None
                    if value is not None:
                        parsed_item = {**item, "value": value, "prev": prev}
                        break
                if parsed_item:
                    break

            if parsed_item:
                results[country][metric] = {**parsed_item, "kind": cfg["kind"]}
            elif best_fallback_item:
                results[country][metric] = {**best_fallback_item, "value": None, "prev": None, "kind": cfg["kind"]}
            else:
                results[country][metric] = None
        except Exception as e:
            results[country][metric] = {"title": f"Error: {e}", "link": "", "source": "",
                                         "published": "", "value": None, "prev": None, "kind": cfg["kind"]}
    return results


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

            items = [item for _, item in chosen]
            news[market] = items or None
        except Exception as e:
            news[market] = [{"title": f"Error: {e}", "link": "", "source": "", "published": ""}]
    return news


def _render_ticker(index_rows, currency_rows):
    """Render a sleek, continuously-scrolling right-to-left ticker banner
    summarizing every index and currency on the page."""
    rows = list(index_rows) + list(currency_rows)
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


def _render_pmi(pmi_data):
    """Render Manufacturing & Services PMI, grouped by country. Each reading
    is live-fetched (see fetch_pmi_data); if we could parse a number out of
    the latest headline we show it as a metric with month-over-month delta,
    otherwise we fall back to showing the headline itself with a source link
    so the person can read the actual figure at the source."""
    countries = list(PMI_QUERY_VARIANTS.keys())
    country_names = list(dict.fromkeys(c for c, _ in countries))  # stable order, de-duped
    country_cols = st.columns(len(country_names))
    for col, country in zip(country_cols, country_names):
        with col:
            st.markdown(f"**{country}**")
            for kind in ("Manufacturing", "Services"):
                item = pmi_data.get(country, {}).get(kind)
                if not item:
                    st.caption(f"{kind} PMI: _no data available right now._")
                    continue
                if item["value"] is not None:
                    if item["prev"] is not None:
                        st.metric(f"{kind} PMI", f"{item['value']:.1f}",
                                   f"{item['value'] - item['prev']:+.1f}")
                    else:
                        st.metric(f"{kind} PMI", f"{item['value']:.1f}")
                else:
                    st.markdown(f"**{kind} PMI**")
                if item["link"]:
                    st.caption(f"[{item['source'] or 'source'}]({item['link']}) · {item['published']}")
                else:
                    st.caption(item["title"])


def _render_employment(employment_data):
    """Render unemployment rate (all 4 markets) & US Non-Farm Payrolls,
    grouped by country. Each reading is live-fetched (see
    fetch_employment_data); if we could parse a figure out of the latest
    headline we show it as a metric with month-over-month delta where
    available, otherwise we fall back to showing the headline itself with a
    source link so the person can read the actual figure at the source."""
    country_names = list(dict.fromkeys(c for c, _ in EMPLOYMENT_METRICS.keys()))
    country_cols = st.columns(len(country_names))
    for col, country in zip(country_cols, country_names):
        with col:
            st.markdown(f"**{country}**")
            metrics_for_country = [m for c, m in EMPLOYMENT_METRICS.keys() if c == country]
            for metric in metrics_for_country:
                item = employment_data.get(country, {}).get(metric)
                if not item:
                    st.caption(f"{metric}: _no data available right now._")
                    continue
                if item["value"] is not None:
                    if item["kind"] == "rate":
                        delta = f"{item['value'] - item['prev']:+.1f}" if item["prev"] is not None else None
                        st.metric(metric, f"{item['value']:.1f}%", delta)
                    else:  # payrolls, in jobs added/lost
                        st.metric(metric, f"{item['value']:+,.0f} jobs")
                else:
                    st.markdown(f"**{metric}**")
                if item["link"]:
                    st.caption(f"[{item['source'] or 'source'}]({item['link']}) · {item['published']}")
                else:
                    st.caption(item["title"])


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Market Tracker", page_icon="📈", layout="wide")
st.title("📈 Market Tracker")
st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%A, %d %b %Y %H:%M')} "
           f"· Auto-refreshes every {CACHE_TTL // 60} min")

if st.button("🔄 Refresh now"):
    st.cache_data.clear()

_render_ticker(fetch_index_data(), fetch_currency_data())

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

st.markdown("##### 🏭 Manufacturing & Services PMI")
st.caption(
    "A reading above 50 signals expansion, below 50 signals contraction. PMI is only "
    "released once a month per country, so unlike the market prices above, a tile only "
    "changes when a new report actually comes out — but this pulls the latest reputable-"
    "outlet headline for each release live, every refresh, so a new print appears here as "
    "soon as it's reported (no manual updates). Sources: ISM (US), National Bureau of "
    "Statistics of China, S&P Global (India; Singapore services/whole-economy), and SIPMM "
    "(Singapore manufacturing)."
)
_render_pmi(fetch_pmi_data())

st.markdown("##### 👷 Unemployment & Non-Farm Payrolls")
st.caption(
    "Unemployment rate for the US, China, India and Singapore, plus US Non-Farm "
    "Payrolls (the US doesn't have a direct equivalent published for the other "
    "three markets). These are only released monthly (quarterly for Singapore's "
    "MOM labour market report), so a tile only changes when a new report actually "
    "comes out — but this pulls the latest reputable-outlet headline for each "
    "release live, every refresh, so a new print appears here as soon as it's "
    "reported (no manual updates). Sources: U.S. Bureau of Labor Statistics (BLS), "
    "National Bureau of Statistics of China, MoSPI/CMIE (India), and Ministry of "
    "Manpower (Singapore)."
)
_render_employment(fetch_employment_data())

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

def _render_performer_rows(rows, market):
    if not rows:
        st.markdown("_No data available right now._")
        return
    for rank, row in enumerate(rows, start=1):
        pcol, ncol, vcol, ccol = st.columns([0.5, 3, 2, 2])
        with pcol:
            st.markdown(f"**#{rank}**")
        with ncol:
            st.markdown(f"**{row['name']}**")
            st.caption(row["ticker"])
        with vcol:
            currency = MARKET_CURRENCY.get(market, "")
            st.markdown(f"{row['price']:,.2f} {currency}")
        with ccol:
            pct = row["change_pct"]
            arrow = "▲" if pct >= 0 else "▼"
            color = "green" if pct >= 0 else "red"
            st.markdown(f":{color}[{arrow} {pct:+.2f}%]")


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

st.caption(
    "Data sources: Yahoo Finance (indices/currencies/VIX/yields/top performers), Google News RSS "
    "(headlines, PMI, and unemployment/payrolls readings, prioritizing reputable outlets — ISM, NBS "
    "China, S&P Global, SIPMM, BLS, MoSPI/CMIE, MOM Singapore). This is informational only, not "
    "financial advice."
)
