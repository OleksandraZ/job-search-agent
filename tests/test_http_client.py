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


def test_get_and_post_with_retry_dispatch_correct_http_method(monkeypatch):
    methods = []
    monkeypatch.setattr(
        http_client.httpx, "request", lambda method, url, **k: methods.append(method) or _response(200)
    )

    http_client.get_with_retry("https://example.test/")
    http_client.post_with_retry("https://example.test/")

    assert methods == ["GET", "POST"]
