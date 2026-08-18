from __future__ import annotations

import httpx

from adapters.boards import NormalizedJob


def make_job(
    *,
    source_id: str = "test",
    title: str = "Test Engineer",
    company: str = "Test GmbH",
    url: str = "https://example.test/1",
    location: str = "",
    description: str = "",
) -> NormalizedJob:
    return NormalizedJob(
        source_id=source_id,
        title=title,
        company=company,
        url=url,
        location=location,
        description=description,
    )


def fake_response(
    *,
    status_code: int = 200,
    json: object = None,
    text: str | None = None,
    request_url: str = "https://example.test/",
) -> httpx.Response:
    kwargs: dict = {}
    if json is not None:
        kwargs["json"] = json
    elif text is not None:
        kwargs["text"] = text
    return httpx.Response(status_code, request=httpx.Request("GET", request_url), **kwargs)
