"""pracuj.pl — AI-related job offers.

Cloudflare-protected (blocks plain `requests` with a JS challenge), so this
uses a real headless browser (Playwright) instead of raw HTTP. Data comes
from the page's own Next.js `__NEXT_DATA__` hydration payload (React Query
dehydrated state) — same trick as justjoin.it's devtools discovery, just
one more hop because the HTML has to actually render.

Uses pracuj.pl's OWN level + location filters server-side (reverse-engineered
from the site's UI, not guessed) instead of scraping broad results and
filtering locally:
- `wp` = location (e.g. "Warszawa")
- `et` = position level codes, comma-separated. Confirmed via the site's
  "Poziom stanowiska" filter -> "Pokaż oferty" button, then reading the
  resulting URL after a fresh navigation (client-side transitions don't
  refresh __NEXT_DATA__, so the trick is to reproduce the URL and do a real
  page.goto(), not to read the DOM mid-interaction).
  1 = praktykant/stażysta (intern), 3 = asystent, 17 = młodszy specjalista
  / junior. Together these are exactly "intern + junior".

Rate-limited to once per 24h (job_scraping.rate_limit) — a Cloudflare-
protected site should be treated as a polite, infrequent scraper, not
hit on every pipeline/agent run. Within the window, cached results from
the last successful fetch are returned instead of a network call.
"""

import json
import re
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from job_agent.common.models import JobPosting
from job_agent.config import OUTPUTS_DIR
from job_agent.job_scraping.rate_limit import record_fetch, should_fetch

SOURCE = "pracuj.pl"
KEYWORD = "sztuczna inteligencja"
LEVEL_CODES = "1,3,17"  # praktykant/stażysta + asystent + młodszy specjalista (junior)
CACHE_PATH = OUTPUTS_DIR / "jobs_pracuj.json"
MIN_INTERVAL_HOURS = 24.0
PAGES_TO_FETCH = 2  # server-side level+location filtering already narrows a lot

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# (substring found in Polish positionLevels text) -> normalized level.
# Checked against ALL levels listed on an offer; the most junior match wins
# (an offer spanning "mid + senior" is still relevant to a mid-level search).
_LEVEL_MARKERS = [
    ("praktykant", "intern"),
    ("stażyst", "intern"),
    ("asystent", "junior"),
    ("młodszy", "junior"),
    ("junior", "junior"),
    ("specjalista", "mid"),
    ("regular", "mid"),
    ("starszy specjalista", "senior"),
    ("senior", "senior"),
    ("ekspert", "senior"),
    ("kierownik", "manager"),
    ("dyrektor", "manager"),
    ("menedż", "manager"),
]
_LEVEL_ORDER = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "manager": 4}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\n{3,}")


def _map_level(position_levels: list[str]) -> str | None:
    text = " | ".join(position_levels).lower()
    found = {level for marker, level in _LEVEL_MARKERS if marker in text}
    if not found:
        return None
    return min(found, key=lambda lvl: _LEVEL_ORDER[lvl])


def _map_workplace(work_modes: list[str]) -> str | None:
    text = " ".join(work_modes).lower()
    if "zdaln" in text:
        return "remote"
    if "hybryd" in text:
        return "hybrid"
    if "stacjonarn" in text:
        return "office"
    return None


def _clean_html(text: str) -> str:
    text = text.replace("<li>", "\n- ").replace("</p>", "\n")
    text = _HTML_TAG_RE.sub("", text)
    text = _WHITESPACE_RE.sub("\n\n", text)
    return text.strip()


def _build_description(group: dict) -> str | None:
    parts = []
    if summary := group.get("aiSummary"):
        parts.append(_clean_html(summary))
    if desc := group.get("jobDescription"):
        parts.append(_clean_html(desc))
    return "\n\n".join(parts) if parts else None


def _to_job_posting(group: dict) -> JobPosting:
    offer = group["offers"][0]
    return JobPosting(
        source=SOURCE,
        external_id=str(offer["partitionId"]),
        title=group["jobTitle"],
        company=group.get("companyName", ""),
        city=offer.get("displayWorkplace"),
        workplace_type=_map_workplace(group.get("workModes", [])),
        experience_level=_map_level(group.get("positionLevels", [])),
        category="ai",
        skills=[],  # pracuj.pl doesn't expose a clean structured skills list
        salary=[],  # salaryDisplayText is free-form text, not structured
        url=offer["offerAbsoluteUri"],
        apply_url=offer["offerAbsoluteUri"],
        published_at=group.get("lastPublicated"),
        description=_build_description(group),
    )


def _build_search_url(city: str | None) -> str:
    kw_segment = f"{quote(KEYWORD)};kw"
    if city:
        loc_segment = f"{quote(city.lower())};wp"
        return f"https://www.pracuj.pl/praca/{kw_segment}/{loc_segment}?et={LEVEL_CODES}"
    return f"https://www.pracuj.pl/praca/{kw_segment}?et={LEVEL_CODES}"


def _extract_groups(html: str) -> list[dict]:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        raise RuntimeError(
            "pracuj.pl: __NEXT_DATA__ not found — page layout changed or request was blocked"
        )
    data = json.loads(match.group(1))
    queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    job_query = next(q for q in queries if q["queryKey"][0] == "jobOffers")
    return job_query["state"]["data"]["groupedOffers"]


def _scrape_pages(base_url: str, num_pages: int) -> list[dict]:
    # A fresh browser launch per page, not one page.goto() reused across
    # navigations -- reusing a single page for repeat navigations to
    # pracuj.pl reliably hangs (networkidle never resolves), most likely
    # Cloudflare treating same-session rapid re-navigation as suspicious.
    sep = "&" if "?" in base_url else "?"
    groups: list[dict] = []
    for page_number in range(1, num_pages + 1):
        url = f"{base_url}{sep}pn={page_number}"
        # Each page means launching a browser and waiting on a Cloudflare-
        # guarded render (~10s) -- announce it so the dashboard can show
        # live progress instead of a silent stretch.
        print(f"[pracuj.pl] strona {page_number}/{num_pages} — pobieram…", flush=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
            except Exception as e:
                print(f"[pracuj.pl] strona {page_number}: {e} -- pomijam resztę stron")
                browser.close()
                break
            browser.close()
        page_groups = _extract_groups(html)
        if not page_groups:
            break
        groups.extend(page_groups)
    return groups


def _load_cache() -> list[JobPosting]:
    if not CACHE_PATH.exists():
        return []
    return [JobPosting.model_validate(j) for j in json.loads(CACHE_PATH.read_text(encoding="utf-8"))]


def fetch_ai_offers(city: str | None = None, max_results: int | None = None, force: bool = False) -> list[JobPosting]:
    """Fetch intern/junior AI-related offers from pracuj.pl, filtered
    server-side by level (praktykant/asystent/junior) and, if given, by
    city (remote offers still come through — pracuj.pl's own location
    filter already accounts for that).

    Rate-limited to once per MIN_INTERVAL_HOURS — repeated calls within the
    window return the last cached fetch instead of hitting the site again.
    Pass force=True to bypass (not recommended for routine/scheduled use).
    """
    if not force:
        allowed, reason = should_fetch(SOURCE, MIN_INTERVAL_HOURS)
        if not allowed:
            print(f"[pracuj.pl] pomijam fetch ({reason}) — używam cache")
            cached = _load_cache()
            return cached[:max_results] if max_results is not None else cached

    url = _build_search_url(city)
    groups = _scrape_pages(url, PAGES_TO_FETCH)
    postings = [_to_job_posting(g) for g in groups]
    if max_results is not None:
        postings = postings[:max_results]

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps([p.model_dump() for p in postings], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_fetch(SOURCE)
    return postings
