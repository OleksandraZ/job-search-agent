"""Shared helpers for adapters/ats/* modules.

Board sources in sources.yaml are Germany-specific by construction (StepStone
Germany, Bundesagentur, etc.), so pipeline/location.py never needed a country check -
see CLAUDE.md's "verify the country field" checklist item. Company-direct sourcing
breaks that assumption: a company's ATS listing can include non-Germany offices
(a real N26/Greenhouse fetch returned Barcelona, Madrid, Milan, Paris, and Vienna
alongside Berlin), so each ATS adapter applies this light location guard before
emitting a NormalizedJob. A non-remote non-Germany job (e.g. "Barcelona") would
already fail pipeline/location.py's is_munich/is_remote checks downstream and get
dropped harmlessly either way; the guard specifically matters for a job whose
location literally contains "remote" but isn't Germany-scoped (e.g. "Remote - Spain"),
which is_remote() would otherwise treat as a real match.
"""

from __future__ import annotations

import re

GERMANY_HINTS = re.compile(
    r"germany|deutschland|münchen|munich|muenchen|berlin|hamburg|frankfurt|k[öo]ln|cologne|"
    r"stuttgart|d[üu]sseldorf|leipzig|dresden|n[üu]rnberg|nuremberg|hannover|bremen|essen|"
    r"dortmund|bonn|mannheim|karlsruhe|augsburg|wiesbaden|m[üu]nster|freiburg|erlangen|"
    r"heidelberg|potsdam|regensburg|w[üu]rzburg|bielefeld",
    re.IGNORECASE,
)

# Deliberately not "DACH" - the project's scope is Germany only (Munich-local +
# Germany-remote, see agents/munich_local.py and agents/germany_remote.py), so
# Austria/Switzerland are treated as non-Germany here too.
NON_GERMANY_HINTS = re.compile(
    r"\b(usa|united states|u\.s\.|uk|united kingdom|austria|switzerland|spain|france|italy|"
    r"poland|netherlands|portugal|india|canada|australia|ireland|sweden|denmark|belgium|"
    r"barcelona|madrid|paris|milan|rome|vienna|zurich|london|amsterdam|dublin|warsaw|lisbon|"
    r"stockholm|copenhagen|brussels)\b",
    re.IGNORECASE,
)


def is_germany_relevant(location: str) -> bool:
    """Best-effort guard on an ATS's own structured location field. Ambiguous
    strings (e.g. a bare "Remote" with no city/country) default to True - the
    existing Munich/remote filters narrow further downstream, so the cost of an
    unclear case is a harmless miss, not a wrongly-included non-Germany job.
    """
    if GERMANY_HINTS.search(location):
        return True
    return not NON_GERMANY_HINTS.search(location)


def looks_like_a_german_location(text: str) -> bool:
    """Strict version of the guard above: true only on an explicit German city/
    country match, no default-true fallback for an ambiguous case. Needed where
    defaulting to True would be actively harmful rather than just a harmless miss -
    e.g. workday_api.py selecting which of a company's many location facet entries
    (often hundreds of cities worldwide) represent Germany. Known tradeoff: a German
    office in a town not in GERMANY_HINTS (verified live: Roche's Penzberg/Grenzach)
    won't match - same "best-effort, re-verify per source" limitation the rest of
    this heuristic already carries.
    """
    return bool(GERMANY_HINTS.search(text))
