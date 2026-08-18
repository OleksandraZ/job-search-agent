import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from adapters.boards import NormalizedJob

DB_PATH = Path(__file__).parent.parent / "storage" / "jobs.db"


def _job_id(job: NormalizedJob) -> str:
    return hashlib.sha256(f"{job.source_id}:{job.url}".encode("utf-8")).hexdigest()


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                first_seen_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def filter_unseen(jobs: list[NormalizedJob], db_path: Path = DB_PATH) -> list[NormalizedJob]:
    init_db(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        seen_ids = {row[0] for row in conn.execute("SELECT job_id FROM seen_jobs")}
    return [job for job in jobs if _job_id(job) not in seen_ids]


def mark_seen(jobs: list[NormalizedJob], db_path: Path = DB_PATH) -> None:
    if not jobs:
        return

    init_db(db_path)
    first_seen_at = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO seen_jobs (job_id, title, company, first_seen_at)
            VALUES (?, ?, ?, ?)
            """,
            [(_job_id(job), job.title, job.company, first_seen_at) for job in jobs],
        )
        conn.commit()
