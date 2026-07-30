"""Etap 3 (offline): fetch AI/ML job offers from all sources -> merged JSON.

justjoin.it / rocketjobs.pl / olx.pl: public APIs, safe to fetch every run.
pracuj.pl: Cloudflare-protected, rate-limited to 1x/24h in code (see
job_scraping.rate_limit) — repeated runs reuse the cached fetch.
"""

import argparse
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from job_agent.common.models import CVProfileStructured  # noqa: E402
from job_agent.config import OUTPUTS_DIR  # noqa: E402
from job_agent.job_scraping.dedup import dedupe_postings  # noqa: E402
from job_agent.job_scraping.sources.justjoinit import fetch_ai_offers as fetch_justjoinit  # noqa: E402
from job_agent.job_scraping.sources.olx import fetch_ai_offers as fetch_olx  # noqa: E402
from job_agent.job_scraping.sources.pracujpl import fetch_ai_offers as fetch_pracuj  # noqa: E402
from job_agent.job_scraping.sources.rocketjobs import fetch_ai_offers as fetch_rocketjobs  # noqa: E402
from job_agent.job_scraping.sources.theprotocol import fetch_ai_offers as fetch_theprotocol  # noqa: E402
from job_agent.matching.location import extract_candidate_city  # noqa: E402

CV_PATH = OUTPUTS_DIR / "cv_profile_structured.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch AI/ML job offers (justjoin.it + pracuj.pl + rocketjobs.pl + olx.pl)"
    )
    parser.add_argument("--max-results", type=int, default=None, help="Cap per source (default: all)")
    parser.add_argument("--output", type=Path, default=OUTPUTS_DIR / "jobs_ai.json")
    parser.add_argument("--skip-pracuj", action="store_true", help="Skip the Cloudflare-guarded source")
    parser.add_argument("--city", type=str, default=None, help="Override city (default: read from CV)")
    args = parser.parse_args()

    city = args.city
    if city is None and CV_PATH.exists():
        cv = CVProfileStructured.model_validate_json(CV_PATH.read_text(encoding="utf-8"))
        city = extract_candidate_city(cv)
    if city:
        print(f"Lokalizacja kandydata: {city}")

    collected: list = []

    print("Fetching AI/ML job offers from justjoin.it ...")
    jji = fetch_justjoinit(max_results=args.max_results)
    print(f"  justjoin.it: {len(jji)} offers")
    collected += jji

    print("Fetching AI job offers from rocketjobs.pl ...")
    rocket = fetch_rocketjobs(max_results=args.max_results)
    print(f"  rocketjobs.pl: {len(rocket)} offers")
    collected += rocket

    print("Fetching AI job offers from olx.pl ...")
    olx = fetch_olx(city=city, max_results=args.max_results)
    print(f"  olx.pl: {len(olx)} offers")
    collected += olx

    print("Fetching AI job offers from theprotocol.it (intern/junior) ...")
    protocol = fetch_theprotocol(max_results=args.max_results)
    print(f"  theprotocol.it: {len(protocol)} offers")
    collected += protocol

    if not args.skip_pracuj:
        print(f"Fetching AI job offers from pracuj.pl (intern/junior, {city or 'cała Polska'}, max 1x/24h) ...")
        pracuj = fetch_pracuj(city=city, max_results=args.max_results)
        print(f"  pracuj.pl: {len(pracuj)} offers")
        collected += pracuj

    all_postings = dedupe_postings(collected)
    print(f"Total: {len(all_postings)} offers (po deduplikacji tytuł+firma)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps([p.model_dump() for p in all_postings], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
