import sqlite3
from contextlib import closing

from pipeline.dedupe import filter_unseen, init_db, mark_seen
from tests.conftest import make_job


def test_init_db_creates_table_and_is_idempotent(tmp_path):
    db_path = tmp_path / "jobs.db"
    init_db(db_path)
    init_db(db_path)  # must not raise on re-init

    with closing(sqlite3.connect(db_path)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "seen_jobs" in tables


def test_filter_unseen_returns_everything_against_empty_db(tmp_path):
    db_path = tmp_path / "jobs.db"
    jobs = [make_job(url="https://example.test/1"), make_job(url="https://example.test/2")]
    assert filter_unseen(jobs, db_path=db_path) == jobs


def test_mark_seen_then_filter_unseen_excludes_marked_jobs(tmp_path):
    db_path = tmp_path / "jobs.db"
    seen_job = make_job(url="https://example.test/1")
    new_job = make_job(url="https://example.test/2")

    mark_seen([seen_job], db_path=db_path)

    assert filter_unseen([seen_job, new_job], db_path=db_path) == [new_job]


def test_job_id_depends_on_both_source_id_and_url(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_a = make_job(source_id="board_a", url="https://example.test/1")
    mark_seen([job_a], db_path=db_path)

    same_source_same_url = make_job(source_id="board_a", url="https://example.test/1")
    different_source_same_url = make_job(source_id="board_b", url="https://example.test/1")

    unseen = filter_unseen([same_source_same_url, different_source_same_url], db_path=db_path)

    assert unseen == [different_source_same_url]


def test_mark_seen_with_empty_list_does_not_touch_db(tmp_path):
    db_path = tmp_path / "jobs.db"
    mark_seen([], db_path=db_path)
    assert not db_path.exists()
