"""Shared client for the justjoin.it / rocketjobs.pl job API.

Both sites belong to the same operator and expose an identical
`/api/candidate-api/offers` endpoint (same response schema, same
offset pagination via meta.next.cursor) -- only the host, the offer
detail URL and the query filters differ. Endpoint discovered via
browser devtools, not publicly documented.
"""

import requests

from job_agent.common.models import JobPosting, SalaryRange


def _to_job_posting(raw: dict, source: str, detail_url: str) -> JobPosting:
    salary = [
        SalaryRange(
            contract_type=et["type"],
            unit=et["unit"],
            amount_from=et.get("from"),
            amount_to=et.get("to"),
            currency=et["currency"],
        )
        for et in raw.get("employmentTypes", [])
        if et.get("currencySource") == "original"
    ]
    return JobPosting(
        source=source,
        external_id=raw["guid"],
        title=raw["title"],
        company=raw.get("companyName", ""),
        city=raw.get("city"),
        workplace_type=raw.get("workplaceType"),
        experience_level=raw.get("experienceLevel"),
        category=(raw.get("category") or {}).get("key"),
        skills=[s["name"] for s in raw.get("requiredSkills", [])],
        salary=salary,
        url=detail_url.format(slug=raw["slug"]),
        apply_url=raw.get("applyUrl"),
        published_at=raw.get("publishedAt"),
    )


def fetch_offers(
    *,
    source: str,
    api_url: str,
    detail_url: str,
    query: dict,
    max_results: int | None = None,
) -> list[JobPosting]:
    """Page through the offers endpoint until exhausted (or max_results)."""
    postings: list[JobPosting] = []
    offset = 0

    while True:
        response = requests.get(
            api_url,
            params={**query, "sortBy": "publishedAt", "orderBy": "descending", "from": offset},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()

        batch = payload.get("data", [])
        if not batch:
            break

        postings.extend(_to_job_posting(o, source, detail_url) for o in batch)
        # Paging through hundreds of offers is otherwise a silent ~40s stretch --
        # the dashboard streams this line so the UI can show live progress.
        total = payload.get("meta", {}).get("totalItems")
        print(f"[{source}] pobrano {len(postings)}/{total or '?'} ofert", flush=True)
        if max_results is not None and len(postings) >= max_results:
            return postings[:max_results]

        next_cursor = payload.get("meta", {}).get("next", {}).get("cursor")
        if next_cursor is None or next_cursor <= offset:
            break
        offset = next_cursor

    return postings
