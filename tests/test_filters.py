from pipeline.filters import filter_by_title
from tests.conftest import make_job


def test_filter_by_title_matches_case_insensitively():
    job = make_job(title="Senior QA Engineer")
    assert filter_by_title([job], ["qa engineer"]) == [job]


def test_filter_by_title_matches_any_of_multiple_terms():
    job = make_job(title="Test Automation Engineer")
    assert filter_by_title([job], ["qa engineer", "test automation"]) == [job]


def test_filter_by_title_excludes_non_matching_jobs():
    job = make_job(title="Backend Developer")
    assert filter_by_title([job], ["qa engineer"]) == []


def test_filter_by_title_with_no_terms_matches_nothing():
    job = make_job(title="QA Engineer")
    assert filter_by_title([job], []) == []
