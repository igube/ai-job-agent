"""Etap 4 (offline): CV (structured) + oferty AI -> ranking dopasowania.

Docelowy poziom ofert (intern/junior/mid/senior) jest WYKRYWANY z CV, nie
hardcodowany na sztywno "junior" -- inny CV = inny target automatycznie.
Staże/praktyki (intern) sa priorytetyzowane nad "junior" -- oferty junior
czesto i tak wymagaja realnego doswiadczenia -- z automatycznym poszerzeniem
do junior tylko gdy samych stazy jest za malo (patrz job_agent.matching.level_inference).
"""

import argparse
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from job_agent.common.models import CVProfileStructured, JobPosting  # noqa: E402
from job_agent.config import OUTPUTS_DIR  # noqa: E402
from job_agent.matching.ai_scorer import rank_jobs_deep  # noqa: E402
from job_agent.matching.level_inference import filter_by_level_tiers, infer_target_level_tiers  # noqa: E402
from job_agent.matching.location import extract_candidate_city, is_location_compatible  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Score & rank AI job offers against the CV (Etap 4)")
    parser.add_argument("--cv", type=Path, default=OUTPUTS_DIR / "cv_profile_structured.json")
    parser.add_argument("--jobs", type=Path, default=OUTPUTS_DIR / "jobs_ai.json")
    parser.add_argument("--output", type=Path, default=OUTPUTS_DIR / "jobs_ranked.json")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument(
        "--no-level-filter",
        action="store_true",
        help="Score every offer regardless of the inferred experience level",
    )
    parser.add_argument(
        "--no-location-filter",
        action="store_true",
        help="Score every offer regardless of city (remote offers are always kept)",
    )
    args = parser.parse_args()

    if not args.cv.exists():
        raise SystemExit(f"CV not found: {args.cv}. Run scripts/enrich_cv.py first.")
    if not args.jobs.exists():
        raise SystemExit(f"Jobs not found: {args.jobs}. Run scripts/fetch_jobs.py first.")

    cv = CVProfileStructured.model_validate_json(args.cv.read_text(encoding="utf-8"))
    jobs_raw = json.loads(args.jobs.read_text(encoding="utf-8"))
    jobs = [JobPosting.model_validate(j) for j in jobs_raw]

    candidate_city = extract_candidate_city(cv)
    if args.no_location_filter:
        location_filtered = jobs
    else:
        location_filtered = [j for j in jobs if is_location_compatible(candidate_city, j)]
        print(
            f"Lokalizacja kandydata wykryta z CV: {candidate_city or '(brak)'} "
            f"-> oferty stacjonarne/hybrydowe spoza miasta odrzucone (remote zawsze zostaje). "
            f"Oferty po filtrze lokalizacji: {len(location_filtered)} / {len(jobs)}"
        )

    if args.no_level_filter:
        filtered = location_filtered
    else:
        tiers, reason = infer_target_level_tiers(cv)
        filtered, target_levels, widened = filter_by_level_tiers(location_filtered, tiers)
        if widened:
            reason += " (poszerzone -- za mało ofert w priorytetowym progu)"
        print(f"Profil kandydata wykryty z CV: {reason}")
        print(f"Docelowe poziomy ofert: {', '.join(target_levels)}")
        print(f"Oferty po filtrze poziomu: {len(filtered)} / {len(location_filtered)}")

    print(f"\nGłębka analiza AI (lokalny model) dla {len(filtered)} ofert -- to zajmie chwilę...")
    ranked = rank_jobs_deep(cv, filtered)[: args.top]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ranked, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {args.output}")

    print("\nTop dopasowania:")
    for r in ranked[:10]:
        j = r["job"]
        print(f"  [{r['score']}%] ({r['verdict']}) {j['title']} @ {j['company']} ({j['experience_level']}) — {j['url']}")


if __name__ == "__main__":
    main()
