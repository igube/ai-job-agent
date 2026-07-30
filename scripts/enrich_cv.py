"""Etap 2 (AI): JSON (Etap 1, offline) -> local model (Ollama) -> structured JSON.

Requires `ollama serve` running and the model pulled. No API key, no cost.
Run scripts/parse_cv.py first.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from job_agent.common.models import CVProfileRaw  # noqa: E402
from job_agent.config import OUTPUTS_DIR  # noqa: E402
from job_agent.cv_analysis.ai_extractor import enrich_cv_profile  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Structure a CV profile via Claude (Etap 2)")
    parser.add_argument(
        "--input",
        type=Path,
        default=OUTPUTS_DIR / "cv_profile.json",
        help="Path to the Etap 1 output (default: data/outputs/cv_profile.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUTS_DIR / "cv_profile_structured.json",
        help="Where to write the structured JSON",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}. Run scripts/parse_cv.py first.")

    raw = CVProfileRaw.model_validate_json(args.input.read_text(encoding="utf-8"))

    print("Structuring via local model (Ollama) ...")
    structured = enrich_cv_profile(raw)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(structured.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
