import re
from pathlib import Path

import yaml

from adapters.boards import NormalizedJob

CONFIG_PATH = Path(__file__).parent.parent / "config" / "language_rules.yaml"

# How far past a "German required" match to look for a disclaimer ("von Vorteil",
# "wünschenswert", ...) that would mean this particular mention was actually
# optional. Bounded at '.', ';' or the start of any HTML tag ('<') so it can't cross
# into an unrelated sentence or a separate <li> bullet point in the description.
DISCLAIMER_WINDOW = 60
CLAUSE_BOUNDARY = re.compile(r"[.;<]")
ENGLISH_MENTION = re.compile(r"english|englisch", re.IGNORECASE)
HTML_TAG = re.compile(r"<[^>]+>")
WORD = re.compile(r"[a-zA-ZäöüÄÖÜß]+")


def _load_config(config_path: Path = CONFIG_PATH) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


_config = _load_config()
GERMAN_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _config["german_required_patterns"]]
DISCLAIMER_PATTERN = re.compile("|".join(_config["optional_disclaimer_patterns"]), re.IGNORECASE)

_WHOLE_DESC_CONFIG = _config["whole_description_language_signal"]
GERMAN_WORDS = set(_WHOLE_DESC_CONFIG["german_words"])
ENGLISH_WORDS = set(_WHOLE_DESC_CONFIG["english_words"])
MIN_GERMAN_WORDS = _WHOLE_DESC_CONFIG["min_german_words"]
MIN_GERMAN_RATIO = _WHOLE_DESC_CONFIG["min_ratio"]


def _same_clause(text: str) -> str:
    boundary = CLAUSE_BOUNDARY.search(text)
    return text[: boundary.start()] if boundary else text


def _has_explicit_german_requirement(text: str) -> bool:
    for pattern in GERMAN_PATTERNS:
        for match in pattern.finditer(text):
            window = _same_clause(text[match.end() : match.end() + DISCLAIMER_WINDOW])
            disclaimer = DISCLAIMER_PATTERN.search(window)
            if disclaimer and not ENGLISH_MENTION.search(window[: disclaimer.start()]):
                continue  # disclaimer applies to German itself - not a real requirement
            return True
    return False


def _is_predominantly_german(text: str) -> bool:
    # Fallback for postings that never state a language requirement because the
    # whole ad is written in German (see the config's comment for real examples) -
    # a stopword-frequency check rather than a phrase match, since there's no
    # explicit requirement statement to find here.
    words = WORD.findall(HTML_TAG.sub(" ", text).lower())
    german_count = sum(1 for w in words if w in GERMAN_WORDS)
    english_count = sum(1 for w in words if w in ENGLISH_WORDS)
    if german_count < MIN_GERMAN_WORDS:
        return False
    return german_count / (german_count + english_count) >= MIN_GERMAN_RATIO


def is_german_required(job: NormalizedJob) -> bool:
    text = job.description
    return _has_explicit_german_requirement(text) or _is_predominantly_german(text)


def split_by_language(
    jobs: list[NormalizedJob],
) -> tuple[list[NormalizedJob], list[NormalizedJob]]:
    german, english = [], []
    for job in jobs:
        (german if is_german_required(job) else english).append(job)
    return german, english
