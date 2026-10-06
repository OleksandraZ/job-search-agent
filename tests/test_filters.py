from pipeline.filters import (
    exclude_by_description,
    exclude_by_required_years,
    filter_by_title,
    require_term_groups,
)
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


def test_filter_by_title_does_not_match_a_term_inside_an_unrelated_word():
    # "SDET" is a substring of "Emsdetten" (a real German city) - verified live via
    # stellenanzeigen.de, where a tax-clerk job in Emsdetten was matched and sent as
    # a "QA job" before word-boundary matching was added.
    job = make_job(title="Steuerfachangestellte/r (m/w/d) in Emsdetten")
    assert filter_by_title([job], ["SDET"]) == []


def test_require_term_groups_keeps_job_mentioning_term_in_description():
    job = make_job(title="Junior DevOps Engineer", description="You will work with Terraform and AWS.")
    assert require_term_groups([job], [["Terraform", "Kubernetes"]]) == [job]


def test_require_term_groups_keeps_job_mentioning_term_in_title():
    job = make_job(title="Junior Python Developer", description="Build our backend services.")
    assert require_term_groups([job], [["Python"]]) == [job]


def test_require_term_groups_drops_job_mentioning_no_term():
    job = make_job(title="Junior DevOps Engineer", description="Azure and Ansible only.")
    assert require_term_groups([job], [["AWS", "Terraform", "Kubernetes"]]) == []


def test_require_term_groups_needs_a_match_from_every_group():
    groups = [["Python", "SQL"], ["Airflow", "dbt", "Spark", "ETL"]]
    both = make_job(title="Data Engineer", url="https://example.test/1", description="SQL and dbt.")
    only_first = make_job(title="Data Engineer", url="https://example.test/2", description="SQL and Excel.")
    assert require_term_groups([both, only_first], groups) == [both]


def test_require_term_groups_keeps_job_with_empty_description():
    # Some sources never provide a description (e.g. Arbeitnow) - empty means
    # "unknown", so the job must not be silently dropped.
    job = make_job(title="Junior DevOps Engineer", description="  ")
    assert require_term_groups([job], [["AWS"]]) == [job]


def test_require_term_groups_uses_word_boundaries():
    job = make_job(title="Backend Developer", description="Experience with laws and regulations.")
    assert require_term_groups([job], [["AWS"]]) == []


def test_filter_by_title_matches_terms_ending_in_non_word_characters():
    # A plain \b...\b pattern can never match "C#"/"C++" (no word boundary after
    # "#"/"+"), so such a term silently matched nothing.
    job = make_job(title="Software Tester C# / C++ (m/w/d)")
    assert filter_by_title([job], ["C#"]) == [job]
    assert filter_by_title([job], ["C++"]) == [job]


def test_filter_by_title_non_word_ending_term_still_respects_boundaries():
    job = make_job(title="QA Engineer C#Script")
    assert filter_by_title([job], ["C#"]) == []


def test_exclude_by_description_drops_job_mentioning_a_term():
    job = make_job(title="QA Engineer", description="Testing of our SAP S/4HANA landscape.")
    assert exclude_by_description([job], ["SAP"]) == []


def test_exclude_by_description_keeps_job_mentioning_no_term():
    job = make_job(title="QA Engineer", description="Playwright and Python, REST APIs.")
    assert exclude_by_description([job], ["SAP", "Embedded"]) == [job]


def test_exclude_by_description_uses_word_boundaries():
    job = make_job(title="QA Engineer", description="We test our sapphire-themed app.")
    assert exclude_by_description([job], ["SAP"]) == [job]


SELENIUM_RULE = {"terms": ["Selenium", "Cypress"], "unless": ["Playwright", "Python"]}


def test_exclude_by_description_conditional_rule_drops_job_without_unless_term():
    job = make_job(title="QA Engineer", description="Selenium WebDriver with Java, API testing.")
    assert exclude_by_description([job], [SELENIUM_RULE]) == []


def test_exclude_by_description_conditional_rule_keeps_job_with_unless_term():
    job = make_job(title="QA Engineer", description="Playwright preferred, Cypress also fine.")
    assert exclude_by_description([job], [SELENIUM_RULE]) == [job]


def test_exclude_by_description_conditional_rule_checks_title_for_unless_term():
    job = make_job(title="Python QA Engineer", description="Our suite uses Selenium.")
    assert exclude_by_description([job], [SELENIUM_RULE]) == [job]


def test_exclude_by_description_conditional_rule_ignores_job_without_term():
    job = make_job(title="QA Engineer", description="API testing with Postman.")
    assert exclude_by_description([job], [SELENIUM_RULE]) == [job]


def test_exclude_by_description_plain_term_also_checks_title():
    job = make_job(title="Robotics Test Engineer", description="")
    assert exclude_by_description([job], ["Robotics"]) == []


def test_exclude_by_required_years_drops_only_jobs_asking_for_more():
    three = make_job(url="https://example.test/1", description="<li>3+ years of Python experience</li>")
    five = make_job(url="https://example.test/2", description="<li>5+ years of Python experience</li>")
    unstated = make_job(url="https://example.test/3", description="Mehrjährige Erfahrung mit Python.")
    empty = make_job(url="https://example.test/4", description="")
    assert exclude_by_required_years([three, five, unstated, empty], 3) == [three, unstated, empty]
