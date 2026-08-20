import argparse
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from adapters.boards import NormalizedJob
from adapters.registry import fetch_from_companies, fetch_from_sources
from agents import germany_remote, munich_local
from agents._common import SOURCE_IDS
from notifier import telegram
from pipeline import classify_language, filters
from storage import dedupe
from tools.resolve_ats import resolve_pending

CONFIG_DIR = Path(__file__).parent / "config"

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# httpx/httpcore log each request's full URL at INFO - for Telegram that URL embeds
# the bot token (https://api.telegram.org/bot<token>/sendMessage), so leaving this at
# INFO would put a live secret in whatever this run's logs land in (cron output,
# persisted log files, etc).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_report(
    raw_jobs: list[NormalizedJob], keywords_config: dict, db_path: Path
) -> tuple[list[NormalizedJob], list[NormalizedJob]]:
    """Turn already-fetched jobs into the (german, english) report to send. No
    network/Telegram/env dependency, so it's testable with a plain job list -
    main() keeps only the true I/O seams (fetch, send, mark-seen).
    """
    munich_jobs = munich_local.filter_jobs(raw_jobs)
    remote_jobs = germany_remote.filter_jobs(raw_jobs)
    logger.info("%d Munich jobs, %d Germany-remote jobs", len(munich_jobs), len(remote_jobs))

    # A job can be both Munich-based and remote-eligible (e.g. location "München,
    # Germany (Remote available)") and so appear in both filter_jobs() results -
    # dedupe by url before matching/sending so it isn't reported twice.
    by_url = {job.url: job for job in munich_jobs + remote_jobs}
    matched = filters.filter_by_title(list(by_url.values()), keywords_config["title_match_terms"])
    logger.info("%d jobs matched title_match_terms", len(matched))

    unseen = dedupe.filter_unseen(matched, db_path=db_path)
    logger.info("%d of those are new (not previously seen)", len(unseen))

    german_jobs, english_jobs = classify_language.split_by_language(unseen)
    logger.info("%d German-required, %d English jobs", len(german_jobs), len(english_jobs))
    return german_jobs, english_jobs


def main(dry_run: bool = False) -> None:
    sources_config = load_yaml("sources.yaml")
    keywords_config = load_yaml("keywords.yaml")
    db_path = dedupe.DB_PATH

    # A fresh companies.yaml entry (bare name+url, never resolved) has no ats set,
    # so fetch_from_companies() would otherwise silently skip it forever -
    # resolve_pending() classifies any such entry in place on disk before it's
    # loaded below. Only ever-unresolved entries, not already-attempted null/custom
    # ones - see resolve_pending()'s docstring. No-op once every company has been
    # through resolution at least once.
    newly_resolved = resolve_pending()
    if newly_resolved:
        logger.info("resolved %d pending companies before this run", len(newly_resolved))

    companies_config = load_yaml("companies.yaml")

    raw_board_jobs = fetch_from_sources(sources_config, keywords_config, sorted(SOURCE_IDS))
    raw_company_jobs = fetch_from_companies(companies_config, keywords_config)
    logger.info(
        "fetched %d board jobs, %d company jobs", len(raw_board_jobs), len(raw_company_jobs)
    )
    raw_jobs = raw_board_jobs + raw_company_jobs

    german_jobs, english_jobs = build_report(raw_jobs, keywords_config, db_path)

    if dry_run:
        for chunk in telegram.format_message(german_jobs, english_jobs):
            print(chunk)
            print("---")
        return

    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    sent_jobs = telegram.send_report(german_jobs, english_jobs, bot_token, chat_id)
    dedupe.mark_seen(sent_jobs, db_path=db_path)
    logger.info("sent Telegram message(s), marked %d jobs as seen", len(sent_jobs))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the message instead of sending it to Telegram",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
