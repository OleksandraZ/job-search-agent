import argparse
import logging
import os
from pathlib import Path
from typing import NamedTuple

import yaml
from dotenv import load_dotenv

from adapters.boards import NormalizedJob
from adapters.registry import fetch_from_companies, fetch_from_sources
from agents import germany_remote, munich_local
from agents._common import SOURCE_IDS
from notifier import telegram
from pipeline import classify_language, filters
from pipeline.duplicates import JobGroup, group_duplicates
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


def select_jobs(raw_jobs: list[NormalizedJob], keywords_config: dict) -> list[NormalizedJob]:
    """Every already-fetched job that fits one keywords file: in Munich/Germany-remote
    scope and passing all of that file's title/skill/description filters. No dedupe -
    shared by build_report() (daily Telegram run) and tools/market_report.py (full
    statistics, seen or not), so both always apply exactly the same selection.
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

    # Optional: drop jobs whose title carries an explicit disqualifying seniority word
    # (e.g. "Senior"), regardless of which title_match_terms entry matched them - a bare
    # broad term like "Python" would otherwise pull in senior postings too. See
    # keywords_python.yaml's meta.usage.
    if "title_exclude_terms" in keywords_config:
        matched = filters.exclude_by_title(matched, keywords_config["title_exclude_terms"])
        logger.info("%d left after title_exclude_terms", len(matched))

    # Optional: require at least one term from every skill group in the title or
    # description - see pipeline/filters.py:require_term_groups() and
    # keywords_data_engineering.yaml's meta.usage.
    if "require_term_groups" in keywords_config:
        matched = filters.require_term_groups(matched, keywords_config["require_term_groups"])
        logger.info("%d left after require_term_groups", len(matched))

    # Optional: drop jobs whose description mentions an out-of-scope domain/tool - see
    # pipeline/filters.py:exclude_by_description() and keywords_qa.yaml's meta.usage.
    if "description_exclude_terms" in keywords_config:
        matched = filters.exclude_by_description(matched, keywords_config["description_exclude_terms"])
        logger.info("%d left after description_exclude_terms", len(matched))

    # Optional: drop jobs whose description asks for more years of experience than
    # this - see pipeline/experience.py and keywords_python.yaml's meta.usage.
    if "max_required_years" in keywords_config:
        matched = filters.exclude_by_required_years(matched, keywords_config["max_required_years"])
        logger.info("%d left after max_required_years", len(matched))

    return matched


class Report(NamedTuple):
    german: list[JobGroup]
    english: list[JobGroup]
    matched: list[NormalizedJob]  # every job that fit this search, seen or not


def build_report(raw_jobs: list[NormalizedJob], keywords_config: dict, db_path: Path) -> Report:
    """Turn already-fetched jobs into the (german, english) report to send. No
    network/Telegram/env dependency and no DB writes, so it's testable with a plain
    job list - main() keeps only the true I/O seams (fetch, send, mark-seen).

    The same job found on several boards/cities, or already sent within
    dedupe.SEEN_WINDOW under another URL, appears once / not at all - see
    pipeline/duplicates.py.
    """
    matched = select_jobs(raw_jobs, keywords_config)
    unseen = dedupe.filter_unseen(matched, db_path=db_path)
    groups = group_duplicates(unseen)
    logger.info("%d of those are new (not previously seen) - %d distinct jobs", len(unseen), len(groups))

    # Language from the most completely described copy - an empty description
    # would otherwise silently default to English.
    german = [g for g in groups if classify_language.is_german_required(g.best_described)]
    english = [g for g in groups if not classify_language.is_german_required(g.best_described)]
    logger.info("%d German-required, %d English jobs", len(german), len(english))
    return Report(german, english, matched)


def main(dry_run: bool = False, keywords_file: str = "keywords_qa.yaml") -> None:
    sources_config = load_yaml("sources.yaml")
    keywords_config = load_yaml(keywords_file)
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

    report = build_report(raw_jobs, keywords_config, db_path)
    report_label = keywords_config.get("report_label", "QA")

    if dry_run:
        for chunk in telegram.format_message(report.german, report.english, report_label):
            print(chunk)
            print("---")
        return

    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    sent_groups = telegram.send_report(report.german, report.english, bot_token, chat_id, report_label)
    sent_jobs = [job for group in sent_groups for job in group.copies]
    dedupe.mark_seen(sent_jobs, db_path=db_path)
    # Keep already-sent jobs that are still listed "seen" (dedupe.SEEN_WINDOW).
    dedupe.refresh_seen(report.matched, db_path=db_path)
    logger.info(
        "sent Telegram message(s): %d jobs (%d listings) marked as seen", len(sent_groups), len(sent_jobs)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the message instead of sending it to Telegram",
    )
    parser.add_argument(
        "--keywords",
        default="keywords_qa.yaml",
        help="config/ yaml file providing title_match_terms (default: keywords_qa.yaml)",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run, keywords_file=args.keywords)
