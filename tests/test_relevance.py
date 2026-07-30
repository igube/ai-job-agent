"""The relevance gate is what keeps keyword-searched boards (OLX, rocketjobs)
from flooding the pipeline with non-AI jobs. It earned these tests: an early
version passed a fashion-marketing internship that then scored 85% match,
purely because its body copy mentioned "automatyzacja".
"""

from job_agent.common.models import JobPosting
from job_agent.job_scraping.relevance import filter_ai_relevant, is_ai_relevant


def make_job(title: str, description: str = "", skills: list[str] | None = None) -> JobPosting:
    return JobPosting(
        source="test",
        external_id="1",
        title=title,
        company="ACME",
        url="https://example.com",
        description=description,
        skills=skills or [],
    )


class TestStrongTerms:
    def test_machine_learning_in_body_is_enough(self):
        job = make_job("Analityk", description="Praca z machine learning na produkcji.")
        assert is_ai_relevant(job)

    def test_llm_in_skills_is_enough(self):
        assert is_ai_relevant(make_job("Developer", skills=["Python", "LLM"]))

    def test_polish_phrase_counts(self):
        job = make_job("Specjalista", description="Wdrażamy sztuczną inteligencję w firmie.")
        assert is_ai_relevant(job)


class TestWeakTermsNeedTitle:
    def test_weak_term_in_title_counts(self):
        assert is_ai_relevant(make_job("AI Automation Intern"))

    def test_weak_term_only_in_body_is_rejected(self):
        """The regression case: marketing copy name-dropping automation."""
        job = make_job(
            "Młodszy Specjalista ds. Rozwoju Marki",
            description=(
                "Praca w branży fashion. Zajmiesz się analizą rynku, "
                "a także automatyzacją prostych zadań marketingowych."
            ),
        )
        assert not is_ai_relevant(job)

    def test_bare_ai_mention_in_body_is_rejected(self):
        job = make_job("Recepcjonistka", description="Biuro korzysta z narzędzi AI.")
        assert not is_ai_relevant(job)


class TestWordBoundaries:
    def test_email_does_not_match_ai(self):
        job = make_job("Asystent", description="Wyślij email na adres biura.")
        assert not is_ai_relevant(job)

    def test_html_does_not_match_ml(self):
        job = make_job("Frontend", description="Znajomość HTML i CSS.")
        assert not is_ai_relevant(job)


class TestFilter:
    def test_keeps_only_relevant(self):
        jobs = [
            make_job("AI Engineer"),
            make_job("Kierowca kat. C"),
            make_job("Data Scientist"),
        ]
        kept = filter_ai_relevant(jobs)
        assert [j.title for j in kept] == ["AI Engineer", "Data Scientist"]

    def test_empty_input(self):
        assert filter_ai_relevant([]) == []
