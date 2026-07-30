"""Etap 4: score & rank AI/ML job offers against a structured CV profile.

Skill-overlap scoring only, offline, no model calls — cheap enough to run
on every offer. Score = fraction of the job's required skills the
candidate's CV (skills + project tech stacks) already covers.
"""

from job_agent.common.models import CVProfileStructured, JobPosting


def _cv_skill_pool(cv: CVProfileStructured) -> set[str]:
    pool = {s.lower() for s in cv.skills}
    for project in cv.projects:
        pool.update(t.lower() for t in project.tech_stack)
    return pool


def score_job(cv_skills: set[str], job: JobPosting) -> tuple[float, list[str]]:
    job_skills = {s.lower() for s in job.skills}
    if not job_skills:
        return 0.0, []
    matched = sorted(job_skills & cv_skills)
    score = len(matched) / len(job_skills)
    return round(score, 3), matched


def rank_jobs(cv: CVProfileStructured, jobs: list[JobPosting]) -> list[dict]:
    cv_skills = _cv_skill_pool(cv)
    ranked = []
    for job in jobs:
        score, matched = score_job(cv_skills, job)
        ranked.append({"job": job.model_dump(), "score": score, "matched_skills": matched})
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked
