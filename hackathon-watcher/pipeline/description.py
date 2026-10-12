"""Post-description cleanup: tidy formatting and end on a complete sentence.

Descriptions arrive already cut by their sources (devpost/devevents/devfolio
cut at DESCRIPTION_MAX_CHARS and append '…'; generic_enrich hard-slices at 500
chars mid-word), so posts used to end like "...6 workshops, held by…". This is
the single place that repairs that, at format time, for every source.

It never rewrites prose. It only:
  - normalizes whitespace, stray HTML entities and doubled punctuation
  - strips scraping leftovers ("Read more", "[…]")
  - drops a trailing incomplete sentence, so the text ends on the last
    complete one -- and never appends an ellipsis of its own
"""

from __future__ import annotations

import html
import re

# Words whose trailing period does not end a sentence ("e.g. Python", "U.S.
# students", "Dr. Smith"). Single letters are handled separately (initials).
_ABBREVIATIONS = frozenset({
    "e.g", "i.e", "etc", "vs", "approx", "dr", "mr", "mrs", "ms", "prof",
    "inc", "ltd", "co", "corp", "jr", "sr", "st", "no", "nos", "fig", "est",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec", "u.s", "u.k", "a.m", "p.m",
})

_ARTIFACT_RES = [
    re.compile(r"\s*\[(?:…|\.{3}|more)\]\s*$", re.IGNORECASE),
    re.compile(r"\s*\((?:…|\.{3})\)\s*$"),
    re.compile(r"\s*(?:read|show|see|view|learn)\s+more\.?\s*(?:»|›|>|→)?\s*$", re.IGNORECASE),
]
_ZERO_WIDTH_RE = re.compile(r"[​-‍⁠﻿]")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?)](?:\s|$))")
_DOUBLE_PUNCT_RES = [
    (re.compile(r",(?:\s*,)+"), ","),
    (re.compile(r";(?:\s*;)+"), ";"),
    (re.compile(r"(?<!\.)\.\.(?!\.)"), "."),        # exactly two dots -> one
    (re.compile(r"\.{4,}"), "..."),                 # runaway dots -> ellipsis
    (re.compile(r"…\.+|\.+…"), "…"),
    (re.compile(r"([!?])\1{2,}"), r"\1\1"),         # "!!!!" -> "!!"
    (re.compile(r"[,;:]\s*([.!?])"), r"\1"),        # ", ." -> "."
]

# Sentence boundary: terminal punctuation, optional closing quote/bracket,
# whitespace, then something that can start a sentence.
_BOUNDARY_RE = re.compile(r"([.!?])([\"'”’)\]]*)\s+(?=[\"'“‘(\[]?[A-Z0-9#@$€£¥\U0001F300-\U0001FAFF])")

_ENDS_COMPLETE_RE = re.compile(r"(?<!\.\.)[.!?][\"'”’)\]]*$")
_ENDS_ELLIPSIS_RE = re.compile(r"(?:…|\.{3})[\"'”’)\]]*$")


def clean_text(text: str | None) -> str:
    """Formatting-only normalization; the words are left alone."""
    if not text:
        return ""
    text = html.unescape(text)
    text = _ZERO_WIDTH_RE.sub("", text).replace(" ", " ")
    text = re.sub(r"\s+", " ", text).strip()
    for pattern in _ARTIFACT_RES:
        text = pattern.sub("", text)
    for pattern, replacement in _DOUBLE_PUNCT_RES:
        text = pattern.sub(replacement, text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return text.strip()


def _is_abbreviation(chunk: str) -> bool:
    last = chunk.rsplit(" ", 1)[-1].rstrip(".").lower().lstrip("(\"'")
    return last in _ABBREVIATIONS or (len(last) == 1 and last.isalpha())


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY_RE.finditer(text):
        end = match.end(2)
        chunk = text[start:end].strip()
        if match.group(1) == "." and _is_abbreviation(chunk):
            continue
        sentences.append(chunk)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _is_complete(sentence: str) -> bool:
    return bool(_ENDS_COMPLETE_RE.search(sentence)) and not _ENDS_ELLIPSIS_RE.search(sentence)


def _trim_dangling_clause(fragment: str) -> str | None:
    """Last resort for a description that is ONE cut-off sentence, e.g.
    'This hackathon provides 6 workshops, held by…'. Cut back to the last
    clause boundary and close it with a period; None if nothing meaningful
    (at least 4 words) would remain."""
    body = _ENDS_ELLIPSIS_RE.sub("", fragment).rstrip(" ,;:-–—")
    cut = max(body.rfind(","), body.rfind(";"), body.rfind(" – "), body.rfind(" — "))
    if cut <= 0:
        return None
    kept = body[:cut].rstrip(" ,;:-–—")
    if len(kept.split()) < 4:
        return None
    return kept + "."


def summarize(text: str | None, max_sentences: int = 3, max_chars: int | None = None) -> str | None:
    """Up to `max_sentences` complete sentences of `text`, also within
    `max_chars` if given. Ends on a complete sentence whenever the source has
    one; returns None rather than a broken fragment."""
    cleaned = clean_text(text)
    if not cleaned:
        return None

    sentences = split_sentences(cleaned)[:max_sentences]
    complete = list(sentences)
    while complete and not _is_complete(complete[-1]):
        complete.pop()

    if complete:
        while max_chars is not None and complete and len(" ".join(complete)) > max_chars:
            complete.pop()
        return " ".join(complete) if complete else None

    # No complete sentence at all.
    fragment = sentences[0]
    looks_cut = bool(_ENDS_ELLIPSIS_RE.search(fragment)) or len(fragment) >= 300
    if looks_cut:
        fragment = _trim_dangling_clause(fragment)
        if fragment is None:
            return None
    # A short tagline with no final period ("Build AI agents for finance") is
    # a complete thought, not a truncation -- keep it as written.
    if max_chars is not None and len(fragment) > max_chars:
        return None
    return fragment
