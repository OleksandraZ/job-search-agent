import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from adapters.boards import NormalizedJob
from pipeline.duplicates import duplicate_key

DB_PATH = Path(__file__).parent / "jobs.db"

# A job counts as already seen if a job with the same duplicate_key (normalized
# title + company, pipeline/duplicates.py) was seen within this window - whatever
# its URL or board - or one with the same source + URL (a listing retitled in place).
# "Seen" means last_seen_at: refreshed on every real run in which the job still
# shows up, so a continuously listed job is never resent; only one that vanished for
# this long and then reappears counts as new again. 90 days covers
# every real repeat pattern in the 2026-10-06 data (longest: ~7 weeks) - user
# decision 2026-10-06.
SEEN_WINDOW = timedelta(days=90)


def _job_id(job: NormalizedJob) -> str:
    return hashlib.sha256(f"{job.source_id}:{job.url}".encode()).hexdigest()


def init_db(db_path: Path) -> None:
    """Create the table, or migrate an older one in place: rows written before
    duplicate detection existed get dup_key computed from their stored title/company
    and last_seen_at = first_seen_at, so jobs sent before the migration are
    recognized immediately on their next reappearance."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                dup_key TEXT,
                last_seen_at TEXT
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(seen_jobs)")}
        if "dup_key" not in columns:
            conn.execute("ALTER TABLE seen_jobs ADD COLUMN dup_key TEXT")
        if "last_seen_at" not in columns:
            conn.execute("ALTER TABLE seen_jobs ADD COLUMN last_seen_at TEXT")

        legacy = conn.execute(
            "SELECT job_id, title, company FROM seen_jobs WHERE dup_key IS NULL"
        ).fetchall()
        conn.executemany(
            "UPDATE seen_jobs SET dup_key = ?, last_seen_at = COALESCE(last_seen_at, first_seen_at)"
            " WHERE job_id = ?",
            [
                (duplicate_key(NormalizedJob("", title, company, "", "", "")), job_id)
                for job_id, title, company in legacy
            ],
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_jobs_dup_key ON seen_jobs (dup_key)")
        conn.commit()


def _recent(conn: sqlite3.Connection, now: datetime) -> tuple[set[str], set[str]]:
    """(duplicate keys, job_ids) seen within SEEN_WINDOW. Read-only: on a
    not-yet-migrated DB the key/last-seen values are derived in memory (same rule as
    init_db's backfill), so a --dry-run never writes to jobs.db - a locally modified
    jobs.db would block the next `git pull --rebase` against the bot's daily commit."""
    cutoff = (now - SEEN_WINDOW).isoformat()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(seen_jobs)")}
    if not columns:
        return set(), set()
    if "dup_key" in columns:
        rows = conn.execute(
            "SELECT job_id, title, company, dup_key, COALESCE(last_seen_at, first_seen_at)"
            " FROM seen_jobs"
        ).fetchall()
    else:
        legacy = conn.execute("SELECT job_id, title, company, first_seen_at FROM seen_jobs").fetchall()
        rows = [(job_id, title, company, None, first_seen) for job_id, title, company, first_seen in legacy]
    recent = [row for row in rows if row[4] >= cutoff]
    keys = {
        key or duplicate_key(NormalizedJob("", title, company, "", "", ""))
        for _, title, company, key, _ in recent
    }
    return keys, {job_id for job_id, *_ in recent}


def filter_unseen(
    jobs: list[NormalizedJob], db_path: Path, now: datetime | None = None
) -> list[NormalizedJob]:
    """Jobs seen within SEEN_WINDOW neither under their duplicate_key nor under their
    source+URL. The URL check catches a listing retitled in place (medatixx on
    Bundesagentur, 2026-10-13: "Softwaretester ..." -> "Spezialist ..." under the same
    URL), which the title-based key alone treats as a new job. Read-only - never
    creates or migrates the DB."""
    if not db_path.exists():
        return list(jobs)
    with closing(sqlite3.connect(db_path)) as conn:
        keys, job_ids = _recent(conn, now or datetime.now(UTC))
    return [job for job in jobs if duplicate_key(job) not in keys and _job_id(job) not in job_ids]


def mark_seen(jobs: list[NormalizedJob], db_path: Path, now: datetime | None = None) -> None:
    """Record jobs as seen now. Pass every copy of a sent job (all boards/cities),
    not just the one whose link was shown. A row already stored under the same
    source+URL takes the job's current title/company/dup_key: employers retitle
    listings in place (medatixx on Bundesagentur, 2026-10-13), and keeping the old
    key would make filter_unseen treat the new title as unseen on every run."""
    if not jobs:
        return

    init_db(db_path)
    timestamp = (now or datetime.now(UTC)).isoformat()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executemany(
            """
            INSERT INTO seen_jobs (job_id, title, company, first_seen_at, dup_key, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                dup_key = excluded.dup_key,
                last_seen_at = excluded.last_seen_at
            """,
            [
                (_job_id(job), job.title, job.company, timestamp, duplicate_key(job), timestamp)
                for job in jobs
            ],
        )
        conn.commit()


def refresh_seen(jobs: list[NormalizedJob], db_path: Path, now: datetime | None = None) -> None:
    """Bump last_seen_at for every already-recorded job these jobs duplicate or share
    a source+URL with - call with all jobs that still matched in a real run, so
    continuously listed jobs stay 'seen' instead of expiring after SEEN_WINDOW and
    being resent (a retitled listing only matches its row by URL)."""
    if not jobs or not db_path.exists():
        return

    init_db(db_path)
    timestamp = (now or datetime.now(UTC)).isoformat()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executemany(
            "UPDATE seen_jobs SET last_seen_at = ? WHERE dup_key = ? OR job_id = ?",
            [(timestamp, duplicate_key(job), _job_id(job)) for job in jobs],
        )
        conn.commit()
