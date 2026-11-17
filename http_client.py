from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor

import httpx

import source_health

logger = logging.getLogger(__name__)

# 429 = rate limited (seen on Arbeitnow's search endpoint); 5xx = transient server
# error. Neither is worth retrying more than once here - a daily cron job can just
# pick a failed source/send back up on the next run rather than hammering a
# struggling server with more attempts.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_TIMEOUT = 30
DEFAULT_BACKOFF_SECONDS = 5
DEFAULT_MAX_RETRIES = 1
# Cap on a server's own Retry-After: a daily run can afford to wait a minute for a
# rate-limited host, not to stall on an hour-long value.
MAX_RETRY_AFTER_SECONDS = 60

# Telegram's Bot API puts the bot token directly in the URL path
# (api.telegram.org/bot<token>/sendMessage) - the only caller of this shared retry
# helper that embeds a live secret in the URL it passes in. Redacted before logging so
# a retry on that call doesn't put the token in plaintext into whatever this process's
# logs land in (cron output, persisted log files, etc).
_TELEGRAM_TOKEN_PATTERN = re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+(/)")


def _redact_url(url: str) -> str:
    return _TELEGRAM_TOKEN_PATTERN.sub(r"\1***REDACTED***\2", url)


def _retry_delay(response: httpx.Response, backoff_seconds: float) -> float:
    """A 429's own Retry-After (in seconds) when it sends one, capped - waiting
    exactly as long as the server asks beats retrying into the same limit after a
    fixed 5s (Workday tenants 429'd 45 of 50 companies that way, 2026-11-16/17)."""
    if response.status_code == 429:
        try:
            return min(float(response.headers.get("Retry-After", "")), MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            pass  # missing, or an HTTP date - fall back to the fixed backoff
    return backoff_seconds


def _request_with_retry(
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    """Every request's final outcome (after retries) is recorded against the source
    being fetched - see source_health.py."""
    try:
        response = _request_with_retry_unrecorded(method, url, **kwargs)
    except httpx.HTTPError:
        source_health.record_request(failed=True)
        raise
    source_health.record_request(failed=False)
    return response


def _request_with_retry_unrecorded(
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
            delay = _retry_delay(response, backoff_seconds)
            logger.warning(
                "%s %s returned %d, retrying in %ss (attempt %d/%d)",
                method,
                _redact_url(url),
                response.status_code,
                delay,
                attempt,
                max_retries,
            )
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response


def get_with_retry(url: str, **kwargs) -> httpx.Response:
    return _request_with_retry("GET", url, **kwargs)


def post_with_retry(url: str, **kwargs) -> httpx.Response:
    return _request_with_retry("POST", url, **kwargs)


def fetch_each[T, R](
    items: Iterable[T],
    fetch_one: Callable[[T], R],
    *,
    delay_seconds: float,
    logger: logging.Logger,
    log_context: str,
    give_up_after: int | None = None,
) -> Iterator[tuple[T, R]]:
    """Call fetch_one(item) for each item, spacing calls by delay_seconds and
    skipping (with a logged warning) any item whose fetch_one raises httpx.HTTPError -
    one bad request doesn't discard the results already gathered from the others.

    give_up_after: stop after this many failures in a row. For search loops against
    a host that is blocking or not answering, every further item fails the same way -
    StepStone timed out on all 26 search terms on some days, ~65s each with the
    retry, so ~25 minutes of each such run went to waiting. Not for description
    loops: a skipped description silently turns into the English bucket.
    """
    items = list(items)
    consecutive_failures = 0
    for i, item in enumerate(items):
        if give_up_after is not None and consecutive_failures >= give_up_after:
            logger.warning(
                "%s: %d failures in a row, skipping the remaining %d",
                log_context,
                consecutive_failures,
                len(items) - i,
            )
            return
        if i > 0:
            time.sleep(delay_seconds)
        try:
            result = fetch_one(item)
        except httpx.HTTPError as exc:
            consecutive_failures += 1
            logger.warning("%s failed for %r: %s", log_context, item, exc)
            continue
        consecutive_failures = 0
        yield item, result


_FAILED = object()


def fetch_each_concurrent[T, R](
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
    # Worker threads don't inherit the caller's context - carry over which source
    # these requests belong to, so their failures are counted against it.
    source = source_health.current()

    def _safe_fetch(item: T):
        try:
            with source_health.tracking(source):
                return fetch_one(item)
        except httpx.HTTPError as exc:
            logger.warning("%s failed for %r: %s", log_context, item, exc)
            return _FAILED

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for item, result in zip(items, executor.map(_safe_fetch, items), strict=True):
            if result is not _FAILED:
                yield item, result
