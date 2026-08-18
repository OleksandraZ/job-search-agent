from adapters.boards import testdevjobs
from tests.conftest import fake_response

LISTING_PAGE = """
<div class="job-tile-wrapper">
  <p class="jobtitle">QA Engineer</p>
  <p class="comptitle">Acme GmbH</p>
  <a href="/job/qa-engineer-1"></a>
  <span itemprop="address"><span itemprop="addressCountry">Germany,</span></span>
  <span itemprop="address"><span itemprop="addressCountry">🌐 Fully Remote</span></span>
</div>
"""

EMPTY_PAGE = "<html><body></body></html>"

DETAIL_PAGE = '<div itemprop="description">Full description here.</div>'

SOURCE_CONFIG = {"id": "testdevjobs_remote_germany", "path": "/location/remote-germany/", "search_terms": []}


def test_last_badge_is_work_mode_not_location(monkeypatch):
    def fake_get(url, **kwargs):
        if url == "https://testdevjobs.com/location/remote-germany/":
            return fake_response(text=LISTING_PAGE)
        return fake_response(text=EMPTY_PAGE)

    monkeypatch.setattr(testdevjobs, "get_with_retry", fake_get)
    monkeypatch.setattr(testdevjobs.time, "sleep", lambda *_: None)

    jobs = testdevjobs.fetch_jobs(SOURCE_CONFIG)

    assert len(jobs) == 1
    assert jobs[0].title == "QA Engineer"
    assert jobs[0].company == "Acme GmbH"
    assert jobs[0].url == "https://testdevjobs.com/job/qa-engineer-1"
    # "Germany," badge is the location, "🌐 Fully Remote" (the last badge) is the
    # work mode - folded together so is_remote()'s bare "remote" match still applies.
    assert jobs[0].location == "Germany 🌐 Fully Remote"


def test_fills_description_for_title_matched_jobs(monkeypatch):
    def fake_get(url, **kwargs):
        if url == "https://testdevjobs.com/location/remote-germany/":
            return fake_response(text=LISTING_PAGE)
        if url == "https://testdevjobs.com/job/qa-engineer-1":
            return fake_response(text=DETAIL_PAGE)
        return fake_response(text=EMPTY_PAGE)

    monkeypatch.setattr(testdevjobs, "get_with_retry", fake_get)
    monkeypatch.setattr(testdevjobs.time, "sleep", lambda *_: None)

    jobs = testdevjobs.fetch_jobs({**SOURCE_CONFIG, "search_terms": ["qa engineer"]})

    assert "Full description" in jobs[0].description
