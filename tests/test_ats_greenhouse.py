from adapters.ats import greenhouse_api
from tests.conftest import fake_response

RESPONSE = {
    "jobs": [
        {
            "title": "QA Engineer",
            "company_name": "Acme",
            "absolute_url": "https://acme.example/careers/1",
            "location": {"name": "Berlin"},
            "content": "&lt;p&gt;We need someone with &lt;strong&gt;strong&lt;/strong&gt; skills.&lt;/p&gt;",
        },
        {
            "title": "QA Engineer (Barcelona)",
            "company_name": "Acme",
            "absolute_url": "https://acme.example/careers/2",
            "location": {"name": "Barcelona"},
            "content": "&lt;p&gt;desc&lt;/p&gt;",
        },
    ]
}


def test_parses_jobs_and_unescapes_html_content(monkeypatch):
    monkeypatch.setattr(greenhouse_api, "get_with_retry", lambda *a, **k: fake_response(json=RESPONSE))

    jobs = greenhouse_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_id == "greenhouse:acme"
    assert job.title == "QA Engineer"
    assert job.company == "Acme"
    assert job.url == "https://acme.example/careers/1"
    assert job.location == "Berlin"
    assert job.description == "<p>We need someone with <strong>strong</strong> skills.</p>"


def test_filters_out_non_germany_location(monkeypatch):
    monkeypatch.setattr(greenhouse_api, "get_with_retry", lambda *a, **k: fake_response(json=RESPONSE))

    jobs = greenhouse_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert all(job.location != "Barcelona" for job in jobs)


def test_falls_back_to_company_config_name_when_company_name_missing(monkeypatch):
    response = {
        "jobs": [
            {
                "title": "QA Engineer",
                "absolute_url": "https://acme.example/careers/3",
                "location": {"name": "Munich"},
                "content": "&lt;p&gt;desc&lt;/p&gt;",
            }
        ]
    }
    monkeypatch.setattr(greenhouse_api, "get_with_retry", lambda *a, **k: fake_response(json=response))

    jobs = greenhouse_api.fetch_jobs({"identifier": "acme", "name": "Acme Fallback Name"})

    assert jobs[0].company == "Acme Fallback Name"
