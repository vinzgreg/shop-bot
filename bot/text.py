"""
Pure text-processing utilities.

These functions have no external dependencies and are safe to import
anywhere — including test suites that don't install Mastodon.py.
"""

import html
import html.parser
import re


class _HTMLStripper(html.parser.HTMLParser):
    """Collect text content while discarding all HTML tags."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


_MULTI_SPACE = re.compile(r"\s+")


def _collapse_whitespace(text: str) -> str:
    """Replace runs of whitespace with a single space."""
    return _MULTI_SPACE.sub(" ", text).strip()


def strip_html(raw: str) -> str:
    """Convert Mastodon HTML content to plain text."""
    stripper = _HTMLStripper()
    stripper.feed(raw)
    text = stripper.get_text()
    return _collapse_whitespace(html.unescape(text))


def strip_mention(text: str, bot_acct: str) -> str:
    """
    Remove the leading @botname mention from the DM body.

    Mastodon may include the full handle (@shop@instance.social) or just the
    local part (@shop).  We strip whichever form is present.
    """
    local = bot_acct.split("@")[0]
    pattern = re.compile(
        rf"@{re.escape(local)}(?:@\S+)?\s*",
        re.IGNORECASE,
    )
    return pattern.sub("", text, count=1).strip()
