from agents import _common
from agents._common import fetch_from_sources
from tests.conftest import make_job


def _sources_config(*sources):
    return {"sources": list(sources)}


def test_fetches_from_known_source_with_search_terms_injected(monkeypatch):
    received_configs = []

    def fake_fetch(source_config):
        received_configs.append(source_config)
        return [make_job(source_id=source_config["id"])]

    monkeypatch.setitem(_common.ADAPTERS, "fake_adapter", fake_fetch)

    sources_config = _sources_config({"id": "board_a", "adapter": "fake_adapter"})
    keywords_config = {"title_match_terms": ["qa engineer"]}

    jobs = fetch_from_sources(sources_config, keywords_config, ["board_a"])

    assert [job.source_id for job in jobs] == ["board_a"]
    assert received_configs[0]["search_terms"] == ["qa engineer"]
    assert received_configs[0]["id"] == "board_a"


def test_unknown_source_id_is_skipped_without_raising():
    sources_config = _sources_config({"id": "board_a", "adapter": "fake_adapter"})
    keywords_config = {"title_match_terms": []}

    jobs = fetch_from_sources(sources_config, keywords_config, ["does_not_exist"])

    assert jobs == []


def test_unregistered_adapter_name_is_skipped_without_raising():
    sources_config = _sources_config({"id": "board_a", "adapter": "some_todo_adapter"})
    keywords_config = {"title_match_terms": []}

    jobs = fetch_from_sources(sources_config, keywords_config, ["board_a"])

    assert jobs == []


def test_one_source_failing_does_not_stop_the_others(monkeypatch):
    def failing_fetch(source_config):
        raise RuntimeError("boom")

    def working_fetch(source_config):
        return [make_job(source_id=source_config["id"])]

    monkeypatch.setitem(_common.ADAPTERS, "failing_adapter", failing_fetch)
    monkeypatch.setitem(_common.ADAPTERS, "working_adapter", working_fetch)

    sources_config = _sources_config(
        {"id": "broken_board", "adapter": "failing_adapter"},
        {"id": "good_board", "adapter": "working_adapter"},
    )
    keywords_config = {"title_match_terms": []}

    jobs = fetch_from_sources(sources_config, keywords_config, ["broken_board", "good_board"])

    assert [job.source_id for job in jobs] == ["good_board"]
