import httpx

from notifier import telegram
from pipeline.duplicates import JobGroup
from tests.conftest import make_job


def _group(**kwargs) -> JobGroup:
    return JobGroup([make_job(**kwargs)])


def test_format_message_with_no_jobs():
    assert telegram.format_message([], []) == ["No new QA jobs today."]


def test_format_message_english_only_section():
    job = _group(title="QA Engineer", company="Acme")
    chunks = telegram.format_message(german_jobs=[], english_jobs=[job])
    assert len(chunks) == 1
    assert "🇬🇧 English-speaking (1)" in chunks[0]
    assert "🇩🇪" not in chunks[0]
    assert "QA Engineer — Acme" in chunks[0]


def test_format_message_orders_english_before_german():
    en_job = _group(url="https://example.test/en")
    de_job = _group(url="https://example.test/de")
    chunks = telegram.format_message(german_jobs=[de_job], english_jobs=[en_job])
    assert len(chunks) == 1
    assert chunks[0].index("English-speaking") < chunks[0].index("German-speaking")


def test_format_message_splits_into_multiple_chunks_under_the_length_limit():
    many_jobs = [_group(url=f"https://example.test/{i}", title="Q" * 200) for i in range(60)]
    chunks = telegram.format_message(german_jobs=[], english_jobs=many_jobs)
    assert len(chunks) > 1
    assert all(len(chunk) <= telegram.TELEGRAM_MAX_MESSAGE_LENGTH for chunk in chunks)


def test_send_message_posts_to_bot_token_url_with_expected_payload(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))

        class FakeResponse:
            def json(self):
                return {"ok": True}

        return FakeResponse()

    monkeypatch.setattr(telegram, "post_with_retry", fake_post)

    telegram.send_message("hello", bot_token="TOKEN123", chat_id="42")

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://api.telegram.org/botTOKEN123/sendMessage"
    assert kwargs["data"] == {"chat_id": "42", "text": "hello", "disable_web_page_preview": True}


def test_send_report_sends_one_message_per_chunk(monkeypatch):
    sent_texts = []

    def fake_post(url, **kwargs):
        sent_texts.append(kwargs["data"]["text"])

        class FakeResponse:
            def json(self):
                return {"ok": True}

        return FakeResponse()

    monkeypatch.setattr(telegram, "post_with_retry", fake_post)

    many_jobs = [_group(url=f"https://example.test/{i}", title="Q" * 200) for i in range(60)]
    telegram.send_report(german_jobs=[], english_jobs=many_jobs, bot_token="TOKEN", chat_id="1")

    expected_chunks = telegram.format_message(german_jobs=[], english_jobs=many_jobs)
    assert sent_texts == expected_chunks


def test_send_report_stops_and_returns_only_delivered_jobs_on_chunk_failure(monkeypatch):
    sent_texts = []
    call_count = 0

    def fake_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise httpx.HTTPError("boom")
        sent_texts.append(kwargs["data"]["text"])

        class FakeResponse:
            def json(self):
                return {"ok": True}

        return FakeResponse()

    monkeypatch.setattr(telegram, "post_with_retry", fake_post)

    many_jobs = [_group(url=f"https://example.test/{i}", title="Q" * 200) for i in range(60)]
    expected_chunks = telegram.format_message(german_jobs=[], english_jobs=many_jobs)
    assert len(expected_chunks) > 1  # the failure must land on a real 2nd chunk for this to mean anything

    sent_jobs = telegram.send_report(german_jobs=[], english_jobs=many_jobs, bot_token="TOKEN", chat_id="1")

    assert len(sent_texts) == 1
    assert sent_jobs
    assert sent_jobs != many_jobs
    assert all(job in many_jobs for job in sent_jobs)


def test_format_message_shows_one_entry_per_job_with_other_boards_and_all_cities():
    group = JobGroup([
        make_job(source_id="xing_jobs", title="Test Automation Engineer (m/w/d)", company="imbus AG",
                 url="https://www.xing.com/jobs/1?utm_source=x", location="München"),
        make_job(source_id="devjobs_germany_qa_engineer", title="Test Automation Engineer - m/f/d",
                 company="imbus", url="https://en.devjobs.de/job/2", location="Erlangen",
                 description="Longest description wins the main link."),
    ])
    text = telegram.format_message(german_jobs=[], english_jobs=[group])[0]
    assert "🇬🇧 English-speaking (1)" in text
    assert "(Erlangen, München)" in text or "(München, Erlangen)" in text
    assert "https://en.devjobs.de/job/2" in text
    assert "also on: xing.com" in text
    assert "xing.com/jobs/1" not in text  # other boards are named, not linked


def test_format_message_has_no_also_on_line_for_a_single_listing():
    text = telegram.format_message(german_jobs=[], english_jobs=[_group(title="QA Engineer")])[0]
    assert "also on" not in text
