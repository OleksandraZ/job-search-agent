import pytest

import main
from tests.conftest import make_job


def test_build_report_filters_dedupes_and_classifies(tmp_path):
    munich_job = make_job(
        title="QA Engineer",
        url="https://example.test/1",
        location="München",
        description="We need an English-speaking QA engineer.",
    )
    other_job = make_job(title="Sales Manager", url="https://example.test/2", location="München")

    german_jobs, english_jobs = main.build_report(
        [munich_job, other_job], {"title_match_terms": ["QA Engineer"]}, db_path=tmp_path / "jobs.db"
    )

    assert german_jobs == []
    assert english_jobs == [munich_job]


def test_build_report_excludes_previously_seen_jobs(tmp_path):
    db_path = tmp_path / "jobs.db"
    job = make_job(title="QA Engineer", location="München", description="English required.")
    main.dedupe.mark_seen([job], db_path=db_path)

    german_jobs, english_jobs = main.build_report(
        [job], {"title_match_terms": ["QA Engineer"]}, db_path=db_path
    )

    assert german_jobs == []
    assert english_jobs == []


def test_build_report_dedupes_job_matching_both_scopes_by_url(tmp_path):
    # A job that's both Munich-based AND remote-eligible must be reported once, not twice.
    job = make_job(
        title="QA Engineer",
        url="https://example.test/both",
        location="München, Germany (Remote available)",
        description="English required.",
    )

    german_jobs, english_jobs = main.build_report(
        [job], {"title_match_terms": ["QA Engineer"]}, db_path=tmp_path / "jobs.db"
    )

    assert english_jobs == [job]


def _patch_orchestration(monkeypatch, *, german_jobs, english_jobs, calls):
    """Stub out only main()'s true I/O seams - config loading, the pure build_report
    computation (covered separately above), sending, and marking-seen.
    """
    def fake_load_yaml(name):
        if name == "companies.yaml":
            return {"companies": []}
        return {"sources": [], "title_match_terms": []}

    monkeypatch.setattr(main, "load_yaml", fake_load_yaml)
    monkeypatch.setattr(main, "resolve_pending", lambda: [])
    monkeypatch.setattr(
        main, "build_report", lambda raw_jobs, keywords_config, db_path: (german_jobs, english_jobs)
    )

    def fake_mark_seen(jobs, db_path):
        calls.append(("mark_seen", jobs))

    def fake_send_report(german_jobs, english_jobs, bot_token, chat_id):
        calls.append(("send_report", german_jobs, english_jobs))
        return german_jobs + english_jobs

    monkeypatch.setattr(main.dedupe, "mark_seen", fake_mark_seen)
    monkeypatch.setattr(main.telegram, "send_report", fake_send_report)


def test_dry_run_prints_and_never_sends_or_marks_seen(monkeypatch, capsys):
    job = make_job()
    calls: list = []
    _patch_orchestration(monkeypatch, german_jobs=[], english_jobs=[job], calls=calls)

    main.main(dry_run=True)

    assert calls == []
    printed = capsys.readouterr().out
    assert "No new QA jobs today." not in printed
    assert job.title in printed


def test_real_run_marks_seen_only_with_what_send_report_returns(monkeypatch):
    job = make_job()
    calls: list = []
    _patch_orchestration(monkeypatch, german_jobs=[], english_jobs=[job], calls=calls)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    main.main(dry_run=False)

    assert [name for name, *_ in calls] == ["send_report", "mark_seen"]
    assert calls[1][1] == [job]


def test_missing_telegram_env_vars_raises(monkeypatch):
    job = make_job()
    calls: list = []
    _patch_orchestration(monkeypatch, german_jobs=[], english_jobs=[job], calls=calls)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(KeyError):
        main.main(dry_run=False)
