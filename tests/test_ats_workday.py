import httpx

import http_client
from adapters.ats import workday_api
from tests.conftest import fake_response

# Mirrors the real shape seen live: Roche's tenant has no separate country-level
# facet, only a flat city+country "locations" facet where German offices are split
# across per-city entries plus a near-empty literal "Germany" entry.
FACETS_RESPONSE = {
    "total": 1000,
    "jobPostings": [],
    "facets": [
        {
            "facetParameter": "locationMainGroup",
            "values": [
                {
                    "facetParameter": "locations",
                    "descriptor": "Locations",
                    "values": [
                        {"descriptor": "Warsaw", "id": "warsaw-id", "count": 40},
                        {"descriptor": "Mannheim", "id": "mannheim-id", "count": 46},
                        {"descriptor": "Germany", "id": "germany-id", "count": 1},
                    ],
                }
            ],
        }
    ],
}


def _company_config(**overrides):
    config = {
        "identifier": {"tenant": "acme", "wd_host": "wd3", "site": "External"},
        "name": "Acme",
        "search_terms": ["qa engineer"],
    }
    config.update(overrides)
    return config


def _search_response(postings, total=None):
    return {"total": total if total is not None else len(postings), "jobPostings": postings}


def test_selects_only_german_looking_facet_entries(monkeypatch):
    applied = []

    def fake_post(url, **kwargs):
        body = kwargs["json"]
        if body["searchText"] == "":
            return fake_response(json=FACETS_RESPONSE)
        applied.append(body["appliedFacets"])
        return fake_response(json=_search_response([]))

    monkeypatch.setattr(workday_api, "post_with_retry", fake_post)
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    workday_api.fetch_jobs(_company_config())

    assert applied[0] == {"locations": ["mannheim-id", "germany-id"]}


def test_parses_matched_job_and_confirms_country_via_detail_fetch(monkeypatch):
    posting = {
        "title": "QA Engineer",
        "externalPath": "/job/Mannheim/QA-Engineer_JR1",
        "locationsText": "Mannheim",
    }
    detail = {"jobPostingInfo": {"country": {"descriptor": "Germany"}, "jobDescription": "<p>desc</p>"}}

    def fake_post(url, **kwargs):
        body = kwargs["json"]
        if body["searchText"] == "":
            return fake_response(json=FACETS_RESPONSE)
        return fake_response(json=_search_response([posting]))

    monkeypatch.setattr(workday_api, "post_with_retry", fake_post)
    monkeypatch.setattr(workday_api, "get_with_retry", lambda *a, **k: fake_response(json=detail))
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    jobs = workday_api.fetch_jobs(_company_config())

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_id == "workday:acme/External"
    assert job.title == "QA Engineer"
    assert job.url == "https://acme.wd3.myworkdayjobs.com/External/job/Mannheim/QA-Engineer_JR1"
    assert job.description == "<p>desc</p>"


def test_detail_endpoint_country_check_drops_a_false_positive(monkeypatch):
    # Facet selection is a best-effort heuristic and could in principle let a
    # non-Germany job through - the detail endpoint's authoritative country field
    # is the final backstop.
    posting = {
        "title": "QA Engineer",
        "externalPath": "/job/Warsaw/QA-Engineer_JR2",
        "locationsText": "Warsaw",
    }
    detail = {"jobPostingInfo": {"country": {"descriptor": "Poland"}, "jobDescription": "<p>desc</p>"}}

    def fake_post(url, **kwargs):
        body = kwargs["json"]
        if body["searchText"] == "":
            return fake_response(json=FACETS_RESPONSE)
        return fake_response(json=_search_response([posting]))

    monkeypatch.setattr(workday_api, "post_with_retry", fake_post)
    monkeypatch.setattr(workday_api, "get_with_retry", lambda *a, **k: fake_response(json=detail))
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    jobs = workday_api.fetch_jobs(_company_config())

    assert jobs == []


def test_no_germany_facet_returns_empty_list(monkeypatch):
    no_germany = {
        "total": 0,
        "jobPostings": [],
        "facets": [
            {
                "facetParameter": "locationMainGroup",
                "values": [
                    {
                        "facetParameter": "locations",
                        "descriptor": "Locations",
                        "values": [{"descriptor": "Warsaw", "id": "warsaw-id", "count": 10}],
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(workday_api, "post_with_retry", lambda *a, **k: fake_response(json=no_germany))

    jobs = workday_api.fetch_jobs(_company_config())

    assert jobs == []


def test_paginates_when_a_term_has_more_results_than_one_page(monkeypatch):
    page1 = [
        {"title": "QA Engineer", "externalPath": f"/job/Mannheim/QA-{i}", "locationsText": "Mannheim"}
        for i in range(20)
    ]
    page2 = [
        {"title": "QA Engineer", "externalPath": "/job/Mannheim/QA-20", "locationsText": "Mannheim"}
    ]

    calls = {"n": 0}

    def fake_post(url, **kwargs):
        body = kwargs["json"]
        if body["searchText"] == "":
            return fake_response(json=FACETS_RESPONSE)
        calls["n"] += 1
        if body["offset"] == 0:
            return fake_response(json=_search_response(page1, total=21))
        return fake_response(json=_search_response(page2, total=21))

    detail = {"jobPostingInfo": {"country": {"descriptor": "Germany"}, "jobDescription": "<p>d</p>"}}
    monkeypatch.setattr(workday_api, "post_with_retry", fake_post)
    monkeypatch.setattr(workday_api, "get_with_retry", lambda *a, **k: fake_response(json=detail))
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    jobs = workday_api.fetch_jobs(_company_config())

    assert len(jobs) == 21
    assert calls["n"] == 2


def test_a_failed_detail_fetch_falls_back_to_the_location_guard(monkeypatch):
    posting = {
        "title": "QA Engineer",
        "externalPath": "/job/Mannheim/QA-Engineer_JR1",
        "locationsText": "Mannheim",
    }

    def fake_post(url, **kwargs):
        body = kwargs["json"]
        if body["searchText"] == "":
            return fake_response(json=FACETS_RESPONSE)
        return fake_response(json=_search_response([posting]))

    def fake_get(*a, **k):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(workday_api, "post_with_retry", fake_post)
    monkeypatch.setattr(workday_api, "get_with_retry", fake_get)
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    jobs = workday_api.fetch_jobs(_company_config())

    assert len(jobs) == 1
    assert jobs[0].description == ""
