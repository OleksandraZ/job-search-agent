from adapters.boards import devjobs
from tests.conftest import fake_response

PAGE_1 = """
<a href="/job/qa-engineer-1">
  <h2>QA Engineer</h2>
  <div class="ml-2"><p>Acme GmbH</p><span>Berlin</span></div>
  <p class="line-clamp-2">Short summary.</p>
</a>
"""

EMPTY_PAGE = "<html><body>no jobs here</body></html>"

DETAIL_PAGE = '<div class="md:-mt-2">Full <b>role</b> description.</div>'


def test_parses_listing_page_and_stops_pagination_on_empty_page(monkeypatch):
    pages_fetched = []

    def fake_get(url, **kwargs):
        page = kwargs.get("params", {}).get("page")
        pages_fetched.append((kwargs.get("params", {}).get("jobProfessions"), page))
        if page == 1:
            return fake_response(text=PAGE_1)
        return fake_response(text=EMPTY_PAGE)

    monkeypatch.setattr(devjobs, "get_with_retry", fake_get)
    monkeypatch.setattr(devjobs.time, "sleep", lambda *_: None)

    jobs = devjobs.fetch_jobs({"id": "devjobs_germany_qa_engineer", "search_terms": []})

    assert len(jobs) == 1
    assert jobs[0].title == "QA Engineer"
    assert jobs[0].company == "Acme GmbH"
    assert jobs[0].url == "https://en.devjobs.de/job/qa-engineer-1"
    assert jobs[0].location == "Berlin"
    # crawls both known-good professions, stopping each at its first empty page
    assert [p for p, _ in pages_fetched] == [
        "qa-engineer",
        "qa-engineer",
        "test-automation-engineer",
        "test-automation-engineer",
    ]


def test_fills_description_for_title_matched_jobs(monkeypatch):
    def fake_get(url, **kwargs):
        if "/jobs/search" in url:
            page = kwargs.get("params", {}).get("page")
            return fake_response(text=PAGE_1 if page == 1 else EMPTY_PAGE)
        return fake_response(text=DETAIL_PAGE)

    monkeypatch.setattr(devjobs, "get_with_retry", fake_get)
    monkeypatch.setattr(devjobs.time, "sleep", lambda *_: None)

    jobs = devjobs.fetch_jobs({"id": "devjobs_germany_qa_engineer", "search_terms": ["qa engineer"]})

    assert "Full" in jobs[0].description
