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
    lowered = title.lower()
    return any(term.lower() in lowered for term in terms)
