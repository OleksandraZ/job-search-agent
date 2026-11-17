"""Which sources failed during this run - so a quiet day and a broken run don't look
the same in Telegram.

Every adapter catches its own request errors and keeps going (one failed search
term mustn't discard the rest), and adapters.registry catches a whole source
failing. That keeps a run alive, but it also made failures invisible:
stellenanzeigen.de 403'd every request from GitHub Actions for three weeks
(2026-10-29..11-17) and Workday rate-limited 45 of 50 companies on 3 of 4
"no new jobs" days, while every run reported success.

adapters.registry wraps each source/company fetch in board()/company(); http_client
records every request's final outcome (after its retries) against whatever the
current thread is fetching for. main.py turns the totals into warning lines.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

# A board/company counts as failing once at least this share of its requests failed.
# Single failures are normal noise (one detail page 404s, one search times out).
FAILURE_SHARE = 0.5
# A whole ATS vendor is reported once this share of its companies failed - a single
# dead company endpoint is the weekly re-check's job, not a daily alarm.
VENDOR_FAILURE_SHARE = 0.25
VENDOR_MIN_FAILED_COMPANIES = 3


@dataclass
class _Tally:
    requests: int = 0
    failures: int = 0
    crashed: bool = False

    def failing(self) -> bool:
        return self.crashed or (self.requests > 0 and self.failures / self.requests >= FAILURE_SHARE)


# (kind, group, name): ("board", source_id, source_id) or ("company", ats vendor, company name)
Key = tuple[str, str, str]

_current: ContextVar[Key | None] = ContextVar("source_health_current", default=None)
_tallies: dict[Key, _Tally] = {}
_lock = threading.Lock()


def reset() -> None:
    with _lock:
        _tallies.clear()


def current() -> Key | None:
    """What the current thread is fetching for - lets a helper that starts its own
    worker threads (http_client.fetch_each_concurrent) carry it over to them."""
    return _current.get()


@contextmanager
def tracking(key: Key | None) -> Iterator[None]:
    token = _current.set(key)
    if key is not None:
        with _lock:
            _tallies.setdefault(key, _Tally())
    try:
        yield
    finally:
        _current.reset(token)


def board(source_id: str):
    return tracking(("board", source_id, source_id))


def company(vendor: str, name: str):
    return tracking(("company", vendor, name))


def record_request(failed: bool) -> None:
    key = _current.get()
    if key is None:
        return
    with _lock:
        tally = _tallies.setdefault(key, _Tally())
        tally.requests += 1
        tally.failures += failed


def record_crash() -> None:
    """The whole fetch raised - nothing from this source/company made it through."""
    key = _current.get()
    if key is None:
        return
    with _lock:
        _tallies.setdefault(key, _Tally()).crashed = True


def problems() -> list[str]:
    """One human-readable line per failing board / ATS vendor, worst first."""
    with _lock:
        tallies = dict(_tallies)

    lines: list[tuple[float, str]] = []
    vendors: dict[str, list[_Tally]] = {}
    for (kind, group, _name), tally in tallies.items():
        if kind == "company":
            vendors.setdefault(group, []).append(tally)
        elif tally.failing():
            if tally.requests and not (tally.crashed and tally.failures < tally.requests):
                detail = f"{tally.failures} of {tally.requests} requests failed"
                lines.append((tally.failures / tally.requests, f"{group}: {detail}"))
            else:
                lines.append((1.0, f"{group}: failed completely"))

    for vendor, company_tallies in vendors.items():
        failed = sum(t.failing() for t in company_tallies)
        share = failed / len(company_tallies)
        if failed >= VENDOR_MIN_FAILED_COMPANIES and share >= VENDOR_FAILURE_SHARE:
            lines.append((share, f"{vendor} companies: {failed} of {len(company_tallies)} failed"))

    return [text for _share, text in sorted(lines, key=lambda line: -line[0])]
