"""rocketjobs.pl — AI-related job offers. Public API, no auth, no key, no cost.

Same operator and same API contract as justjoin.it (see _justjoin_api), but
rocketjobs.pl is a general (non-IT-only) board, so there is no `ai` category
to filter on -- it has to be a keyword search instead, and results therefore
need the relevance filter that category-filtered justjoin.it does not.
"""

from job_agent.common.models import JobPosting
from job_agent.job_scraping.relevance import filter_ai_relevant
from job_agent.job_scraping.sources._justjoin_api import fetch_offers

SOURCE = "rocketjobs.pl"
API_URL = "https://rocketjobs.pl/api/candidate-api/offers"
# /job-offer/<slug> 307-redirects here; use the canonical path directly.
DETAIL_URL = "https://rocketjobs.pl/oferta-pracy/{slug}"


def fetch_ai_offers(max_results: int | None = None) -> list[JobPosting]:
    """Fetch AI-related job offers from rocketjobs.pl, paginated."""
    postings = fetch_offers(
        source=SOURCE,
        api_url=API_URL,
        detail_url=DETAIL_URL,
        query={"keywords": "AI", "keywordType": "any"},
        max_results=max_results,
    )
    return filter_ai_relevant(postings)
