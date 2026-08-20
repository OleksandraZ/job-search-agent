from adapters.ats import workable_api
from tests.conftest import fake_response

RESPONSE = {
    "jobs": [
        {
            "title": "Legal Counsel (m/f/x)",
            "url": "https://apply.workable.com/j/1",
            "shortlink": "https://apply.workable.com/j/1",
            "country": "Germany",
            "city": "Berlin",
            "description": "<p>desc</p>",
        },
        {
            "title": "Sales Manager (Netherlands)",
            "url": "https://apply.workable.com/j/2",
            "shortlink": "https://apply.workable.com/j/2",
            "country": "Netherlands",
            "city": "Amsterdam",
            "description": "<p>desc</p>",
        },
    ]
}


def test_parses_jobs_and_filters_by_structured_country(monkeypatch):
    monkeypatch.setattr(workable_api, "get_with_retry", lambda *a, **k: fake_response(json=RESPONSE))

    jobs = workable_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Legal Counsel (m/f/x)"
    assert job.location == "Berlin, Germany"
    assert job.url == "https://apply.workable.com/j/1"
    assert job.description == "<p>desc</p>"


def test_falls_back_to_location_guard_when_country_missing(monkeypatch):
    response = {
        "jobs": [
            {
                "title": "QA Engineer",
                "url": "https://apply.workable.com/j/3",
                "country": "",
                "city": "Munich",
                "description": "desc",
            },
            {
                "title": "QA Engineer (Paris)",
                "url": "https://apply.workable.com/j/4",
                "country": "",
                "city": "Paris",
                "description": "desc",
            },
        ]
    }
    monkeypatch.setattr(workable_api, "get_with_retry", lambda *a, **k: fake_response(json=response))

    jobs = workable_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert [job.location for job in jobs] == ["Munich, Germany"]
