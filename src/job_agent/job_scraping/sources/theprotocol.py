"""theprotocol.it — junior/intern AI-ML job offers.

Same Next.js `__NEXT_DATA__` trick as pracuj.pl (both are Grupa Pracuj), but
without the Cloudflare challenge, so plain requests work and there is no need
for Playwright or a 24h rate limit.

Filtering happens server-side through the site's own URL segments:
  /filtry/ai-ml;sp/praktykant-stazysta,asystent,junior;p
    ai-ml;sp  -> specialization
    ...;p     -> position levels (praktykant/stażysta, asystent, junior)
so only relevant offers are fetched rather than filtered locally.

Overlaps partly with pracuj.pl (same operator cross-posts some offers) --
job_scraping.dedup removes the duplicates downstream.
"""

import json
import re

import requests

from job_agent.common.models import JobPosting, SalaryRange

SOURCE = "theprotocol.it"
SEARCH_URL = "https://theprotocol.it/filtry/ai-ml;sp/praktykant-stazysta,asystent,junior;p"
DETAIL_URL = "https://theprotocol.it/praca/{slug}"
PAGE_SIZE = 50

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

# theprotocol already publishes normalised level slugs; only the trainee one
# needs renaming to the pipeline's vocabulary.
_LEVEL_MAP = {
    "trainee": "intern",
    "assistant": "junior",
    "junior": "junior",
    "mid": "mid",
    "senior": "senior",
    "expert": "senior",
    "manager": "manager",
}
_LEVEL_ORDER = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "manager": 4}


def _map_level(position_levels: list[dict]) -> str | None:
    found = {
        _LEVEL_MAP[v]
        for lv in position_levels
        if (v := (lv.get("value") or "").lower()) in _LEVEL_MAP
    }
    if not found:
        return None
    # An offer spanning junior+mid is still relevant to a junior search.
    return min(found, key=lambda lvl: _LEVEL_ORDER[lvl])


def _map_workplace(work_modes: list[str]) -> str | None:
    text = " ".join(work_modes).lower()
    if "remote" in text or "zdaln" in text:
        return "remote"
    if "hybrid" in text or "hybryd" in text:
        return "hybrid"
    if "office" in text or "stacjonarn" in text:
        return "office"
    return None


def _map_salary(raw: dict) -> list[SalaryRange]:
    salary = raw.get("salary")
    if not isinstance(salary, dict) or salary.get("from") is None:
        return []
    return [
        SalaryRange(
            contract_type=str(salary.get("typeName") or "unknown"),
            unit=str(salary.get("timeUnit") or "?"),
            amount_from=salary.get("from"),
            amount_to=salary.get("to"),
            currency=str(salary.get("currency") or "PLN"),
        )
    ]


def _to_job_posting(raw: dict) -> JobPosting:
    workplace = raw.get("workplace") or []
    city = workplace[0].get("city") if workplace else None
    about = raw.get("aboutProject") or []
    return JobPosting(
        source=SOURCE,
        external_id=str(raw["id"]),
        title=raw["title"],
        company=raw.get("employer") or "",
        city=city,
        workplace_type=_map_workplace(raw.get("workModes") or []),
        experience_level=_map_level(raw.get("positionLevels") or []),
        category="ai",
        skills=list(raw.get("technologies") or []),
        salary=_map_salary(raw),
        url=DETAIL_URL.format(slug=raw["offerUrlName"]),
        apply_url=DETAIL_URL.format(slug=raw["offerUrlName"]),
        published_at=raw.get("publicationDateUtc"),
        description="\n\n".join(about) if about else None,
    )


def _extract_response(html: str) -> dict:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError(
            "theprotocol.it: __NEXT_DATA__ not found — page layout changed or request blocked"
        )
    data = json.loads(match.group(1))
    return data["props"]["pageProps"]["offersResponse"]


def fetch_ai_offers(max_results: int | None = None) -> list[JobPosting]:
    """Fetch intern/junior AI-ML offers, filtered server-side by the site's
    own specialization + position-level URL filters."""
    postings: list[JobPosting] = []
    page_number = 1

    while True:
        response = requests.get(
            SEARCH_URL,
            params={"pageNumber": page_number},
            headers={"User-Agent": USER_AGENT},
            timeout=25,
        )
        response.raise_for_status()
        payload = _extract_response(response.text)

        batch = payload.get("offers") or []
        if not batch:
            break

        postings.extend(_to_job_posting(o) for o in batch)
        total = payload.get("offersCount")
        print(f"[{SOURCE}] pobrano {len(postings)}/{total or '?'} ofert", flush=True)

        if max_results is not None and len(postings) >= max_results:
            return postings[:max_results]

        page_count = (payload.get("page") or {}).get("count") or 1
        if page_number >= page_count:
            break
        page_number += 1

    return postings
