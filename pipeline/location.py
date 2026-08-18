import re

from adapters.boards import NormalizedJob

MUNICH_PATTERN = re.compile(r"münchen|munich|muenchen", re.IGNORECASE)

# GermanTechJobs has no real per-job location field - every job gets the literal
# placeholder "Germany" (see adapters/boards/html_scrape.py), so a Munich mention can
# only come from the free-text description there. Every other source's location field
# is real, source-provided structured data - once we have that, description text adds
# only false-positive risk, not real signal: a real StepStone posting for a Kirchdorf
# an der Iller (near Ulm) role was misclassified as Munich because its description's
# standard company-boilerplate opener ("Das Unternehmen mit Sitz in Taufkirchen bei
# München...") mentions the company's HQ city, not the job's actual location - the
# same "mit Sitz in <city>" opener recurs across other StepStone postings regardless
# of where the role itself is, so this isn't a one-off. See job_search_agent_phase5
# memory.
GENERIC_LOCATION_PLACEHOLDERS = {"germany", "deutschland"}

# Arbeitnow's `location` field is a short, deliberate value the company set (e.g.
# "Fully Remote"), so a bare "remote" there is trustworthy. GermanTechJobs has no
# location field — only free-text description prose — where a bare "remote" or
# "homeoffice" is NOT trustworthy: it also matches things like "Remote-Erstgespräch"
# (a remote first interview call) or "2 Tage pro Woche Homeoffice" (hybrid, not full
# remote). So description text requires an unambiguous full-remote phrase instead.
# "remote-first" used to be in this list but isn't actually unambiguous - a real
# TestDevJobs posting reads "Remote-first – work where you work best, whether from
# home or in a hybrid mode from our office ... in Berlin": the company's own
# definition of "remote-first" here explicitly includes hybrid office work, so it
# isn't a commitment to full-remote the way "100% remote"/"fully remote" are. See
# job_search_agent_phase5 memory.
LOCATION_REMOTE_PATTERN = re.compile(r"remote", re.IGNORECASE)
DESCRIPTION_REMOTE_PATTERN = re.compile(
    r"100\s*%\s*remote|full(?:y)?[\s-]*remote|vollständig\s+remote|komplett\s+remote|"
    r"remote\s+only",
    re.IGNORECASE,
)

# Even an unambiguous phrase like "full remote" isn't safe from negation: a real
# Arbeitnow posting reads "On-site availability in Nürnberg (hybrid, not full
# remote)" - "full remote" matches DESCRIPTION_REMOTE_PATTERN, but "not" immediately
# before it means the opposite. Checked against the clause right before the match
# (bounded the same way as classify_language.py's disclaimer check - stop at
# sentence punctuation or an HTML tag boundary, so a negation in an unrelated
# earlier clause/bullet point can't bleed into this one).
NEGATION_PATTERN = re.compile(r"\bnot\b|\bnicht\b|\bkeine?\b|\bno\s+longer\b", re.IGNORECASE)
CLAUSE_BOUNDARY = re.compile(r"[.;<]")
NEGATION_WINDOW = 30


def _preceding_clause(text: str, match_start: int) -> str:
    segment = text[max(0, match_start - NEGATION_WINDOW) : match_start]
    boundaries = list(CLAUSE_BOUNDARY.finditer(segment))
    return segment[boundaries[-1].end() :] if boundaries else segment


def is_munich(job: NormalizedJob) -> bool:
    if MUNICH_PATTERN.search(job.location):
        return True

    location = job.location.strip().lower()
    if not location or location in GENERIC_LOCATION_PLACEHOLDERS:
        return bool(MUNICH_PATTERN.search(job.description))
    return False


def is_remote(job: NormalizedJob) -> bool:
    if LOCATION_REMOTE_PATTERN.search(job.location):
        return True

    text = job.description
    for match in DESCRIPTION_REMOTE_PATTERN.finditer(text):
        if NEGATION_PATTERN.search(_preceding_clause(text, match.start())):
            continue
        return True
    return False


def filter_munich(jobs: list[NormalizedJob]) -> list[NormalizedJob]:
    return [job for job in jobs if is_munich(job)]


def filter_remote(jobs: list[NormalizedJob]) -> list[NormalizedJob]:
    return [job for job in jobs if is_remote(job)]
