import pytest

import source_health
from adapters import registry
from adapters.registry import fetch_from_sources
from tests.conftest import make_job

_KEYWORDS = {"title_match_terms": ["qa engineer"]}


@pytest.fixture(autouse=True)
def _clean_tallies():
    source_health.reset()
    yield
    source_health.reset()


def _sources(**extra):
    return {"sources": [{"id": "blocked_board", "adapter": "fake_board", **extra}]}


def _fake_board(source_config):
    return [make_job(source_id=source_config["id"])]


def test_skip_in_ci_source_is_skipped_on_github_actions(monkeypatch):
    monkeypatch.setitem(registry.ADAPTERS, "fake_board", lambda _config: pytest.fail("should be skipped"))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert fetch_from_sources(_sources(skip_in_ci=True), _KEYWORDS, ["blocked_board"]) == []
    assert source_health.problems() == []  # a deliberate skip isn't a failure


def test_skip_in_ci_source_still_runs_locally(monkeypatch):
    monkeypatch.setitem(registry.ADAPTERS, "fake_board", _fake_board)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    jobs = fetch_from_sources(_sources(skip_in_ci=True), _KEYWORDS, ["blocked_board"])

    assert [job.source_id for job in jobs] == ["blocked_board"]


def test_crashing_source_is_reported(monkeypatch):
    def crash(_config):
        raise ValueError("unexpected page layout")

    monkeypatch.setitem(registry.ADAPTERS, "fake_board", crash)

    assert fetch_from_sources(_sources(), _KEYWORDS, ["blocked_board"]) == []
    assert source_health.problems() == ["blocked_board: failed completely"]
