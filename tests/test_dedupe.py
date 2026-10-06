import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

from storage.dedupe import SEEN_WINDOW, filter_unseen, init_db, mark_seen, refresh_seen
from tests.conftest import make_job

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_init_db_creates_table_and_is_idempotent(tmp_path):
    db_path = tmp_path / "jobs.db"
    init_db(db_path)
    init_db(db_path)  # must not raise on re-init

    with closing(sqlite3.connect(db_path)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "seen_jobs" in tables


def test_filter_unseen_returns_everything_against_empty_db(tmp_path):
    db_path = tmp_path / "jobs.db"
    jobs = [make_job(title="QA Engineer"), make_job(title="Test Engineer", url="https://example.test/2")]
    assert filter_unseen(jobs, db_path=db_path) == jobs


def test_mark_seen_then_filter_unseen_excludes_marked_jobs(tmp_path):
    db_path = tmp_path / "jobs.db"
    seen_job = make_job(title="QA Engineer", url="https://example.test/1")
    new_job = make_job(title="Test Engineer", url="https://example.test/2")

    mark_seen([seen_job], db_path=db_path, now=NOW)

    assert filter_unseen([seen_job, new_job], db_path=db_path, now=NOW) == [new_job]


def test_same_job_on_another_board_or_url_counts_as_seen(tmp_path):
    # Real case: one Blackwave posting was sent 21 times - Xing's tracking parameters
    # gave it a new URL every few days, and other boards listed it too.
    db_path = tmp_path / "jobs.db"
    mark_seen(
        [make_job(source_id="xing_jobs", title="Quality Engineer (m/w/d) Aerospace", company="Blackwave GmbH",
                  url="https://www.yourfirm.de/job/detail/YF-51679/?location_hash=E40B4DCE")],
        db_path=db_path, now=NOW,
    )
    repost = make_job(source_id="xing_jobs", title="Quality Engineer (m/w/d) Aerospace",
                      company="Blackwave GmbH",
                      url="https://www.yourfirm.de/job/detail/YF-51679/?location_hash=8E7D8886")
    other_board = make_job(source_id="stellenanzeigende", title="Quality Engineer - m/w/d Aerospace",
                           company="Blackwave", url="https://www.stellenanzeigen.de/job/yf-51679")
    assert filter_unseen([repost, other_board], db_path=db_path, now=NOW + timedelta(days=3)) == []


def test_job_counts_as_new_again_after_the_seen_window(tmp_path):
    db_path = tmp_path / "jobs.db"
    job = make_job(title="QA Engineer")
    mark_seen([job], db_path=db_path, now=NOW)

    assert filter_unseen([job], db_path=db_path, now=NOW + SEEN_WINDOW - timedelta(days=1)) == []
    assert filter_unseen([job], db_path=db_path, now=NOW + SEEN_WINDOW + timedelta(days=1)) == [job]


def test_refresh_seen_keeps_a_continuously_listed_job_seen(tmp_path):
    db_path = tmp_path / "jobs.db"
    job = make_job(title="QA Engineer")
    mark_seen([job], db_path=db_path, now=NOW)

    # Still listed (under a new URL) 80 days later - a real run refreshes it.
    refresh_seen([make_job(title="QA Engineer", url="https://example.test/new")], db_path=db_path,
                 now=NOW + timedelta(days=80))

    assert filter_unseen([job], db_path=db_path, now=NOW + SEEN_WINDOW + timedelta(days=30)) == []


def test_init_db_migrates_an_old_table_and_backfills_duplicate_keys(tmp_path):
    db_path = tmp_path / "jobs.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "CREATE TABLE seen_jobs (job_id TEXT PRIMARY KEY, title TEXT NOT NULL,"
            " company TEXT NOT NULL, first_seen_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO seen_jobs VALUES ('old-id', 'QA Engineer (m/w/d)', 'JetBrains GmbH', ?)",
            (NOW.isoformat(),),
        )
        conn.commit()

    init_db(db_path)  # what the first real run's mark_seen/refresh_seen does

    repost = make_job(title="QA Engineer", company="JetBrains", url="https://example.test/new-url")
    assert filter_unseen([repost], db_path=db_path, now=NOW + timedelta(days=10)) == []

    with closing(sqlite3.connect(db_path)) as conn:
        dup_key, last_seen = conn.execute("SELECT dup_key, last_seen_at FROM seen_jobs").fetchone()
    assert dup_key == "qa engineer|jetbrains"
    assert last_seen == NOW.isoformat()


def test_mark_seen_with_empty_list_does_not_touch_db(tmp_path):
    db_path = tmp_path / "jobs.db"
    mark_seen([], db_path=db_path)
    assert not db_path.exists()


def test_refresh_seen_does_not_create_a_db(tmp_path):
    db_path = tmp_path / "jobs.db"
    refresh_seen([make_job()], db_path=db_path)
    assert not db_path.exists()


def test_filter_unseen_is_read_only_on_an_old_db(tmp_path):
    # A --dry-run must not migrate (= modify) a git-tracked jobs.db.
    db_path = tmp_path / "jobs.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "CREATE TABLE seen_jobs (job_id TEXT PRIMARY KEY, title TEXT NOT NULL,"
            " company TEXT NOT NULL, first_seen_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO seen_jobs VALUES ('id', 'QA Engineer', 'Acme', ?)", (NOW.isoformat(),))
        conn.commit()
    before = db_path.read_bytes()

    repost = make_job(title="QA Engineer (m/w/d)", company="Acme GmbH", url="https://example.test/new")
    assert filter_unseen([repost], db_path=db_path, now=NOW + timedelta(days=1)) == []
    assert db_path.read_bytes() == before


def test_filter_unseen_does_not_create_a_db(tmp_path):
    db_path = tmp_path / "jobs.db"
    assert filter_unseen([make_job()], db_path=db_path) == [make_job()]
    assert not db_path.exists()
