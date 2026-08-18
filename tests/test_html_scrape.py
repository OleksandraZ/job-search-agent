from adapters.boards import html_scrape
from tests.conftest import fake_response

RSS_FEED = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>QA Engineer @ Acme GmbH [Munich]</title>
    <link>https://germantechjobs.de/jobs/1</link>
    <description>Wir suchen dich.</description>
  </item>
  <item>
    <title>Untitled Posting With No Company Marker</title>
    <link>https://germantechjobs.de/jobs/2</link>
    <description></description>
  </item>
</channel></rss>
"""


def test_parses_title_at_company_pattern(monkeypatch):
    monkeypatch.setattr(html_scrape, "get_with_retry", lambda *a, **k: fake_response(text=RSS_FEED))

    jobs = html_scrape.fetch_jobs({"id": "germantechjobs_testing_germany", "rss_url": "https://example.test/rss"})

    assert jobs[0].title == "QA Engineer"
    assert jobs[0].company == "Acme GmbH"
    assert jobs[0].url == "https://germantechjobs.de/jobs/1"
    assert jobs[0].location == "Germany"
    assert jobs[0].description == "Wir suchen dich."


def test_falls_back_to_raw_title_and_unknown_company_when_pattern_does_not_match(monkeypatch):
    monkeypatch.setattr(html_scrape, "get_with_retry", lambda *a, **k: fake_response(text=RSS_FEED))

    jobs = html_scrape.fetch_jobs({"id": "germantechjobs_testing_germany", "rss_url": "https://example.test/rss"})

    assert jobs[1].title == "Untitled Posting With No Company Marker"
    assert jobs[1].company == "Unknown"
