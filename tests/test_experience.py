import pytest

from pipeline.experience import required_years

# Every case below is a real phrasing from fetched Python/Cloud/Data postings
# (2026-10-06), lightly trimmed.


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<li>5+ years of professional software development in Python</li>", 5),
        ("<li>Minimum 2 years of comprehensive experience in quality assurance</li>", 2),
        ("Du verfügst über mindestens zwei Jahre einschlägige Berufserfahrung", 2),
        ("Informatik in Kombination mit mehr als 4 Jahren relevanter Berufserfahrung", 4),
        ("Etwa drei bis fünf Jahre Berufserfahrung als Software Engineer mit Python", 3),
        ("Mehrjährige praktische Erfahrung nach Abschluss des Studiums (mind. 2 Jahre)", 2),
        ("<li>At least 6–8 years building and running backend systems in production</li>", 6),
        ("Kubernetes roles, with5+ years focused on production-scale Kubernetes", 5),
        ("At leas t 2+ year s of relevant experience in fields like Analytics Engineering", 2),
        ("<li>5–8+ years in DevOps, SRE, or infrastructure engineering</li>", 5),
        ("Mindestens <b>6 Jahre Erfahrung</b> im Bereich DevOps", 6),
        ("Minimum of four years of professional experience in machine learning", 4),
    ],
)
def test_required_years_finds_real_requirement_phrasings(text, expected):
    assert required_years(text) == expected


def test_required_years_takes_the_highest_requirement():
    text = "<li>5+ years of cloud services experience, with at least 3 years on AWS</li>"
    assert required_years(text) == 5


@pytest.mark.parametrize(
    "text",
    [
        "IT-Beratungsunternehmen mit über 30 Jahren Expertise.",
        "Nearly 150 years of expertise, meeting the ambition and technology",
        "leisten wir seit über 25 Jahren Pionierarbeit",
        "The contract is for a fixed term duration of three years and is subject to probation.",
        "Before joining flexa, I spent 7 years as a manager in tech consulting.",
        "Sabbatical bis zu einem Jahr möglich",
        "25 days' vacation - plus an extra day for every 2 years here",
        "Wir suchen Dich mit mehrjähriger Berufserfahrung in Python.",
    ],
)
def test_required_years_ignores_non_requirement_mentions(text):
    assert required_years(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Idealerweise 2 - 4 Jahre professioneller Berufserfahrung.",
        "Bestenfalls mindestens fünf Jahre relevante Berufserfahrung in der Entwicklung",
        "<li>3+ years of Terraform experience is a plus</li>",
    ],
)
def test_required_years_ignores_requirements_marked_optional(text):
    assert required_years(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # "ideally"/"bestenfalls" AFTER the number qualify the field, not the years -
        # a first version skipped both of these real requirements.
        ("You bring 3+ years of building data pipelines in production, ideally at a SaaS company.", 3),
        ("mit mehr als 4 Jahren relevanter Berufserfahrung bestenfalls in der Entwicklung", 4),
    ],
)
def test_required_years_keeps_requirement_followed_by_ideally(text, expected):
    assert required_years(text) == expected
