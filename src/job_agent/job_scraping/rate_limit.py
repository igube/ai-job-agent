"""Per-source fetch rate limiting. Protects Cloudflare-protected sources
(pracuj.pl) from being hit more than once per interval, no matter how many
times the pipeline/agent is actually run that day — enforced in code, not
by discipline.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from job_agent.config import DATA_DIR

STATE_PATH = DATA_DIR / "fetch_state.json"


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def should_fetch(source: str, min_interval_hours: float = 24.0) -> tuple[bool, str]:
    """Returns (allowed, human-readable reason)."""
    last = _load_state().get(source)
    if last is None:
        return True, "brak wcześniejszego fetchu"

    elapsed_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
    if elapsed_hours >= min_interval_hours:
        return True, f"ostatni fetch {elapsed_hours:.1f}h temu (limit {min_interval_hours}h)"

    remaining = min_interval_hours - elapsed_hours
    return False, f"ostatni fetch {elapsed_hours:.1f}h temu, limit {min_interval_hours}h -> jeszcze {remaining:.1f}h"


def record_fetch(source: str) -> None:
    state = _load_state()
    state[source] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
