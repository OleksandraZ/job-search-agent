from dataclasses import dataclass


@dataclass
class NormalizedJob:
    source_id: str
    title: str
    company: str
    url: str
    location: str
    description: str
