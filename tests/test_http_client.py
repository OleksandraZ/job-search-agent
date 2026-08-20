import httpx
import pytest

import http_client


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("GET", "https://example.test/"))


def test_succeeds_on_first_try_without_sleeping(monkeypatch):
    monkeypatch.setattr(http_client.httpx, "request", lambda *a, **k: _response(200))
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: pytest.fail("should not sleep"))

    response = http_client.get_with_retry("https://example.test/")

    assert response.status_code == 200


def test_retries_once_on_429_then_succeeds(monkeypatch):
    responses = iter([_response(429), _response(200)])
    monkeypatch.setattr(http_client.httpx, "request", lambda *a, **k: next(responses))
    sleeps = []
    monkeypatch.setattr(http_client.time, "sleep", lambda s: sleeps.append(s))

    response = http_client.get_with_retry("https://example.test/")

    assert response.status_code == 200
    assert sleeps == [http_client.DEFAULT_BACKOFF_SECONDS]


def test_raises_once_retries_are_exhausted(monkeypatch):
    monkeypatch.setattr(http_client.httpx, "request", lambda *a, **k: _response(503))
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    with pytest.raises(httpx.HTTPStatusError):
        http_client.get_with_retry("https://example.test/")


def test_non_retryable_status_raises_immediately_without_sleeping(monkeypatch):
    monkeypatch.setattr(http_client.httpx, "request", lambda *a, **k: _response(404))
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: pytest.fail("should not sleep"))

    with pytest.raises(httpx.HTTPStatusError):
        http_client.get_with_retry("https://example.test/")


def test_retries_once_on_connect_error_then_succeeds(monkeypatch):
    attempts = iter([httpx.ConnectError("nodename nor servname provided, or not known"), _response(200)])

    def fake_request(*a, **k):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(http_client.httpx, "request", fake_request)
    sleeps = []
    monkeypatch.setattr(http_client.time, "sleep", lambda s: sleeps.append(s))

    response = http_client.get_with_retry("https://example.test/")

    assert response.status_code == 200
    assert sleeps == [http_client.DEFAULT_BACKOFF_SECONDS]


def test_raises_once_connect_error_retries_are_exhausted(monkeypatch):
    def fake_request(*a, **k):
        raise httpx.ConnectError("nodename nor servname provided, or not known")

    monkeypatch.setattr(http_client.httpx, "request", fake_request)
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    with pytest.raises(httpx.ConnectError):
        http_client.get_with_retry("https://example.test/")


def test_retry_warning_redacts_telegram_bot_token(monkeypatch, caplog):
    responses = iter([_response(429), _response(200)])
    monkeypatch.setattr(http_client.httpx, "request", lambda *a, **k: next(responses))
    monkeypatch.setattr(http_client.time, "sleep", lambda *_: None)

    with caplog.at_level("WARNING"):
        http_client.post_with_retry("https://api.telegram.org/bot123456:secretvalue/sendMessage")

    assert "secretvalue" not in caplog.text
    assert "bot***REDACTED***" in caplog.text


def test_get_and_post_with_retry_dispatch_correct_http_method(monkeypatch):
    methods = []
    monkeypatch.setattr(
        http_client.httpx, "request", lambda method, url, **k: methods.append(method) or _response(200)
    )

    http_client.get_with_retry("https://example.test/")
    http_client.post_with_retry("https://example.test/")

    assert methods == ["GET", "POST"]


def test_fetch_each_concurrent_preserves_input_order():
    results = list(
        http_client.fetch_each_concurrent(
            [1, 2, 3, 4],
            lambda i: i * 10,
            max_workers=4,
            logger=http_client.logger,
            log_context="test",
        )
    )

    assert results == [(1, 10), (2, 20), (3, 30), (4, 40)]


def test_fetch_each_concurrent_skips_failed_items_without_stopping_others():
    def fetch_one(i):
        if i == 2:
            raise httpx.ConnectError("boom")
        return i * 10

    results = list(
        http_client.fetch_each_concurrent(
            [1, 2, 3],
            fetch_one,
            max_workers=4,
            logger=http_client.logger,
            log_context="test",
        )
    )

    assert results == [(1, 10), (3, 30)]
