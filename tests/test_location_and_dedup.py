"""Location filtering and cross-board deduplication.

Both exist because of concrete failures: the shortlist once surfaced only
office jobs in other cities, and pracuj.pl's boosted "superoferty" listed the
same posting twice under different offer IDs.
"""

from job_agent.common.models import CVProfileStructured, Contact, JobPosting
from job_agent.job_scraping.dedup import dedupe_postings
from job_agent.matching.location import extract_candidate_city, is_location_compatible


def job(title="T", company="ACME", city=None, workplace_type=None, external_id="1"):
    return JobPosting(
        source="test", external_id=external_id, title=title, company=company,
        url="https://example.com", city=city, workplace_type=workplace_type,
    )


class TestCandidateCity:
    def test_takes_city_before_the_comma(self):
        profile = CVProfileStructured(contact=Contact(location="Warszawa, Polska"))
        assert extract_candidate_city(profile) == "Warszawa"

    def test_missing_location_is_none(self):
        assert extract_candidate_city(CVProfileStructured(contact=Contact())) is None


class TestLocationCompatibility:
    def test_remote_is_always_kept(self):
        """Distance is irrelevant for remote work -- filtering it out was the
        original bug that hid good offers."""
        assert is_location_compatible("Warszawa", job(city="Gdańsk", workplace_type="remote"))

    def test_same_city_hybrid_is_kept(self):
        assert is_location_compatible("Warszawa", job(city="Warszawa", workplace_type="hybrid"))

    def test_district_suffix_still_matches(self):
        assert is_location_compatible("Warszawa", job(city="Warszawa, Wola", workplace_type="office"))

    def test_other_city_office_is_rejected(self):
        assert not is_location_compatible("Warszawa", job(city="Kraków", workplace_type="office"))

    def test_case_insensitive(self):
        assert is_location_compatible("warszawa", job(city="WARSZAWA", workplace_type="office"))

    def test_unknown_data_is_not_filtered_blindly(self):
        assert is_location_compatible(None, job(city="Kraków", workplace_type="office"))
        assert is_location_compatible("Warszawa", job(city=None, workplace_type="office"))


class TestDedup:
    def test_removes_same_title_and_company(self):
        jobs = [
            job(title="AI Intern", company="Polpharma", external_id="1"),
            job(title="AI Intern", company="Polpharma", external_id="2"),
        ]
        assert len(dedupe_postings(jobs)) == 1

    def test_keeps_first_occurrence(self):
        jobs = [
            job(title="AI Intern", company="Polpharma", external_id="first"),
            job(title="AI Intern", company="Polpharma", external_id="second"),
        ]
        assert dedupe_postings(jobs)[0].external_id == "first"

    def test_same_title_different_company_is_kept(self):
        jobs = [
            job(title="AI Intern", company="Polpharma"),
            job(title="AI Intern", company="Samsung"),
        ]
        assert len(dedupe_postings(jobs)) == 2

    def test_ignores_case_and_whitespace(self):
        jobs = [job(title="AI Intern", company="ACME"), job(title="  ai intern ", company="acme")]
        assert len(dedupe_postings(jobs)) == 1

    def test_empty_input(self):
        assert dedupe_postings([]) == []
