import httpx

from adapters.boards import arbeitnow_api
from tests.conftest import fake_response

SEARCH_FRAGMENT = """
<div data-link="https://www.arbeitnow.com/jobs/qa-engineer-1">
  <h3 itemprop="title"><a>QA Engineer</a></h3>
  <a itemprop="hiringOrganization">Acme GmbH</a>
  <span class="text-gray-600">Berlin, Germany</span>
</div>
"""

DETAIL_HTML = '<div itemprop="description">We need someone with <b>strong</b> skills.</div>'


def test_parses_search_fragment_into_normalized_jobs(monkeypatch):
    monkeypatch.setattr(
        arbeitnow_api, "get_with_retry", lambda *a, **k: fake_response(json={"data": SEARCH_FRAGMENT})
    )

    jobs = arbeitnow_api.fetch_jobs({"id": "arbeitnow_qa_jobs", "search_terms": ["qa engineer"]})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "QA Engineer"
    assert job.company == "Acme GmbH"
    assert job.url == "https://www.arbeitnow.com/jobs/qa-engineer-1"
    assert job.location == "Berlin, Germany"
    assert job.description == ""


def test_fills_description_only_for_title_matched_jobs(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        if "arbeitnow.com/api/jobs" in url:
            return fake_response(json={"data": SEARCH_FRAGMENT})
        calls.append(url)
        return fake_response(text=DETAIL_HTML)

    monkeypatch.setattr(arbeitnow_api, "get_with_retry", fake_get)
    monkeypatch.setattr(arbeitnow_api.time, "sleep", lambda *_: None)

    jobs = arbeitnow_api.fetch_jobs({"id": "arbeitnow_qa_jobs", "search_terms": ["qa engineer"]})

    assert calls == ["https://www.arbeitnow.com/jobs/qa-engineer-1"]
    assert "strong" in jobs[0].description


def test_no_description_fetch_when_title_does_not_match(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        if "arbeitnow.com/api/jobs" in url:
            return fake_response(json={"data": SEARCH_FRAGMENT})
        calls.append(url)
        return fake_response(text=DETAIL_HTML)

    monkeypatch.setattr(arbeitnow_api, "get_with_retry", fake_get)

    jobs = arbeitnow_api.fetch_jobs({"id": "arbeitnow_qa_jobs", "search_terms": ["backend developer"]})

    assert calls == []
    assert jobs[0].description == ""


def test_a_failed_search_term_does_not_drop_other_terms_results(monkeypatch):
    def fake_get(url, **kwargs):
        term = kwargs.get("params", {}).get("search")
        if term == "broken":
            raise httpx.HTTPError("boom")
        return fake_response(json={"data": SEARCH_FRAGMENT})

    monkeypatch.setattr(arbeitnow_api, "get_with_retry", fake_get)
    monkeypatch.setattr(arbeitnow_api.time, "sleep", lambda *_: None)

    jobs = arbeitnow_api.fetch_jobs({"id": "arbeitnow_qa_jobs", "search_terms": ["broken", "qa engineer"]})

    assert len(jobs) == 1
