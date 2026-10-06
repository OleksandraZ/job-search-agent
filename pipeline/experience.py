"""Minimum years of professional experience a job description asks for.

Built against real phrasings from fetched Python/Cloud/Data postings (2026-10-06):
"5+ years of ... experience", "Minimum 2 years", "mindestens zwei Jahre
Berufserfahrung", "mehr als 4 Jahren", "drei bis fünf Jahre" (a range counts as its
lower bound), "mind. 2 Jahre", "At least 6-8 years building ...", "with5+ years",
"2+ year s" (broken spacing from HTML).

A "<number> years" mention only counts as a requirement when it has a "+", OR a
requirement cue directly precedes it ("at least"/"mindestens"/"mind."/...), OR an
experience word follows it within the same bullet/sentence. That rules out the
real false positives seen in the same data: company history ("über 30 Jahren
Expertise", "Nearly 150 years of expertise", "seit über 25 Jahren"), contract terms
("fixed term duration of three years"), testimonials ("I spent 7 years as a
manager"), "Sabbatical bis zu einem Jahr". Numbers above MAX_PLAUSIBLE_YEARS are
ignored too (no job asks for 16+ years; company ages routinely exceed that), and a
mention marked optional ("Idealerweise 2-4 Jahre", "... is a plus") is not a
requirement - see _PREFERENCE_BEFORE/_PREFERENCE_AFTER.
"""

import re

MAX_PLAUSIBLE_YEARS = 15

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
    "ein": 1, "eine": 1, "einem": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
}
_NUM = r"(?<![\d.,])\d{1,2}(?![\d.,])|\b(?:" + "|".join(_NUMBER_WORDS) + r")\b"
_YEARS_MENTION = re.compile(
    rf"(?P<low>{_NUM})\s*(?P<plus>\+)?\s*(?:(?:-|–|—|to|bis|or|oder)\s*(?:{_NUM})\s*(?P<plus2>\+)?\s*)?"
    r"(?:years?|yrs?|Jahre|Jahren|Jahres|Jahr)(?!\w)",
    re.IGNORECASE,
)
_REQUIREMENT_CUE = re.compile(
    r"(?:at\s+leas\s*t|at\s+least|minimum(?:\s+of)?|min\.|mindestens|mind\.|more\s+than|mehr\s+als)"
    r"[\s|]*$",
    re.IGNORECASE,
)
_EXPERIENCE_WORD = re.compile(
    r"experience|erfahrung|berufserfahrung|praxis|professional|hands-on|in\s+(?:a|an|the)?\s*\w+\s+roles?",
    re.IGNORECASE,
)
# "Ideally 2-4 years" / "Bestenfalls mindestens fünf Jahre": a preference cue BEFORE
# the number makes it optional. AFTER the number, "ideally"/"bestenfalls" qualify the
# field instead ("4+ years ..., ideally at a SaaS company", "mehr als 4 Jahren
# Berufserfahrung bestenfalls in der Entwicklung" - both real requirements, wrongly
# skipped by a first version that checked the whole sentence), so only explicit
# "it's optional" endings count there.
_PREFERENCE_BEFORE = re.compile(
    r"ideally|idealerweise|bestenfalls|preferabl|preferred|nice[\s-]to[\s-]have|wünschenswert",
    re.IGNORECASE,
)
_PREFERENCE_AFTER = re.compile(
    r"is\s+a\s+plus|a\s+plus\b|nice[\s-]to[\s-]have|wünschenswert|von\s+vorteil",
    re.IGNORECASE,
)
# HTML tags, bullets, ";" and sentence ends bound a requirement - a cue or experience
# word on the other side of one belongs to a different bullet/sentence.
_TAG = re.compile(r"<[^>]+>")
_BOUNDARY = re.compile(r"\||•|;|\.\s+(?=[A-ZÄÖÜ])")


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token.lower()]


def required_years(description: str) -> int | None:
    """Highest minimum-years requirement found, or None if the text states none."""
    text = re.sub(r"\s+", " ", _TAG.sub(" | ", description.replace("&nbsp;", " ").replace("&#xa0;", " ")))
    found: list[int] = []
    for match in _YEARS_MENTION.finditer(text):
        years = _to_int(match.group("low"))
        if years > MAX_PLAUSIBLE_YEARS:
            continue

        before = text[max(0, match.start() - 30) : match.start()]
        after = text[match.end() : match.end() + 70]
        after_clause = _BOUNDARY.split(after, maxsplit=1)[0]
        before_clause = _BOUNDARY.split(text[max(0, match.start() - 120) : match.start()])[-1]

        is_requirement = (
            bool(match.group("plus") or match.group("plus2"))
            or bool(_REQUIREMENT_CUE.search(before))
            or bool(_EXPERIENCE_WORD.search(after_clause))
        )
        if (
            not is_requirement
            or _PREFERENCE_BEFORE.search(before_clause)
            or _PREFERENCE_AFTER.search(after_clause)
        ):
            continue
        found.append(years)
    return max(found) if found else None
