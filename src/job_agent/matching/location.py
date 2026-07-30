"""Etap 4: location relevance, inferred from the CV's contact location.

Not hardcoded to "Warszawa" — read from cv.contact.location every run, so
a different CV (different city) automatically filters differently.

Remote offers are always kept regardless of city — location only matters
for hybrid/office roles.
"""

from job_agent.common.models import CVProfileStructured, JobPosting


def extract_candidate_city(cv: CVProfileStructured) -> str | None:
    location = cv.contact.location
    if not location:
        return None
    return location.split(",")[0].strip() or None


def is_location_compatible(candidate_city: str | None, job: JobPosting) -> bool:
    if job.workplace_type == "remote":
        return True
    if not candidate_city or not job.city:
        return True  # nothing to compare against — don't filter blindly
    candidate_city = candidate_city.lower()
    job_city = job.city.lower()
    return candidate_city in job_city or job_city in candidate_city
