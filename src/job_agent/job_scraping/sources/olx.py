"""OLX.pl — AI-related job offers. Public JSON API, no auth, no key, no cost.

GET /api/v1/offers/?category_id=4 (category 4 = "praca"). OLX is a general
classifieds board: AI postings are scattered across many job subcategories,
so there is no single category to filter on -- it has to be a keyword search
plus the relevance gate (job_scraping.relevance), otherwise a query for "AI"
also returns warehouse work abroad.

Experience maps cleanly onto the pipeline's levels: OLX's own
`exp_no` / `exp_yes` flag plus a "student status" requirement is enough to
tell an internship-grade posting from one expecting prior experience.
"""

import html as html_lib
import re

import requests

from job_agent.common.models import JobPosting, SalaryRange
from job_agent.job_scraping.relevance import filter_ai_relevant

SOURCE = "olx.pl"
API_URL = "https://www.olx.pl/api/v1/offers/"
JOBS_CATEGORY_ID = 4
PAGE_SIZE = 50

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# OLX salary is per-hour or per-month; the pipeline's SalaryRange keeps the
# unit as-is rather than normalising, same as the other sources.
_SALARY_UNIT = {"hourly": "Hour", "monthly": "Month"}


_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_RE = re.compile(r"\n{3,}")


def _clean_description(text: str | None) -> str | None:
    """OLX returns raw HTML. Left as-is it wastes the scorer's context on
    markup and makes the model reason over tags instead of content."""
    if not text:
        return None
    text = re.sub(r"</(p|div|li|ul|ol|h\d)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = html_lib.unescape(text)
    return _BLANK_RE.sub("\n\n", text).strip() or None


def _param(raw: dict, key: str) -> dict | None:
    for p in raw.get("params", []):
        if p.get("key") == key:
            return p.get("value") or {}
    return None


def _map_level(raw: dict) -> str | None:
    """OLX has no seniority ladder -- only "experience required" yes/no, plus
    an optional "student status" requirement. Map the no-experience end onto
    intern/junior and leave the rest as mid so it still sorts sensibly."""
    experience = _param(raw, "experience") or {}
    special = _param(raw, "special_requirements") or {}
    wants_student = "student_status" in (special.get("key") or [])

    if experience.get("key") == "exp_no":
        return "intern" if wants_student else "junior"
    if wants_student:
        return "intern"
    if experience.get("key") == "exp_yes":
        return "mid"
    return None


def _map_workplace(raw: dict) -> str | None:
    availability = _param(raw, "availability") or {}
    keys = availability.get("key") or []
    if "home_office" in keys or "remote" in keys:
        return "remote"
    return "office"


def _map_salary(raw: dict) -> list[SalaryRange]:
    salary = _param(raw, "salary")
    if not salary or salary.get("from") is None:
        return []
    agreement = _param(raw, "agreement") or {}
    contract = ", ".join(agreement.get("key") or []) or "unknown"
    return [
        SalaryRange(
            contract_type=contract,
            unit=_SALARY_UNIT.get(salary.get("type", ""), salary.get("type", "?")),
            amount_from=salary.get("from"),
            amount_to=salary.get("to"),
            currency=salary.get("currency", "PLN"),
        )
    ]


def _to_job_posting(raw: dict) -> JobPosting:
    location = raw.get("location") or {}
    return JobPosting(
        source=SOURCE,
        external_id=str(raw["id"]),
        title=raw["title"],
        company=(raw.get("user") or {}).get("name") or "",
        city=(location.get("city") or {}).get("name"),
        workplace_type=_map_workplace(raw),
        experience_level=_map_level(raw),
        category="ai",
        skills=[],  # OLX has no structured skills list
        salary=_map_salary(raw),
        url=raw["url"],
        apply_url=raw["url"],
        published_at=raw.get("created_time"),
        description=_clean_description(raw.get("description")),
    )


def fetch_ai_offers(city: str | None = None, max_results: int | None = None) -> list[JobPosting]:
    """Fetch AI-related job offers from OLX, paginated, then drop the
    keyword-search noise via the relevance gate."""
    postings: list[JobPosting] = []
    offset = 0

    while True:
        params: dict[str, object] = {
            "category_id": JOBS_CATEGORY_ID,
            "query": "AI",
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        if city:
            params["city"] = city

        response = requests.get(
            API_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20
        )
        response.raise_for_status()
        payload = response.json()

        batch = payload.get("data", [])
        if not batch:
            break

        postings.extend(_to_job_posting(o) for o in batch)
        total = (payload.get("metadata") or {}).get("total_elements")
        print(f"[{SOURCE}] pobrano {len(postings)}/{total or '?'} ofert", flush=True)

        if max_results is not None and len(postings) >= max_results:
            postings = postings[:max_results]
            break
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return filter_ai_relevant(postings)
