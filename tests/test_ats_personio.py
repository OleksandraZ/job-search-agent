import httpx

from adapters.ats import personio_feed
from tests.conftest import fake_response

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
<position>
    <id>1</id>
    <office>Berlin</office>
    <additionalOffices>
        <office>Frankfurt am Main</office>
    </additionalOffices>
    <name>QA Engineer (m/w/d)</name>
    <jobDescriptions>
        <jobDescription>
            <name>About</name>
            <value><![CDATA[<p>We need <strong>strong</strong> QA skills.</p>]]></value>
        </jobDescription>
    </jobDescriptions>
</position>
<position>
    <id>2</id>
    <office>Barcelona</office>
    <name>QA Engineer (Spain)</name>
    <jobDescriptions>
        <jobDescription>
            <name>About</name>
            <value><![CDATA[<p>desc</p>]]></value>
        </jobDescription>
    </jobDescriptions>
</position>
</workzag-jobs>
"""


def test_parses_jobs_with_real_html_description(monkeypatch):
    monkeypatch.setattr(personio_feed, "get_with_retry", lambda *a, **k: fake_response(text=FEED))

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_id == "personio:acme"
    assert job.title == "QA Engineer (m/w/d)"
    assert job.company == "Acme"
    assert job.url == "https://acme.jobs.personio.de/job/1"
    assert job.location == "Berlin, Frankfurt am Main"
    assert job.description == "<p>We need <strong>strong</strong> QA skills.</p>"


def test_filters_out_non_germany_location(monkeypatch):
    monkeypatch.setattr(personio_feed, "get_with_retry", lambda *a, **k: fake_response(text=FEED))

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert all(job.location != "Barcelona" for job in jobs)


def test_fetch_failure_returns_empty_list_without_raising(monkeypatch):
    def fake_get(*a, **k):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(personio_feed, "get_with_retry", fake_get)

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert jobs == []


def test_malformed_xml_returns_empty_list_without_raising(monkeypatch):
    monkeypatch.setattr(personio_feed, "get_with_retry", lambda *a, **k: fake_response(text="<not-xml"))

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert jobs == []


SEARCH_JSON = [
    {"id": 7, "name": "QA Engineer (m/w/d)", "description": "", "office": "München", "offices": ["München"]},
    {"id": 8, "name": "Sales Manager", "description": "", "office": "Berlin", "offices": ["Berlin"]},
    {"id": 9, "name": "QA Engineer (Spain)", "description": "", "office": "Barcelona",
     "offices": ["Barcelona"]},
]
DETAIL_PAGE = """<html><head>
<script type="application/ld+json">{"@type": "Organization", "name": "Acme"}</script>
<script type="application/ld+json">{"@type": "JobPosting", "title": "QA Engineer",
 "description": "<p>Playwright und Python</p>"}</script>
</head></html>"""


def _http_error(url, status_code):
    return httpx.HTTPStatusError(
        str(status_code), request=httpx.Request("GET", url), response=fake_response(status_code=status_code)
    )


def _xml_404_then(responses):
    """get_with_retry stub: /xml 404s (feed switched off), other URLs from `responses`."""
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        if url.endswith("/xml"):
            raise _http_error(url, 404)
        return responses(url)

    return fake_get, requested


def test_falls_back_to_search_json_when_xml_feed_is_switched_off(monkeypatch):
    # Real case (2026-10-23): finAPI/Carly's /xml 404s while /search.json lists jobs.
    def responses(url):
        if url.endswith("/search.json"):
            return fake_response(json=SEARCH_JSON)
        return fake_response(text=DETAIL_PAGE)

    fake_get, requested = _xml_404_then(responses)
    monkeypatch.setattr(personio_feed, "get_with_retry", fake_get)
    monkeypatch.setattr(personio_feed, "REQUEST_DELAY_SECONDS", 0)

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme", "search_terms": ["QA Engineer"]})

    assert [(j.title, j.location, j.url) for j in jobs] == [
        ("QA Engineer (m/w/d)", "München", "https://acme.jobs.personio.de/job/7"),
        ("Sales Manager", "Berlin", "https://acme.jobs.personio.de/job/8"),
    ]
    assert jobs[0].description == "<p>Playwright und Python</p>"
    # Detail pages only for the title-matched subset.
    assert jobs[1].description == ""
    assert "https://acme.jobs.personio.de/job/8" not in requested


def test_careers_page_switched_off_entirely_returns_empty_list(monkeypatch):
    def not_found(url):
        raise _http_error(url, 404)

    fake_get, _ = _xml_404_then(not_found)
    monkeypatch.setattr(personio_feed, "get_with_retry", fake_get)

    assert personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"}) == []


def test_non_404_feed_error_does_not_fall_back(monkeypatch):
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        raise _http_error(url, 500)

    monkeypatch.setattr(personio_feed, "get_with_retry", fake_get)

    assert personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"}) == []
    assert requested == ["https://acme.jobs.personio.de/xml"]
