import re
from dataclasses import dataclass
from functools import lru_cache
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


@dataclass(frozen=True)
class _Rules:
    german_patterns: list[re.Pattern]
    disclaimer_pattern: re.Pattern
    german_words: set[str]
    english_words: set[str]
    min_german_words: int
    min_ratio: float


@lru_cache(maxsize=1)
def _rules() -> _Rules:
    # Computed on first use, not at import - importing this module (e.g. transitively
    # through main.py during test collection) must not do real file I/O as a side
    # effect just because something else needed NormalizedJob or split_by_language's
    # signature, not its config-derived behavior.
    config = _load_config()
    whole_desc = config["whole_description_language_signal"]
    return _Rules(
        german_patterns=[re.compile(p, re.IGNORECASE) for p in config["german_required_patterns"]],
        disclaimer_pattern=re.compile("|".join(config["optional_disclaimer_patterns"]), re.IGNORECASE),
        german_words=set(whole_desc["german_words"]),
        english_words=set(whole_desc["english_words"]),
        min_german_words=whole_desc["min_german_words"],
        min_ratio=whole_desc["min_ratio"],
    )


def _same_clause(text: str) -> str:
    boundary = CLAUSE_BOUNDARY.search(text)
    return text[: boundary.start()] if boundary else text


def _has_explicit_german_requirement(text: str) -> bool:
    rules = _rules()
    for pattern in rules.german_patterns:
        for match in pattern.finditer(text):
            window = _same_clause(text[match.end() : match.end() + DISCLAIMER_WINDOW])
            disclaimer = rules.disclaimer_pattern.search(window)
            if disclaimer and not ENGLISH_MENTION.search(window[: disclaimer.start()]):
                continue  # disclaimer applies to German itself - not a real requirement
            return True
    return False


def _is_predominantly_german(text: str) -> bool:
    # Fallback for postings that never state a language requirement because the
    # whole ad is written in German (see the config's comment for real examples) -
    # a stopword-frequency check rather than a phrase match, since there's no
    # explicit requirement statement to find here.
    rules = _rules()
    words = WORD.findall(HTML_TAG.sub(" ", text).lower())
    german_count = sum(1 for w in words if w in rules.german_words)
    english_count = sum(1 for w in words if w in rules.english_words)
    if german_count < rules.min_german_words:
        return False
    return german_count / (german_count + english_count) >= rules.min_ratio


def is_german_required(job: NormalizedJob) -> bool:
    text = job.description
    return _has_explicit_german_requirement(text) or _is_predominantly_german(text)


def split_by_language(
    jobs: list[NormalizedJob],
) -> tuple[list[NormalizedJob], list[NormalizedJob]]:
    german: list[NormalizedJob] = []
    english: list[NormalizedJob] = []
    for job in jobs:
        (german if is_german_required(job) else english).append(job)
    return german, english
