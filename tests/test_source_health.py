import httpx
import pytest

import http_client
import source_health


@pytest.fixture(autouse=True)
def _clean_tallies():
    source_health.reset()
    yield
    source_health.reset()


def _requests(results: list[bool]) -> None:
    for failed in results:
        source_health.record_request(failed=failed)


def test_healthy_run_reports_nothing():
    with source_health.board("stepstone_germany"):
        _requests([False] * 10 + [True])  # one failed detail page is noise
    assert source_health.problems() == []


def test_board_with_most_requests_failing_is_reported():
    # The real 2026-10-29..11-17 case: every stellenanzeigen.de search 403'd.
    with source_health.board("stellenanzeigende"):
        _requests([True] * 26)
    assert source_health.problems() == ["stellenanzeigende: 26 of 26 requests failed"]


def test_board_whose_fetch_crashed_is_reported():
    with source_health.board("bundesagentur"):
        _requests([False])
        source_health.record_crash()
    assert source_health.problems() == ["bundesagentur: failed completely"]


def test_vendor_reported_when_many_of_its_companies_fail():
    for i in range(50):
        with source_health.company("workday", f"Company {i}"):
            if i < 45:
                source_health.record_crash()
            else:
                _requests([False])
    assert source_health.problems() == ["workday companies: 45 of 50 failed"]


def test_single_dead_company_is_not_a_daily_alarm():
    for i in range(10):
        with source_health.company("personio", f"Company {i}"):
            _requests([i == 0])
    assert source_health.problems() == []


def test_requests_outside_any_source_are_ignored():
    _requests([True, True])
    assert source_health.problems() == []


def test_http_client_records_final_outcome_after_retries(monkeypatch):
    responses = iter([httpx.Response(503, request=httpx.Request("GET", "https://x.test/"))] * 2)
    monkeypatch.setattr(http_client.httpx, "request", lambda *a, **k: next(responses))
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    with source_health.board("flaky"), pytest.raises(httpx.HTTPStatusError):
        http_client.get_with_retry("https://x.test/")

    # One request with one retry is one failure, not two.
    assert source_health.problems() == ["flaky: 1 of 1 requests failed"]


def test_concurrent_fetch_counts_worker_requests_against_the_caller(monkeypatch):
    def fake_request(*_args, **_kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(http_client.httpx, "request", fake_request)
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    with source_health.board("devjobs"):
        results = list(
            http_client.fetch_each_concurrent(
                ["a", "b"],
                lambda url: http_client.get_with_retry(f"https://x.test/{url}"),
                max_workers=2,
                logger=http_client.logger,
                log_context="test",
            )
        )

    assert results == []
    assert source_health.problems() == ["devjobs: 2 of 2 requests failed"]
