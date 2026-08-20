import httpx

import http_client
from adapters.ats import smartrecruiters_api
from tests.conftest import fake_response

LIST_RESPONSE = {
    "content": [
        {
            "id": "1",
            "name": "QA Engineer",
            "location": {"country": "de", "fullLocation": "Berlin, BE, Germany"},
        },
        {
            "id": "2",
            "name": "QA Engineer (UK)",
            "location": {"country": "gb", "fullLocation": "London, UK"},
        },
        {
            "id": "3",
            "name": "Sales Manager",
            "location": {"country": "de", "fullLocation": "Munich, BY, Germany"},
        },
    ]
}

DETAIL_RESPONSE = {
    "jobAd": {
        "sections": {
            "companyDescription": {"text": "<p>About us</p>"},
            "jobDescription": {"text": "<p>Strong QA skills needed</p>"},
            "qualifications": {"text": ""},
        }
    }
}


def test_filters_by_country_and_url_is_stable(monkeypatch):
    monkeypatch.setattr(
        smartrecruiters_api, "get_with_retry", lambda *a, **k: fake_response(json=LIST_RESPONSE)
    )

    jobs = smartrecruiters_api.fetch_jobs(
        {"identifier": "acme", "name": "Acme", "search_terms": ["qa engineer"]}
    )

    assert [job.title for job in jobs] == ["QA Engineer", "Sales Manager"]
    assert jobs[0].url == "https://jobs.smartrecruiters.com/acme/1"
    assert jobs[0].source_id == "smartrecruiters:acme"


def test_fetches_description_only_for_title_matched_jobs(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        if url == smartrecruiters_api.LIST_URL_TEMPLATE.format(identifier="acme"):
            return fake_response(json=LIST_RESPONSE)
        calls.append(url)
        return fake_response(json=DETAIL_RESPONSE)

    monkeypatch.setattr(smartrecruiters_api, "get_with_retry", fake_get)
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    jobs = smartrecruiters_api.fetch_jobs(
        {"identifier": "acme", "name": "Acme", "search_terms": ["qa engineer"]}
    )

    assert calls == [smartrecruiters_api.DETAIL_URL_TEMPLATE.format(identifier="acme", posting_id="1")]
    qa_job = next(job for job in jobs if job.title == "QA Engineer")
    sales_job = next(job for job in jobs if job.title == "Sales Manager")
    assert "Strong QA skills needed" in qa_job.description
    assert sales_job.description == ""


def test_a_failed_detail_fetch_leaves_description_empty_but_keeps_the_job(monkeypatch):
    def fake_get(url, **kwargs):
        if url == smartrecruiters_api.LIST_URL_TEMPLATE.format(identifier="acme"):
            return fake_response(json=LIST_RESPONSE)
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(smartrecruiters_api, "get_with_retry", fake_get)
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    jobs = smartrecruiters_api.fetch_jobs(
        {"identifier": "acme", "name": "Acme", "search_terms": ["qa engineer"]}
    )

    assert len(jobs) == 2
    assert all(job.description == "" for job in jobs)
