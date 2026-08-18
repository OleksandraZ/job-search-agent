import argparse
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agents import germany_remote, munich_local
from agents._common import fetch_from_sources
from notifier import telegram
from pipeline import classify_language, dedupe, filters

CONFIG_DIR = Path(__file__).parent / "config"

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main(dry_run: bool = False) -> None:
    sources_config = load_yaml("sources.yaml")
    keywords_config = load_yaml("keywords.yaml")

    source_ids = sorted(set(munich_local.SOURCE_IDS) | set(germany_remote.SOURCE_IDS))
    raw_jobs = fetch_from_sources(sources_config, keywords_config, source_ids)
    logger.info("fetched %d jobs total", len(raw_jobs))

    munich_jobs = munich_local.filter_jobs(raw_jobs)
    remote_jobs = germany_remote.filter_jobs(raw_jobs)
    logger.info("%d Munich jobs, %d Germany-remote jobs", len(munich_jobs), len(remote_jobs))

    # A job can be both Munich-based and remote-eligible (e.g. location "München,
    # Germany (Remote available)") and so appear in both filter_jobs() results -
    # dedupe by url before matching/sending so it isn't reported twice.
    by_url = {job.url: job for job in munich_jobs + remote_jobs}
    matched = filters.filter_by_title(list(by_url.values()), keywords_config["title_match_terms"])
    logger.info("%d jobs matched title_match_terms", len(matched))

    unseen = dedupe.filter_unseen(matched)
    logger.info("%d of those are new (not previously seen)", len(unseen))

    german_jobs, english_jobs = classify_language.split_by_language(unseen)
    logger.info("%d German-required, %d English jobs", len(german_jobs), len(english_jobs))

    if dry_run:
        for chunk in telegram.format_message(german_jobs, english_jobs):
            print(chunk)
            print("---")
        return

    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    telegram.send_report(german_jobs, english_jobs, bot_token, chat_id)
    dedupe.mark_seen(unseen)
    logger.info("sent Telegram message(s), marked %d jobs as seen", len(unseen))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the message instead of sending it to Telegram",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
