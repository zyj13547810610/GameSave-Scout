from __future__ import annotations

import re

_VERSION_TOKEN = r"(?:v(?:er(?:sion)?)?|build)[\s._-]*\d+(?:\.\d+)*"
_VERSION_SUFFIX = re.compile(
    rf"""^(?P<title>.+?)(?:
        [\s._-]+(?P<plain>{_VERSION_TOKEN})
        |
        \s*[（(]\s*(?P<bracket>{_VERSION_TOKEN})\s*[）)]\s*
    )$""",
    re.IGNORECASE | re.VERBOSE,
)


def split_title_and_version(raw_name: str) -> tuple[str, str | None]:
    value = raw_name.strip()
    match = _VERSION_SUFFIX.fullmatch(value)
    if match is None:
        return value, None
    title = match.group("title").strip()
    version = (match.group("plain") or match.group("bracket")).strip()
    if not title:
        return value, None
    return title, version
