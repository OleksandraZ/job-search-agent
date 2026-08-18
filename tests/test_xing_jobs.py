import json

from adapters.boards import xing_jobs
from tests.conftest import fake_response


def _search_page(job_id: str) -> str:
    return f"""
    <article data-testid="job-search-result">
      <a href="/jobs/{job_id}">
        <span data-testid="job-teaser-list-title">QA Engineer</span>
      </a>
      <p class="Company-abc123">Acme GmbH</p>
      <div class="multi-location-display-styles__Container-xyz">Bautzen , Görlitz + 3 weitere</div>
    </article>
    """


def _detail_page(country: str) -> str:
    ld_json = json.dumps(
        {
            "@type": "JobPosting",
            "jobLocation": [{"address": {"addressCountry": country}}],
        }
    )
    return f"""
    <div data-testid="expandable-content">Full <b>role</b> description.</div>
    <script type="application/ld+json">{ld_json}</script>
    """


def test_location_overflow_suffix_is_stripped(monkeypatch):
    search_page = _search_page("qa-engineer-1")
    monkeypatch.setattr(xing_jobs, "get_with_retry", lambda *a, **k: fake_response(text=search_page))

    jobs = xing_jobs.fetch_jobs({"id": "xing_jobs", "search_terms": ["backend developer"]})

    assert jobs[0].location == "Bautzen , Görlitz"


def test_non_germany_job_is_dropped_after_detail_page_fetch(monkeypatch):
    def fake_get(url, **kwargs):
        if url == "https://www.xing.com/jobs/search":
            return fake_response(text=_search_page("qa-engineer-1"))
        return fake_response(text=_detail_page("AT"))

    monkeypatch.setattr(xing_jobs, "get_with_retry", fake_get)
    monkeypatch.setattr(xing_jobs.time, "sleep", lambda *_: None)

    jobs = xing_jobs.fetch_jobs({"id": "xing_jobs", "search_terms": ["qa engineer"]})

    assert jobs == []


def test_germany_job_keeps_fetched_description(monkeypatch):
    def fake_get(url, **kwargs):
        if url == "https://www.xing.com/jobs/search":
            return fake_response(text=_search_page("qa-engineer-1"))
        return fake_response(text=_detail_page("DE"))

    monkeypatch.setattr(xing_jobs, "get_with_retry", fake_get)
    monkeypatch.setattr(xing_jobs.time, "sleep", lambda *_: None)

    jobs = xing_jobs.fetch_jobs({"id": "xing_jobs", "search_terms": ["qa engineer"]})

    assert len(jobs) == 1
    assert "Full" in jobs[0].description
