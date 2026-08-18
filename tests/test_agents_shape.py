import pytest

from agents import germany_remote, munich_local
from tests.conftest import make_job


@pytest.mark.parametrize("agent", [munich_local, germany_remote])
def test_source_ids_are_non_empty(agent):
    assert len(agent.SOURCE_IDS) > 0


def test_both_agents_share_the_same_source_ids():
    # main.py fetches once via the union of both agents' SOURCE_IDS rather than
    # calling each agent's run() separately - that only avoids doubling request
    # volume if both lists are actually the same set.
    assert set(munich_local.SOURCE_IDS) == set(germany_remote.SOURCE_IDS)


def test_munich_local_filter_jobs_delegates_to_is_munich():
    munich_job = make_job(location="München")
    other_job = make_job(location="Hamburg")

    assert munich_local.filter_jobs([munich_job, other_job]) == [munich_job]


def test_germany_remote_filter_jobs_delegates_to_is_remote():
    remote_job = make_job(location="Fully Remote")
    other_job = make_job(location="Hamburg")

    assert germany_remote.filter_jobs([remote_job, other_job]) == [remote_job]


def test_munich_local_run_composes_fetch_and_filter(monkeypatch):
    munich_job = make_job(location="München")
    other_job = make_job(location="Hamburg", url="https://example.test/other")

    monkeypatch.setattr(munich_local, "fetch_from_sources", lambda *a, **k: [munich_job, other_job])

    jobs = munich_local.run(sources_config={}, keywords_config={})

    assert jobs == [munich_job]
