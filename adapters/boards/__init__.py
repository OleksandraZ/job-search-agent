import re
from dataclasses import dataclass


@dataclass
class NormalizedJob:
    source_id: str
    title: str
    company: str
    url: str
    location: str
    description: str


def title_matches(title: str, terms: list[str]) -> bool:
    # A bare substring check let "SDET" match inside "Emsdetten" (a German city
    # name, verified live via stellenanzeigen.de) - a false positive invisible on
    # earlier sources only because their title text never happened to contain that
    # substring. A leading \b alone would already reject that specific case (there's
    # no boundary between "m" and "s" in "Em|sdet|ten"), but a trailing \b is added
    # too for the general "whole word/phrase" principle CLAUDE.md already applies
    # elsewhere (see docs/lessons/classification.md's "unambiguous phrase, not a
    # bare word" rule) - accepting the tradeoff that a term won't match a title that
    # appends a German inflectional suffix directly (e.g. "Softwaretester" term
    # against a literal "Softwaretesterin" title with no separating space/slash).
    return any(re.search(rf"\b{re.escape(term)}\b", title, re.IGNORECASE) for term in terms)
