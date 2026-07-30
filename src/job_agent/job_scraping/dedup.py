"""Deduplicate job postings by (title, company). Job boards (pracuj.pl in
particular, via "superoferty"/boosted listings) sometimes list the exact
same posting twice under different offer IDs — same title, same company,
different URL. Keeps the first occurrence encountered.
"""

from job_agent.common.models import JobPosting


def _key(job: JobPosting) -> tuple[str, str]:
    return (job.title.strip().lower(), job.company.strip().lower())


def dedupe_postings(postings: list[JobPosting]) -> list[JobPosting]:
    seen: set[tuple[str, str]] = set()
    deduped: list[JobPosting] = []
    for job in postings:
        key = _key(job)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    return deduped
