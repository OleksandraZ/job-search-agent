from adapters import registry
from adapters.registry import fetch_from_companies
from tests.conftest import make_job


def _companies_config(*companies):
    return {"companies": list(companies)}


_KEYWORDS = {"title_match_terms": ["qa engineer"]}


def test_fetches_from_companies_with_a_resolved_ats(monkeypatch):
    received_configs = []

    def fake_fetch(company_config):
        received_configs.append(company_config)
        return [make_job(source_id=f"fake:{company_config['identifier']}")]

    monkeypatch.setitem(registry.ATS_ADAPTERS, "fake_ats", fake_fetch)

    companies_config = _companies_config(
        {"name": "Acme", "ats": "fake_ats", "identifier": "acme"}
    )

    jobs = fetch_from_companies(companies_config, _KEYWORDS)

    assert [job.source_id for job in jobs] == ["fake:acme"]
    assert received_configs[0]["identifier"] == "acme"
    assert received_configs[0]["search_terms"] == ["qa engineer"]


def test_unresolved_ats_is_skipped_without_raising():
    companies_config = _companies_config({"name": "Acme", "ats": None, "identifier": None})

    jobs = fetch_from_companies(companies_config, _KEYWORDS)

    assert jobs == []


def test_unregistered_ats_is_skipped_without_raising():
    companies_config = _companies_config({"name": "Acme", "ats": "not_built_yet", "identifier": "acme"})

    jobs = fetch_from_companies(companies_config, _KEYWORDS)

    assert jobs == []


def test_one_company_failing_does_not_stop_the_others(monkeypatch):
    def failing_fetch(company_config):
        raise RuntimeError("boom")

    def working_fetch(company_config):
        return [make_job(source_id=f"fake:{company_config['identifier']}")]

    monkeypatch.setitem(registry.ATS_ADAPTERS, "failing_ats", failing_fetch)
    monkeypatch.setitem(registry.ATS_ADAPTERS, "working_ats", working_fetch)

    companies_config = _companies_config(
        {"name": "Broken Co", "ats": "failing_ats", "identifier": "broken"},
        {"name": "Good Co", "ats": "working_ats", "identifier": "good"},
    )

    jobs = fetch_from_companies(companies_config, _KEYWORDS)

    assert [job.source_id for job in jobs] == ["fake:good"]


def test_workday_companies_run_one_at_a_time_alongside_the_others(monkeypatch):
    import threading
    import time

    running = {"workday": 0, "other": 0}
    peak = {"workday": 0, "other": 0}
    lock = threading.Lock()

    def make_fetch(vendor):
        def fetch(company_config):
            with lock:
                running[vendor] += 1
                peak[vendor] = max(peak[vendor], running[vendor])
            time.sleep(0.02)
            with lock:
                running[vendor] -= 1
            return [make_job(source_id=company_config["name"])]

        return fetch

    monkeypatch.setitem(registry.ATS_ADAPTERS, "workday", make_fetch("workday"))
    monkeypatch.setitem(registry.ATS_ADAPTERS, "other", make_fetch("other"))
    companies = [{"name": f"wd{i}", "ats": "workday", "identifier": i} for i in range(4)] + [
        {"name": f"o{i}", "ats": "other", "identifier": i} for i in range(8)
    ]

    jobs = fetch_from_companies(_companies_config(*companies), _KEYWORDS)

    assert [job.source_id for job in jobs] == [c["name"] for c in companies]  # yaml order kept
    assert peak["workday"] == 1
    assert peak["other"] > 1
