from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

# 429 = rate limited (seen on Arbeitnow's search endpoint); 5xx = transient server
# error. Neither is worth retrying more than once here - a daily cron job can just
# pick a failed source/send back up on the next run rather than hammering a
# struggling server with more attempts.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_TIMEOUT = 30
DEFAULT_BACKOFF_SECONDS = 5
DEFAULT_MAX_RETRIES = 1


def _request_with_retry(
    method: str,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    **kwargs,
) -> httpx.Response:
    """Bounded retry-after-backoff on rate-limit/transient-server-error status codes.
    Raises via response.raise_for_status() on any non-retryable error status, or once
    retries are exhausted - callers decide whether to catch that (httpx.HTTPError)
    per-request (to keep partial results, e.g. one failed search term out of many) or
    let it propagate (to fail the whole call).
    """
    attempt = 0
    while True:
        response = httpx.request(method, url, timeout=timeout, follow_redirects=True, **kwargs)
        if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
            attempt += 1
            logger.warning(
                "%s %s returned %d, retrying in %ss (attempt %d/%d)",
                method,
                url,
                response.status_code,
                backoff_seconds,
                attempt,
                max_retries,
            )
            time.sleep(backoff_seconds)
            continue
        response.raise_for_status()
        return response


def get_with_retry(url: str, **kwargs) -> httpx.Response:
    return _request_with_retry("GET", url, **kwargs)


def post_with_retry(url: str, **kwargs) -> httpx.Response:
    return _request_with_retry("POST", url, **kwargs)
