import json

from adapters.ats import join_api
from tests.conftest import fake_response

LISTING_STATE = {
    "props": {
        "pageProps": {
            "initialState": {
                "jobs": {
                    "items": [
                        {
                            "id": 1,
                            "idParam": "1-backend-engineer",
                            "title": "Backend Engineer (f/m/d)",
                            "city": {"cityName": "Munich", "countryName": "Germany"},
                            "country": {"iso3166": "DE"},
                        },
                        {
                            "id": 2,
                            "idParam": "2-sales-rep",
                            "title": "Sales Rep (Austria)",
                            "city": {"cityName": "Vienna", "countryName": "Austria"},
                            "country": {"iso3166": "AT"},
                        },
                    ]
                }
            }
        }
    }
}
DETAIL_STATE = {
    "props": {"pageProps": {"initialState": {"job": {"description": "Full description here."}}}}
}


def _html_with_next_data(state: dict) -> str:
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(state)}</script>'


def _fake_get(url, **kwargs):
    if url.endswith("1-backend-engineer"):
        return fake_response(text=_html_with_next_data(DETAIL_STATE))
    return fake_response(text=_html_with_next_data(LISTING_STATE))


def test_parses_listing_and_detail_filtering_by_iso_country(monkeypatch):
    monkeypatch.setattr(join_api, "get_with_retry", _fake_get)

    jobs = join_api.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Backend Engineer (f/m/d)"
    assert job.location == "Munich, Germany"
    assert job.url == "https://join.com/companies/acme/1-backend-engineer"
    assert job.description == "Full description here."
