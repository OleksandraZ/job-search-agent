from adapters.boards import wearedevelopers
from tests.conftest import fake_response

JOBS_MD = """
## QA Engineer
- **Company:** Acme GmbH
- **Location:** Berlin, Germany
- [View job](https://www.wearedevelopers.com/jobs/qa-engineer-1)

## Backend Developer
- **Company:** Other GmbH
- **Location:** Munich, Germany
- [View job](https://www.wearedevelopers.com/jobs/backend-2)
"""

DETAIL_MD = """
## QA Engineer
About the role: full description text goes here.
"""


def test_parses_jobs_md_headings_into_normalized_jobs(monkeypatch):
    monkeypatch.setattr(wearedevelopers, "get_with_retry", lambda *a, **k: fake_response(text=JOBS_MD))

    jobs = wearedevelopers.fetch_jobs({"id": "wearedevelopers_jobs", "search_terms": ["backend developer"]})

    titles = {job.title: job for job in jobs}
    assert titles["QA Engineer"].company == "Acme GmbH"
    assert titles["QA Engineer"].location == "Berlin, Germany"
    assert titles["QA Engineer"].url == "https://www.wearedevelopers.com/jobs/qa-engineer-1"


def test_fills_description_only_for_title_matched_jobs(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        if url.endswith(".md") and "jobs.md" not in url:
            calls.append(url)
            return fake_response(text=DETAIL_MD)
        return fake_response(text=JOBS_MD)

    monkeypatch.setattr(wearedevelopers, "get_with_retry", fake_get)
    monkeypatch.setattr(wearedevelopers.time, "sleep", lambda *_: None)

    jobs = wearedevelopers.fetch_jobs({"id": "wearedevelopers_jobs", "search_terms": ["qa engineer"]})

    assert calls == ["https://www.wearedevelopers.com/jobs/qa-engineer-1.md"]
    matched = next(job for job in jobs if job.title == "QA Engineer")
    assert "full description text" in matched.description
