from adapters.ats import bamboohr_api
from tests.conftest import fake_response

LISTING = {
    "result": [
        {
            "id": "1",
            "jobOpeningName": "Head of QA",
            "location": {"city": "Munich", "state": None},
            "atsLocation": {"country": None, "city": None},
        },
        {
            "id": "2",
            "jobOpeningName": "Field Engineer (China)",
            "location": {"city": None, "state": None},
            "atsLocation": {"country": "China", "city": "Shenzhen"},
        },
    ]
}
DETAIL = {"result": {"jobOpening": {"description": "<p>desc</p>"}}}


def _fake_get(url, **kwargs):
    if url.endswith("/detail"):
        return fake_response(json=DETAIL)
    return fake_response(json=LISTING)


def test_parses_listing_and_detail_with_dual_location_fallback(monkeypatch):
    monkeypatch.setattr(bamboohr_api, "get_with_retry", _fake_get)

    jobs = bamboohr_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Head of QA"
    assert job.location == "Munich, Germany"
    assert job.url == "https://acme.bamboohr.com/careers/1"
    assert job.description == "<p>desc</p>"
