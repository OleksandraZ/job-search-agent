import httpx

from tests.conftest import fake_response
from tools import resolve_ats


def _company(name="Acme", url="https://acme.test"):
    return {"name": name, "url": url}


def test_signature_found_directly_on_homepage(monkeypatch):
    html = '<a href="https://jobs.lever.co/acme">Careers</a>'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "lever",
        "identifier": "acme",
        "careers_url": "https://acme.test",
        "match_method": "page_scan",
    }


def test_follows_discovered_career_link_when_homepage_has_no_signature(monkeypatch):
    homepage_html = '<a href="/careers">Karriere</a>'
    career_html = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'

    def fake_get(url, **kwargs):
        if url == "https://acme.test":
            return fake_response(text=homepage_html, request_url=url)
        if url == "https://acme.test/careers":
            return fake_response(text=career_html, request_url=url)
        raise httpx.HTTPError("unexpected url")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "greenhouse",
        "identifier": "acme",
        "careers_url": "https://acme.test/careers",
        "match_method": "page_scan",
    }


def test_falls_back_to_path_guess_when_no_career_link_found(monkeypatch):
    homepage_html = "<p>No careers link here.</p>"
    guess_html = '<a href="https://jobs.ashbyhq.com/acme">Open roles</a>'

    def fake_get(url, **kwargs):
        if url == "https://acme.test":
            return fake_response(text=homepage_html, request_url=url)
        if url == "https://acme.test/careers":
            return fake_response(text=guess_html, request_url=url)
        raise httpx.HTTPError("404")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "ashby",
        "identifier": "acme",
        "careers_url": "https://acme.test/careers",
        "match_method": "page_scan",
    }


def test_no_careers_page_found_anywhere_resolves_to_unresolved(monkeypatch):
    # Homepage itself has no signature, and every other candidate (career-page
    # guesses, active platform probes) 404s - nothing to bucket as "custom" here,
    # since no real careers page was ever actually found.
    def fake_get(url, **kwargs):
        if url == "https://acme.test":
            return fake_response(text="<p>nothing here</p>", request_url=url)
        raise httpx.HTTPError("404")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._detect_ats(_company())

    assert result == {"ats": "unresolved", "identifier": None, "careers_url": None, "match_method": None}


def test_careers_page_found_with_no_fingerprint_resolves_to_custom(monkeypatch):
    # Every candidate URL 200s (a real careers page exists) but none of it matches a
    # known vendor - the "custom" bucket exists specifically to distinguish this from
    # a company where no careers page could be found at all.
    monkeypatch.setattr(
        resolve_ats,
        "get_with_retry",
        lambda url, **k: fake_response(text="<p>nothing here</p>", request_url=url),
    )

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "custom",
        "identifier": None,
        "careers_url": "https://acme.test/careers",
        "match_method": None,
    }


def test_unreachable_homepage_resolves_to_unresolved_without_raising(monkeypatch):
    def fake_get(url, **kwargs):
        raise httpx.HTTPError("connection failed")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._detect_ats(_company())

    assert result == {"ats": "unresolved", "identifier": None, "careers_url": None, "match_method": None}


def test_greenhouse_v1_boards_prefix_with_no_real_slug_does_not_false_positive(monkeypatch):
    # Real commercetools careers page: contains the literal text
    # "boards-api.greenhouse.io/v1/boards/" followed by a JS template variable (the
    # real slug is injected at runtime, not present in the static HTML). An earlier
    # version of the greenhouse pattern used an optional `(?:v1/boards/)?` group,
    # and regex backtracking matched "v1" itself as a bogus identifier here instead
    # of failing outright. The page is still real (200s everywhere), so this now
    # correctly buckets as "custom" rather than fully unresolved - the guard under
    # test is that it's NOT falsely captured as a real greenhouse match.
    html = 'fetch(`//boards-api.greenhouse.io/v1/boards/${slug}/jobs`)'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company())

    assert result["ats"] == "custom"
    assert result["identifier"] is None


def test_json_escaped_slashes_in_embedded_page_data_still_match(monkeypatch):
    # Verified live against n8n: its careers page is a Next.js app whose embedded
    # page-data JSON has the real ashbyhq URL with every "/" written as the
    # 6-character escape sequence u002F, not a literal slash - a plain substring
    # match against the raw pattern would miss it entirely.
    html = 'component:"https:\\u002F\\u002Fjobs.ashbyhq.com\\u002Fn8n"'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "ashby",
        "identifier": "n8n",
        "careers_url": "https://acme.test",
        "match_method": "page_scan",
    }


def test_regional_greenhouse_job_boards_domain_resolves_via_standard_slug(monkeypatch):
    # Verified live against Raisin: their careers page links to
    # job-boards.eu.greenhouse.io/raisin, not boards.greenhouse.io - the slug still
    # works against the standard boards-api.greenhouse.io endpoint regardless.
    html = '<a href="https://job-boards.eu.greenhouse.io/raisin">Careers</a>'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "greenhouse",
        "identifier": "raisin",
        "careers_url": "https://acme.test",
        "match_method": "page_scan",
    }


def test_workday_identifier_has_three_parts(monkeypatch):
    html = '<a href="https://acme.wd5.myworkdayjobs.com/External">Careers</a>'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "workday",
        "identifier": {"tenant": "acme", "wd_host": "wd5", "site": "External"},
        "careers_url": "https://acme.test",
        "match_method": "page_scan",
    }


def test_data_attribute_only_embed_is_detected(monkeypatch):
    # Greenhouse's snippet embed carries the slug in a data-board-token attribute,
    # never in a URL a domain-shaped regex would catch.
    html = '<div id="grnhse_app" data-board-token="acme"></div>'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "greenhouse",
        "identifier": "acme",
        "careers_url": "https://acme.test",
        "match_method": "data_attr",
    }


def test_new_vendor_pattern_recruitee_matches(monkeypatch):
    html = '<a href="https://acme.recruitee.com/">Jobs</a>'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "recruitee",
        "identifier": "acme",
        "careers_url": "https://acme.test",
        "match_method": "page_scan",
    }


def test_prefers_name_matching_identifier_over_a_shared_tracking_subdomain(monkeypatch):
    # Verified live: Softgarden injects its own analytics subdomain
    # ("matomo.softgarden.io") on every page it hosts, appearing before the real
    # company slug ("cqse.softgarden.io") in the raw HTML - taking the first regex
    # match blindly picked the tracker instead of the real company board.
    html = (
        '<script src="https://matomo.softgarden.io/js"></script>'
        '<a href="https://cqse.softgarden.io/en/">Jobs</a>'
    )
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company(name="CQSE"))

    assert result["ats"] == "softgarden"
    assert result["identifier"] == "cqse"


def test_falls_back_to_first_match_when_no_candidate_matches_the_company_name(monkeypatch):
    # No candidate's slug fuzzy-matches "Acme" - preserves the old default-permissive
    # behavior (first match wins) rather than discarding a real signal outright.
    html = (
        '<script src="https://matomo.softgarden.io/js"></script>'
        '<a href="https://other-co.softgarden.io/en/">Jobs</a>'
    )
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company(name="Acme"))

    assert result["ats"] == "softgarden"
    assert result["identifier"] == "matomo"


def test_softgarden_career_dot_de_domain_convention_matches(monkeypatch):
    # A second, distinct softgarden domain shape confirmed live on Sunfire -
    # <slug>.career.softgarden.de, not just <slug>.softgarden.io.
    html = '<a href="https://sunfire.career.softgarden.de/application/?jobId=1">Apply</a>'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company(name="Sunfire"))

    assert result == {
        "ats": "softgarden",
        "identifier": "sunfire",
        "careers_url": "https://acme.test",
        "match_method": "page_scan",
    }


def test_career_link_pattern_matches_german_terms():
    html = '<a href="/stellenangebote">Unsere Stellenangebote</a>'

    assert resolve_ats._find_matching_links(resolve_ats.CAREER_LINK_PATTERN, "https://acme.test", html) == [
        "https://acme.test/stellenangebote"
    ]


def test_find_matching_links_returns_every_match_not_just_the_first():
    # A homepage can have an earlier, unrelated match before the real careers link -
    # verified live against Taxfix (see the docstring on _find_matching_links).
    html = (
        '<a href="/steuerklasse-6-zweitjob/">Personen mit Zweitjob</a>'
        '<a href="/en/careers/">Karriere</a>'
    )

    links = resolve_ats._find_matching_links(resolve_ats.CAREER_LINK_PATTERN, "https://acme.test", html)

    assert links == ["https://acme.test/steuerklasse-6-zweitjob/", "https://acme.test/en/careers/"]


def test_find_matching_links_dedupes_by_resolved_url():
    html = '<a href="/careers">Careers</a><a href="/careers">Careers again</a>'

    links = resolve_ats._find_matching_links(resolve_ats.CAREER_LINK_PATTERN, "https://acme.test", html)

    assert links == ["https://acme.test/careers"]


def test_second_hop_finds_ats_signature_on_a_job_listing_page_linked_from_a_bare_career_hub(
    monkeypatch,
):
    # Mirrors Taxfix live: the homepage's real "Karriere" link leads to a marketing
    # hub page with zero ATS signature, which itself links to the actual job listing
    # page via "See our open roles" - text that CAREER_LINK_PATTERN alone would never
    # match.
    homepage_html = '<a href="/en/careers/">Karriere</a>'
    hub_html = '<p>Meet the team.</p><a href="/en/job-openings/">See our open roles</a>'
    listing_html = '<a href="https://jobs.ashbyhq.com/acme">Apply</a>'

    def fake_get(url, **kwargs):
        if url == "https://acme.test":
            return fake_response(text=homepage_html, request_url=url)
        if url == "https://acme.test/en/careers/":
            return fake_response(text=hub_html, request_url=url)
        if url == "https://acme.test/en/job-openings/":
            return fake_response(text=listing_html, request_url=url)
        raise httpx.HTTPError("404")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "ashby",
        "identifier": "acme",
        "careers_url": "https://acme.test/en/job-openings/",
        "match_method": "page_scan",
    }


def test_workable_apply_subdomain_matches(monkeypatch):
    html = '<a href="https://apply.workable.com/plana/#jobs">Careers</a>'
    monkeypatch.setattr(
        resolve_ats, "get_with_retry", lambda url, **k: fake_response(text=html, request_url=url)
    )

    result = resolve_ats._detect_ats(_company())

    assert result == {
        "ats": "workable",
        "identifier": "plana",
        "careers_url": "https://acme.test",
        "match_method": "page_scan",
    }


def test_slug_candidates_strip_domain_noise_and_hyphenate_the_name():
    company = _company(name="Scalable Capital", url="https://de.scalable.capital")

    assert resolve_ats._slug_candidates(company) == ["scalable", "scalable-capital"]


def test_slug_candidates_dedupe_when_domain_and_name_agree():
    company = _company(name="Acme", url="https://acme.test")

    assert resolve_ats._slug_candidates(company) == ["acme"]


def test_names_match_is_fuzzy_and_case_insensitive():
    assert resolve_ats._names_match("GetYourGuide", "GetYourGuide GmbH") is True
    assert resolve_ats._names_match("Contentful", "Raisin") is False


def test_active_probe_finds_a_greenhouse_board_with_no_html_signature_anywhere(monkeypatch):
    # Verified live: GetYourGuide's own site never mentions "greenhouse" anywhere,
    # yet boards-api.greenhouse.io/v1/boards/getyourguide/jobs is a real board -
    # the passive HTML/JSON scan can never find this, only an active API probe can.
    def fake_get(url, **kwargs):
        if url == "https://boards-api.greenhouse.io/v1/boards/getyourguide/jobs?content=true":
            return fake_response(
                json={"jobs": [{"company_name": "GetYourGuide", "title": "QA Engineer"}]}
            )
        if "acme.test" in url:
            return fake_response(text="<p>no ats mentioned here</p>", request_url=url)
        raise httpx.HTTPError("not found")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    company = _company(name="GetYourGuide", url="https://acme.test")
    result = resolve_ats._detect_ats(company)

    assert result == {
        "ats": "greenhouse",
        "identifier": "getyourguide",
        "careers_url": None,
        "match_method": "api_probe",
    }


def test_active_probe_rejects_a_slug_whose_company_name_does_not_match(monkeypatch):
    # Guards against a coincidental slug collision with an unrelated company.
    def fake_get(url, **kwargs):
        if "greenhouse" in url:
            return fake_response(json={"jobs": [{"company_name": "Some Other Company"}]})
        raise httpx.HTTPError("not found")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._probe_all_platforms(_company(name="Acme"))

    assert result is None


def test_active_probe_accepts_an_empty_but_valid_board_with_no_name_to_check(monkeypatch):
    def fake_get(url, **kwargs):
        if url == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true":
            return fake_response(json={"jobs": []})
        raise httpx.HTTPError("not found")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._probe_all_platforms(_company(name="Acme"))

    assert result == {"ats": "greenhouse", "identifier": "acme"}


def test_active_probe_falls_through_to_lever_when_greenhouse_has_no_board(monkeypatch):
    def fake_get(url, **kwargs):
        if "greenhouse" in url:
            raise httpx.HTTPError("404")
        if url == "https://api.ashbyhq.com/posting-api/job-board/acme":
            raise httpx.HTTPError("404")
        if url == "https://api.lever.co/v0/postings/acme?mode=json":
            return fake_response(json=[{"text": "QA Engineer"}])
        raise httpx.HTTPError("not found")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._probe_all_platforms(_company(name="Acme"))

    assert result == {"ats": "lever", "identifier": "acme"}


def test_active_probe_finds_nothing_stays_unresolved(monkeypatch):
    def fake_get(url, **kwargs):
        raise httpx.HTTPError("404")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    result = resolve_ats._probe_all_platforms(_company(name="Acme"))

    assert result is None


def test_one_company_failing_does_not_stop_the_others(monkeypatch):
    def fake_get(url, **kwargs):
        if "broken" in url:
            raise RuntimeError("boom")
        return fake_response(text='<a href="https://jobs.lever.co/good">Careers</a>', request_url=url)

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    companies = [_company("Broken", "https://broken.test"), _company("Good", "https://good.test")]
    resolve_ats.resolve_all(companies)

    assert companies[0]["ats"] == "unresolved"
    assert companies[1]["ats"] == "lever"
    assert companies[1]["identifier"] == "good"


def test_default_run_only_resolves_null_or_custom_companies(monkeypatch, tmp_path):
    companies_path = tmp_path / "companies.yaml"
    companies_path.write_text(
        "companies:\n"
        "- name: AlreadyResolved\n"
        "  url: https://resolved.test\n"
        "  ats: lever\n"
        "  identifier: resolved\n"
        "- name: StillUnresolved\n"
        "  url: https://acme.test\n"
        "  ats: null\n"
        "  identifier: null\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(resolve_ats, "COMPANIES_PATH", companies_path)
    monkeypatch.setattr(resolve_ats, "REPORT_PATH", tmp_path / "report.md")

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return fake_response(text='<a href="https://jobs.lever.co/acme">Careers</a>', request_url=url)

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    resolve_ats.main([])

    assert "https://resolved.test" not in calls
    assert "https://acme.test" in calls


def test_force_flag_reresolves_every_company(monkeypatch, tmp_path):
    companies_path = tmp_path / "companies.yaml"
    companies_path.write_text(
        "companies:\n"
        "- name: AlreadyResolved\n"
        "  url: https://resolved.test\n"
        "  ats: lever\n"
        "  identifier: resolved\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(resolve_ats, "COMPANIES_PATH", companies_path)
    monkeypatch.setattr(resolve_ats, "REPORT_PATH", tmp_path / "report.md")

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return fake_response(text="<p>nothing here</p>", request_url=url)

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    resolve_ats.main(["--force"])

    assert "https://resolved.test" in calls


def test_is_new_entry_true_only_when_ats_is_null():
    # ats: null is reserved exclusively for "never attempted" - a real attempt
    # always leaves ats set to a vendor, "custom", or the literal string
    # "unresolved" (never back to null), so this check can be a plain `is None`.
    assert resolve_ats.is_new_entry(_company()) is True
    assert resolve_ats.is_new_entry({**_company(), "ats": None}) is True
    assert resolve_ats.is_new_entry({**_company(), "ats": "unresolved"}) is False
    assert resolve_ats.is_new_entry({**_company(), "ats": "custom"}) is False
    assert resolve_ats.is_new_entry({**_company(), "ats": "lever"}) is False


def test_resolve_pending_only_resolves_never_attempted_entries(monkeypatch, tmp_path):
    # A prior attempt that found nothing is stored as ats: "unresolved", not null -
    # resolve_pending() must not re-fetch it (unlike the CLI's own default, which
    # does), since the main.py caller runs this on every single invocation and
    # re-fetching an already-attempted dead/vendor-less careers page on every run
    # adds real latency for an outcome that essentially never changes.
    companies_path = tmp_path / "companies.yaml"
    companies_path.write_text(
        "companies:\n"
        "- name: AlreadyUnresolved\n"
        "  url: https://unresolved.test\n"
        "  ats: unresolved\n"
        "  identifier: null\n"
        "  resolved_at: '2026-01-01T00:00:00+00:00'\n"
        "- name: BrandNew\n"
        "  url: https://acme.test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(resolve_ats, "COMPANIES_PATH", companies_path)
    monkeypatch.setattr(resolve_ats, "REPORT_PATH", tmp_path / "report.md")

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return fake_response(text='<a href="https://jobs.lever.co/acme">Careers</a>', request_url=url)

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    resolved = resolve_ats.resolve_pending()

    assert "https://unresolved.test" not in calls
    assert "https://acme.test" in calls
    assert [c["name"] for c in resolved] == ["BrandNew"]


def test_resolve_pending_is_a_noop_when_no_company_is_new(monkeypatch, tmp_path):
    companies_path = tmp_path / "companies.yaml"
    companies_path.write_text(
        "companies:\n"
        "- name: AlreadyResolved\n"
        "  url: https://resolved.test\n"
        "  ats: lever\n"
        "  identifier: resolved\n"
        "  resolved_at: '2026-01-01T00:00:00+00:00'\n"
        "- name: AlreadyUnresolved\n"
        "  url: https://unresolved.test\n"
        "  ats: unresolved\n"
        "  identifier: null\n"
        "  resolved_at: '2026-01-01T00:00:00+00:00'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(resolve_ats, "COMPANIES_PATH", companies_path)

    def fake_get(url, **kwargs):
        raise AssertionError("resolve_pending() should not make any requests when nothing is new")

    monkeypatch.setattr(resolve_ats, "get_with_retry", fake_get)

    assert resolve_ats.resolve_pending() == []
