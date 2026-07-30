"""Etap 5: run the AI Job Agent. Local model (Ollama), no API key, no cost.

Requires `ollama serve` running and cv_profile_structured.json to exist
(run scripts/parse_cv.py + scripts/enrich_cv.py first).
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from job_agent.agent.agent import DEFAULT_GOAL, run_agent  # noqa: E402
from job_agent.config import OUTPUTS_DIR  # noqa: E402

REPORT_PATH = OUTPUTS_DIR / "agent_report.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI Job Agent")
    parser.add_argument("--goal", type=str, default=DEFAULT_GOAL)
    args = parser.parse_args()

    result = run_agent(goal=args.goal)
    print("\n=== Ocena agenta ===\n")
    print(result)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    REPORT_PATH.write_text(f"_Ostatnia ocena: {timestamp}_\n\n{result}", encoding="utf-8")


if __name__ == "__main__":
    main()
