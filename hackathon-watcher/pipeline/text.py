"""Small text helpers shared by sources and enrichment.

Kept separate from any one source so markdown arriving from different
places (Devfolio's API, DoraHacks' schema.org description) is cleaned the
same way rather than in two drifting copies.
"""

from __future__ import annotations

import re

_MD_HEADER_RE = re.compile(r"^#{1,6}\s*", re.M)
_MD_BOLD_ITALIC_RE = re.compile(r"[*_]{1,3}")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def strip_markdown(text: str) -> str:
    """Flatten markdown to plain prose: links keep their label, headings and
    emphasis markers are dropped, whitespace collapses to single spaces."""
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_HEADER_RE.sub("", text)
    text = _MD_BOLD_ITALIC_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()
