import httpx

from adapters.ats import personio_feed
from tests.conftest import fake_response

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
<position>
    <id>1</id>
    <office>Berlin</office>
    <additionalOffices>
        <office>Frankfurt am Main</office>
    </additionalOffices>
    <name>QA Engineer (m/w/d)</name>
    <jobDescriptions>
        <jobDescription>
            <name>About</name>
            <value><![CDATA[<p>We need <strong>strong</strong> QA skills.</p>]]></value>
        </jobDescription>
    </jobDescriptions>
</position>
<position>
    <id>2</id>
    <office>Barcelona</office>
    <name>QA Engineer (Spain)</name>
    <jobDescriptions>
        <jobDescription>
            <name>About</name>
            <value><![CDATA[<p>desc</p>]]></value>
        </jobDescription>
    </jobDescriptions>
</position>
</workzag-jobs>
"""


def test_parses_jobs_with_real_html_description(monkeypatch):
    monkeypatch.setattr(personio_feed, "get_with_retry", lambda *a, **k: fake_response(text=FEED))

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_id == "personio:acme"
    assert job.title == "QA Engineer (m/w/d)"
    assert job.company == "Acme"
    assert job.url == "https://acme.jobs.personio.de/job/1"
    assert job.location == "Berlin, Frankfurt am Main"
    assert job.description == "<p>We need <strong>strong</strong> QA skills.</p>"


def test_filters_out_non_germany_location(monkeypatch):
    monkeypatch.setattr(personio_feed, "get_with_retry", lambda *a, **k: fake_response(text=FEED))

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert all(job.location != "Barcelona" for job in jobs)


def test_fetch_failure_returns_empty_list_without_raising(monkeypatch):
    def fake_get(*a, **k):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(personio_feed, "get_with_retry", fake_get)

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert jobs == []


def test_malformed_xml_returns_empty_list_without_raising(monkeypatch):
    monkeypatch.setattr(personio_feed, "get_with_retry", lambda *a, **k: fake_response(text="<not-xml"))

    jobs = personio_feed.fetch_jobs({"identifier": "acme", "name": "Acme"})

    assert jobs == []
