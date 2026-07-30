"""Level targeting is inferred from the CV, never hardcoded -- a different CV
must produce a different target. These tests pin that behaviour, plus the
tier-widening rule that prevents the shortlist from collapsing to a handful
of internships when more junior roles are available.
"""

from job_agent.common.models import (
    CVProfileStructured,
    Contact,
    Education,
    Experience,
    JobPosting,
)
from job_agent.matching.level_inference import (
    filter_by_level_tiers,
    infer_target_level_tiers,
)


def cv(*, education: list[Education] | None = None, experience: list[Experience] | None = None):
    return CVProfileStructured(
        contact=Contact(name="Test", location="Warszawa, Polska"),
        education=education or [],
        experience=experience or [],
    )


def job(level: str) -> JobPosting:
    return JobPosting(
        source="test", external_id="1", title="T", company="C",
        url="https://example.com", experience_level=level,
    )


class TestStudentWithoutCommercialExperience:
    """Should target internships first: "junior" postings routinely expect
    production skills a student without a job has no way to have."""

    def setup_method(self):
        self.profile = cv(
            education=[Education(institution="SGH", end_date="obecnie")],
            experience=[
                Experience(position="Self-directed AI projects", description="własne projekty"),
            ],
        )

    def test_intern_is_the_first_tier(self):
        tiers, _ = infer_target_level_tiers(self.profile)
        assert tiers[0] == ["intern"]

    def test_reason_mentions_internships(self):
        _, reason = infer_target_level_tiers(self.profile)
        assert "staż" in reason.lower()

    def test_junior_is_available_as_fallback(self):
        tiers, _ = infer_target_level_tiers(self.profile)
        assert "junior" in tiers[-1]


class TestExperiencedCandidate:
    def test_several_commercial_roles_target_mid_senior(self):
        profile = cv(
            experience=[
                Experience(position="Data Engineer", company="A", description="produkcja"),
                Experience(position="ML Engineer", company="B", description="modele"),
                Experience(position="Analityk", company="C", description="raporty"),
                Experience(position="Backend Developer", company="D", description="API"),
            ]
        )
        tiers, _ = infer_target_level_tiers(profile)
        assert tiers[0] == ["mid", "senior"]

    def test_graduate_with_no_experience_still_gets_intern_tier(self):
        profile = cv(education=[Education(institution="SGH", end_date="07.2025")])
        tiers, _ = infer_target_level_tiers(profile)
        assert "intern" in tiers[0]


class TestTierWidening:
    TIERS = [["intern"], ["intern", "junior"]]

    def test_uses_first_tier_when_it_has_enough(self):
        jobs = [job("intern")] * 5 + [job("junior")] * 5
        filtered, levels, widened = filter_by_level_tiers(jobs, self.TIERS, min_results=3)
        assert levels == ["intern"]
        assert len(filtered) == 5
        assert not widened

    def test_widens_when_first_tier_is_too_thin(self):
        jobs = [job("intern")] * 2 + [job("junior")] * 6
        filtered, levels, widened = filter_by_level_tiers(jobs, self.TIERS, min_results=5)
        assert levels == ["intern", "junior"]
        assert len(filtered) == 8
        assert widened

    def test_falls_back_to_broadest_tier_when_nothing_qualifies(self):
        jobs = [job("intern")]
        filtered, levels, _ = filter_by_level_tiers(jobs, self.TIERS, min_results=99)
        assert levels == ["intern", "junior"]
        assert len(filtered) == 1

    def test_excludes_levels_outside_the_tier(self):
        jobs = [job("intern"), job("senior"), job("manager")]
        filtered, _, _ = filter_by_level_tiers(jobs, self.TIERS, min_results=1)
        assert [j.experience_level for j in filtered] == ["intern"]
