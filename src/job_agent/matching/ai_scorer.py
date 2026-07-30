"""Etap 4+ (AI): deep match scoring via the local model.

Unlike scorer.py (mechanical skill-name-string overlap), this reads the
FULL job posting (title, required skills, description when available,
level, salary, work mode) against the FULL CV (skills, every experience
entry's description, every project, education) and asks the model for a
genuine judgment — not just "how many skill names match".

Deliberately runs only on the already level/location-filtered candidate
set (matching.level_inference + matching.location) — those are cheap and
narrow hundreds of offers down to a handful first. Running this on every
raw offer would be far too slow; that's exactly why the cheap filters
exist as a first pass.
"""

import json

import ollama

from job_agent.ai_config import OLLAMA_HOST, OLLAMA_MODEL
from job_agent.common.models import CVProfileStructured, JobPosting

# Scoring dimensions and their weight in the final score. Asking for a single
# 0-100 number made the model emit the same few round values (50/65/75) for
# very different offers; scoring several concrete dimensions and combining them
# here gives both a granular number and a breakdown you can argue with.
DIMENSIONS: list[tuple[str, float, str]] = [
    ("wymagania", 0.30, "pokrycie wymagań oferty przez umiejętności, projekty i doświadczenie kandydata"),
    ("poziom", 0.25, "czy realny poziom trudności oferty jest osiągalny dla kandydata (nie deklarowany, tylko wynikający z opisu)"),
    ("dziedzina", 0.20, "czy to faktycznie praca z AI/automatyzacją zgodna z kierunkiem kandydata, czy tylko doklejone AI"),
    ("rozwoj", 0.15, "ile kandydat się tu nauczy i czy przybliża go to do celu z jego podsumowania CV"),
    ("warunki", 0.10, "lokalizacja, tryb pracy, forma zatrudnienia i widełki względem sytuacji kandydata"),
]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                name: {"type": "integer", "description": f"0-100: {desc}"}
                for name, _, desc in DIMENSIONS
            },
            "required": [name for name, _, _ in DIMENSIONS],
        },
        "verdict": {"type": "string", "description": "dokładnie jedno słowo: polecam, rozważ albo odradzam"},
        "reasoning": {"type": "string", "description": "jedno zdanie po polsku, max 25 słów"},
        "strengths": {"type": "array", "items": {"type": "string"}, "description": "1-3 hasła, każde max 6 słów"},
        "concerns": {"type": "array", "items": {"type": "string"}, "description": "0-3 hasła, każde max 6 słów"},
    },
    "required": ["scores", "verdict", "reasoning", "strengths", "concerns"],
}

SYSTEM_PROMPT = """\
Jesteś rekruterem oceniającym dopasowanie kandydata do oferty pracy AI/ML. \
Dostajesz PEŁNE dane kandydata (CV: umiejętności, każdy wpis doświadczenia \
z opisem, projekty, wykształcenie) i PEŁNE dane oferty (tytuł, wymagane \
umiejętności, opis stanowiska jeśli dostępny, poziom, tryb pracy, widełki).

Oceń realistycznie, nie tylko po nazwach technologii:
- Czy doświadczenie i projekty kandydata (także własne projekty, automatyzacje, \
boty) rzeczywiście dają podstawy do tej roli?
- Czy opis stanowiska zdradza wymagania nieadekwatne do deklarowanego poziomu \
(np. "junior", a opis brzmi jak potrzeba trzech lat doświadczenia)?
- Czy to faktycznie rola AI/ML, czy zwykły software albo marketing z dopisanym "AI"?
- Umiejętności przenoszalne też się liczą (praca z API, automatyzacja, Python), \
nawet jeśli konkretna biblioteka z oferty nie pada w CV wprost.

OCEŃ PIĘĆ WYMIARÓW, każdy w skali 0-100, niezależnie od siebie:
- wymagania: na ile umiejętności, projekty i doświadczenie kandydata pokrywają \
to, czego oferta realnie wymaga. Licz też umiejętności przenoszalne.
- poziom: czy trudność wynikająca Z OPISU (nie z etykiety "junior") jest \
osiągalna dla kandydata. Oferta "junior" wymagająca Kubernetes i trzech lat \
doświadczenia dostaje tu niski wynik.
- dziedzina: czy to praca faktycznie z AI/automatyzacją, zgodna z kierunkiem \
kandydata z jego podsumowania. Ogłoszenie marketingowe z doklejonym "AI" \
dostaje niski wynik.
- rozwoj: ile kandydat się tu nauczy i czy przybliża go to do celu, który sam \
opisał w podsumowaniu CV.
- warunki: lokalizacja, tryb pracy, forma zatrudnienia, widełki — względem \
sytuacji kandydata (student, konkretne miasto).

Używaj pełnej skali i konkretnych liczb (np. 37, 64, 82), a nie zaokrągleń \
w stylu 50, 60, 70. Każdy wymiar oceniaj osobno — mogą się mocno różnić.

FORMAT ODPOWIEDZI — trzymaj się ściśle:
- scores: obiekt z pięcioma liczbami 0-100 (wymagania, poziom, dziedzina, rozwoj, warunki).
- verdict: dokładnie jedno słowo — "polecam", "rozważ" albo "odradzam".
- reasoning: JEDNO zdanie, maksymalnie 25 słów. Bez wstępów typu "Kandydat ma".
- strengths: 1-3 krótkie hasła, każde do 6 słów, konkretne. Wypisz najważniejsze \
czynniki przemawiające ZA tą ofertą, np. "Python i OpenAI API w CV", \
"staż nie wymaga doświadczenia", "praca zdalna". Nie powielaj treści ogłoszenia.
- concerns: 0-3 krótkie hasła, każde do 6 słów, np. "wymaga Kubernetes", \
"brak widełek płacowych".

JĘZYK: pisz poprawną, naturalną polszczyzną. Zwracaj uwagę na odmianę i rodzaj \
gramatyczny. Nie kalkuj z angielskiego. Nie zgaduj informacji, których nie ma w danych.
"""


def _format_cv(cv: CVProfileStructured) -> str:
    lines: list[str] = []
    if cv.summary:
        # The candidate's own words about what they are after -- the single
        # most useful signal for "rozwoj"/"dziedzina", and absent from skills.
        lines.append(f"PROFIL / CEL KANDYDATA:\n{cv.summary}\n")

    lines.append("UMIEJĘTNOŚCI: " + (", ".join(cv.skills) or "(brak wpisanych wprost)"))
    if cv.languages:
        lines.append("JĘZYKI: " + ", ".join(cv.languages))

    if cv.experience:
        lines.append("\nDOŚWIADCZENIE:")
        for exp in cv.experience:
            period = f"{exp.start_date or '?'} - {exp.end_date or '?'}"
            lines.append(f"- {exp.position or '?'} @ {exp.company or '?'} ({period})")
            if exp.description:
                lines.append(f"  {exp.description}")

    if cv.projects:
        lines.append("\nPROJEKTY:")
        for proj in cv.projects:
            tech = ", ".join(proj.tech_stack) if proj.tech_stack else "?"
            lines.append(f"- {proj.name or '?'} [{tech}]")
            if proj.description:
                lines.append(f"  {proj.description}")

    if cv.education:
        lines.append("\nWYKSZTAŁCENIE:")
        for edu in cv.education:
            period = f"{edu.start_date or '?'} - {edu.end_date or '?'}"
            lines.append(f"- {edu.degree or '?'} {edu.field or ''} @ {edu.institution or '?'} ({period})")

    return "\n".join(lines)


def _format_job(job: JobPosting) -> str:
    lines = [
        f"TYTUŁ: {job.title}",
        f"FIRMA: {job.company}",
        f"POZIOM: {job.experience_level or '?'}",
        f"TRYB PRACY: {job.workplace_type or '?'} ({job.city or '?'})",
        f"WYMAGANE UMIEJĘTNOŚCI: {', '.join(job.skills) or '(brak listy -- patrz opis)'}",
    ]
    if job.salary:
        s = job.salary[0]
        lines.append(f"WIDEŁKI: {s.amount_from}-{s.amount_to} {s.currency} ({s.contract_type}, {s.unit})")
    if job.description:
        lines.append(f"\nOPIS STANOWISKA:\n{job.description}")
    return "\n".join(lines)


def _combine(dimension_scores: dict) -> int:
    """Weighted mean of the per-dimension scores. Computing the headline
    number here (rather than asking the model for it) is what keeps it
    granular -- and keeps it consistent with the breakdown shown to the user."""
    total = 0.0
    for name, weight, _ in DIMENSIONS:
        raw = dimension_scores.get(name, 0)
        value = raw if isinstance(raw, (int, float)) else 0
        total += max(0, min(100, value)) * weight
    return round(total)


def score_job_deep(cv: CVProfileStructured, job: JobPosting) -> dict:
    client = ollama.Client(host=OLLAMA_HOST) if OLLAMA_HOST else ollama.Client()
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"KANDYDAT:\n{_format_cv(cv)}\n\n---\n\nOFERTA:\n{_format_job(job)}"},
        ],
        format=RESPONSE_SCHEMA,
        options={"temperature": 0.1},
    )
    data = json.loads(response.message.content)
    dimension_scores = data.get("scores") or {}
    data["scores"] = dimension_scores
    data["score"] = _combine(dimension_scores)
    return data


def rank_jobs_deep(cv: CVProfileStructured, jobs: list[JobPosting], verbose: bool = True) -> list[dict]:
    """Deep-scores every job in `jobs` (expects an already-filtered, small
    set -- see module docstring) and returns them sorted best-first."""
    results = []
    for i, job in enumerate(jobs, 1):
        if verbose:
            print(f"[ai_scorer] {i}/{len(jobs)}: {job.title} @ {job.company}")
        try:
            evaluation = score_job_deep(cv, job)
        except Exception as e:
            evaluation = {
                "score": 0,
                "scores": {},
                "verdict": "błąd",
                "reasoning": f"Ocena nieudana: {e}",
                "strengths": [],
                "concerns": [],
            }
        results.append({"job": job.model_dump(), **evaluation})

    results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return results
