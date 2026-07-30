"""Etap 6: dashboard. Streamlit UI reading the pipeline's JSON outputs --
CV profile, ranked job offers, latest agent evaluation. Pure viewer +
"run agent now" trigger — no business logic lives here, it all stays in
job_agent.*.

Landing-page UX: on load, show only a centered "start" button. Job offers
only appear after the agent has actually run (or after choosing to view a
previous run's results) -- not before.

Run with: streamlit run scripts/dashboard.py
"""

import html
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from job_agent.config import OUTPUTS_DIR  # noqa: E402

CV_PATH = OUTPUTS_DIR / "cv_profile_structured.json"
RANKED_PATH = OUTPUTS_DIR / "jobs_ranked.json"
JOBS_PATH = OUTPUTS_DIR / "jobs_ai.json"
REPORT_PATH = OUTPUTS_DIR / "agent_report.txt"
LOCK_PATH = OUTPUTS_DIR / ".agent_running.lock"
STALE_LOCK_MINUTES = 30

# Progress markers printed by matching.ai_scorer -- "[ai_scorer] 3/6: Title @ Co"
SCORER_RE = re.compile(r"^\[ai_scorer\]\s+(\d+)/(\d+):\s*(.+)$")
# "[justjoin.it] pobrano 250/557 ofert" -- both numbers are real (they come
# from the API's own total), so the bar tracks actual work. Same line shape
# for every API-backed source.
FETCH_RE = re.compile(r"^\[([\w.]+)\]\s+pobrano\s+(\d+)/(\d+)\s+ofert$")
# "[olx.pl] odrzucono 3 ofert bez związku z AI"
DROPPED_RE = re.compile(r"^\[([\w.]+)\]\s+odrzucono\s+(\d+)\s+ofert")
# "[pracuj.pl] strona 1/2 — pobieram…"
PRACUJ_RE = re.compile(r"^\[pracuj\.pl\]\s+strona\s+(\d+)/(\d+)\s+—")
# "... -> jeszcze 5.7h) — używam cache"
LEFT_RE = re.compile(r"jeszcze\s+([\d.]+)h")
# Share of the bar given to the fetch phase. Measured on a warm run:
# fetch ~25s vs deep scoring ~45s, so scoring gets the larger slice.
FETCH_SHARE = 0.3
# API-backed sources that report "pobrano N/TOTAL" (pracuj.pl uses Playwright
# and reports per-page instead, so it is not part of this split).
API_SOURCES = 4

# Model verdict -> (pill style, icon, label on the card, grouping key).
# Older result files used a different wording, so those spellings stay mapped.
VERDICT_META = {
    "polecam": ("success", "✓", "Polecana", "good"),
    "rozważ": ("warn", "•", "Do rozważenia", "maybe"),
    "odradzam": ("danger", "✕", "Niepolecana", "bad"),
    "neutralnie": ("warn", "•", "Do rozważenia", "maybe"),
    "pomiń": ("danger", "✕", "Niepolecana", "bad"),
    "błąd": ("danger", "!", "Błąd oceny", "bad"),
}
DIMENSION_LABELS = {
    "wymagania": "Wymagania",
    "poziom": "Poziom",
    "dziedzina": "Dziedzina AI",
    "rozwoj": "Rozwój",
    "warunki": "Warunki",
}
VERDICT_GROUPS = [
    ("good", "✅ Oferty polecane", "Brak ofert w tej kategorii."),
    ("maybe", "🤔 Oferty do rozważenia", "Brak ofert w tej kategorii."),
    ("bad", "🚫 Oferty niepolecane", "Brak ofert w tej kategorii."),
]

st.set_page_config(page_title="AI Job Agent", page_icon="🎯", layout="wide")


# ---------------------------------------------------------------- styling --

def inject_css(landing: bool) -> None:
    landing_css = """
/* full-bleed dark hero, true center (both axes) */
[data-testid="stAppViewContainer"] {
  background: radial-gradient(circle at 50% 0%, #1E1B4B 0%, #0B0F1E 55%, #05070D 100%);
}
[data-testid="stHeader"] { background: transparent; }
.block-container {
  min-height: 100vh; max-width: 1100px; padding: 0 1rem !important;
}
.block-container > div[data-testid="stVerticalBlock"] {
  min-height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center;
}
.hero-title {
  font-size: 5rem; line-height: 1.05; font-weight: 800; text-align: center; letter-spacing: -0.04em;
  background: linear-gradient(135deg, #A5B4FC 0%, #C4B5FD 45%, #F0ABFC 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  margin-bottom: 1rem; filter: drop-shadow(0 0 40px rgba(129,140,248,0.35));
}
.hero-sub { text-align: center; color: #94A3B8; font-size: 1.3rem; margin-bottom: 2.5rem; max-width: 640px; }
[data-testid="column"] .stButton > button { font-size: 1.15rem !important; padding: 1.6rem 1rem !important; }
[data-testid="column"] .stButton > button:not([kind="primary"]) {
  background: transparent !important; border-color: #334155 !important; color: #CBD5E1 !important;
}
"""
    results_css = """
[data-testid="stAppViewContainer"] { background: #F1F5F9; }
.block-container { padding-top: 2.2rem; max-width: 1100px; }
"""
    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
p, span, div, h1, h2, h3, h4, h5, h6, button, input, label, li {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}}

#MainMenu, footer, header, [data-testid="stDecoration"] {{ visibility: hidden; height: 0; }}

:root {{
  --ink: #0F172A;
  --muted: #64748B;
  --line: #E2E8F0;
  --card: #FFFFFF;
  --accent: #6366F1;
  --accent-dim: #EEF2FF;
  --success: #059669; --success-bg: #ECFDF5; --success-line: #A7F3D0;
  --warn: #B45309;    --warn-bg: #FFFBEB;    --warn-line: #FDE68A;
  --danger: #DC2626;  --danger-bg: #FEF2F2;  --danger-line: #FECACA;
}}

{landing_css if landing else results_css}

/* buttons */
.stButton > button {{
  border-radius: 10px !important; font-weight: 600 !important; border: 1px solid var(--line) !important;
  transition: all 0.15s ease !important;
}}
.stButton > button[kind="primary"] {{
  background: var(--accent) !important; border: none !important;
  box-shadow: 0 4px 14px rgba(99,102,241,0.35) !important;
}}
.stButton > button[kind="primary"]:hover {{ transform: translateY(-1px); box-shadow: 0 6px 18px rgba(99,102,241,0.45) !important; }}
.stButton > button:not([kind="primary"]):hover {{ border-color: var(--accent) !important; color: var(--accent) !important; }}

/* status container ("Agent pracuje…") -- identical fill/radius/shadow to the
   primary button, so it reads as the same component family */
[data-testid="stExpander"] details {{
  background: var(--accent) !important;
  border: none !important;
  border-radius: 10px !important;
  box-shadow: 0 4px 14px rgba(99,102,241,0.35) !important;
}}
/* the summary row carries its own white background -- without this the
   header strip stays white and the white label on it is invisible */
[data-testid="stExpander"] summary {{
  font-weight: 600 !important;
  background: transparent !important;
  border: none !important;
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  gap: 0.5rem !important;
}}
/* the chevron would otherwise sit flush right and pull the label off-centre */
[data-testid="stExpander"] summary [data-testid="stExpanderToggleIcon"] {{ display: none !important; }}
/* Streamlit nests the spinner+label inside two `flex: 1 1 auto` wrappers
   (a SPAN, then a DIV) that stretch the full row width and left-align their
   contents -- so justify-content on the summary alone centres nothing.
   Shrink both wrappers to their content and centre inside them too. */
[data-testid="stExpander"] summary > span,
[data-testid="stExpander"] summary > span > div {{
  flex: 0 1 auto !important;
  width: auto !important;
  justify-content: center !important;
}}
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] {{
  text-align: center !important;
}}
[data-testid="stExpander"] summary:hover {{ background: rgba(255,255,255,0.08) !important; }}
/* solid indigo fill -> every bit of text on it must be white to stay legible */
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] p,
[data-testid="stExpander"] strong,
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {{
  color: #FFFFFF !important;
}}
[data-testid="stExpander"] [data-testid="stCaptionContainer"] p {{
  color: rgba(255,255,255,0.75) !important;
}}
[data-testid="stExpander"] summary svg {{ color: #FFFFFF !important; fill: #FFFFFF !important; }}

/* progress bar: same indigo->violet gradient as the hero title */
[data-testid="stProgressBarTrack"] > div {{
  background: linear-gradient(90deg, #6366F1 0%, #A855F7 100%) !important;
}}

/* metrics */
[data-testid="stMetricValue"] {{ font-weight: 800; color: var(--ink); }}
[data-testid="stMetric"] {{
  background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 0.9rem 1rem;
}}

/* offer card */
.offer-card {{
  background: var(--card); border: 1px solid var(--line); border-radius: 14px;
  padding: 1.25rem 1.4rem; margin-bottom: 1rem; transition: box-shadow 0.15s ease, border-color 0.15s ease;
}}
.offer-card:hover {{ box-shadow: 0 6px 24px rgba(15,23,42,0.06); border-color: #CBD5E1; }}
.offer-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }}
.offer-title {{ font-size: 1.08rem; font-weight: 700; color: var(--ink); text-decoration: none; }}
.offer-title:hover {{ color: var(--accent); }}
.offer-company {{ color: var(--muted); font-size: 0.92rem; margin-top: 0.1rem; }}
.offer-score {{
  font-weight: 800; font-size: 1.3rem; color: var(--accent); white-space: nowrap; line-height: 1;
}}
.offer-score-label {{ font-size: 0.68rem; color: var(--muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }}
.offer-meta {{ color: var(--muted); font-size: 0.85rem; margin: 0.55rem 0 0.7rem; }}
.offer-meta .dot {{ margin: 0 0.35rem; opacity: 0.5; }}

.pill {{
  display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.18rem 0.65rem; border-radius: 999px;
  font-size: 0.8rem; font-weight: 700; border: 1px solid transparent;
}}
.pill-success {{ background: var(--success-bg); color: var(--success); border-color: var(--success-line); }}
.pill-warn    {{ background: var(--warn-bg);    color: var(--warn);    border-color: var(--warn-line); }}
.pill-danger  {{ background: var(--danger-bg);  color: var(--danger);  border-color: var(--danger-line); }}

.offer-reasoning {{ margin-top: 0.6rem; color: #334155; font-size: 0.92rem; line-height: 1.5; }}

/* key factors as chips instead of a comma-joined run-on line */
.factors {{ margin-top: 0.7rem; display: flex; flex-wrap: wrap; gap: 0.35rem; }}
.factor {{
  display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.82rem; font-weight: 500;
  padding: 0.2rem 0.6rem; border-radius: 8px; line-height: 1.35;
}}
.factor-pro {{ background: var(--success-bg); color: #065F46; border: 1px solid var(--success-line); }}
.factor-con {{ background: var(--warn-bg);    color: #92400E; border: 1px solid var(--warn-line); }}

/* per-dimension score breakdown */
.dims {{ margin-top: 0.85rem; display: grid; gap: 0.3rem; }}
.dim {{ display: grid; grid-template-columns: 6.5rem 1fr 2rem; align-items: center; gap: 0.55rem; }}
.dim-name {{ font-size: 0.78rem; color: var(--muted); }}
.dim-track {{ height: 6px; background: #EEF2F7; border-radius: 999px; overflow: hidden; }}
.dim-fill {{ display: block; height: 100%; border-radius: 999px;
  background: linear-gradient(90deg, #6366F1 0%, #A855F7 100%); }}
.dim-val {{ font-size: 0.75rem; font-weight: 700; color: #475569; text-align: right; }}

/* grouped verdict panel */
.group-head {{
  display: flex; align-items: baseline; gap: 0.5rem; margin: 1.1rem 0 0.5rem;
  font-weight: 700; font-size: 0.95rem;
}}
.group-count {{
  font-size: 0.75rem; font-weight: 700; padding: 0.05rem 0.5rem; border-radius: 999px;
  background: #E2E8F0; color: #475569;
}}
.group-item {{
  border-left: 3px solid var(--line); padding: 0.35rem 0 0.35rem 0.7rem; margin-bottom: 0.45rem;
}}
.group-item a {{ color: var(--ink); text-decoration: none; font-weight: 600; font-size: 0.9rem; }}
.group-item a:hover {{ color: var(--accent); }}
.group-item .sub {{ color: var(--muted); font-size: 0.8rem; margin-top: 0.1rem; }}
.group-good  .group-item {{ border-left-color: var(--success); }}
.group-maybe .group-item {{ border-left-color: #D97706; }}
.group-bad   .group-item {{ border-left-color: #CBD5E1; }}
.group-empty {{ color: var(--muted); font-size: 0.85rem; font-style: italic; }}

/* candidate card in sidebar */
.candidate-name {{ font-weight: 700; font-size: 1.05rem; color: var(--ink); }}
.candidate-line {{ color: var(--muted); font-size: 0.88rem; margin: 0.15rem 0; }}
.skill-chip {{
  display: inline-block; background: var(--accent-dim); color: var(--accent); font-size: 0.75rem;
  font-weight: 600; padding: 0.15rem 0.55rem; border-radius: 999px; margin: 0.15rem 0.25rem 0.15rem 0;
}}
</style>
        """,
        unsafe_allow_html=True,
    )


def verdict_meta(verdict: str) -> tuple[str, str, str, str]:
    return VERDICT_META.get(verdict, ("warn", "•", verdict or "?", "maybe"))


def verdict_pill(verdict: str) -> str:
    cls, icon, label, _ = verdict_meta(verdict)
    return f'<span class="pill pill-{cls}">{icon} {html.escape(label)}</span>'


def render_offer_card(r: dict) -> None:
    job = r["job"]
    score = r.get("score", 0)
    reasoning = html.escape(r.get("reasoning", ""))
    title = html.escape(job["title"])
    company = html.escape(job["company"])
    meta = " <span class='dot'>·</span> ".join(
        html.escape(str(v)) for v in [
            job.get("city") or "-",
            job.get("workplace_type") or "-",
            job.get("experience_level") or "-",
            job.get("source"),
        ]
    )
    # Key factors as separate chips: scannable at a glance, unlike one long
    # comma-joined sentence.
    chips = [
        f"<span class='factor factor-pro'>✓ {html.escape(s)}</span>"
        for s in (r.get("strengths") or [])[:3]
    ] + [
        f"<span class='factor factor-con'>! {html.escape(c)}</span>"
        for c in (r.get("concerns") or [])[:3]
    ]
    tags_html = f"<div class='factors'>{''.join(chips)}</div>" if chips else ""

    # Per-dimension breakdown: shows *why* the headline number is what it is.
    dims = r.get("scores") or {}
    dims_html = ""
    if dims:
        bars = "".join(
            f"<div class='dim'>"
            f"<span class='dim-name'>{html.escape(DIMENSION_LABELS.get(k, k))}</span>"
            f"<span class='dim-track'><span class='dim-fill' style='width:{max(0, min(100, v))}%'></span></span>"
            f"<span class='dim-val'>{v}</span>"
            f"</div>"
            for k, v in dims.items()
            if isinstance(v, (int, float))
        )
        dims_html = f"<div class='dims'>{bars}</div>"
    tags_html += dims_html

    st.markdown(
        f"""
<div class="offer-card">
  <div class="offer-head">
    <div>
      <a class="offer-title" href="{job['url']}" target="_blank">{title}</a>
      <div class="offer-company">{company}</div>
    </div>
    <div style="text-align:right">
      <div class="offer-score">{score}%</div>
      <div class="offer-score-label">dopasowanie</div>
    </div>
  </div>
  <div class="offer-meta">{meta}</div>
  {verdict_pill(r.get("verdict", ""))}
  <div class="offer-reasoning">{reasoning}</div>
  {tags_html}
</div>
        """,
        unsafe_allow_html=True,
    )


if "revealed" not in st.session_state:
    st.session_state.revealed = False

inject_css(landing=not st.session_state.revealed)


def _ollama_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=1):
            return True
    except OSError:
        return False


def ensure_ollama_running(timeout: float = 30.0) -> bool:
    """So the button is self-sufficient: no need to have manually run
    `ollama serve` (or Claude Code) beforehand. Starts it detached and
    waits until it responds."""
    if _ollama_reachable():
        return True
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ollama_reachable():
            return True
        time.sleep(0.5)
    return False


def run_agent_now() -> None:
    # Cross-session guard: each browser tab/reload gets its own
    # st.session_state, so a session-level flag does NOT stop a second tab
    # (or an impatient double-click after a reload) from launching another
    # run. Each run loads a 9GB model into VRAM -- concurrent runs pin the
    # GPU at 100% and make everything crawl. A lock file is the only thing
    # that actually serializes across sessions.
    if LOCK_PATH.exists():
        age_min = (time.time() - LOCK_PATH.stat().st_mtime) / 60
        if age_min < STALE_LOCK_MINUTES:
            st.warning(
                f"Agent już pracuje (uruchomiony {age_min:.0f} min temu). "
                "Poczekaj na zakończenie — równoległe uruchomienia obciążają GPU."
            )
            return
        LOCK_PATH.unlink()  # stale lock from a crashed/killed run

    with st.spinner("Uruchamiam lokalny model (Ollama)..."):
        if not ensure_ollama_running():
            st.error(
                "Nie udało się uruchomić Ollama automatycznie. Sprawdź, czy jest "
                "zainstalowana (ollama.com), i spróbuj ponownie."
            )
            return

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(str(time.time()), encoding="utf-8")

    started = time.time()
    tail: list[str] = []
    returncode = 1

    # Stream the child's stdout instead of subprocess.run()'s capture_output:
    # the pipeline already prints its own step markers ("[ai_scorer] 3/6: ..."),
    # so real progress can be surfaced rather than a blind multi-minute spinner.
    try:
        with st.status("Agent pracuje…", expanded=True) as status:
            step_slot = st.empty()
            bar = st.progress(0.0)
            sources_slot = st.empty()
            time_slot = st.empty()
            # Per-source outcome, kept visible for the whole run -- otherwise
            # a one-off line (e.g. "pracuj.pl served from cache") is overwritten
            # by the next step and the user never sees why a source was skipped.
            sources: dict[str, str] = {}

            def render_sources() -> None:
                if sources:
                    sources_slot.caption(
                        " · ".join(f"{k}: {v}" for k, v in sources.items())
                    )

            step_slot.markdown("**Pobieram oferty** z justjoin.it i pracuj.pl…")

            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
            proc = subprocess.Popen(
                [sys.executable, "-u", str(ROOT_DIR / "scripts" / "run_agent.py")],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            scored = total_to_score = 0
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.rstrip()
                if not line:
                    continue
                tail.append(line)
                del tail[:-40]
                elapsed = time.time() - started

                m = SCORER_RE.match(line)
                if m:
                    scored, total_to_score = int(m.group(1)), int(m.group(2))
                    label = m.group(3)
                    step_slot.markdown(
                        f"**Analizuję oferty** ({scored}/{total_to_score}) — {html.escape(label)}"
                    )
                    bar.progress(FETCH_SHARE + (scored / total_to_score) * (1 - FETCH_SHARE))
                elif line.startswith("[agent]") and "score_jobs" in line:
                    step_slot.markdown("**Dopasowuję oferty** do CV…")
                    bar.progress(FETCH_SHARE)
                elif (pp := PRACUJ_RE.match(line)) is not None:
                    step_slot.markdown(
                        f"**Pobieram oferty** z pracuj.pl — strona {pp.group(1)}/{pp.group(2)}…"
                    )
                    sources["pracuj.pl"] = f"pobieram (strona {pp.group(1)}/{pp.group(2)})"
                    render_sources()
                elif line.startswith("[pracuj.pl]") and "cache" in line:
                    left = LEFT_RE.search(line)
                    sources["pracuj.pl"] = (
                        f"cache (limit 1×/24h, odświeży się za {left.group(1)}h)"
                        if left
                        else "cache (limit 1×/24h)"
                    )
                    render_sources()
                elif (f := FETCH_RE.match(line)) is not None:
                    src, got, total_offers = f.group(1), int(f.group(2)), int(f.group(3))
                    step_slot.markdown(f"**Pobieram oferty** z {src} — {got}/{total_offers}…")
                    sources[src] = f"{got} ofert"
                    render_sources()
                    # Each API source advances an equal slice of the fetch
                    # phase, so the bar keeps moving across all of them.
                    done_sources = sum(1 for k in sources if k != "pracuj.pl")
                    frac = (done_sources - 1 + min(got / total_offers, 1.0)) / API_SOURCES
                    bar.progress(min(frac, 1.0) * FETCH_SHARE)
                elif (d := DROPPED_RE.match(line)) is not None:
                    src = d.group(1)
                    if src in sources:
                        sources[src] += f" (−{d.group(2)} nie-AI)"
                        render_sources()

                # ETA only once at least one offer is scored -- before that
                # there is nothing to extrapolate from, and a made-up number
                # is worse than none.
                eta = ""
                if scored and total_to_score and scored < total_to_score:
                    per_offer = elapsed / scored
                    remaining = per_offer * (total_to_score - scored)
                    eta = f" · pozostało ~{remaining / 60:.1f} min"
                time_slot.caption(f"⏱ {elapsed / 60:.1f} min{eta}")

            returncode = proc.wait()
            if returncode == 0:
                bar.progress(1.0)
                step_slot.markdown("**Gotowe**")
                time_slot.caption(f"⏱ zakończono w {(time.time() - started) / 60:.1f} min")
                status.update(label="Agent zakończył pracę", state="complete", expanded=False)
            else:
                status.update(label="Agent zakończył się błędem", state="error")
    finally:
        LOCK_PATH.unlink(missing_ok=True)

    if returncode != 0:
        st.error("Błąd:\n" + "\n".join(tail[-15:]))
        return
    st.session_state.revealed = True


# --- Landing page: ONLY the title and one button, nothing else ---
if not st.session_state.revealed:
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown("<div class='hero-title'>AI JOB AGENT</div>", unsafe_allow_html=True)
        if st.button("Uruchom agenta", type="primary", use_container_width=True):
            run_agent_now()
            # Only rerun on success -- an unconditional rerun would wipe the
            # error/warning message off the screen, so a failed run would look
            # like the button simply did nothing.
            if st.session_state.revealed:
                st.rerun()
    st.stop()


# --- Results view ---
with st.sidebar:
    st.markdown("#### Kandydat")
    if CV_PATH.exists():
        cv = json.loads(CV_PATH.read_text(encoding="utf-8"))
        contact = cv.get("contact", {})
        st.markdown(f"<div class='candidate-name'>{html.escape(contact.get('name') or '-')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='candidate-line'>📍 {html.escape(contact.get('location') or '-')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='candidate-line'>✉️ {html.escape(contact.get('email') or '-')}</div>", unsafe_allow_html=True)
        skills = cv.get("skills", [])
        if skills:
            st.markdown("<div style='margin-top:0.6rem'>" + "".join(
                f"<span class='skill-chip'>{html.escape(s)}</span>" for s in skills
            ) + "</div>", unsafe_allow_html=True)
    else:
        st.warning("Brak CV.\n\nUruchom:\n`scripts/parse_cv.py`\n`scripts/enrich_cv.py`")

    st.divider()

    if st.button("🔄  Uruchom agenta ponownie", type="primary", use_container_width=True):
        run_agent_now()
        st.rerun()

    if st.button("⬅  Wróć na start", use_container_width=True):
        st.session_state.revealed = False
        st.rerun()

st.markdown("### 🎯 AI Job Agent")

ranked = json.loads(RANKED_PATH.read_text(encoding="utf-8")) if RANKED_PATH.exists() else []
grouped: dict[str, list[dict]] = {"good": [], "maybe": [], "bad": []}
for r in ranked:
    grouped[verdict_meta(r.get("verdict", ""))[3]].append(r)

col1, col2, col3 = st.columns(3)
if JOBS_PATH.exists():
    total = len(json.loads(JOBS_PATH.read_text(encoding="utf-8")))
    col1.metric("Znalezione oferty AI", total)
col2.metric("Ocenione przez agenta", len(ranked))
col3.metric("Polecane", len(grouped["good"]))

st.write("")

left, right = st.columns([3, 2])

with left:
    st.markdown("##### Ranking ofert")
    st.caption("Każda oferta oceniona przez model na podstawie pełnego ogłoszenia i całego CV.")
    if not ranked:
        st.info(
            "Brak ocenionych ofert. Uruchom agenta — jeśli już działał, "
            "prawdopodobnie żadna oferta nie przeszła filtrów poziomu i lokalizacji."
        )
    for r in ranked:
        render_offer_card(r)

with right:
    st.markdown("##### Podsumowanie")
    st.caption("Oferty pogrupowane według rekomendacji agenta.")
    if not ranked:
        st.info("Brak ocen do podsumowania.")
    else:
        for key, heading, empty_text in VERDICT_GROUPS:
            items = grouped[key]
            st.markdown(
                f"<div class='group-head'>{heading}"
                f"<span class='group-count'>{len(items)}</span></div>",
                unsafe_allow_html=True,
            )
            if not items:
                st.markdown(f"<div class='group-empty'>{empty_text}</div>", unsafe_allow_html=True)
                continue
            rows = "".join(
                f"<div class='group-item'>"
                f"<a href='{i['job']['url']}' target='_blank'>{html.escape(i['job']['title'])}</a>"
                f"<div class='sub'>{html.escape(i['job']['company'])} · {i.get('score', 0)}%</div>"
                f"</div>"
                for i in items
            )
            st.markdown(f"<div class='group-{key}'>{rows}</div>", unsafe_allow_html=True)
