from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# 429 = rate limited (seen on Arbeitnow's search endpoint); 5xx = transient server
# error. Neither is worth retrying more than once here - a daily cron job can just
# pick a failed source/send back up on the next run rather than hammering a
# struggling server with more attempts.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_TIMEOUT = 30
DEFAULT_BACKOFF_SECONDS = 5
DEFAULT_MAX_RETRIES = 1

# Telegram's Bot API puts the bot token directly in the URL path
# (api.telegram.org/bot<token>/sendMessage) - the only caller of this shared retry
# helper that embeds a live secret in the URL it passes in. Redacted before logging so
# a retry on that call doesn't put the token in plaintext into whatever this process's
# logs land in (cron output, persisted log files, etc).
_TELEGRAM_TOKEN_PATTERN = re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+(/)")


def _redact_url(url: str) -> str:
    return _TELEGRAM_TOKEN_PATTERN.sub(r"\1***REDACTED***\2", url)


def _request_with_retry(
    method: str,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    **kwargs,
) -> httpx.Response:
    """Bounded retry-after-backoff on rate-limit/transient-server-error status codes,
    and on connection-level failures (httpx.TransportError - covers ConnectError,
    ConnectTimeout, ReadTimeout, etc.). The latter turned out to matter once
    adapters.registry started fetching sources/companies concurrently instead of one
    at a time - several simultaneous DNS lookups from one process reliably tripped
    "nodename nor servname provided" on macOS's resolver (verified live: every one of
    98 concurrently-fetched companies failed this way on an unretried first attempt),
    something that was invisible when everything ran sequentially.
    Raises via response.raise_for_status() (or the original TransportError) on any
    non-retryable failure, or once retries are exhausted - callers decide whether to
    catch that (httpx.HTTPError) per-request (to keep partial results, e.g. one failed
    search term out of many) or let it propagate (to fail the whole call).
    """
    attempt = 0
    while True:
        try:
            response = httpx.request(method, url, timeout=timeout, follow_redirects=True, **kwargs)
        except httpx.TransportError as exc:
            if attempt >= max_retries:
                raise
            attempt += 1
            logger.warning(
                "%s %s failed (%s), retrying in %ss (attempt %d/%d)",
                method,
                _redact_url(url),
                type(exc).__name__,
                backoff_seconds,
                attempt,
                max_retries,
            )
            time.sleep(backoff_seconds)
            continue

        if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
            attempt += 1
            logger.warning(
                "%s %s returned %d, retrying in %ss (attempt %d/%d)",
                method,
                _redact_url(url),
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


def fetch_each(
    items: Iterable[T],
    fetch_one: Callable[[T], R],
    *,
    delay_seconds: float,
    logger: logging.Logger,
    log_context: str,
) -> Iterator[tuple[T, R]]:
    """Call fetch_one(item) for each item, spacing calls by delay_seconds and
    skipping (with a logged warning) any item whose fetch_one raises httpx.HTTPError -
    one bad request doesn't discard the results already gathered from the others.
    """
    for i, item in enumerate(items):
        if i > 0:
            time.sleep(delay_seconds)
        try:
            yield item, fetch_one(item)
        except httpx.HTTPError as exc:
            logger.warning("%s failed for %r: %s", log_context, item, exc)


_FAILED = object()


def fetch_each_concurrent(
    items: Iterable[T],
    fetch_one: Callable[[T], R],
    *,
    max_workers: int,
    logger: logging.Logger,
    log_context: str,
) -> Iterator[tuple[T, R]]:
    """Concurrent counterpart to fetch_each - same per-item exception handling and
    (item, result) yield contract (input order preserved), but overlaps up to
    max_workers requests instead of spacing every one of them by delay_seconds.

    Only worth it for a detail-page-per-item loop (dozens-to-hundreds of items, one
    board's own description-fetch pass) where fetch_each's fixed per-item delay was
    the dominant cost - every item here still hits the same host, so max_workers
    should stay modest (a handful) rather than unbounded, to avoid tripping that
    host's own rate limiting the way registry.py's cross-host fetch already
    demonstrated is possible for DNS resolution under too much concurrency.
    """
    items = list(items)

    def _safe_fetch(item: T):
        try:
            return fetch_one(item)
        except httpx.HTTPError as exc:
            logger.warning("%s failed for %r: %s", log_context, item, exc)
            return _FAILED

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for item, result in zip(items, executor.map(_safe_fetch, items)):
            if result is not _FAILED:
                yield item, result
