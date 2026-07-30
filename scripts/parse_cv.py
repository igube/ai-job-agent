"""Etap 1 (offline): PDF -> tekst -> JSON. Bez wywolan do zadnego API."""

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from job_agent.common.models import CVProfileRaw  # noqa: E402
from job_agent.config import OUTPUTS_DIR  # noqa: E402
from job_agent.cv_analysis.local_extractor import parse_cv_local  # noqa: E402
from job_agent.cv_analysis.parser import extract_text  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a CV PDF into structured JSON (offline)")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT_DIR / "cv" / "cv.pdf.pdf",
        help="Path to the CV PDF (default: cv/cv.pdf.pdf)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUTS_DIR / "cv_profile.json",
        help="Where to write the extracted JSON",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"CV file not found: {args.input}")

    print(f"Reading {args.input} ...")
    text = extract_text(args.input)

    print("Extracting contact + sections locally (no API calls) ...")
    result = parse_cv_local(text)
    profile = CVProfileRaw(source_file=str(args.input), **result)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(profile.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
