import httpx

from tests.conftest import fake_response
from tools import company_lists, resolve_ats


def _c(name, ats, identifier="acme", **extra):
    url = f"https://{name.lower()}.test"
    return {"name": name, "url": url, "ats": ats, "identifier": identifier, **extra}


def _404(url):
    request = httpx.Request("GET", url)
    return httpx.HTTPStatusError("404", request=request, response=fake_response(status_code=404))


def _alive(mapping):
    return lambda company: mapping.get(company["name"])


def test_rebalance_moves_unfetchable_entries_out_with_a_reason(monkeypatch):
    monkeypatch.setattr(company_lists, "endpoint_alive", _alive({}))
    companies = [
        _c("Good", "greenhouse"),
        _c("Custom", "custom", None, careers_url="https://custom.test/jobs"),
        _c("Gone", "unresolved", None, reason="domain doesn't resolve (DNS) - site gone?"),
        _c("Rexx", "rexx", None),
    ]

    kept, unresolved, moved_in, moved_out = company_lists.rebalance(companies, [])

    assert [c["name"] for c in kept] == ["Good"]
    assert moved_in == []
    assert {c["name"]: c["reason"] for c in moved_out} == {
        "Custom": "careers page has no supported ATS",
        "Gone": "domain doesn't resolve (DNS) - site gone?",
        "Rexx": "rexx: no adapter yet",
    }
    assert unresolved == moved_out


def test_rebalance_moves_a_dead_endpoint_out_only_when_checked(monkeypatch):
    # Real case (2026-10-23): 59 Personio careers pages switched off entirely.
    monkeypatch.setattr(company_lists, "endpoint_alive", _alive({"Dead": False, "Unknown": None}))
    dead, unknown = _c("Dead", "personio", "tracify"), _c("Unknown", "lever")

    kept, _, _, moved_out = company_lists.rebalance([dead, unknown], [], check_live=[dead, unknown])
    assert [c["name"] for c in kept] == ["Unknown"]  # "couldn't tell" never moves anything
    assert moved_out[0]["reason"] == "personio endpoint for 'tracify' is gone (404)"

    kept, _, _, moved_out = company_lists.rebalance([dead], [])
    assert [c["name"] for c in kept] == ["Dead"]  # not checked -> left alone
    assert moved_out == []


def test_rebalance_brings_back_a_company_that_resolves_to_a_live_supported_ats(monkeypatch):
    monkeypatch.setattr(company_lists, "endpoint_alive", _alive({"Back": True, "StillDead": False}))
    back = _c("Back", "ashby", "koro", reason="careers page has no supported ATS")
    still_dead = _c("StillDead", "personio", "envoria-gmbh")
    custom = _c("Custom", "custom", None)

    kept, unresolved, moved_in, _ = company_lists.rebalance([], [back, still_dead, custom])

    assert [c["name"] for c in kept] == ["Back"]
    assert "reason" not in kept[0]
    assert moved_in == kept
    # A supported-ATS entry that stays has a dead endpoint - and says so.
    assert {c["name"]: c["reason"] for c in unresolved} == {
        "StillDead": "personio endpoint for 'envoria-gmbh' is gone (404)",
        "Custom": "careers page has no supported ATS",
    }


def test_endpoint_alive_reads_404_as_dead_and_errors_as_unknown(monkeypatch):
    def fake_get(url, **kwargs):
        if "dead" in url:
            raise _404(url)
        if "flaky" in url:
            raise httpx.ConnectTimeout("timeout")
        return fake_response(json={"jobs": []}, request_url=url)

    monkeypatch.setattr(company_lists, "get_with_retry", fake_get)

    assert company_lists.endpoint_alive(_c("A", "greenhouse", "live")) is True
    assert company_lists.endpoint_alive(_c("B", "greenhouse", "dead")) is False
    assert company_lists.endpoint_alive(_c("C", "greenhouse", "flaky")) is None
    # SmartRecruiters answers 200 for any slug - no signal, never reported dead.
    assert company_lists.endpoint_alive(_c("D", "smartrecruiters", "dead")) is None


def test_endpoint_alive_personio_counts_either_feed(monkeypatch):
    def fake_get(url, **kwargs):
        if url.endswith("/xml"):
            raise _404(url)
        if "carly" in url:
            return fake_response(json=[], request_url=url)
        raise _404(url)

    monkeypatch.setattr(company_lists, "get_with_retry", fake_get)

    assert company_lists.endpoint_alive(_c("Carly", "personio", "carly")) is True
    assert company_lists.endpoint_alive(_c("Tracify", "personio", "tracify")) is False


def test_resolver_cli_retries_the_unresolved_file_and_moves_entries_both_ways(monkeypatch, tmp_path):
    companies_path = tmp_path / "companies.yaml"
    unresolved_path = tmp_path / "unresolved_companies.yaml"
    company_lists.save(companies_path, [_c("Fetchable", "lever", "fetchable")])
    company_lists.save(
        unresolved_path,
        [{"name": "NowOnLever", "url": "https://acme.test", "ats": "custom", "identifier": None}],
        header=company_lists.UNRESOLVED_HEADER,
    )
    monkeypatch.setattr(resolve_ats, "COMPANIES_PATH", companies_path)
    monkeypatch.setattr(resolve_ats, "UNRESOLVED_PATH", unresolved_path)
    monkeypatch.setattr(resolve_ats, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(company_lists, "endpoint_alive", _alive({"Fetchable": False, "NowOnLever": True}))
    page = '<a href="https://jobs.lever.co/acme">Jobs</a>'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **kw: fake_response(text=page, request_url=url)
    )

    resolve_ats.main([])

    assert [c["name"] for c in company_lists.load(companies_path)] == ["NowOnLever"]
    assert [c["name"] for c in company_lists.load(unresolved_path)] == ["Fetchable"]
    assert unresolved_path.read_text().startswith("# Companies whose jobs can't be fetched")
    report = (tmp_path / "report.md").read_text()
    assert "NowOnLever — lever:acme" in report
    assert "Fetchable — lever endpoint for 'fetchable' is gone (404)" in report


def test_an_excluded_company_never_moves_back_even_with_a_live_ats(monkeypatch):
    # Real case (2026-10-23): Kingstone removed by hand; its Personio board is live.
    monkeypatch.setattr(company_lists, "endpoint_alive", _alive({"Kingstone": True}))
    kingstone = _c("Kingstone", "personio", "kingstone-im", excluded=True, reason="removed by hand")

    kept, unresolved, moved_in, moved_out = company_lists.rebalance([kingstone], [])
    assert kept == [] and moved_out[0]["reason"] == "removed by hand"

    kept, unresolved, moved_in, _ = company_lists.rebalance([], unresolved)
    assert kept == [] and moved_in == [] and unresolved[0]["name"] == "Kingstone"


def test_resolver_cli_never_redetects_an_excluded_company(monkeypatch, tmp_path):
    unresolved_path = tmp_path / "unresolved_companies.yaml"
    company_lists.save(
        unresolved_path, [_c("Gone", "unresolved", None, excluded=True, reason="removed by hand")]
    )
    monkeypatch.setattr(resolve_ats, "COMPANIES_PATH", tmp_path / "companies.yaml")
    monkeypatch.setattr(resolve_ats, "UNRESOLVED_PATH", unresolved_path)
    monkeypatch.setattr(resolve_ats, "REPORT_PATH", tmp_path / "report.md")

    def no_requests(url, **kwargs):
        raise AssertionError(f"excluded company was re-detected: {url}")

    monkeypatch.setattr(resolve_ats, "get_with_retry", no_requests)

    resolve_ats.main([])

    assert company_lists.load(unresolved_path)[0]["reason"] == "removed by hand"
