"""Etap 2 (AI): turns the offline CVProfileRaw (contact + raw sections) into
a fully structured CVProfileStructured, using a local model via Ollama.

No API key, no per-token cost, no data leaves the machine. Requires
`ollama serve` running and the model pulled (see ai_config.OLLAMA_MODEL).
Only this module talks to the model — Etap 1 (parser.py, local_extractor.py)
has no dependency on it.
"""

import json

import ollama

from job_agent.ai_config import OLLAMA_HOST, OLLAMA_MODEL
from job_agent.common.models import CVProfileRaw, CVProfileStructured

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": ["string", "null"]},
                    "position": {"type": ["string", "null"]},
                    "start_date": {"type": ["string", "null"]},
                    "end_date": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                },
                "required": ["company", "position", "start_date", "end_date", "location", "description"],
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": ["string", "null"]},
                    "degree": {"type": ["string", "null"]},
                    "field": {"type": ["string", "null"]},
                    "start_date": {"type": ["string", "null"]},
                    "end_date": {"type": ["string", "null"]},
                },
                "required": ["institution", "degree", "field", "start_date", "end_date"],
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "tech_stack": {"type": "array", "items": {"type": "string"}},
                    "url": {"type": ["string", "null"]},
                },
                "required": ["name", "description", "tech_stack", "url"],
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "languages": {
            "type": "array",
            "items": {"type": "string"},
            "description": "np. 'angielski C1', 'polski ojczysty'",
        },
    },
    "required": ["experience", "education", "projects", "skills", "languages"],
}

SYSTEM_PROMPT = (
    "You receive raw text extracted from a CV/resume PDF, split into rough sections. "
    "The PDF may have a multi-column layout, so text from different columns (e.g. skills "
    "listed beside experience entries) can be interleaved or misplaced into the wrong "
    "section — use your judgment to reassign items to the right place. "
    "Structure the content into experience, education, projects and a clean deduplicated "
    "skills list. Use null for fields not present. Keep dates in the format found in the "
    "source. Do not invent information not present in the text. "
    "Respond with a single JSON object matching the schema — no prose, no markdown fences."
)


def _build_user_message(raw: CVProfileRaw) -> str:
    parts = [f"Znane umiejętności (może być niekompletne): {', '.join(raw.skills) or '(brak)'}", ""]
    if raw.summary:
        parts.append(f"PODSUMOWANIE / PROFIL KANDYDATA:\n{raw.summary}")
    for name, text in raw.sections.items():
        parts.append(f"SEKCJA: {name}\n{text}")
    return "\n\n".join(parts)


def enrich_cv_profile(raw: CVProfileRaw) -> CVProfileStructured:
    client = ollama.Client(host=OLLAMA_HOST) if OLLAMA_HOST else ollama.Client()

    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(raw)},
        ],
        format=RESPONSE_SCHEMA,
        options={"temperature": 0.1},
    )

    data = json.loads(response["message"]["content"])
    # summary is carried straight through from the offline stage -- it is
    # already the candidate's own words, nothing for the model to restructure.
    return CVProfileStructured(contact=raw.contact, summary=raw.summary, **data)
