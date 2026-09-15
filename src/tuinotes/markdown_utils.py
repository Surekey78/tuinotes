"""Markdown helpers: titles, previews, #tags, [[wikilinks]] and statistics.

Everything here is deliberately dependency-free and side-effect free so it can
be used from the CLI, the indexer and the TUI alike.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Tuple

#: ``#tag`` — letters/digits/underscore/dash/dot, unicode aware.
TAG_RE = re.compile(r"(?<![\w`])#([\w][\w\-.]{0,63})", re.UNICODE)
#: ``[[target]]`` or ``[[target|alias]]``.
WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]*)?\]\]")
#: ATX heading: ``# Title``.
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
#: Fenced code block delimiters.
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
#: Setext underline (``===`` / ``---`` under a title).
SETEXT_RE = re.compile(r"^\s{0,3}(=+|-{2,})\s*$")
#: Inline markup we strip when building previews.
INLINE_MD_RE = re.compile(
    r"(\*\*|__|\*|_|~~|`{1,3}|\[|\]|\(|\)|!\[|\[\[|\]\]|https?://)", re.UNICODE
)
WS_RE = re.compile(r"\s+")

SLUG_FORBIDDEN_RE = re.compile(r"[^\w\s\-.]", re.UNICODE)


def strip_code_fences(text: str) -> str:
    """Return ``text`` with fenced code blocks blanked out.

    Keeps line numbers intact (fences are replaced with empty lines) so that
    highlight spans computed on the result still map onto the original.
    """
    out: List[str] = []
    in_fence = False
    fence_token = ""
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if match:
            token = match.group(1)
            if not in_fence:
                in_fence = True
                fence_token = token
            elif token == fence_token:
                in_fence = False
                fence_token = ""
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def extract_title(text: str, fallback: str = "Untitled") -> str:
    """Derive a note title from its content.

    Priority: first ATX/setext heading → first non-empty, non-metadata line →
    the caller's fallback.
    """
    if not text:
        return fallback
    first_text_line = ""
    previous = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = HEADING_RE.match(line)
        if heading:
            title = heading.group(2).strip()
            return _clean_title(title) or fallback
        stripped = line.strip()
        if SETEXT_RE.match(line) and previous.strip():
            return _clean_title(previous.strip()) or fallback
        if not stripped:
            previous = line
            continue
        # Skip front-matter delimiters and horizontal rules.
        if stripped in {"---", "***", "___"}:
            previous = line
            continue
        if not first_text_line:
            first_text_line = _clean_title(stripped)
        previous = line
    return (first_text_line or fallback)[:120] or fallback


def _clean_title(text: str) -> str:
    """Remove list markers, emphasis and trailing #tags so titles look tidy."""
    cleaned = re.sub(r"^\s*(?:[-*+]\s+\[[ xX]\]\s+|[-*+]\s+|\d+\.\s+)", "", text)
    cleaned = TAG_RE.sub("", cleaned)
    cleaned = WS_RE.sub(" ", cleaned).strip()
    cleaned = cleaned.lstrip("#> \t").strip()
    cleaned = re.sub(r"(?:\*\*|__|[*_`])+$", "", cleaned).rstrip()
    return cleaned


def rename_heading(text: str, old_title: str, new_title: str) -> str:
    """Rewrite the first ``# old title`` heading after a rename.

    Notes created by tuinotes start with a heading that mirrors the file name,
    so renaming a note has to update it or the index would resurrect the old
    title on the next reindex.
    """
    if not text or not old_title:
        return text
    for index, line in enumerate(text.splitlines()):
        heading = HEADING_RE.match(line)
        if heading and heading.group(2).strip().lower() == old_title.strip().lower():
            lines = text.splitlines()
            lines[index] = f"{heading.group(1)} {new_title}"
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        if line.strip():
            break
    return text


def extract_preview(text: str, limit: int = 120) -> str:
    """First meaningful line of body text, markdown markers removed."""
    in_fence = False
    fence_token = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fence = FENCE_RE.match(line)
        if fence:
            token = fence.group(1)
            if not in_fence:
                in_fence, fence_token = True, token
            elif token == fence_token:
                in_fence, fence_token = False, ""
            continue
        if in_fence:
            continue
        if HEADING_RE.match(line) or SETEXT_RE.match(line):
            continue
        if line.startswith((">", "|", "![")):
            line = line.lstrip(">| ").strip()
        line = re.sub(r"^\s*(?:[-*+]\s+\[[ xX]\]\s+|[-*+]\s+|\d+\.\s+)", "", line)
        line = INLINE_MD_RE.sub("", line)
        line = WS_RE.sub(" ", line).strip()
        if not line:
            continue
        if len(line) > limit:
            return line[: limit - 1].rstrip() + "…"
        return line
    return ""


def extract_tags(text: str) -> List[str]:
    """All ``#hashtags`` in the document, de-duplicated, order preserved.

    Headings (``# Title``), fenced code and inline code are ignored.
    """
    if not text:
        return []
    scan_text = strip_code_fences(text)
    seen: List[str] = []
    lowered = set()
    for line in scan_text.splitlines():
        if HEADING_RE.match(line):
            # Drop the heading marker itself, keep any tags after it.
            line = HEADING_RE.sub(lambda m: m.group(2), line)
        for match in TAG_RE.finditer(line):
            tag = match.group(1).rstrip(".-_,;:")
            if not tag or tag.lower() in lowered:
                continue
            lowered.add(tag.lower())
            seen.append(tag)
    return seen


def extract_links(text: str) -> List[str]:
    """Targets of ``[[wikilinks]]``, de-duplicated, order preserved."""
    if not text:
        return []
    scan_text = strip_code_fences(text)
    seen: List[str] = []
    lowered = set()
    for match in WIKILINK_RE.finditer(scan_text):
        target = match.group(1).strip()
        if not target or target.lower() in lowered:
            continue
        lowered.add(target.lower())
        seen.append(target)
    return seen


def count_words(text: str) -> int:
    """Word count that ignores markdown syntax noise."""
    if not text:
        return 0
    scan = strip_code_fences(text)
    scan = INLINE_MD_RE.sub(" ", scan)
    return len([word for word in scan.split() if any(ch.isalnum() for ch in word)])


def count_chars(text: str) -> int:
    return len(text)


def reading_time_minutes(word_count: int, words_per_minute: int = 220) -> int:
    return max(1, round(word_count / float(words_per_minute))) if word_count else 0


def slugify(title: str, max_length: int = 60) -> str:
    """Filesystem-safe, sync-friendly slug for a note title."""
    text = unicodedata.normalize("NFKD", title)
    text = text.encode("ascii", "ignore").decode("ascii")
    if not text.strip():
        # Non-latin titles survive as unicode; only path-hostile chars are cut.
        text = SLUG_FORBIDDEN_RE.sub("", title)
    text = SLUG_FORBIDDEN_RE.sub("", text)
    text = WS_RE.sub("-", text.strip())
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    return (text[:max_length].rstrip("-.") or "note")


def summarize(text: str) -> Tuple[int, int]:
    """Return ``(word_count, char_count)``."""
    return count_words(text), count_chars(text)


def iter_lines_with_tags(text: str) -> Iterable[Tuple[int, str]]:
    """Yield ``(line_index, tag)`` for every tag occurrence."""
    for index, line in enumerate(strip_code_fences(text).splitlines()):
        for match in TAG_RE.finditer(line):
            yield index, match.group(1).rstrip(".-_,;:")


def find_occurrences(text: str, needle: str, case_sensitive: bool = False) -> List[int]:
    """Character offsets of ``needle`` in ``text`` (used by editor search)."""
    if not needle:
        return []
    haystack = text if case_sensitive else text.lower()
    target = needle if case_sensitive else needle.lower()
    offsets: List[int] = []
    start = haystack.find(target)
    while start != -1:
        offsets.append(start)
        start = haystack.find(target, start + 1)
    return offsets


def location_of_offset(text: str, offset: int) -> Tuple[int, int]:
    """Convert a character offset into a ``(line, column)`` location."""
    offset = max(0, min(offset, len(text)))
    prefix = text[:offset]
    line = prefix.count("\n")
    column = offset - (prefix.rfind("\n") + 1)
    return line, column
