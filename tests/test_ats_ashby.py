from adapters.ats import ashby_api
from tests.conftest import fake_response

RESPONSE = {
    "jobs": [
        {
            "title": "QA Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/acme/1",
            "location": "Berlin",
            "address": {"postalAddress": {"addressCountry": "Germany"}},
            "descriptionHtml": "<p>We need someone with strong skills.</p>",
        },
        {
            "title": "QA Engineer (London)",
            "jobUrl": "https://jobs.ashbyhq.com/acme/2",
            "location": "London",
            "address": {"postalAddress": {"addressCountry": "United Kingdom"}},
            "descriptionHtml": "<p>desc</p>",
        },
    ]
}


def test_parses_jobs(monkeypatch):
    monkeypatch.setattr(ashby_api, "get_with_retry", lambda *a, **k: fake_response(json=RESPONSE))

    jobs = ashby_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_id == "ashby:acme"
    assert job.title == "QA Engineer"
    assert job.company == "Acme"
    assert job.url == "https://jobs.ashbyhq.com/acme/1"
    assert job.location == "Berlin"
    assert job.description == "<p>We need someone with strong skills.</p>"


def test_filters_out_non_germany_country(monkeypatch):
    monkeypatch.setattr(ashby_api, "get_with_retry", lambda *a, **k: fake_response(json=RESPONSE))

    jobs = ashby_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert all(job.location != "London" for job in jobs)


def test_falls_back_to_location_guard_when_address_missing(monkeypatch):
    response = {
        "jobs": [
            {
                "title": "QA Engineer",
                "jobUrl": "https://jobs.ashbyhq.com/acme/3",
                "location": "Munich",
                "descriptionHtml": "<p>desc</p>",
            },
            {
                "title": "QA Engineer (Madrid)",
                "jobUrl": "https://jobs.ashbyhq.com/acme/4",
                "location": "Madrid",
                "descriptionHtml": "<p>desc</p>",
            },
        ]
    }
    monkeypatch.setattr(ashby_api, "get_with_retry", lambda *a, **k: fake_response(json=response))

    jobs = ashby_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert [job.location for job in jobs] == ["Munich"]
