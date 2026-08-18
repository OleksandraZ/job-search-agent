from datetime import datetime

from adapters.boards import NormalizedJob
from http_client import post_with_retry

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def _entries(jobs: list[NormalizedJob]) -> list[str]:
    return [
        f"{i}. {job.title} — {job.company} ({job.location})\n   {job.url}" for i, job in enumerate(jobs, 1)
    ]


def format_message(german_jobs: list[NormalizedJob], english_jobs: list[NormalizedJob]) -> list[str]:
    """Format the EN/DE-split report into one or more messages, each under Telegram's length limit."""
    if not german_jobs and not english_jobs:
        return ["No new QA jobs today."]

    date_str = datetime.now().strftime("%d.%m.%Y")
    blocks = [f"📅 {date_str} — New QA jobs"]

    if english_jobs:
        blocks.append(f"🇬🇧 English-speaking ({len(english_jobs)})")
        blocks.extend(_entries(english_jobs))
    if german_jobs:
        blocks.append(f"🇩🇪 German-speaking ({len(german_jobs)})")
        blocks.extend(_entries(german_jobs))

    chunks = []
    current_parts: list[str] = []
    current_len = 0
    for block in blocks:
        if current_parts and current_len + len(block) + 2 > TELEGRAM_MAX_MESSAGE_LENGTH:
            chunks.append("\n\n".join(current_parts))
            current_parts = []
            current_len = 0
        current_parts.append(block)
        current_len += len(block) + 2

    if current_parts:
        chunks.append("\n\n".join(current_parts))
    return chunks


def send_message(text: str, bot_token: str, chat_id: str) -> dict:
    url = TELEGRAM_API_URL.format(token=bot_token)
    response = post_with_retry(
        url,
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
    )
    return response.json()


def send_report(
    german_jobs: list[NormalizedJob], english_jobs: list[NormalizedJob], bot_token: str, chat_id: str
) -> None:
    for chunk in format_message(german_jobs, english_jobs):
        send_message(chunk, bot_token, chat_id)
