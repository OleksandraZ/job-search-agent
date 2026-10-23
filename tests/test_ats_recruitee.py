from adapters.ats import recruitee_api
from tests.conftest import fake_response

RESPONSE = {
    "offers": [
        {
            "title": "Fachtrainer (m/w/d)",
            "careers_url": "https://acme.recruitee.com/o/1",
            "country_code": "DE",
            "location": "Köln, Nordrhein-Westfalen, Deutschland",
            "description": "<p>desc</p>",
        },
        {
            "title": "Sales Rep (Serbia)",
            "careers_url": "https://acme.recruitee.com/o/2",
            "country_code": "RS",
            "location": "Belgrade, Serbia",
            "description": "<p>desc</p>",
        },
    ]
}


def test_parses_offers_and_filters_by_country_code(monkeypatch):
    monkeypatch.setattr(recruitee_api, "get_with_retry", lambda *a, **k: fake_response(json=RESPONSE))

    jobs = recruitee_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Fachtrainer (m/w/d)"
    assert job.location == "Köln, Nordrhein-Westfalen, Deutschland"
    assert job.url == "https://acme.recruitee.com/o/1"
    assert job.description == "<p>desc</p>"


def test_custom_career_domain_identifier_uses_that_domain(monkeypatch):
    # Real case (2026-10-23): Quantum Systems' slug API is disabled, its own careers
    # domain serves the same /api/offers/.
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return fake_response(json=RESPONSE)

    monkeypatch.setattr(recruitee_api, "get_with_retry", fake_get)

    recruitee_api.fetch_jobs({"identifier": "career.quantum-systems.com", "name": "Quantum Systems"})
    recruitee_api.fetch_jobs({"identifier": "instagrid", "name": "Instagrid"})

    assert requested == [
        "https://career.quantum-systems.com/api/offers/",
        "https://instagrid.recruitee.com/api/offers/",
    ]
