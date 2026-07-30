"""justjoin.it — AI/ML category job offers. Public API, no auth, no key, no cost.

Shares its API shape with rocketjobs.pl (same operator) -- see _justjoin_api.
justjoin.it is IT-only, so it has a dedicated `ai` category to filter on.
"""

from job_agent.common.models import JobPosting
from job_agent.job_scraping.sources._justjoin_api import fetch_offers

SOURCE = "justjoin.it"
API_URL = "https://justjoin.it/api/candidate-api/offers"
DETAIL_URL = "https://justjoin.it/job-offer/{slug}"


def fetch_ai_offers(max_results: int | None = None) -> list[JobPosting]:
    """Fetch all AI/ML-category job offers from justjoin.it, paginated."""
    return fetch_offers(
        source=SOURCE,
        api_url=API_URL,
        detail_url=DETAIL_URL,
        query={"categories": "ai"},
        max_results=max_results,
    )
