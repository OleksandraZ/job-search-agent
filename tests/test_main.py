import pytest

import main
from tests.conftest import make_job


def _patch_pipeline(monkeypatch, *, matched_jobs, calls):
    """Stub out fetch/filter_jobs/dedupe/telegram so main.main() only exercises its
    own orchestration logic, not any real source's adapter or a real DB/network call.
    """
    monkeypatch.setattr(main, "fetch_from_sources", lambda *a, **k: matched_jobs)
    monkeypatch.setattr(main.munich_local, "filter_jobs", lambda jobs: jobs)
    monkeypatch.setattr(main.germany_remote, "filter_jobs", lambda jobs: [])
    monkeypatch.setattr(main.filters, "filter_by_title", lambda jobs, terms: jobs)
    monkeypatch.setattr(main.dedupe, "filter_unseen", lambda jobs: jobs)
    monkeypatch.setattr(main.classify_language, "split_by_language", lambda jobs: ([], jobs))

    def fake_mark_seen(jobs):
        calls.append(("mark_seen", jobs))

    def fake_send_report(german_jobs, english_jobs, bot_token, chat_id):
        calls.append(("send_report", german_jobs, english_jobs))

    monkeypatch.setattr(main.dedupe, "mark_seen", fake_mark_seen)
    monkeypatch.setattr(main.telegram, "send_report", fake_send_report)
    monkeypatch.setattr(main, "load_yaml", lambda name: {"sources": [], "title_match_terms": []})


def test_dry_run_prints_and_never_sends_or_marks_seen(monkeypatch, capsys):
    job = make_job()
    calls: list = []
    _patch_pipeline(monkeypatch, matched_jobs=[job], calls=calls)

    main.main(dry_run=True)

    assert calls == []
    printed = capsys.readouterr().out
    assert "No new QA jobs today." not in printed
    assert job.title in printed


def test_real_run_marks_seen_only_after_send_succeeds(monkeypatch):
    job = make_job()
    calls: list = []
    _patch_pipeline(monkeypatch, matched_jobs=[job], calls=calls)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    main.main(dry_run=False)

    assert [name for name, *_ in calls] == ["send_report", "mark_seen"]
    assert calls[1][1] == [job]


def test_job_matching_both_scopes_is_deduped_by_url_before_matching(monkeypatch):
    shared_url = "https://example.test/both"
    job = make_job(url=shared_url)
    calls: list = []

    monkeypatch.setattr(main, "fetch_from_sources", lambda *a, **k: [job])
    monkeypatch.setattr(main.munich_local, "filter_jobs", lambda jobs: jobs)
    monkeypatch.setattr(main.germany_remote, "filter_jobs", lambda jobs: jobs)

    seen_by_filter_by_title = []

    def fake_filter_by_title(jobs, terms):
        seen_by_filter_by_title.append(jobs)
        return jobs

    monkeypatch.setattr(main.filters, "filter_by_title", fake_filter_by_title)
    monkeypatch.setattr(main.dedupe, "filter_unseen", lambda jobs: jobs)
    monkeypatch.setattr(main.classify_language, "split_by_language", lambda jobs: ([], jobs))
    monkeypatch.setattr(main.dedupe, "mark_seen", lambda jobs: calls.append(("mark_seen", jobs)))
    monkeypatch.setattr(
        main.telegram,
        "send_report",
        lambda german_jobs, english_jobs, bot_token, chat_id: calls.append("send_report"),
    )
    monkeypatch.setattr(main, "load_yaml", lambda name: {"sources": [], "title_match_terms": []})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    main.main(dry_run=False)

    assert len(seen_by_filter_by_title[0]) == 1


def test_missing_telegram_env_vars_raises(monkeypatch):
    job = make_job()
    calls: list = []
    _patch_pipeline(monkeypatch, matched_jobs=[job], calls=calls)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(KeyError):
        main.main(dry_run=False)
