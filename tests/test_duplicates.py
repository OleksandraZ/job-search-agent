from pipeline.duplicates import JobGroup, duplicate_key, group_duplicates
from tests.conftest import make_job


def test_duplicate_key_ignores_gender_markers_legal_forms_and_casing():
    a = make_job(title="Test Automation Engineer (m/w/d)", company="imbus AG")
    b = make_job(title="Test Automation Engineer - m/f/d", company="Imbus Ag")
    c = make_job(title="Testingenieur - Software / Hardware (m/w/d)", company="FERCHAU GmbH Niederlassung")
    d = make_job(title="Testingenieur - Software / Hardware (m/w/d)", company="FERCHAU – Connecting People")
    assert duplicate_key(a) == duplicate_key(b)
    assert duplicate_key(c) == duplicate_key(d)
    assert duplicate_key(a) != duplicate_key(make_job(title="QA Engineer", company="imbus AG"))


def test_group_duplicates_keeps_first_seen_order():
    first = make_job(title="QA Engineer", company="Alpha", url="https://example.test/1")
    other = make_job(title="Test Engineer", company="Beta", url="https://example.test/2")
    repost = make_job(title="QA Engineer (m/w/d)", company="Alpha GmbH", url="https://example.test/3")
    groups = group_duplicates([first, other, repost])
    assert [g.copies for g in groups] == [[first, repost], [other]]


def test_main_prefers_the_company_career_page_over_boards():
    board = make_job(source_id="stepstone_germany", url="https://www.stepstone.de/job/1",
                     description="A much longer board description " * 10)
    company = make_job(source_id="greenhouse:acme", url="https://boards.greenhouse.io/acme/1",
                       description="Short.")
    group = JobGroup([board, company])
    assert group.main is company
    assert group.best_described is board  # language still comes from the fullest text


def test_main_falls_back_to_the_most_completely_described_board_copy():
    empty = make_job(source_id="xing_jobs", url="https://www.xing.com/jobs/1", description="")
    full = make_job(source_id="devjobs_germany_qa_engineer", url="https://en.devjobs.de/job/2",
                    description="Text.")
    assert JobGroup([empty, full]).main is full


def test_locations_are_unique():
    cities = ["München", "Berlin", "München"]
    group = JobGroup([make_job(location=c, url=f"https://example.test/{i}") for i, c in enumerate(cities)])
    assert group.locations == "München, Berlin"


def test_long_location_lists_are_cut_at_a_comma():
    # Real StepStone listing: one location field with ~20 cities.
    many = "Berlin, Frankfurt am Main, Mannheim, Düsseldorf, Kassel, Hessen, Hamburg, München, Stuttgart"
    text = JobGroup([make_job(location=many)]).locations
    assert text.endswith(", …")
    assert len(text) <= 64
    assert text.startswith("Berlin, Frankfurt am Main")


def test_other_hosts_name_the_other_sites_without_the_main_one():
    main = make_job(source_id="greenhouse:acme", url="https://boards.greenhouse.io/acme/1")
    group = JobGroup([
        main,
        make_job(source_id="xing_jobs", url="https://www.xing.com/jobs/1?utm_source=x"),
        make_job(source_id="xing_jobs", url="https://www.xing.com/jobs/2"),
        make_job(source_id="devjobs_germany_qa_engineer", url="https://en.devjobs.de/job/3"),
        make_job(source_id="greenhouse:acme", url="https://boards.greenhouse.io/acme/2"),
    ])
    assert group.other_hosts == ["xing.com", "devjobs.de"]
