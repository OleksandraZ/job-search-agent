from adapters.boards import stepstone
from tests.conftest import fake_response

SEARCH_PAGE = """
<div data-testid="job-item">
  <a data-testid="job-item-title" href="/stellenangebote--QA-Engineer--1.html">QA Engineer</a>
  <span data-at="job-item-company-name">Acme GmbH</span>
  <span data-at="job-item-location">Munich</span>
  <div data-at="jobcard-content">Short snippet...</div>
</div>
"""

DETAIL_PAGE = '<div data-at="job-ad-content">Full <b>job</b> description.</div>'


def test_parses_search_page_into_normalized_jobs(monkeypatch):
    monkeypatch.setattr(stepstone, "get_with_retry", lambda *a, **k: fake_response(text=SEARCH_PAGE))

    jobs = stepstone.fetch_jobs({"id": "stepstone_germany", "search_terms": ["backend developer"]})

    assert jobs[0].title == "QA Engineer"
    assert jobs[0].company == "Acme GmbH"
    assert jobs[0].url == "https://www.stepstone.de/stellenangebote--QA-Engineer--1.html"
    assert jobs[0].location == "Munich"


def test_detail_page_fetch_sends_a_referer_header(monkeypatch):
    seen_headers = {}

    def fake_get(url, **kwargs):
        if url.startswith("https://www.stepstone.de/jobs/"):
            return fake_response(text=SEARCH_PAGE)
        seen_headers.update(kwargs.get("headers") or {})
        return fake_response(text=DETAIL_PAGE)

    monkeypatch.setattr(stepstone, "get_with_retry", fake_get)
    monkeypatch.setattr(stepstone.time, "sleep", lambda *_: None)

    jobs = stepstone.fetch_jobs({"id": "stepstone_germany", "search_terms": ["qa engineer"]})

    assert seen_headers.get("Referer") == "https://www.stepstone.de/jobs/qa-engineer"
    assert "Full" in jobs[0].description
