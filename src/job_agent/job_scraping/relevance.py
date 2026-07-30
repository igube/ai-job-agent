"""Keep only genuinely AI-related postings.

Needed for keyword-searched sources (OLX, rocketjobs.pl). Their search is
fuzzy and the boards are general-purpose, so a query for "AI" also returns
warehouse work abroad and fashion-marketing internships whose body copy
happens to name-drop "AI" or "automatyzacja".

Two tiers, because a bare "AI" mention in a long job description is nearly
meaningless marketing filler, while "machine learning" or "LLM" is not:

  STRONG term anywhere            -> relevant
  any term in the TITLE           -> relevant
  only a WEAK term in the body    -> rejected

Deliberately a cheap keyword gate, not a model call: it runs over hundreds
of raw postings, while the expensive per-offer judgment (matching.ai_scorer)
runs only on the handful that survive level/location filtering.
"""

import re

from job_agent.common.models import JobPosting

# Unambiguous -- these effectively never appear in non-AI job copy.
_STRONG_TERMS = [
    r"\bLLM\b",
    r"\bGPT\b",
    r"\bNLP\b",
    r"machine learning",
    r"uczeni[ea] maszynow",
    r"deep learning",
    r"sieci neuronow",
    r"computer vision",
    r"data scien",
    r"\bMLOps\b",
    r"OpenAI",
    r"prompt engineer",
    # Polish declines both words: "sztuczna inteligencja", "sztucznej
    # inteligencji", "sztuczną inteligencję" -- match the stems, not fixed forms.
    r"sztuczn\w*\s+inteligencj",
    r"generatywn\w*\s+(AI|sztuczn\w*)",
]
# Common enough in ordinary marketing/office copy that a body-text hit alone
# proves nothing -- only counted when they show up in the job title.
_WEAK_TERMS = [
    r"\bAI\b",
    r"\bA\.I\.",
    r"\bML\b",
    r"automatyzacj",
    r"automation",
    r"chatbot",
    r"Copilot",
    r"\bprompt\w*",
]

_STRONG_RE = re.compile("|".join(_STRONG_TERMS), re.IGNORECASE)
_ANY_RE = re.compile("|".join(_STRONG_TERMS + _WEAK_TERMS), re.IGNORECASE)


def is_ai_relevant(job: JobPosting) -> bool:
    if _ANY_RE.search(job.title):
        return True
    body = " ".join(filter(None, [job.description or "", " ".join(job.skills)]))
    return bool(_STRONG_RE.search(body))


def filter_ai_relevant(jobs: list[JobPosting]) -> list[JobPosting]:
    kept = [j for j in jobs if is_ai_relevant(j)]
    dropped = len(jobs) - len(kept)
    if dropped:
        source = jobs[0].source if jobs else "?"
        print(f"[{source}] odrzucono {dropped} ofert bez związku z AI", flush=True)
    return kept
