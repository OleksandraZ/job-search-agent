from agents import _common, germany_remote, munich_local
from tests.conftest import make_job


def test_source_ids_are_non_empty():
    assert len(_common.SOURCE_IDS) > 0


def test_munich_local_filter_jobs_delegates_to_is_munich():
    munich_job = make_job(location="München")
    other_job = make_job(location="Hamburg")

    assert munich_local.filter_jobs([munich_job, other_job]) == [munich_job]


def test_germany_remote_filter_jobs_delegates_to_is_remote():
    remote_job = make_job(location="Fully Remote")
    other_job = make_job(location="Hamburg")

    assert germany_remote.filter_jobs([remote_job, other_job]) == [remote_job]
