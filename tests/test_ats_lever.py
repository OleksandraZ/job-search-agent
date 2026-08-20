from adapters.ats import lever_api
from tests.conftest import fake_response

RESPONSE = [
    {
        "text": "QA Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/1",
        "categories": {"location": "Munich"},
        "description": "<div>We need someone with strong skills.</div>",
        "country": "DE",
    },
    {
        "text": "QA Engineer (Barcelona)",
        "hostedUrl": "https://jobs.lever.co/acme/2",
        "categories": {"location": "Barcelona"},
        "description": "<div>desc</div>",
        "country": "ES",
    },
]


def test_parses_jobs_and_keeps_real_html_description(monkeypatch):
    monkeypatch.setattr(lever_api, "get_with_retry", lambda *a, **k: fake_response(json=RESPONSE))

    jobs = lever_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_id == "lever:acme"
    assert job.title == "QA Engineer"
    assert job.company == "Acme"
    assert job.url == "https://jobs.lever.co/acme/1"
    assert job.location == "Munich"
    assert job.description == "<div>We need someone with strong skills.</div>"


def test_filters_out_non_de_country(monkeypatch):
    monkeypatch.setattr(lever_api, "get_with_retry", lambda *a, **k: fake_response(json=RESPONSE))

    jobs = lever_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert all(job.location != "Barcelona" for job in jobs)


def test_falls_back_to_location_guard_when_country_missing(monkeypatch):
    response = [
        {
            "text": "QA Engineer",
            "hostedUrl": "https://jobs.lever.co/acme/3",
            "categories": {"location": "Berlin"},
            "description": "<div>desc</div>",
            "country": "",
        },
        {
            "text": "QA Engineer (Paris)",
            "hostedUrl": "https://jobs.lever.co/acme/4",
            "categories": {"location": "Paris"},
            "description": "<div>desc</div>",
            "country": "",
        },
    ]
    monkeypatch.setattr(lever_api, "get_with_retry", lambda *a, **k: fake_response(json=response))

    jobs = lever_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert [job.location for job in jobs] == ["Berlin"]
