from __future__ import annotations

import logging
from datetime import datetime

import httpx

from adapters.boards import NormalizedJob
from http_client import post_with_retry

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def _entry(i: int, job: NormalizedJob) -> str:
    return f"{i}. {job.title} — {job.company} ({job.location})\n   {job.url}"


def _blocks(
    german_jobs: list[NormalizedJob], english_jobs: list[NormalizedJob]
) -> list[tuple[str, NormalizedJob | None]]:
    """Header/section-header/per-job blocks, each paired with the job it represents
    (None for the date header and the two section headers) so a chunk built from
    these blocks can report exactly which jobs it contains.
    """
    date_str = datetime.now().strftime("%d.%m.%Y")
    blocks: list[tuple[str, NormalizedJob | None]] = [(f"📅 {date_str} — New QA jobs", None)]

    if english_jobs:
        blocks.append((f"🇬🇧 English-speaking ({len(english_jobs)})", None))
        blocks.extend((_entry(i, job), job) for i, job in enumerate(english_jobs, 1))
    if german_jobs:
        blocks.append((f"🇩🇪 German-speaking ({len(german_jobs)})", None))
        blocks.extend((_entry(i, job), job) for i, job in enumerate(german_jobs, 1))

    return blocks


def _pack_chunks(blocks: list[tuple[str, NormalizedJob | None]]) -> list[tuple[str, list[NormalizedJob]]]:
    """Greedily pack blocks into chunks under Telegram's length limit, each chunk
    paired with the jobs whose blocks it contains.
    """
    chunks = []
    current_parts: list[str] = []
    current_jobs: list[NormalizedJob] = []
    current_len = 0
    for text, job in blocks:
        if current_parts and current_len + len(text) + 2 > TELEGRAM_MAX_MESSAGE_LENGTH:
            chunks.append(("\n\n".join(current_parts), current_jobs))
            current_parts = []
            current_jobs = []
            current_len = 0
        current_parts.append(text)
        if job is not None:
            current_jobs.append(job)
        current_len += len(text) + 2

    if current_parts:
        chunks.append(("\n\n".join(current_parts), current_jobs))
    return chunks


def format_message(german_jobs: list[NormalizedJob], english_jobs: list[NormalizedJob]) -> list[str]:
    """Format the EN/DE-split report into one or more messages, each under Telegram's length limit."""
    if not german_jobs and not english_jobs:
        return ["No new QA jobs today."]
    return [text for text, _jobs in _pack_chunks(_blocks(german_jobs, english_jobs))]


def send_message(text: str, bot_token: str, chat_id: str) -> dict:
    url = TELEGRAM_API_URL.format(token=bot_token)
    response = post_with_retry(
        url,
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
    )
    return response.json()


def send_report(
    german_jobs: list[NormalizedJob], english_jobs: list[NormalizedJob], bot_token: str, chat_id: str
) -> list[NormalizedJob]:
    """Send each chunk in order, stopping at the first failure rather than raising.
    Returns only the jobs whose chunk actually sent, so the caller marks exactly
    those as seen - a job in a later, undelivered chunk is retried next run instead
    of being silently dropped or resent as a duplicate alongside jobs that already
    went out.
    """
    if not german_jobs and not english_jobs:
        send_message("No new QA jobs today.", bot_token, chat_id)
        return []

    total = len(german_jobs) + len(english_jobs)
    sent_jobs: list[NormalizedJob] = []
    for text, jobs_in_chunk in _pack_chunks(_blocks(german_jobs, english_jobs)):
        try:
            send_message(text, bot_token, chat_id)
        except httpx.HTTPError as exc:
            logger.warning(
                "telegram send failed after delivering %d/%d jobs - remainder will be retried next run: %s",
                len(sent_jobs),
                total,
                exc,
            )
            break
        sent_jobs.extend(jobs_in_chunk)
    return sent_jobs
