"""Etap 5: agent, not a script. Decides when to call fetch_jobs/score_jobs
and compiles the results into a final answer. The deep per-offer judgment
itself (score, verdict, reasoning, strengths, concerns) is already done
inside score_jobs (matching.ai_scorer) — the agent's job here is fetching,
triggering that analysis, and presenting it, not re-deriving it from
scratch in a second LLM pass.

Local model via Ollama, same as Etap 2 — no API key, no per-token cost.
Scope, by design: fetch + score + evaluate. No CV/cover-letter generation,
no applying — those are explicitly out of scope for this agent.
"""

import json

import ollama

from job_agent.agent.tools import TOOL_IMPLS, TOOLS
from job_agent.ai_config import OLLAMA_HOST, OLLAMA_MODEL

SYSTEM_PROMPT = """\
Jesteś agentem AI Job Agent. Twoje zadanie: znaleźć i ocenić oferty pracy \
AI/ML dopasowane do kandydata na podstawie jego CV.

Masz dostęp do narzędzi:
- fetch_jobs: pobiera świeże oferty AI/ML z justjoin.it i pracuj.pl
- score_jobs: filtruje oferty wg poziomu doświadczenia i lokalizacji WYKRYTYCH \
z CV kandydata (priorytet: staż/praktyka, automatyczne poszerzenie do junior \
gdy za mało wyników), a potem GŁĘBOKO analizuje każdą przez lokalny model \
(pełny opis oferty vs pełne CV, nie tylko nazwy umiejętności). Każda zwrócona \
oferta ma już gotowy score, verdict (polecam / rozważ / odradzam), reasoning, \
strengths i concerns — to jest już pełna ocena, nie surowy procent.

CV kandydata jest już zapisane na dysku — narzędzia czytają je same, nie musisz \
o nic pytać użytkownika. Zawsze najpierw wywołaj fetch_jobs, potem score_jobs.

Twoje zadanie: zebrać wyniki score_jobs i przedstawić je czytelnie użytkownikowi \
— dla każdej oferty werdykt + reasoning + kluczowe strengths/concerns z narzędzia. \
NIE wymyślaj własnej oceny od nowa — score_jobs już to zrobiło dogłębnie, Twoja \
rola to zebranie i podsumowanie (ile ofert polecane i dlaczego te są najlepsze), \
ewentualnie dodanie ogólnego komentarza jeśli zauważysz coś ponad to co jest \
w danych z narzędzia.

Nie generuj CV ani listu motywacyjnego. Nie aplikuj. Twoje zadanie kończy \
się na ocenie i rekomendacji.
"""

DEFAULT_GOAL = "Znajdź i oceń najlepsze aktualne oferty AI/ML dla mojego CV."

MAX_ITERATIONS = 6
MAX_RETRIES = 3


def _run_conversation(goal: str, verbose: bool) -> tuple[str, bool]:
    """Runs one conversation attempt. Returns (result_text, used_any_tool)."""
    client = ollama.Client(host=OLLAMA_HOST) if OLLAMA_HOST else ollama.Client()

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": goal},
    ]
    used_any_tool = False

    for iteration in range(1, MAX_ITERATIONS + 1):
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=TOOLS,
            options={"temperature": 0.1},
        )
        message = response.message
        messages.append(message.model_dump())

        if not message.tool_calls:
            return message.content or "", used_any_tool

        for call in message.tool_calls:
            name = call.function.name
            args = call.function.arguments or {}
            if verbose:
                print(f"[agent] iteracja {iteration}: {name}({args})")

            impl = TOOL_IMPLS.get(name)
            used_any_tool = True
            if impl is None:
                result = {"error": f"unknown tool: {name}"}
            else:
                try:
                    result = impl(**args)
                except TypeError as e:
                    # Local models occasionally hallucinate wrong argument
                    # names/types — feed the error back instead of crashing,
                    # so the model can retry with corrected arguments.
                    result = {"error": f"invalid arguments for {name}: {e}"}

            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return "Agent nie zakończył oceny w limicie iteracji.", used_any_tool


def run_agent(goal: str = DEFAULT_GOAL, verbose: bool = True) -> str:
    """Local models occasionally mangle tool-call output or skip tools
    entirely (observed with qwen2.5:14b-instruct). If a run never actually
    called fetch_jobs/score_jobs, it produced no real work — retry fresh
    rather than surface a hallucinated or empty answer."""
    last_result = ""
    for attempt in range(1, MAX_RETRIES + 1):
        result, used_tool = _run_conversation(goal, verbose)
        if used_tool:
            return result
        last_result = result
        if verbose:
            print(f"[agent] próba {attempt}/{MAX_RETRIES}: model nie użył narzędzi, ponawiam")

    return (
        "Agent nie zdołał wykonać zadania (model lokalny nie wywołał narzędzi "
        f"po {MAX_RETRIES} próbach). Ostatnia odpowiedź modelu:\n\n{last_result}"
    )
