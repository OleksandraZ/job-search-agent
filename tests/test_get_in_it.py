import json

import http_client
from adapters.boards import get_in_it
from tests.conftest import fake_response


def _next_data_html(jobs):
    payload = {"props": {"initialState": {"jobSearchJobs": {"jobs": jobs}}}}
    return f'<html><script id="__NEXT_DATA__">{json.dumps(payload)}</script></html>'


def _detail_html(content: str):
    payload = {"props": {"initialState": {"jobJob": {"job": {"content": content}}}}}
    return f'<html><script id="__NEXT_DATA__">{json.dumps(payload)}</script></html>'


SEARCH_HTML = _next_data_html(
    [
        {
            "title": "QA Engineer",
            "company": {"title": "Acme GmbH"},
            "url": "/jobs/qa-engineer-1",
            "locations": [{"name": "Berlin"}, {"name": "Munich"}],
        }
    ]
)


def test_parses_next_data_search_state(monkeypatch):
    monkeypatch.setattr(get_in_it, "get_with_retry", lambda *a, **k: fake_response(text=SEARCH_HTML))

    jobs = get_in_it.fetch_jobs({"id": "get_in_it", "search_terms": ["backend developer"]})

    assert jobs[0].title == "QA Engineer"
    assert jobs[0].company == "Acme GmbH"
    assert jobs[0].url == "https://www.get-in-it.de/jobs/qa-engineer-1"
    assert jobs[0].location == "Berlin, Munich"


def test_missing_next_data_script_returns_no_jobs(monkeypatch):
    monkeypatch.setattr(
        get_in_it, "get_with_retry", lambda *a, **k: fake_response(text="<html><body>oops</body></html>")
    )

    jobs = get_in_it.fetch_jobs({"id": "get_in_it", "search_terms": []})

    assert jobs == []


def test_malformed_job_entries_are_skipped_not_crashed(monkeypatch):
    html = _next_data_html(
        [
            {
                "title": "QA Engineer",
                "company": {"title": "Acme GmbH"},
                "url": "/jobs/qa-engineer-1",
                "locations": [{"name": "Berlin"}],
            },
            {
                "title": "Null Company Posting",
                "company": None,
                "url": "/jobs/null-company-2",
                "locations": [],
            },
            {
                "title": "Missing URL Posting",
                "company": {"title": "Ghost GmbH"},
                "locations": [],
            },
        ]
    )
    monkeypatch.setattr(get_in_it, "get_with_retry", lambda *a, **k: fake_response(text=html))

    jobs = get_in_it.fetch_jobs({"id": "get_in_it", "search_terms": []})

    urls = [job.url for job in jobs]
    assert urls == [
        "https://www.get-in-it.de/jobs/qa-engineer-1",
        "https://www.get-in-it.de/jobs/null-company-2",
    ]
    null_company_job = next(job for job in jobs if job.title == "Null Company Posting")
    assert null_company_job.company == ""


def test_fills_description_for_title_matched_jobs(monkeypatch):
    def fake_get(url, **kwargs):
        if url == "https://www.get-in-it.de/jobsuche":
            return fake_response(text=SEARCH_HTML)
        return fake_response(text=_detail_html("Full role description."))

    monkeypatch.setattr(get_in_it, "get_with_retry", fake_get)
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    jobs = get_in_it.fetch_jobs({"id": "get_in_it", "search_terms": ["qa engineer"]})

    assert "Full role" in jobs[0].description
