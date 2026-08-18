import json

from adapters.boards import instaffo
from tests.conftest import fake_response

SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://jobs.instaffo.com/de/job/qualitatssicherung-ingenieur-abc123def456</loc></url>
  <url><loc>https://jobs.instaffo.com/en/job/qualitatssicherung-ingenieur-abc123def456</loc></url>
  <url><loc>https://jobs.instaffo.com/en/job/backend-developer-fed654cba321</loc></url>
</urlset>
"""


def _detail_html(title="Quality Assurance Engineer", country="Berlin"):
    ld_json = json.dumps(
        {
            "@type": "JobPosting",
            "title": title,
            "hiringOrganization": {"name": "Acme GmbH"},
            "jobLocation": [{"address": {"addressLocality": country}}],
            "description": "Full role description.",
        }
    )
    return f'<html><script type="application/ld+json">{ld_json}</script></html>'


def test_umlaut_normalized_slug_prefilter_matches_real_title_term(monkeypatch):
    # "Qualitätssicherung" (real search term, has an umlaut) must still match the
    # transliterated "qualitatssicherung" slug via the shared UMLAUT_MAP.
    fetched_urls = []

    def fake_get(url, **kwargs):
        if url == instaffo.SITEMAP_URL:
            return fake_response(text=SITEMAP)
        fetched_urls.append(url)
        return fake_response(text=_detail_html())

    monkeypatch.setattr(instaffo, "get_with_retry", fake_get)
    monkeypatch.setattr(instaffo.time, "sleep", lambda *_: None)

    instaffo.fetch_jobs({"id": "instaffo_qa_engineer", "search_terms": ["Qualitätssicherung"]})

    assert fetched_urls == ["https://jobs.instaffo.com/en/job/qualitatssicherung-ingenieur-abc123def456"]


def test_non_matching_slugs_are_never_fetched(monkeypatch):
    fetched_urls = []

    def fake_get(url, **kwargs):
        if url == instaffo.SITEMAP_URL:
            return fake_response(text=SITEMAP)
        fetched_urls.append(url)
        return fake_response(text=_detail_html())

    monkeypatch.setattr(instaffo, "get_with_retry", fake_get)
    monkeypatch.setattr(instaffo.time, "sleep", lambda *_: None)

    instaffo.fetch_jobs({"id": "instaffo_qa_engineer", "search_terms": ["ingenieur"]})

    assert "https://jobs.instaffo.com/en/job/backend-developer-fed654cba321" not in fetched_urls


def test_parses_job_posting_json_ld_from_detail_page(monkeypatch):
    def fake_get(url, **kwargs):
        if url == instaffo.SITEMAP_URL:
            return fake_response(text=SITEMAP)
        return fake_response(text=_detail_html())

    monkeypatch.setattr(instaffo, "get_with_retry", fake_get)
    monkeypatch.setattr(instaffo.time, "sleep", lambda *_: None)

    jobs = instaffo.fetch_jobs({"id": "instaffo_qa_engineer", "search_terms": ["ingenieur"]})

    assert len(jobs) == 1
    assert jobs[0].title == "Quality Assurance Engineer"
    assert jobs[0].company == "Acme GmbH"
    assert jobs[0].location == "Berlin"
    assert jobs[0].description == "Full role description."
