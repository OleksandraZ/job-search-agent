from adapters.boards import builtin
from tests.conftest import fake_response

LISTING_PAGE = """
<div class="job-bounded-responsive">
  <a data-id="job-card-title" href="/job/qa-engineer-1">QA Engineer</a>
  <span data-id="company-title"><span>Acme GmbH</span></span>
  <div class="d-flex"><i class="fa-location-dot"></i><span>Berlin, Germany</span></div>
  <div><i class="fa-house-building"></i></div><span>Remote</span>
</div>
"""

EMPTY_PAGE = "<html><body></body></html>"

DETAIL_PAGE = '<div class="job-post-item">Full role description.</div>'


def test_work_mode_is_folded_into_location_not_description(monkeypatch):
    def fake_get(url, **kwargs):
        page = kwargs.get("params", {}).get("page")
        return fake_response(text=LISTING_PAGE if page == 1 else EMPTY_PAGE)

    monkeypatch.setattr(builtin, "get_with_retry", fake_get)
    monkeypatch.setattr(builtin.time, "sleep", lambda *_: None)

    jobs = builtin.fetch_jobs({"id": "built_in_qa_germany", "search_terms": []})

    assert len(jobs) == 1
    assert jobs[0].title == "QA Engineer"
    assert jobs[0].company == "Acme GmbH"
    assert jobs[0].url == "https://builtin.com/job/qa-engineer-1"
    assert jobs[0].location == "Berlin, Germany Remote"
    assert jobs[0].description == ""


def test_fills_description_for_title_matched_jobs(monkeypatch):
    def fake_get(url, **kwargs):
        if "page" in kwargs.get("params", {}):
            page = kwargs["params"]["page"]
            return fake_response(text=LISTING_PAGE if page == 1 else EMPTY_PAGE)
        return fake_response(text=DETAIL_PAGE)

    monkeypatch.setattr(builtin, "get_with_retry", fake_get)
    monkeypatch.setattr(builtin.time, "sleep", lambda *_: None)

    jobs = builtin.fetch_jobs({"id": "built_in_qa_germany", "search_terms": ["qa engineer"]})

    assert "Full role" in jobs[0].description
