"""Etap 4: infer which job experience levels to target, based on the CV.

Not hardcoded to "junior" — recomputed from the parsed CV every run, so a
different CV (more commercial experience) automatically targets different
levels (mid/senior) without touching this code.

For a candidate with no commercial experience, "junior" offers still often
expect real production skills (Kubernetes, specific tooling, X years) —
"intern"/staż offers explicitly don't. So the priority order is a list of
TIERS, most realistic first: try intern-only, and only widen to include
junior if intern alone doesn't have enough offers to be useful. This is
enforced in code (filter_by_level_tiers), not left to an LLM to remember.

justjoin.it experienceLevel values: intern, junior, mid, senior, manager, c_level.
"""

from job_agent.common.models import CVProfileStructured, JobPosting

STUDENT_END_DATE_MARKERS = ("obecnie", "present", "currently", "now")
NON_COMMERCIAL_ROLE_MARKERS = (
    "student",
    "praktyk",
    "staż",
    "stażyst",
    "intern",
    "self-directed",
    "projekt studencki",
    "własnych projekt",
    "wolontar",
)

# How many offers a preferred tier must yield before it's accepted on its own.
# Set generously: internships alone are usually a handful, and stopping there
# hides perfectly reasonable junior roles. Widening costs only scoring time.
MIN_RESULTS_PER_TIER = 15


def _is_current_student(cv: CVProfileStructured) -> bool:
    return any(
        edu.end_date and any(marker in edu.end_date.lower() for marker in STUDENT_END_DATE_MARKERS)
        for edu in cv.education
    )


def _count_substantial_experience(cv: CVProfileStructured) -> int:
    """Experience entries that read like a real commercial job, not a
    self-directed project, internship, or student placement."""
    count = 0
    for exp in cv.experience:
        text = f"{exp.position or ''} {exp.description or ''}".lower()
        if any(marker in text for marker in NON_COMMERCIAL_ROLE_MARKERS):
            continue
        count += 1
    return count


def infer_target_level_tiers(cv: CVProfileStructured) -> tuple[list[list[str]], str]:
    """Returns (tiers, reason). `tiers` is a list of level-sets in priority
    order, most realistic-for-this-candidate first. Callers should use the
    first tier with enough offers (see filter_by_level_tiers) rather than
    always taking tiers[0] blindly."""
    is_student = _is_current_student(cv)
    substantial = _count_substantial_experience(cv)
    total = len(cv.experience)

    if is_student and substantial == 0:
        tiers = [["intern"], ["intern", "junior"]]
        reason = (
            f"aktualne studia + {total} wpis(y) doświadczenia, żaden nie wygląda na "
            f"pełną rolę komercyjną -> priorytet: staż/praktyka (junior często i tak "
            f"wymaga realnego doświadczenia, którego kandydat nie ma)"
        )
    elif is_student or substantial <= 1:
        tiers = [["intern", "junior"], ["intern", "junior", "mid"]]
        reason = f"studia w toku i/lub {substantial} wpis komercyjny -> priorytet: intern/junior"
    elif substantial <= 3:
        tiers = [["junior", "mid"]]
        reason = f"{substantial} wpisy komercyjnego doświadczenia -> profil junior/mid"
    else:
        tiers = [["mid", "senior"]]
        reason = f"{substantial} wpisy komercyjnego doświadczenia -> profil mid/senior"

    return tiers, reason


def infer_target_levels(cv: CVProfileStructured) -> tuple[list[str], str]:
    """Simple single-tier variant (most preferred tier only) for callers
    that don't do result-count-based fallback."""
    tiers, reason = infer_target_level_tiers(cv)
    return tiers[0], reason


def filter_by_level_tiers(
    jobs: list[JobPosting], tiers: list[list[str]], min_results: int = MIN_RESULTS_PER_TIER
) -> tuple[list[JobPosting], list[str], bool]:
    """Try each tier in priority order against already-location-filtered
    jobs; use the first tier that clears min_results, otherwise fall back
    to the broadest tier. Returns (filtered_jobs, levels_used, was_widened).
    """
    last_levels = tiers[-1]
    last_filtered: list[JobPosting] = []
    for i, levels in enumerate(tiers):
        filtered = [j for j in jobs if j.experience_level in levels]
        last_levels, last_filtered = levels, filtered
        if len(filtered) >= min_results:
            return filtered, levels, i > 0
    return last_filtered, last_levels, len(tiers) > 1
