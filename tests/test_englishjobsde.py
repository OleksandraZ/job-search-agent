from adapters.boards import englishjobsde
from tests.conftest import fake_response

SEARCH_PAGE = """
<div class="job js-job" id="job-abc123">
  <span itemprop="title">Senior <em>QA</em>/QC <em>Engineer</em></span>
  <ul class="space-y-1">
    <li>Acme GmbH</li>
    <li>Berlin</li>
    <li>2 days ago</li>
  </ul>
  <div class="mr-4">Looking for a skilled tester...</div>
  <a href="/clickout/abc123?sig=signed-token-that-changes-every-request"></a>
</div>
"""


def test_url_uses_stable_card_id_not_the_signed_clickout_href(monkeypatch):
    monkeypatch.setattr(englishjobsde, "get_with_retry", lambda *a, **k: fake_response(text=SEARCH_PAGE))

    jobs = englishjobsde.fetch_jobs({"id": "englishjobsde", "search_terms": ["qa engineer"]})

    assert jobs[0].url == "https://englishjobs.de/clickout/job-abc123"


def test_title_spacing_around_em_tags_is_preserved(monkeypatch):
    # get_text() with no separator (not strip=True/" ") is required here - a naive
    # separator would invent a space inside "QA/QC" that was never in the source.
    monkeypatch.setattr(englishjobsde, "get_with_retry", lambda *a, **k: fake_response(text=SEARCH_PAGE))

    jobs = englishjobsde.fetch_jobs({"id": "englishjobsde", "search_terms": ["qa engineer"]})

    assert jobs[0].title == "Senior QA/QC Engineer"


def test_parses_company_and_location_fields(monkeypatch):
    monkeypatch.setattr(englishjobsde, "get_with_retry", lambda *a, **k: fake_response(text=SEARCH_PAGE))

    jobs = englishjobsde.fetch_jobs({"id": "englishjobsde", "search_terms": ["qa engineer"]})

    assert jobs[0].company == "Acme GmbH"
    assert jobs[0].location == "Berlin"
    assert "skilled tester" in jobs[0].description
