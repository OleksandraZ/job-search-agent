import datetime

from tests.conftest import make_job
from tools.market_report import (
    build_workbook,
    drop_disabled_boards,
    duplicate_key,
    load_raw_jobs,
    save_raw_jobs,
    sheet_title,
    union_search_terms,
)


def test_union_search_terms_dedupes_case_insensitively_in_first_seen_order():
    configs = [{"title_match_terms": ["QA Engineer", "Python"]}, {"title_match_terms": ["python", "DevOps"]}]
    assert union_search_terms(configs) == ["QA Engineer", "Python", "DevOps"]


def test_sheet_title_strips_characters_excel_rejects():
    assert sheet_title("Junior Cloud/DevOps") == "Junior Cloud-DevOps"


def test_build_workbook_writes_one_sheet_per_search_and_summary_counts():
    munich = make_job(title="QA Engineer", company="Alpha GmbH", url="https://example.test/1",
                      location="München", description="English team.")
    remote = make_job(title="QA Engineer", company="Beta AG", url="https://example.test/2",
                      location="Remote, Germany", description="English team.")

    wb = build_workbook([("QA", [munich, remote]), ("Junior Cloud/DevOps", [munich])],
                        datetime.date(2026, 10, 5))

    assert wb.sheetnames == ["Übersicht", "QA", "Junior Cloud-DevOps"]
    assert wb["QA"].max_row == 3  # header + 2 jobs
    assert wb["QA"]["G2"].hyperlink.target == "https://example.test/1"
    rows = {row[0]: row for row in wb["Übersicht"].iter_rows(values_only=True) if row and row[0]}
    assert rows["QA"][1:4] == (2, 1, 1)
    assert rows["Eindeutige Stellen über alle Suchprofile"][1] == 2


def test_raw_jobs_round_trip_through_json(tmp_path):
    job = make_job(title="QA Engineer", location="München", description="Playwright, Python – Umlaute äöü.")
    path = tmp_path / "raw.json"
    save_raw_jobs([job], path)
    assert load_raw_jobs(path) == [job]


def test_drop_disabled_boards_keeps_enabled_boards_and_company_jobs():
    sources = {"sources": [{"id": "stepstone_germany"}, {"id": "wearedevelopers_jobs"}]}
    enabled = make_job(source_id="stepstone_germany", url="https://example.test/1")
    disabled = make_job(source_id="wearedevelopers_jobs", url="https://example.test/2")
    company = make_job(source_id="greenhouse:helsing", url="https://example.test/3")
    assert drop_disabled_boards([enabled, disabled, company], sources) == [enabled, company]


def test_duplicate_key_ignores_gender_markers_legal_forms_and_casing():
    a = make_job(title="Test Automation Engineer (m/w/d)", company="imbus AG")
    b = make_job(title="Test Automation Engineer - m/f/d", company="Imbus Ag")
    c = make_job(title="Testingenieur - Software / Hardware (m/w/d)", company="FERCHAU GmbH Niederlassung")
    d = make_job(title="Testingenieur - Software / Hardware (m/w/d)", company="FERCHAU – Connecting People")
    assert duplicate_key(a) == duplicate_key(b)
    assert duplicate_key(c) == duplicate_key(d)
    assert duplicate_key(a) != duplicate_key(make_job(title="QA Engineer", company="imbus AG"))


def test_build_workbook_merges_the_same_job_from_several_boards():
    board_a = make_job(source_id="xing_jobs", title="Quality Engineer (m/w/d)", company="Blackwave GmbH",
                       url="https://example.test/1", location="Garching bei München", description="")
    board_b = make_job(source_id="stellenanzeigende", title="Quality Engineer (m/w/d)", company="Blackwave",
                       url="https://example.test/2", location="Taufkirchen, München",
                       description="English-speaking team.")

    wb = build_workbook([("QA", [board_a, board_b])], datetime.date(2026, 10, 6))

    assert wb["QA"].max_row == 2  # header + one merged row
    row = [cell.value for cell in wb["QA"][2]]
    assert row[5] == "xing_jobs, stellenanzeigende"
    assert row[6] == "https://example.test/2"  # the copy with a description
    summary = {r[0]: r for r in wb["Übersicht"].iter_rows(values_only=True) if r and r[0]}
    assert summary["QA"][1] == 1
    assert summary["Eindeutige Stellen über alle Suchprofile"][1] == 1
