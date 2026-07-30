"""Measure how well the local scorer agrees with reference labels.

Without this there is no way to know whether the scoring is any good --
"the output looks reasonable" is not a measurement. Reports exact and
adjacent agreement, a confusion matrix, and the individual disagreements
so the failure modes are visible rather than averaged away.

Also sweeps the verdict thresholds, so the cutoffs in ai_scorer are picked
against data instead of by feel.

Usage:
    python scripts/evaluate_scoring.py
    python scripts/evaluate_scoring.py --sweep
"""

import argparse
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from job_agent.config import OUTPUTS_DIR  # noqa: E402
from job_agent.matching.ai_scorer import (  # noqa: E402
    CONSIDER_THRESHOLD,
    RECOMMEND_THRESHOLD,
    verdict_from_score,
)

LABELS_PATH = ROOT_DIR / "eval" / "reference_labels.json"
RANKED_PATH = OUTPUTS_DIR / "jobs_ranked.json"

ORDER = {"odradzam": 0, "rozważ": 1, "polecam": 2}


def key(title: str, company: str) -> tuple[str, str]:
    return (title.strip().lower(), company.strip().lower())


def load_pairs() -> list[dict]:
    """Join reference labels with the scorer's output on (title, company)."""
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    by_key = {key(l["title"], l["company"]): l for l in labels}

    ranked = json.loads(RANKED_PATH.read_text(encoding="utf-8"))
    pairs = []
    for r in ranked:
        job = r["job"]
        ref = by_key.get(key(job["title"], job["company"]))
        if ref is None:
            continue
        pairs.append(
            {
                "title": job["title"],
                "company": job["company"],
                "score": r.get("score", 0),
                "predicted": r.get("verdict", "?"),
                "model_verdict": r.get("model_verdict"),
                "expected": ref["label"],
                "reason": ref["reason"],
            }
        )
    return pairs


def agreement(pairs: list[dict], pred_field: str = "predicted") -> tuple[float, float]:
    if not pairs:
        return 0.0, 0.0
    exact = sum(1 for p in pairs if p[pred_field] == p["expected"])
    # "Adjacent" = off by one step on the 3-point scale (e.g. polecam vs
    # rozważ). Worth reporting separately: confusing neighbours is a much
    # milder failure than recommending something that should be rejected.
    adjacent = sum(
        1
        for p in pairs
        if p[pred_field] in ORDER
        and abs(ORDER[p[pred_field]] - ORDER[p["expected"]]) <= 1
    )
    return exact / len(pairs) * 100, adjacent / len(pairs) * 100


def print_confusion(pairs: list[dict]) -> None:
    names = ["polecam", "rozważ", "odradzam"]
    matrix = {e: {p: 0 for p in names} for e in names}
    for p in pairs:
        if p["expected"] in matrix and p["predicted"] in names:
            matrix[p["expected"]][p["predicted"]] += 1

    print(f"\n{'oczekiwane \\ ocena':<22}" + "".join(f"{n:>11}" for n in names))
    for e in names:
        row = "".join(f"{matrix[e][p]:>11}" for p in names)
        print(f"{e:<22}{row}")


def sweep(pairs: list[dict]) -> None:
    """Find the thresholds that maximise exact agreement."""
    best = []
    for recommend in range(60, 90, 2):
        for consider in range(35, recommend, 2):
            hits = sum(
                1
                for p in pairs
                if (
                    "polecam" if p["score"] >= recommend
                    else "rozważ" if p["score"] >= consider
                    else "odradzam"
                )
                == p["expected"]
            )
            best.append((hits / len(pairs) * 100, recommend, consider))
    best.sort(reverse=True)
    print("\nNajlepsze progi (zgodność dokładna):")
    for acc, recommend, consider in best[:5]:
        marker = " <- aktualne" if (recommend, consider) == (RECOMMEND_THRESHOLD, CONSIDER_THRESHOLD) else ""
        print(f"  polecam >= {recommend}, rozważ >= {consider}: {acc:.0f}%{marker}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ewaluacja jakości oceniania ofert")
    parser.add_argument("--sweep", action="store_true", help="Przetestuj różne progi werdyktu")
    args = parser.parse_args()

    if not RANKED_PATH.exists():
        raise SystemExit(f"Brak {RANKED_PATH}. Uruchom najpierw scripts/score_jobs.py.")

    pairs = load_pairs()
    if not pairs:
        raise SystemExit(
            "Żadna oceniona oferta nie pasuje do etykiet referencyjnych.\n"
            "Etykiety są kluczowane po (tytuł, firma) -- oferty mogły wygasnąć."
        )

    exact, adjacent = agreement(pairs)
    print(f"Ofert w ewaluacji: {len(pairs)}")
    print(f"Zgodność dokładna:  {exact:.0f}%")
    print(f"Zgodność +/-1 stopień: {adjacent:.0f}%")

    if any(p["model_verdict"] for p in pairs):
        raw_exact, _ = agreement(pairs, "model_verdict")
        print(f"\nDla porównania -- werdykt podany przez model 14B wprost: {raw_exact:.0f}%")
        print("(wersja wyliczana z progów jest tym, co pokazuje dashboard)")

    print_confusion(pairs)

    misses = [p for p in pairs if p["predicted"] != p["expected"]]
    if misses:
        print(f"\nRozbieżności ({len(misses)}):")
        for p in sorted(misses, key=lambda x: -x["score"]):
            print(f"  [{p['score']}%] {p['title'][:52]}")
            print(f"      ocena: {p['predicted']}  |  oczekiwane: {p['expected']}")
            print(f"      dlaczego: {p['reason']}")

    if args.sweep:
        sweep(pairs)


if __name__ == "__main__":
    main()
