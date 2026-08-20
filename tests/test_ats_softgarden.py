from adapters.ats import softgarden_scrape
from tests.conftest import fake_response

LISTING_HTML = """
<a href="../job/111/Software-Engineer">Software Engineer (m/f/d)</a>
<a href="../job/222/Sales-Manager">Sales Manager</a>
<a href="/en/vacancies?-1.-navigationPanel">Jobs</a>
"""
DETAIL_HTML = "<html><body>Full job description text here.</body></html>"


def _fake_get(url, **kwargs):
    if "/job/111/" in url:
        return fake_response(text=DETAIL_HTML, request_url=url)
    # The root URL redirects to whichever locale the company has configured -
    # simulated here by returning the post-redirect URL regardless of locale, same
    # as httpx's follow_redirects=True would after a real 30x.
    return fake_response(text=LISTING_HTML, request_url="https://acme.softgarden.io/de/vacancies")


def test_parses_listing_and_fetches_description_only_for_title_matched_subset(monkeypatch):
    monkeypatch.setattr(softgarden_scrape, "get_with_retry", _fake_get)

    jobs = softgarden_scrape.fetch_jobs(
        {"identifier": "acme", "name": "Acme", "search_terms": ["Software Engineer"]}
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Software Engineer (m/f/d)"
    assert job.location == "Germany"
    assert "job/111" in job.url
    assert job.description == "Full job description text here."


def test_no_search_terms_keeps_every_listed_job(monkeypatch):
    monkeypatch.setattr(softgarden_scrape, "get_with_retry", _fake_get)

    jobs = softgarden_scrape.fetch_jobs({"identifier": "acme", "name": "Acme", "search_terms": []})

    assert len(jobs) == 2


def test_requests_the_bare_root_not_a_hardcoded_english_locale(monkeypatch):
    # Regression test: a company with no English locale configured 404s on a
    # hardcoded /en/vacancies path - verified live against Donner & Reuschel and
    # RTLZWEI, both German-locale-only. The adapter must request the bare root and
    # let the redirect land wherever the company's real locale is.
    requested_urls = []

    def fake_get(url, **kwargs):
        requested_urls.append(url)
        return _fake_get(url, **kwargs)

    monkeypatch.setattr(softgarden_scrape, "get_with_retry", fake_get)

    softgarden_scrape.fetch_jobs({"identifier": "acme", "name": "Acme", "search_terms": []})

    assert requested_urls[0] == "https://acme.softgarden.io/"
