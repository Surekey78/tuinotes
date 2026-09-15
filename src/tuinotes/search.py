"""Search: fuzzy scoring, query parsing and rich highlighting.

Two engines cooperate:

* SQLite FTS5 (with a LIKE fallback) does the heavy lifting for word/phrase
  matches — fast even with thousands of notes.
* A pure-Python subsequence scorer rescues typos and partial words
  (``prog rust`` → ``#programming``/``rust-notes``) without a compiled
  dependency, which matters on Termux.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Iterable, List, Optional, Sequence, Tuple

from rich.text import Text

from tuinotes.markdown_utils import INLINE_MD_RE, WS_RE
from tuinotes.models import NoteRef

HIGHLIGHT_STYLE = "bold reverse"
TAG_STYLE = "cyan"
MATCH_STYLE = "bold yellow"


@dataclasses.dataclass(frozen=True)
class ParsedQuery:
    """Result of parsing a raw search string."""

    text: str = ""
    tags: Tuple[str, ...] = ()
    negated_tags: Tuple[str, ...] = ()
    phrases: Tuple[str, ...] = ()
    path_filter: str = ""
    title_only: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.text or self.tags or self.negated_tags or self.path_filter)


@dataclasses.dataclass(frozen=True)
class SearchResult:
    ref: NoteRef
    score: float = 0.0
    snippet: str = ""
    matched_tags: Tuple[str, ...] = ()

    @property
    def path(self) -> str:
        return self.ref.path


def parse_query(raw: str) -> ParsedQuery:
    """Parse ``#tag -#tag in:folder title:word free text``.

    Supported prefixes:

    * ``#tag`` / ``-#tag`` — require / exclude a tag,
    * ``in:folder`` — restrict to a sub-folder,
    * ``title:word`` — search titles only,
    * ``"quoted phrase"`` — exact phrase.
    """
    if raw is None:
        return ParsedQuery()
    tokens: List[str] = []
    tags: List[str] = []
    negated: List[str] = []
    phrases: List[str] = []
    path_filter = ""
    title_only = False

    for match in re.finditer(r'"([^"]*)"|(\S+)', raw):
        quoted, token = match.group(1), match.group(2)
        if quoted is not None:
            if quoted.strip():
                phrases.append(quoted.strip())
            continue
        lowered = token.lower()
        if token.startswith("#") and len(token) > 1:
            tags.append(token[1:].rstrip(",;:"))
        elif token.startswith("-#") and len(token) > 2:
            negated.append(token[2:].rstrip(",;:"))
        elif lowered.startswith("in:") and len(token) > 3:
            path_filter = token[3:].strip("/")
        elif lowered.startswith("title:"):
            title_only = True
            remainder = token[len("title:") :].strip()
            if remainder:
                tokens.append(remainder)
        else:
            tokens.append(token)

    text = " ".join(tokens + phrases).strip()
    return ParsedQuery(
        text=text,
        tags=tuple(dict.fromkeys(tags)),
        negated_tags=tuple(dict.fromkeys(negated)),
        phrases=tuple(phrases),
        path_filter=path_filter,
        title_only=title_only,
    )


def fuzzy_score(query: str, text: str) -> Optional[float]:
    """Subsequence score in ``0..1`` or ``None`` when ``query`` is not a subsequence.

    Rewards contiguous runs, word-initial matches and short targets so that
    ``rn`` prefers ``rust-notes`` over ``learning-nonsense``.
    """
    if not query:
        return None
    if not text:
        return 0.0
    query = query.lower()
    haystack = text.lower()

    direct = haystack.find(query)
    if direct != -1:
        score = 0.65 + 0.3 * min(1.0, len(query) / max(len(haystack), 1))
        if direct == 0 or haystack[direct - 1] in " -_./":
            score += 0.25
        return min(1.0, score)

    score = 0.0
    haystack_index = 0
    previous_index = -2
    run = 0
    for char in query:
        index = haystack.find(char, haystack_index)
        if index == -1:
            return None
        if index == previous_index + 1:
            run += 1
            score += 0.10 + 0.04 * min(run, 4)
        else:
            run = 0
            score += 0.06
        if index == 0 or haystack[index - 1] in " -_./#":
            score += 0.06
        previous_index = index
        haystack_index = index + 1

    coverage = len(query) / float(max(len(haystack), 1))
    return min(1.0, score * 0.9 + coverage * 0.5)


def best_field_score(query: str, ref: NoteRef) -> Tuple[float, str]:
    """Best fuzzy score across title/preview/tags plus the field it came from."""
    best = 0.0
    field = ""
    title_score = fuzzy_score(query, ref.title)
    if title_score is not None:
        best, field = title_score, "title"
    for tag in ref.tags:
        tag_score = fuzzy_score(query, tag)
        if tag_score is not None and tag_score * 0.95 > best:
            best, field = tag_score * 0.95, "tag"
    if ref.preview:
        preview_score = fuzzy_score(query, ref.preview)
        if preview_score is not None and preview_score * 0.7 > best:
            best, field = preview_score * 0.7, "preview"
    if not field and ref.path:
        path_score = fuzzy_score(query, ref.stem)
        if path_score is not None and path_score * 0.8 > best:
            best, field = path_score * 0.8, "path"
    return best, field


def snippet_around(text: str, query: str, width: int = 140) -> str:
    """A short excerpt of ``text`` centred on the first ``query`` hit."""
    cleaned = WS_RE.sub(" ", INLINE_MD_RE.sub("", text)).strip()
    if not cleaned:
        return ""
    if not query:
        return cleaned[:width] + ("…" if len(cleaned) > width else "")
    index = cleaned.lower().find(query.lower())
    if index == -1:
        return cleaned[:width] + ("…" if len(cleaned) > width else "")
    start = max(0, index - width // 3)
    end = min(len(cleaned), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(cleaned) else ""
    return prefix + cleaned[start:end].strip() + suffix


def highlight(text: str, needles: Sequence[str], style: str = HIGHLIGHT_STYLE) -> Text:
    """Return a :class:`rich.text.Text` with every needle occurrence styled."""
    result = Text(text)
    if not text:
        return result
    lowered = text.lower()
    spans: List[Tuple[int, int]] = []
    for needle in needles:
        if not needle:
            continue
        target = needle.lower()
        start = lowered.find(target)
        while start != -1:
            spans.append((start, start + len(target)))
            start = lowered.find(target, start + 1)
    if not spans:
        return result
    spans.sort()
    merged: List[List[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    for start, end in merged:
        result.stylize(style, start, end)
    return result


def highlight_tags(text: str, style: str = TAG_STYLE) -> Text:
    """Style ``#hashtags`` inside a snippet/preview."""
    result = Text(text)
    for match in re.finditer(r"(?<![\w`])#[\w][\w\-.]{0,63}", text):
        result.stylize(style, match.start(), match.end())
    return result


def matches_tags(ref: NoteRef, required: Iterable[str], negated: Iterable[str] = ()) -> bool:
    """Tag filter with case-insensitive comparison."""
    owned = {tag.lower() for tag in ref.tags}
    for tag in required:
        if tag.lower() not in owned:
            return False
    for tag in negated:
        if tag.lower() in owned:
            return False
    return True


def rank(results: Iterable[SearchResult]) -> List[SearchResult]:
    """Sort results: score first, then most recently modified."""
    return sorted(results, key=lambda r: (-r.score, -(r.ref.modified or 0.0)))
