"""Tools the agent can call. Thin wrappers around Etap 3/4 logic — no new
business logic here, just glue + compact JSON summaries (keep tokens down).
"""

import json

from job_agent.common.models import CVProfileStructured, JobPosting
from job_agent.config import OUTPUTS_DIR
from job_agent.job_scraping.dedup import dedupe_postings
from job_agent.job_scraping.sources.justjoinit import fetch_ai_offers as fetch_justjoinit
from job_agent.job_scraping.sources.olx import fetch_ai_offers as fetch_olx
from job_agent.job_scraping.sources.pracujpl import fetch_ai_offers as fetch_pracuj
from job_agent.job_scraping.sources.rocketjobs import fetch_ai_offers as fetch_rocketjobs
from job_agent.job_scraping.sources.theprotocol import fetch_ai_offers as fetch_theprotocol
from job_agent.matching.ai_scorer import rank_jobs_deep
from job_agent.matching.level_inference import filter_by_level_tiers, infer_target_level_tiers
from job_agent.matching.location import extract_candidate_city, is_location_compatible

JOBS_PATH = OUTPUTS_DIR / "jobs_ai.json"
CV_PATH = OUTPUTS_DIR / "cv_profile_structured.json"
RANKED_PATH = OUTPUTS_DIR / "jobs_ranked.json"


def fetch_jobs(max_results: int | None = None) -> dict:
    """Fetch fresh AI/ML job offers from all four boards and save them.

    justjoin.it / rocketjobs.pl / olx.pl are plain public APIs. pracuj.pl is
    fetched already pre-filtered server-side (its own "Poziom stanowiska" +
    location filters) to intern/junior offers in the candidate's CV city —
    not scraped broad and filtered locally. It is Cloudflare-protected and
    rate-limited to once/24h in code (job_scraping.rate_limit) — if already
    fetched today, cached results are reused, no extra network call.
    """
    candidate_city = None
    if CV_PATH.exists():
        cv = CVProfileStructured.model_validate_json(CV_PATH.read_text(encoding="utf-8"))
        candidate_city = extract_candidate_city(cv)

    per_source = {
        "justjoin.it": fetch_justjoinit(max_results=max_results),
        "rocketjobs.pl": fetch_rocketjobs(max_results=max_results),
        "olx.pl": fetch_olx(city=candidate_city, max_results=max_results),
        "theprotocol.it": fetch_theprotocol(max_results=max_results),
        "pracuj.pl": fetch_pracuj(city=candidate_city, max_results=max_results),
    }
    raw_total = sum(len(v) for v in per_source.values())
    postings = dedupe_postings([p for group in per_source.values() for p in group])

    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOBS_PATH.write_text(
        json.dumps([p.model_dump() for p in postings], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "fetched_total": len(postings),
        "per_source": {k: len(v) for k, v in per_source.items()},
        "duplicates_removed": raw_total - len(postings),
        "saved_to": str(JOBS_PATH),
    }


def score_jobs(top: int = 25) -> dict:
    """Filter fetched offers by CV-inferred experience level + city, then
    DEEPLY analyze each remaining offer against the full CV (every
    experience/project description, not just skill-name matching) using
    the local model. Each returned offer already has a score, verdict
    (polecam/neutralnie/pomiń), reasoning, strengths and concerns — this
    is a real per-offer judgment, not a raw percentage for you to
    re-interpret. No arguments needed for the common case.

    Level selection prioritizes internships/staż automatically: "junior"
    postings frequently still expect real production skills the candidate
    doesn't have yet, so intern-only is tried first and only widened to
    include junior if intern alone doesn't have enough offers.

    This step is slow (one model call per offer) — keep `top` modest."""
    if not CV_PATH.exists():
        return {"error": f"missing {CV_PATH}. Run scripts/enrich_cv.py first."}
    if not JOBS_PATH.exists():
        return {"error": f"missing {JOBS_PATH}. Call fetch_jobs first."}

    cv = CVProfileStructured.model_validate_json(CV_PATH.read_text(encoding="utf-8"))
    jobs = [JobPosting.model_validate(j) for j in json.loads(JOBS_PATH.read_text(encoding="utf-8"))]

    candidate_city = extract_candidate_city(cv)
    location_filtered = [j for j in jobs if is_location_compatible(candidate_city, j)]

    tiers, level_reason = infer_target_level_tiers(cv)
    filtered, levels, widened = filter_by_level_tiers(location_filtered, tiers)
    if widened:
        level_reason += " (poszerzone o kolejny poziom -- za mało ofert w priorytetowym progu)"

    ranked = rank_jobs_deep(cv, filtered[:top])

    RANKED_PATH.write_text(json.dumps(ranked, ensure_ascii=False, indent=2), encoding="utf-8")

    offers = [
        {
            "title": r["job"]["title"],
            "company": r["job"]["company"],
            "level": r["job"]["experience_level"],
            "city": r["job"]["city"],
            "workplace_type": r["job"]["workplace_type"],
            "score": r["score"],
            "verdict": r["verdict"],
            "reasoning": r["reasoning"],
            "strengths": r["strengths"],
            "concerns": r["concerns"],
            "url": r["job"]["url"],
        }
        for r in ranked
    ]
    return {
        "inferred_level_reason": level_reason,
        "target_levels": levels,
        "candidate_city": candidate_city,
        "location_note": "remote offers are kept regardless of city; hybrid/office offers outside candidate_city are excluded",
        "candidates_before_filter": len(jobs),
        "candidates_after_filter": len(filtered),
        "count": len(offers),
        "offers": offers,
    }


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_jobs",
            "description": "Fetch the latest AI/ML job offers from justjoin.it, rocketjobs.pl, olx.pl, theprotocol.it and pracuj.pl (pracuj.pl pre-filtered server-side to intern/junior + candidate's CV city) and save them locally, deduplicated. Call this once at the start of a run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Optional cap on number of offers to fetch. Omit to fetch all.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_jobs",
            "description": (
                "Filter offers by CV-inferred city + experience level (internships "
                "prioritized over junior automatically), then deeply analyze each "
                "remaining offer against the FULL CV using the local model — reads "
                "the offer's description and every CV experience/project entry, not "
                "just skill-name matching. Each returned offer already has a score, "
                "verdict (polecam/neutralnie/pomiń), reasoning, strengths and "
                "concerns — a real judgment, not a raw number to re-derive. "
                "Takes no arguments; it analyses every offer that passes the "
                "filters."
            ),
            # No parameters on purpose: given a `top` knob the local model
            # picks an arbitrarily small value (observed: 5) and silently
            # throws away most of the shortlist.
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

TOOL_IMPLS = {
    "fetch_jobs": fetch_jobs,
    "score_jobs": score_jobs,
}
