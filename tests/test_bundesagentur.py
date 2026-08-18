from adapters.boards import bundesagentur
from tests.conftest import fake_response

SEARCH_RESPONSE = {
    "ergebnisliste": [
        {
            "referenznummer": "REF-1",
            "stellenangebotsTitel": "QA Engineer",
            "firma": "Acme GmbH",
            "stellenlokationen": [
                {"adresse": {"land": "DEUTSCHLAND", "ort": "Berlin"}},
                {"adresse": {"land": "DEUTSCHLAND", "ort": "Munich"}},
            ],
        },
        {
            "referenznummer": "REF-2",
            "stellenangebotsTitel": "QA Engineer Luxembourg",
            "firma": "Other GmbH",
            "stellenlokationen": [
                {"adresse": {"land": "LUXEMBURG", "ort": "Luxembourg"}},
            ],
        },
        {
            "referenznummer": "REF-3",
            "stellenangebotsTitel": "No location at all",
            "firma": "Ghost GmbH",
            "stellenlokationen": [],
        },
    ]
}

DETAIL_HTML = """
<script type="application/ld+json">
{"@type": "JobPosting", "description": "Full role description."}
</script>
"""

NULL_ADDRESS_RESPONSE = {
    "ergebnisliste": [
        {
            "referenznummer": "REF-4",
            "stellenangebotsTitel": "Null Address Posting",
            "firma": "Ghost GmbH",
            "stellenlokationen": [{"adresse": None}],
        }
    ]
}

SOURCE_CONFIG = {"id": "bundesagentur_für_arbeit_jobsuche", "search_terms": ["qa engineer"]}


def test_non_germany_locations_are_dropped_and_multi_location_joined(monkeypatch):
    monkeypatch.setattr(bundesagentur, "get_with_retry", lambda *a, **k: fake_response(json=SEARCH_RESPONSE))

    jobs = bundesagentur.fetch_jobs(SOURCE_CONFIG)

    assert len(jobs) == 1
    assert jobs[0].title == "QA Engineer"
    assert jobs[0].location == "Berlin, Munich"
    assert jobs[0].url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/REF-1"


def test_job_with_no_german_locations_is_dropped_entirely(monkeypatch):
    monkeypatch.setattr(bundesagentur, "get_with_retry", lambda *a, **k: fake_response(json=SEARCH_RESPONSE))

    jobs = bundesagentur.fetch_jobs(SOURCE_CONFIG)

    urls = [job.url for job in jobs]
    assert "https://www.arbeitsagentur.de/jobsuche/jobdetail/REF-2" not in urls
    assert "https://www.arbeitsagentur.de/jobsuche/jobdetail/REF-3" not in urls


def test_null_adresse_field_does_not_crash_and_job_is_dropped(monkeypatch):
    monkeypatch.setattr(
        bundesagentur, "get_with_retry", lambda *a, **k: fake_response(json=NULL_ADDRESS_RESPONSE)
    )

    jobs = bundesagentur.fetch_jobs(SOURCE_CONFIG)

    assert jobs == []


def test_fills_description_via_job_posting_json_ld(monkeypatch):
    def fake_get(url, **kwargs):
        if url == bundesagentur.SEARCH_API_URL:
            return fake_response(json=SEARCH_RESPONSE)
        return fake_response(text=DETAIL_HTML)

    monkeypatch.setattr(bundesagentur, "get_with_retry", fake_get)
    monkeypatch.setattr(bundesagentur.time, "sleep", lambda *_: None)

    jobs = bundesagentur.fetch_jobs(SOURCE_CONFIG)

    assert "Full role description" in jobs[0].description
